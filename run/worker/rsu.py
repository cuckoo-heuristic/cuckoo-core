from __future__ import annotations

import threading
import traceback
from typing import Dict, Any, List

from django.db import close_old_connections

from object.models import RSUVehicle, Application
from system.build_context import MiniSystemContextBuilder
from algorithm.main_dcsga import dcsga_run


class RSUWorker(threading.Thread):

    def __init__(self, rsu_id, cfg):
        super().__init__(daemon=True)
        self.rsu_id=int(rsu_id)
        self.cfg=cfg
        self._stop_flag=threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):

        close_old_connections()

        t=0
        tick=max(1,int(getattr(self.cfg,"tick_seconds",1)))
        total_time=float(getattr(self.cfg,"total_time",120))

        while t<total_time and not self._stop_flag.is_set():

            close_old_connections()

            try:
                vehicle_ids=list(
                    RSUVehicle.objects.filter(
                        rsu_id_id=self.rsu_id,
                        end_time__isnull=True
                    ).values_list("vehicle_id_id",flat=True)
                )
            except Exception:
                vehicle_ids=[]

            for vid in vehicle_ids:
                self._handle_vehicle(vid)

            if self._stop_flag.wait(tick):
                break

            t+=tick

    def _handle_vehicle(self,vehicle_id:int):

        try:
            apps=list(
                Application.objects.filter(
                    vehicle_id_id=vehicle_id,
                    is_finished=False
                )
            )

            if not apps:
                return

            for app in apps:

                try:
                    builder=MiniSystemContextBuilder(
                        vehicle_id=vehicle_id,
                        application_id=app.id,
                        rsu_id=self.rsu_id
                    )

                    ctx=builder.build_context()

                except Exception:
                    traceback.print_exc()
                    continue

                try:
                    best_solution,quality,cache_state=dcsga_run(ctx)
                except Exception:
                    traceback.print_exc()
                    continue

                try:
                    self.apply_offloading(app.id,best_solution)
                    self.apply_cache(cache_state)
                except Exception:
                    traceback.print_exc()

        except Exception:
            traceback.print_exc()

    def apply_offloading(self,application_id:int,best_solution:List):

        for task_id,provider_id,rank in best_solution:
            pass

    def apply_cache(self,cache_state:Dict[int,Any]):

        for sp_id,items in cache_state.items():
            pass
