from __future__ import annotations

import random
import threading
from datetime import timedelta

from django.db import transaction, close_old_connections
from django.db.models import Count
from django.utils import timezone

from object.models import Vehicle
from dag.models import  ApplicationType
from application.models import Application
from run.worker.vehicle import SimulationConfig
from parameter.services import load_params_obj


def _sim_datetime(cfg: SimulationConfig, sim_seconds: float):
    base = cfg.base_time or timezone.now()
    return base + timedelta(seconds=max(0.0, float(sim_seconds)))


def _pick_application_type_id(min_tasks: int = 3) -> int | None:
    qs = (
        ApplicationType.objects
        .annotate(task_count=Count("task"))
        .filter(task_count__gte=int(min_tasks))
        .values_list("id", flat=True)
    )
    ids = list(qs)
    if not ids:
        return None
    return int(random.choice(ids))


class TaskGeneratorWorker(threading.Thread):
    def __init__(self, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.cfg = cfg

        params = load_params_obj()
        self.min_tasks = int(getattr(params, "min_tasks_per_app_type", 3) or 3)

        self.interval_seconds = int(getattr(self.cfg, "tick_seconds", 0) or 0)
        if self.interval_seconds <= 0:
            raise ValueError(f"Invalid cfg.tick_seconds={getattr(self.cfg, 'tick_seconds', None)}")

        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):
        close_old_connections()

        t = 0
        # IMPORTANT: strictly < total_time (avoid creating new apps at the exact end boundary).
        while (t < self.cfg.total_time) and (not self._stop_flag.is_set()):
            close_old_connections()

            app_type_id = _pick_application_type_id(min_tasks=self.min_tasks)
            if app_type_id is not None:
                now_dt = _sim_datetime(self.cfg, float(t))
                vehicles = list(Vehicle.objects.all())

                with transaction.atomic():
                    for v in vehicles:
                        exists = Application.objects.filter(
                            vehicle_id_id=int(v.id),
                            is_progress=True,
                        ).exists()
                        if exists:
                            continue

                        Application.objects.create(
                            vehicle_id_id=int(v.id),
                            application_type_id_id=int(app_type_id),
                            start_at=now_dt,
                            end_at=None,
                            is_progress=True,
                        )

            if self._stop_flag.wait(self.interval_seconds):
                break

            t += self.interval_seconds