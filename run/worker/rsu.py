from __future__ import annotations
import threading
import traceback
from datetime import timedelta
from typing import Dict, Any, List
from django.db import close_old_connections, transaction
from django.utils import timezone
from object.models import RSUVehicle, ServiceProvider
from execution.models import TaskExecution
from application.models import Application
from cache.models import cache as CacheModel
from resource.models import Resource
from state.models import State
from system.build_context import MiniSystemContextBuilder
from algorithm.main_dcsga import dcsga_run, ch_gain, rate
from algorithm.greedy_nests import t_finish, e_com

class RSUWorker(threading.Thread):

    def __init__(self, rsu_id, cfg):
        super().__init__(daemon=True)
        self.rsu_id = int(rsu_id)
        self.cfg = cfg
        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):
        close_old_connections()
        t = 0
        tick = max(1, int(getattr(self.cfg, "tick_seconds", 1)))
        total_time = float(getattr(self.cfg, "total_time", 120))

        while t < total_time and not self._stop_flag.is_set():
            close_old_connections()
            try:
                vehicle_ids = list(
                    RSUVehicle.objects.filter(
                        rsu_id_id=self.rsu_id,
                        end_time__isnull=True,
                        is_current=True
                    ).values_list("vehicle_id_id", flat=True)
                )
            except Exception:
                vehicle_ids = []

            for vid in vehicle_ids:
                self._handle_vehicle(vid, t)

            if self._stop_flag.wait(tick):
                break
            t += tick

    def _handle_vehicle(self, vehicle_id: int, t: int):
        try:
            apps = list(
                Application.objects.filter(
                    vehicle_id_id=vehicle_id,
                    is_progress=True
                )
            )

            for app in apps:
                try:
                    builder = MiniSystemContextBuilder(application_id=app.id)
                    ctx = builder.build_context()
                    
                    best_solution, quality, cache_state = dcsga_run(ctx)
                    
                    max_finish_time = self.apply_offloading(app, best_solution, ctx, t)
                    self.apply_cache(cache_state)
                    self._finalize_application(app, t, max_finish_time)
                    
                except Exception:
                    traceback.print_exc()
                    continue
        except Exception:
            traceback.print_exc()

    def apply_offloading(self, app: Application, best_solution: List, ctx: Dict, time_step: int) -> float:
        base_time = getattr(self.cfg, "base_time", timezone.now())
        sim_now = base_time + timedelta(seconds=time_step)
        overall_max_t = 0.0
        
        for task_id, provider_id, rank in best_solution:
            try:
                sp = ServiceProvider.objects.get(id=provider_id)
                
                exec_time_val = float(t_finish(ctx, provider_id, task_id))
                energy_val = float(e_com(ctx, provider_id, task_id))
                cpu_load = float(ctx["cpu_cycles"].get(task_id, 0))

                gain_val = float(ch_gain(ctx, provider_id))
                rate_val = float(rate(ctx, provider_id))
                distance_val = float(ctx["distance"].get(provider_id, 0.0))

                if exec_time_val > overall_max_t:
                    overall_max_t = exec_time_val

                with transaction.atomic():
                    te = TaskExecution.objects.create(
                        application_id=app,
                        sp_id=sp,
                        task_id_id=task_id,
                        start_time=sim_now,
                        end_time=sim_now + timedelta(seconds=exec_time_val),
                        exec_time=exec_time_val,
                        energy=energy_val
                    )

                    State.objects.create(
                        time_step=time_step,
                        task_execution_id=te,
                        from_vehicle_id=app.vehicle_id,
                        to_vehicle_id=sp.vehicle_id if sp.vehicle_id_id else None,
                        to_rsu_id=sp.rsu_id if sp.rsu_id_id else None,
                        gain=gain_val,
                        distance=distance_val,
                        rate=rate_val
                    )

                    res, _ = Resource.objects.get_or_create(
                        sp_id=sp,
                        defaults={"cpu_used": 0, "cache_used": 0}
                    )
                    res.cpu_used = float(res.cpu_used or 0) + cpu_load
                    res.save(update_fields=["cpu_used"])
                    
            except Exception:
                traceback.print_exc()
        return overall_max_t

    def apply_cache(self, cache_state: Dict[int, Any]):
        for sp_id, task_type_ids in cache_state.items():
            try:
                sp = ServiceProvider.objects.get(id=sp_id)
                for tt_id in task_type_ids:
                    if not CacheModel.objects.filter(sp_id=sp, task_type_id_id=tt_id).exists():
                        with transaction.atomic():
                            CacheModel.objects.create(
                                sp_id=sp,
                                task_type_id_id=tt_id
                            )
                            res, _ = Resource.objects.get_or_create(
                                sp_id=sp,
                                defaults={"cpu_used": 0, "cache_used": 0}
                            )
                            res.cache_used = float(res.cache_used or 0) + 1.0
                            res.save(update_fields=["cache_used"])
            except Exception:
                traceback.print_exc()

    def _finalize_application(self, app: Application, current_t: int, duration: float):
        base_time = getattr(self.cfg, "base_time", timezone.now())
        app.is_progress = False
        app.end_at = base_time + timedelta(seconds=(current_t + duration))
        app.save(update_fields=["is_progress", "end_at"])
