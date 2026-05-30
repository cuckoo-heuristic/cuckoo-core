from __future__ import annotations

import random
import threading
from datetime import timedelta
from typing import Optional, Tuple, List

from django.db import close_old_connections, transaction
from django.db.models import Count
from django.utils import timezone
from django.core.cache import cache

from monarch_pylib.model import transmission

from parameter.services import load_params_obj
from object.models import RSU, RSUVehicle, Vehicle, ServiceProvider
from dag.models import ApplicationType
from application.models import Application


class SimulationConfig:
    def __init__(self, total_time: int, tick_seconds: int, cell_radius_rsu: float, base_time):
        self.total_time = int(total_time)
        self.tick_seconds = int(tick_seconds)
        self.cell_radius_rsu = float(cell_radius_rsu)
        self.base_time = base_time
        self.clock_tick_seconds = 1
        self.motion_tick_seconds = 1


def _sim_datetime(cfg: SimulationConfig, sim_seconds: float):
    base = cfg.base_time or timezone.now()
    return base + timedelta(seconds=max(0.0, float(sim_seconds)))


def _pick_application_type_id(vehicle_id: int, min_tasks: int = 3) -> int | None:
    qs = (
        ApplicationType.objects
        .annotate(task_count=Count("task"))
        .filter(task_count__gte=int(min_tasks))
    )

    used_type_ids = Application.objects.filter(
        vehicle_id_id=int(vehicle_id)
    ).values_list("application_type_id_id", flat=True)

    qs = qs.exclude(id__in=list(used_type_ids))

    ids = list(qs.values_list("id", flat=True))
    if not ids:
        return None
    return int(random.choice(ids))


def _to_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _euclid3(ax: float, ay: float, ah: float, bx: float, by: float, bh: float) -> float:
    return float(
        transmission.distance_3d(
            _to_float(ax), _to_float(ay), _to_float(ah),
            _to_float(bx), _to_float(by), _to_float(bh),
        )
    )


def _nearest_rsu(rsus, pos_xyz: Tuple[float, float, float], h_rsu: float) -> Optional[RSU]:
    best = None
    best_d = None
    vx, vy, vh = pos_xyz

    for r in rsus:
        if r.x_coord is None or r.y_coord is None:
            continue

        rx = _to_float(r.x_coord)
        ry = _to_float(r.y_coord)
        rh = _to_float(h_rsu)

        d = _euclid3(vx, vy, vh, rx, ry, rh)

        if best is None or best_d is None or d < best_d:
            best = r
            best_d = d

    return best


def _sync_rsu_vehicle(vehicle_id: int, new_rsu_id: Optional[int], now_dt):
    open_qs = RSUVehicle.objects.filter(
        vehicle_id_id=vehicle_id,
        end_time__isnull=True
    )

    if new_rsu_id is not None:
        open_qs.exclude(rsu_id_id=new_rsu_id).update(end_time=now_dt, is_current=False)
    else:
        open_qs.update(end_time=now_dt, is_current=False)

    if new_rsu_id is None:
        return

    obj, created = RSUVehicle.objects.get_or_create(
        vehicle_id_id=vehicle_id,
        rsu_id_id=new_rsu_id,
        end_time__isnull=True,
        defaults={
            "start_time": now_dt,
            "is_current": True
        },
    )

    if not created and not obj.is_current:
        obj.is_current = True
        obj.save(update_fields=["is_current"])


def discover_available_sps(vehicle: Vehicle) -> List[int]:
    available = []

    rv = RSUVehicle.objects.filter(
        vehicle_id=vehicle.id,
        is_current=True
    ).select_related("rsu_id").first()

    if not rv:
        return available

    rsu = rv.rsu_id

    sp_rsu = ServiceProvider.objects.filter(
        rsu_id=rsu,
        type="rsu"
    ).first()

    if sp_rsu:
        available.append(sp_rsu.id)

    vehicle_ids = RSUVehicle.objects.filter(
        rsu_id=rsu,
        is_current=True
    ).exclude(
        vehicle_id=vehicle.id
    ).values_list("vehicle_id_id", flat=True)

    sp_vehicles = ServiceProvider.objects.filter(
        vehicle_id_id__in=vehicle_ids,
        type="vehicle"
    ).values_list("id", flat=True)

    available.extend(list(sp_vehicles))

    return available


class VehicleWorker(threading.Thread):

    def __init__(self, vehicle_id: int, cfg: SimulationConfig):
        super().__init__(daemon=True)

        self.vehicle_id = int(vehicle_id)
        self.cfg = cfg
        self._stop_flag = threading.Event()

        self.params = load_params_obj()
        self.min_tasks = int(getattr(self.params, "min_tasks_per_app_type", 3) or 3)
        self.app_interval = int(getattr(self.cfg, "tick_seconds", 0) or 0)

        self.h_vehicle = float(getattr(self.params, "h_vehicle", 0.0) or 0.0)
        self.h_rsu = float(getattr(self.params, "h_rsu", 0.0) or 0.0)

    def stop(self):
        self._stop_flag.set()

    def run(self):

        close_old_connections()

        rsus = list(RSU.objects.all())
        t = 0
        motion_tick = max(1, int(getattr(self.cfg, "motion_tick_seconds", 1) or 1))

        available_sps = []

        while (t <= self.cfg.total_time) and (not self._stop_flag.is_set()):

            close_old_connections()

            v = Vehicle.objects.filter(id=self.vehicle_id).first()
            if v is None:
                break

            if v.path:

                x, y = transmission.current_position(
                    float(self.cfg.total_time),
                    float(t),
                    v.path,
                )

                Vehicle.objects.filter(id=self.vehicle_id).update(
                    x_coord=x,
                    y_coord=y
                )

                v.refresh_from_db(fields=["x_coord", "y_coord"])

                nearest = _nearest_rsu(
                    rsus,
                    (float(x), float(y), float(self.h_vehicle)),
                    h_rsu=float(self.h_rsu),
                )

                now_dt = self.cfg.base_time + timedelta(seconds=int(t))

                with transaction.atomic():
                    _sync_rsu_vehicle(
                        self.vehicle_id,
                        nearest.id if nearest else None,
                        now_dt
                    )

                available_sps = discover_available_sps(v)

                cache.set(
                    f"vehicle_available_sps_{self.vehicle_id}",
                    available_sps,
                    timeout=300
                )

            if self.app_interval > 0 and (t % self.app_interval == 0) and (t < self.cfg.total_time):

                app_type_id = _pick_application_type_id(
                    vehicle_id=self.vehicle_id,
                    min_tasks=self.min_tasks
                )

                if app_type_id is not None:

                    now_dt = _sim_datetime(self.cfg, float(t))

                    with transaction.atomic():

                        exists = Application.objects.filter(
                            vehicle_id_id=self.vehicle_id,
                            is_progress=True,
                        ).exists()

                        if not exists:

                            Application.objects.create(
                                vehicle_id_id=self.vehicle_id,
                                application_type_id_id=int(app_type_id),
                                start_at=now_dt,
                                end_at=None,
                                is_progress=True,
                            )

            if self._stop_flag.wait(int(motion_tick)):
                break

            t += int(motion_tick)

        close_old_connections()

        end_dt = self.cfg.base_time + timedelta(seconds=int(self.cfg.total_time))

        RSUVehicle.objects.filter(
            vehicle_id_id=self.vehicle_id,
            end_time__isnull=True
        ).update(
            end_time=end_dt,
            is_current=False,
        )
