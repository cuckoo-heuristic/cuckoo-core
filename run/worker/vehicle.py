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


def _pick_application_type_id(
    vehicle_id: int,
    min_tasks: int = 3,
    rng: random.Random | None = None,
) -> int | None:
    ids = list(
        ApplicationType.objects
        .annotate(task_count=Count("task"))
        .filter(task_count__gte=int(min_tasks))
        .order_by("id")
        .values_list("id", flat=True)
    )
    if not ids:
        return None
    chooser = rng if rng is not None else random
    return int(chooser.choice(ids))


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


def _nearest_rsu(
    rsus,
    pos_xyz: Tuple[float, float, float],
    h_rsu: float,
    cell_radius_rsu: float | None = None
) -> Optional[RSU]:

    best = None
    best_d = None
    vx, vy, vh = pos_xyz

    radius = None
    if cell_radius_rsu is not None:
        radius = max(0.0, float(cell_radius_rsu))

    for r in rsus:
        if r.x_coord is None or r.y_coord is None:
            continue

        rx = _to_float(r.x_coord)
        ry = _to_float(r.y_coord)
        rh = _to_float(h_rsu)

        d = _euclid3(vx, vy, vh, rx, ry, rh)

        if radius is not None and d > radius:
            continue

        if best is None or best_d is None or d < best_d:
            best = r
            best_d = d

    return best
def _close_rsu_vehicle_connections(queryset, end_time) -> int:
    """Close active RSU links through model.save() so connect_time is persisted."""
    closed = 0

    for link in queryset.select_for_update().order_by("id"):
        link.end_time = end_time
        link.is_current = False
        link.save(
            update_fields=[
                "end_time",
                "connect_time",
                "is_current",
            ]
        )
        closed += 1

    return closed


def _sync_rsu_vehicle(vehicle_id: int, new_rsu_id: Optional[int], now_dt):
    open_qs = RSUVehicle.objects.filter(
        vehicle_id_id=vehicle_id,
        end_time__isnull=True
    )

    if new_rsu_id is not None:
        _close_rsu_vehicle_connections(
            open_qs.exclude(rsu_id_id=new_rsu_id),
            now_dt,
        )
    else:
        _close_rsu_vehicle_connections(open_qs, now_dt)

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

    rv = (
        RSUVehicle.objects
        .filter(
            vehicle_id=vehicle.id,
            is_current=True,
        )
        .select_related("rsu_id")
        .first()
    )

    if not rv:
        return available

    current_rsu = rv.rsu_id

    # M: تمام MEC Serverها مطابق X_n = M ∪ V_n
    rsu_provider_ids = (
        ServiceProvider.objects
        .filter(
            type="rsu",
            rsu_id__isnull=False,
        )
        .values_list("id", flat=True)
    )

    available.extend(
        int(sp_id)
        for sp_id in rsu_provider_ids
    )

    # V_n: خودروهای متصل به همان RSU، به‌جز خودروی مأموریت
    peer_vehicle_ids = (
        RSUVehicle.objects
        .filter(
            rsu_id=current_rsu,
            is_current=True,
        )
        .exclude(vehicle_id=vehicle.id)
        .values_list("vehicle_id_id", flat=True)
    )

    peer_provider_ids = (
        ServiceProvider.objects
        .filter(
            vehicle_id_id__in=peer_vehicle_ids,
            type="vehicle",
        )
        .values_list("id", flat=True)
    )

    available.extend(
        int(sp_id)
        for sp_id in peer_provider_ids
    )

    return list(dict.fromkeys(available))

class VehicleWorker(threading.Thread):
    def __init__(self, vehicle_id: int, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.vehicle_id = int(vehicle_id)
        self.cfg = cfg
        self._stop_flag = threading.Event()
        self.params = load_params_obj()
        self.h_vehicle = float(getattr(self.params, "h_vehicle", 0.0) or 0.0)
        self.h_rsu = float(getattr(self.params, "h_rsu", 0.0) or 0.0)

    def stop(self):
        self._stop_flag.set()

    def _speed_kmh(self) -> float:
        lower = float(getattr(self.cfg, "vehicle_speed_min_kmh", 60.0))
        upper = float(getattr(self.cfg, "vehicle_speed_max_kmh", 80.0))
        if lower <= 0.0 or upper <= 0.0 or upper < lower:
            raise ValueError("Invalid vehicle speed range")
        if lower == upper:
            return lower
        seed = int(getattr(self.cfg, "simulation_seed", 1))
        rng = random.Random(seed * 1_000_003 + self.vehicle_id * 9_973)
        return float(rng.uniform(lower, upper))

    def run(self):
        close_old_connections()
        rsus = list(RSU.objects.all())
        total_time = float(self.cfg.total_time)
        motion_tick = max(
            0.1,
            float(
                getattr(
                    self.cfg,
                    "motion_tick_seconds",
                    1.0,
                )
                or 1.0
            ),
        )
        speed_mps = self._speed_kmh() / 3.6
        get_sim_time = getattr(
            self.cfg,
            "get_sim_time_s",
            None,
        )
        last_processed_time = None

        while not self._stop_flag.is_set():
            close_old_connections()

            if callable(get_sim_time):
                t = min(
                    total_time,
                    max(
                        0.0,
                        float(get_sim_time()),
                    ),
                )
            else:
                t = (
                    0.0
                    if last_processed_time is None
                    else min(
                        total_time,
                        float(last_processed_time) + motion_tick,
                    )
                )

            if (
                last_processed_time is not None
                and t <= float(last_processed_time)
            ):
                if self._stop_flag.wait(0.1):
                    break
                continue

            vehicle = Vehicle.objects.filter(
                id=self.vehicle_id
            ).first()

            if vehicle is None:
                break

            nearest_id = None
            available_sps = []
            route_active = False

            if vehicle.path and len(vehicle.path) >= 2:
                path_length = float(
                    transmission.path_length_2d(
                        vehicle.path
                    )
                )

                travel_time = (
                    path_length / speed_mps
                    if path_length > 0.0
                    else 0.0
                )

                route_active = (
                    travel_time > 0.0
                    and t <= travel_time
                )

                position_time = (
                    min(t, travel_time)
                    if travel_time > 0.0
                    else 0.0
                )

                x, y = transmission.current_position(
                    max(
                        travel_time,
                        motion_tick,
                    ),
                    position_time,
                    vehicle.path,
                )

                Vehicle.objects.filter(
                    id=self.vehicle_id
                ).update(
                    x_coord=x,
                    y_coord=y,
                )

                vehicle.x_coord = x
                vehicle.y_coord = y

                if route_active:
                    nearest = _nearest_rsu(
                        rsus,
                        (
                            float(x),
                            float(y),
                            float(self.h_vehicle),
                        ),
                        h_rsu=float(self.h_rsu),
                        cell_radius_rsu=float(
                            self.cfg.cell_radius_rsu
                        ),
                    )

                    nearest_id = (
                        nearest.id
                        if nearest
                        else None
                    )

            now_dt = _sim_datetime(
                self.cfg,
                t,
            )

            with transaction.atomic():
                _sync_rsu_vehicle(
                    self.vehicle_id,
                    nearest_id,
                    now_dt,
                )

            if route_active and nearest_id is not None:
                available_sps = discover_available_sps(
                    vehicle
                )

            cache.set(
                f"vehicle_available_sps_{self.vehicle_id}",
                available_sps,
                timeout=300,
            )

            last_processed_time = t

            if self._stop_flag.wait(0.1):
                break

        close_old_connections()

        final_t = (
            min(
                total_time,
                max(
                    0.0,
                    float(get_sim_time()),
                ),
            )
            if callable(get_sim_time)
            else min(
                total_time,
                float(last_processed_time or 0.0),
            )
        )

        end_dt = _sim_datetime(
            self.cfg,
            final_t,
        )

        with transaction.atomic():
            _close_rsu_vehicle_connections(
                RSUVehicle.objects.filter(
                    vehicle_id_id=self.vehicle_id,
                    end_time__isnull=True,
                ),
                end_dt,
            )


class ApplicationGeneratorWorker(threading.Thread):
    def __init__(self, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.cfg = cfg
        self._stop_flag = threading.Event()
        params = load_params_obj()
        self.min_tasks = int(getattr(params, "min_tasks_per_app_type", 3) or 3)
        self.rate = max(0.0, float(getattr(cfg, "application_rate_per_second", 10.0)))
        self.seed = int(getattr(cfg, "simulation_seed", 1))

    def stop(self):
        self._stop_flag.set()

    def _create_batch(self, sim_second: int, count: int) -> int:
        if count <= 0:
            return 0
        connected_vehicle_ids = list(
            RSUVehicle.objects.filter(
                is_current=True,
                end_time__isnull=True,
                vehicle_id_id__isnull=False,
            )
            .order_by("vehicle_id_id")
            .values_list("vehicle_id_id", flat=True)
            .distinct()
        )
        active_vehicle_ids = set(
            Application.objects.filter(is_progress=True)
            .values_list("vehicle_id_id", flat=True)
        )
        candidate_ids = [
            int(vehicle_id)
            for vehicle_id in connected_vehicle_ids
            if int(vehicle_id) not in active_vehicle_ids
        ]
        if not candidate_ids:
            return 0

        rng = random.Random(self.seed * 1_000_003 + int(sim_second) * 97_409)
        rng.shuffle(candidate_ids)
        selected_ids = candidate_ids[: min(int(count), len(candidate_ids))]
        start_at = _sim_datetime(self.cfg, float(sim_second))
        created = 0

        with transaction.atomic():
            locked_ids = list(
                Vehicle.objects.select_for_update()
                .filter(id__in=selected_ids)
                .order_by("id")
                .values_list("id", flat=True)
            )
            for vehicle_id in locked_ids:
                if Application.objects.filter(
                    vehicle_id_id=int(vehicle_id),
                    is_progress=True,
                ).exists():
                    continue
                app_type_id = _pick_application_type_id(
                    int(vehicle_id),
                    min_tasks=self.min_tasks,
                    rng=rng,
                )
                if app_type_id is None:
                    continue
                Application.objects.create(
                    vehicle_id_id=int(vehicle_id),
                    application_type_id_id=int(app_type_id),
                    start_at=start_at,
                    end_at=None,
                    is_progress=True,
                )
                created += 1
        return created

    def run(self):
        close_old_connections()

        tick = 1.0
        next_second = 0
        carry = 0.0
        total_time = int(self.cfg.total_time)

        get_sim_time = getattr(
            self.cfg,
            "get_sim_time_s",
            None,
        )

        while not self._stop_flag.is_set():
            close_old_connections()

            if callable(get_sim_time):
                current_second = min(
                    total_time,
                    max(
                        0,
                        int(float(get_sim_time())),
                    ),
                )
            else:
                current_second = min(
                    total_time,
                    next_second,
                )

            upper_bound = min(
                total_time,
                current_second + 1,
            )

            while next_second < upper_bound:
                carry += self.rate * tick

                requested = int(carry)
                carry -= requested

                self._create_batch(
                    next_second,
                    requested,
                )

                next_second += 1

            if current_second >= total_time:
                break

            if self._stop_flag.wait(0.1):
                break

        close_old_connections()