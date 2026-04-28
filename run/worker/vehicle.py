from __future__ import annotations

import math
import threading
from datetime import timedelta
from typing import Optional, Tuple, List

from django.db import close_old_connections, transaction
from django.utils import timezone

from monarch_pylib.model import transmission

from parameter.services import load_params_obj
from object.models import RSU, RSUVehicle, Vehicle, ServiceProvider


class SimulationConfig:
    def __init__(self, total_time: int, tick_seconds: int, cell_radius_rsu: float, base_time):
        self.total_time = int(total_time)
        self.tick_seconds = int(tick_seconds)
        self.cell_radius_rsu = float(cell_radius_rsu)
        self.base_time = base_time
        self.clock_tick_seconds = 1
        self.motion_tick_seconds = 1


def _euclid2(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return float(transmission.distance_2d(float(a[0]), float(a[1]), float(b[0]), float(b[1])))


def _nearest_rsu(rsus, pos_xy: Tuple[float, float]) -> Optional[RSU]:
    best = None
    best_d = None
    for r in rsus:
        if r.x_coord is None or r.y_coord is None:
            continue

        d = _euclid2((float(r.x_coord), float(r.y_coord)), pos_xy)

        if best is None or (best_d is not None and d < best_d):
            best = r
            best_d = d

    return best


def _sync_rsu_vehicle(vehicle_id: int, new_rsu_id: Optional[int], now_dt):

    open_qs = RSUVehicle.objects.filter(
        vehicle_id_id=vehicle_id,
        end_time__isnull=True
    )

    if new_rsu_id is not None:
        open_qs_other = open_qs.exclude(rsu_id_id=new_rsu_id)
    else:
        open_qs_other = open_qs

    open_qs_other.update(end_time=now_dt, is_current=False)

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

    if not created:
        if not obj.is_current:
            obj.is_current = True
            obj.save(update_fields=["is_current"])


def discover_available_sps(vehicle: Vehicle, rsus: List[RSU], params) -> List[ServiceProvider]:

    available_sps = []

    vx = float(vehicle.x_coord)
    vy = float(vehicle.y_coord)

    # RSU range
    rsu_range = float(getattr(params, "rsu_range", 300))
    v2v_range = float(getattr(params, "v2v_range", 100))

    # ---------- RSU providers ----------
    for rsu in rsus:

        if rsu.x_coord is None or rsu.y_coord is None:
            continue

        d = _euclid2((vx, vy), (rsu.x_coord, rsu.y_coord))

        if d <= rsu_range:

            sp = ServiceProvider.objects.filter(
                rsu_id=rsu,
                type="rsu"
            ).first()

            if sp:
                available_sps.append(sp)

    # ---------- Vehicle providers ----------
    vehicles = Vehicle.objects.exclude(id=vehicle.id)

    for v in vehicles:

        if v.x_coord is None or v.y_coord is None:
            continue

        d = _euclid2((vx, vy), (v.x_coord, v.y_coord))

        if d <= v2v_range:

            sp = ServiceProvider.objects.filter(
                vehicle_id=v,
                type="vehicle"
            ).first()

            if sp:
                available_sps.append(sp)

    return available_sps


class VehicleWorker(threading.Thread):

    def __init__(self, vehicle_id: int, cfg: SimulationConfig):
        super().__init__(daemon=True)

        self.vehicle_id = int(vehicle_id)
        self.cfg = cfg
        self._stop_flag = threading.Event()
        self.params = load_params_obj()

    def stop(self):
        self._stop_flag.set()

    def run(self):

        close_old_connections()

        rsus = list(RSU.objects.all())

        t = 0

        motion_tick = 1

        try:
            motion_tick = max(1, int(getattr(self.cfg, "motion_tick_seconds", 1) or 1))
        except Exception:
            motion_tick = 1

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

                nearest = _nearest_rsu(rsus, (float(x), float(y)))

                now_dt = self.cfg.base_time + timedelta(seconds=int(t))

                with transaction.atomic():
                    _sync_rsu_vehicle(
                        self.vehicle_id,
                        nearest.id if nearest else None,
                        now_dt
                    )

  
                available_sps = discover_available_sps(v, rsus, self.params)

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
