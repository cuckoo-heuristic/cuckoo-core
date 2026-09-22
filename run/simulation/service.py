import threading
from datetime import timedelta
import traceback
from time import monotonic
from django.db import close_old_connections, transaction
from django.utils import timezone

from parameter.services import load_params_obj

from object.models import RSU, RSUVehicle, Vehicle, ServiceProvider
from cache.models import cache as CacheModel
from resource.models import Resource
from dag.models import Task
from execution.models import TaskExecution
from application.models import Application

from run.worker.vehicle import ApplicationGeneratorWorker, VehicleWorker, SimulationConfig
from run.worker.rsu import RSUWorker
from system.build_context import MiniSystemContextBuilder as build_context


_registry_lock = threading.Lock()

_vehicle_workers = []
_rsu_workers = []
_status_worker = None
_context_worker = None
_clock_worker = None
_application_generator_worker = None
_running = False
_stopping = False
_stop_reaper = None
_cfg: SimulationConfig | None = None
_sim_time_s: float = 0.0
_stop_requested: bool = False

_snapshot = {
    "ts": None,
    "context": {
        "ok": 0,
        "fail": 0,
        "sample": None,
        "vehicles": [],
        "sim_time_s": None,
        "base_time": None,
        "base_time_type": None,
        "last_error": None,
    },
}


def ensure_service_providers():
    with transaction.atomic():
        provider_ids = []

        for rsu in RSU.objects.order_by("id"):
            sp, _ = ServiceProvider.objects.get_or_create(
                rsu_id=rsu,
                defaults={
                    "type": "rsu",
                },
            )
            provider_ids.append(int(sp.id))

        for vehicle in Vehicle.objects.order_by("id"):
            sp, _ = ServiceProvider.objects.get_or_create(
                vehicle_id=vehicle,
                defaults={
                    "type": "vehicle",
                },
            )
            provider_ids.append(int(sp.id))

        existing_provider_ids = list(
            Resource.objects.filter(
                sp_id_id__in=provider_ids
            ).values_list("sp_id_id", flat=True)
        )

        if len(existing_provider_ids) != len(set(existing_provider_ids)):
            raise ValueError("Duplicate resource rows exist for a service provider")

        missing_provider_ids = sorted(
            set(provider_ids) - set(int(x) for x in existing_provider_ids)
        )

        Resource.objects.bulk_create([
            Resource(
                sp_id_id=provider_id,
                cpu_used=0,
                cache_used=0,
            )
            for provider_id in missing_provider_ids
        ])

def _safe_int(x, name: str) -> int:
    if x is None:
        raise ValueError(f"Missing parameter: {name}")
    try:
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            raise ValueError(f"Invalid parameter: {name}={x}")


def _safe_float(x, name: str) -> float:
    if x is None:
        raise ValueError(f"Missing parameter: {name}")
    try:
        return float(x)
    except Exception:
        raise ValueError(f"Invalid parameter: {name}={x}")


def _build_cfg(params) -> SimulationConfig:
    total_time = _safe_int(
        getattr(params, "simulate_time", None),
        "simulate_time",
    )
    application_rate = _safe_float(
        getattr(params, "application_rate_per_second", None),
        "application_rate_per_second",
    )
    runtime_batch_interval = _safe_int(
        getattr(params, "taking_task_time", None),
        "taking_task_time",
    )
    cell_radius_rsu = _safe_float(
        getattr(params, "cell_radius_rsu", None),
        "cell_radius_rsu",
    )

    if total_time <= 0:
        raise ValueError(
            f"Invalid parameter: simulate_time={total_time}"
        )
    if application_rate <= 0.0:
        raise ValueError(
            "Invalid parameter: "
            f"application_rate_per_second={application_rate}"
        )
    if runtime_batch_interval <= 0 or runtime_batch_interval > total_time:
        raise ValueError(
            "Invalid parameter: "
            f"taking_task_time={runtime_batch_interval}"
        )
    if cell_radius_rsu <= 0.0:
        raise ValueError(
            f"Invalid parameter: cell_radius_rsu={cell_radius_rsu}"
        )
    base_time = timezone.now()

    cfg = SimulationConfig(
        total_time=total_time,
        tick_seconds=runtime_batch_interval,
        cell_radius_rsu=cell_radius_rsu,
        base_time=base_time,
    )

    speed_min = _safe_float(
        getattr(params, "vehicle_speed_min_kmh", 60.0),
        "vehicle_speed_min_kmh",
    )
    speed_max = _safe_float(
        getattr(params, "vehicle_speed_max_kmh", 80.0),
        "vehicle_speed_max_kmh",
    )
    simulation_seed = _safe_int(
        getattr(params, "simulation_seed", 1),
        "simulation_seed",
    )

    if speed_min <= 0.0 or speed_max < speed_min:
        raise ValueError("Invalid vehicle speed range")

    cfg.clock_tick_seconds = 1
    cfg.motion_tick_seconds = 1
    cfg.vehicle_speed_min_kmh = speed_min
    cfg.vehicle_speed_max_kmh = speed_max
    cfg.application_rate_per_second = application_rate
    cfg.simulation_seed = simulation_seed

    # Runtime-only workload controls.  Benchmark code and algorithm files are
    # intentionally untouched.  ``taking_task_time`` is the release interval;
    # a fixed seeded set of 20 mission vehicles receives one application per
    # interval, leaving the other vehicles available for V2V cooperation.
    cfg.runtime_batch_interval_s = int(runtime_batch_interval)
    cfg.runtime_batch_size = 20
    cfg.runtime_scheduler_busy = threading.Event()
    cfg.runtime_coordinator_rsu_id = None
    cfg.runtime_mission_vehicle_ids = []
    cfg.runtime_batches_released = 0
    cfg.runtime_batches_completed = 0
    cfg.runtime_created_applications = 0
    cfg.runtime_skipped_applications = 0
    cfg.runtime_last_error = None
    cfg.runtime_last_batch_metrics = None

    return cfg


def _refresh_vehicle_motion_for_simulation(total_time: int) -> None:
    """Recompute every vehicle speed from its route length and simulation time.

    This keeps the runtime worker aligned with ``Vehicle.compute_speed``:
    each valid route is completed at ``total_time`` rather than assigning an
    unrelated random speed in the 60--80 km/h range.
    """
    if int(total_time) <= 0:
        raise ValueError("Simulation time must be positive")

    vehicles = list(Vehicle.objects.all())
    for vehicle in vehicles:
        vehicle.length = vehicle.compute_length()
        vehicle.speed = vehicle.compute_speed(int(total_time))

    if vehicles:
        Vehicle.objects.bulk_update(vehicles, ["length", "speed"])


def _sim_now_dt(base_time, sim_time_s: float):
    bt = base_time or timezone.now()
    return bt + timedelta(seconds=float(sim_time_s))


def _get_sim_time_s() -> float:
    with _registry_lock:
        return float(_sim_time_s)


def get_logical_now():
    """Return current logical simulation datetime, or None when stopped."""
    with _registry_lock:
        cfg = _cfg
        active = bool(_running or _stopping)
        sim_time_s = float(_sim_time_s)
        base_time = getattr(cfg, "base_time", None) if cfg is not None else None

    if not active or base_time is None:
        return None

    return _sim_now_dt(base_time, sim_time_s)


def _set_sim_time_s(v: float) -> None:
    global _sim_time_s
    with _registry_lock:
        _sim_time_s = float(v)


def _set_stop_requested(v: bool) -> None:
    global _stop_requested
    with _registry_lock:
        _stop_requested = bool(v)


def _get_stop_requested() -> bool:
    with _registry_lock:
        return bool(_stop_requested)


def _summarize_ctx(ctx: dict, vehicle_id: int, sim_time_s: float) -> dict:
    actor = ctx.get("actor") or {}
    tasks = ctx.get("tasks") or {}
    deps = ctx.get("task_dependencies") or []
    te_list = ctx.get("task_executions") or []

    ready_list = (tasks.get("ready") or []) if isinstance(tasks, dict) else []
    all_list = (tasks.get("all") or []) if isinstance(tasks, dict) else []

    ready_ids = [int(t.get("id")) for t in ready_list if isinstance(t, dict) and t.get("id") is not None]
    all_ids = [int(t.get("id")) for t in all_list if isinstance(t, dict) and t.get("id") is not None]

    base_time = ctx.get("base_time") if isinstance(ctx, dict) else None
    now_dt = _sim_now_dt(base_time, sim_time_s=float(sim_time_s))

    done_ids = []
    running_ids = []
    for te in te_list:
        if not isinstance(te, dict):
            continue
        tid = te.get("task_id_id")
        if tid is None:
            continue
        st = te.get("start_time")
        et = te.get("end_time")

        if st is None:
            continue

        if et is None:
            if st <= now_dt:
                running_ids.append(int(tid))
            continue

        if st <= now_dt < et:
            running_ids.append(int(tid))
        elif et <= now_dt:
            done_ids.append(int(tid))

    done_set = set(done_ids)
    ready_set = set(ready_ids)
    running_set = set(running_ids)

    blocked_ids = [tid for tid in all_ids if tid not in done_set and tid not in ready_set and tid not in running_set]

    preds = {}
    if isinstance(deps, list):
        for d in deps:
            if not isinstance(d, dict):
                continue
            p = d.get("parent_task_id")
            c = d.get("child_task_id")
            if p is None or c is None:
                continue
            preds.setdefault(int(c), []).append(int(p))

    blocked_detail = []
    for tid in blocked_ids:
        pre = preds.get(int(tid), [])
        unmet = [p for p in pre if p not in done_set]
        blocked_detail.append({"task_id": int(tid), "pred": pre, "unmet_pred": unmet})

    app = ctx.get("application") or None
    app_id = None
    if isinstance(app, dict):
        app_id = app.get("id")
    else:
        app_id = getattr(app, "id", None)

    return {
        "sim_time_s": float(sim_time_s),
        "vehicle_id": int(vehicle_id),
        "rsu_id": actor.get("rsu_id"),
        "neighbors": len(actor.get("neighbor_vehicle_ids") or []),
        "has_application": app_id is not None,
        "application_id": app_id,
        "ready_tasks": len(ready_ids),
        "ready_tasks_count": len(ready_ids),
        "ready_task_ids": ready_ids,
        "running_task_ids": sorted(list(running_set)),
        "done_task_ids": sorted(list(done_set)),
        "blocked_task_ids": blocked_ids,
        "blocked": blocked_detail,
        "db_debug": ctx.get("db_debug") if isinstance(ctx, dict) else None,
    }


class ClockWorker(threading.Thread):
    def __init__(self, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.cfg = cfg
        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):
        close_old_connections()
        clock_tick = int(getattr(self.cfg, "clock_tick_seconds", 1) or 1)
        total_time = int(getattr(self.cfg, "total_time", 0) or 0)
        t = 0.0
        _set_sim_time_s(0.0)
        _set_stop_requested(False)
        scheduler_busy = getattr(self.cfg, "runtime_scheduler_busy", None)

        while (not self._stop_flag.is_set()) and (t < float(total_time)):
            # Algorithm wall-clock time is not simulation time.  Pause the
            # logical clock while a whole mission batch is being optimized and
            # persisted, then continue from the same release instant.
            while (
                scheduler_busy is not None
                and scheduler_busy.is_set()
                and not self._stop_flag.is_set()
            ):
                if self._stop_flag.wait(0.1):
                    break

            if self._stop_flag.is_set():
                break

            if self._stop_flag.wait(clock_tick):
                break

            if scheduler_busy is not None and scheduler_busy.is_set():
                continue

            t = min(float(total_time), t + float(clock_tick))
            _set_sim_time_s(t)
        if not self._stop_flag.is_set():
            _set_sim_time_s(float(total_time))
            _set_stop_requested(True)


class StatusWorker(threading.Thread):
    def __init__(self, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.cfg = cfg
        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):
        close_old_connections()
        clock_tick = int(getattr(self.cfg, "clock_tick_seconds", 1) or 1)
        while not self._stop_flag.is_set():
            close_old_connections()
            with _registry_lock:
                _snapshot["ts"] = timezone.now().isoformat()
            if self._stop_flag.wait(clock_tick):
                break



class ContextWorker(threading.Thread):
    def __init__(self, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.cfg = cfg
        self._stop_flag = threading.Event()
        self._last_benchmark_time = -1
    def stop(self):
        self._stop_flag.set()

    def run(self):
        close_old_connections()

        clock_tick = int(
            getattr(self.cfg, "clock_tick_seconds", 1) or 1
        )
        total_time = int(
            getattr(self.cfg, "total_time", 0) or 0
        )

        while not self._stop_flag.is_set():
            close_old_connections()

            t = min(_get_sim_time_s(), float(total_time))

            if int(t) == self._last_benchmark_time:
                if (
                    _get_stop_requested()
                    and t >= float(total_time)
                    and not Application.objects.filter(is_progress=True).exists()
                ):
                    stop_simulation()
                    break

                if self._stop_flag.wait(clock_tick):
                    break
                continue

            self._last_benchmark_time = int(t)

            ok = 0
            fail = 0
            sample = None
            last_error = None
            vehicle_summaries = []

            active_applications = list(
                Application.objects.filter(is_progress=True)
                .order_by("id")[:1]
            )

            for app in active_applications:
                if self._stop_flag.is_set():
                    break

                try:
                    base_ctx = build_context(
                        application_id=app.id
                    ).build_context()

                    cur_sample = {
                        "sim_time_s": float(t),
                        "vehicle_id": int(app.vehicle_id_id),
                        "application_id": int(app.id),
                        "has_application": True,
                        "task_count": len(
                            base_ctx.get("task_ids", [])
                        ),
                        "provider_count": len(
                            base_ctx.get("provider_ids", [])
                        ),
                        "local_sp_id": base_ctx.get(
                            "local_sp_id"
                        ),
                    }

                    vehicle_summaries.append(cur_sample)

                    if sample is None:
                        sample = cur_sample

                    ok += 1

                except Exception:
                    fail += 1
                    last_error = traceback.format_exc()

            with _registry_lock:
                _snapshot["context"] = {
                    "ok": ok,
                    "fail": fail,
                    "sample": sample,
                    "vehicles": vehicle_summaries,
                    "sim_time_s": float(t),
                    "base_time": self.cfg.base_time,
                    "base_time_type": (
                        type(self.cfg.base_time).__name__
                        if self.cfg.base_time
                        else None
                    ),
                    "last_error": last_error,
                }

            if (
                _get_stop_requested()
                and t >= float(total_time)
                and not Application.objects.filter(is_progress=True).exists()
            ):
                stop_simulation()
                break

            if self._stop_flag.wait(clock_tick):
                break
def reset_simulation():
    with transaction.atomic():
        TaskExecution.objects.all().delete()
        Application.objects.all().delete()
        RSUVehicle.objects.all().delete()
        CacheModel.objects.all().delete()
        Resource.objects.all().update(cpu_used=0.0, cache_used=0.0)
    _set_sim_time_s(0.0)
    _set_stop_requested(False)


def run_simulation(
    tmax: int = 10,
):
    global _running, _stopping, _vehicle_workers, _rsu_workers, _status_worker, _context_worker, _clock_worker, _application_generator_worker, _cfg

    with _registry_lock:
        if _running or _stopping:
            return
        _running = True
        _stopping = False

    try:
        params = load_params_obj()
        cfg = _build_cfg(params)
        cfg.tmax = int(tmax)
        cfg.get_sim_time_s = _get_sim_time_s
        _cfg = cfg

        _set_sim_time_s(0.0)
        _set_stop_requested(False)
        ensure_service_providers()
        _refresh_vehicle_motion_for_simulation(cfg.total_time)

        _clock_worker = ClockWorker(cfg=cfg)
        _vehicle_workers = [
            VehicleWorker(vehicle_id=vehicle.id, cfg=cfg)
            for vehicle in Vehicle.objects.all()
        ]
        _application_generator_worker = ApplicationGeneratorWorker(cfg=cfg)
        runtime_rsu_ids = list(
            RSU.objects.order_by("id").values_list("id", flat=True)
        )
        if not runtime_rsu_ids:
            raise ValueError("At least one RSU is required for runtime scheduling")
        cfg.runtime_coordinator_rsu_id = int(runtime_rsu_ids[0])
        _rsu_workers = [
            RSUWorker(rsu_id=rsu_id, cfg=cfg)
            for rsu_id in runtime_rsu_ids
        ]
        _status_worker = StatusWorker(cfg=cfg)
        _context_worker = ContextWorker(cfg=cfg)

        # Initialize the runtime topology at simulation time zero before the
        # clock is allowed to advance.  Vehicle workers need one motion tick
        # to persist their initial RSU associations.  Starting the clock first
        # made the application generator occasionally begin at t=1 and then
        # backfill applications stamped at t=0, which introduced an artificial
        # one-second waiting time against 30-100 ms deadlines.
        for worker in _vehicle_workers:
            worker.start()

        threading.Event().wait(cfg.motion_tick_seconds)

        for worker in _rsu_workers:
            worker.start()

        _status_worker.start()
        _context_worker.start()
        _application_generator_worker.start()

        # Start simulated time only after all workers are ready.  The
        # generator therefore creates the t=0 batch at t=0, and later batches
        # are released only when the simulation clock reaches their second.
        _clock_worker.start()

    except Exception:
        cleanup_workers = [
            _application_generator_worker,
            _status_worker,
            _context_worker,
            _clock_worker,
            *_vehicle_workers,
            *_rsu_workers,
        ]

        for worker in cleanup_workers:
            if worker is None:
                continue
            try:
                worker.stop()
            except Exception:
                pass

        current = threading.current_thread()
        for worker in cleanup_workers:
            if worker is None or worker is current:
                continue
            try:
                if worker.is_alive():
                    worker.join(timeout=5.0)
            except Exception:
                pass

        with _registry_lock:
            _running = False
            _stopping = False
            _vehicle_workers = []
            _rsu_workers = []
            _status_worker = None
            _context_worker = None
            _clock_worker = None
            _application_generator_worker = None
            _cfg = None

        _set_sim_time_s(0.0)
        _set_stop_requested(False)
        raise


def _clear_worker_registry():
    global _running, _stopping, _stop_reaper
    global _vehicle_workers, _rsu_workers
    global _status_worker, _context_worker, _clock_worker
    global _application_generator_worker, _cfg

    _running = False
    _stopping = False
    _stop_reaper = None
    _vehicle_workers = []
    _rsu_workers = []
    _status_worker = None
    _context_worker = None
    _clock_worker = None
    _application_generator_worker = None
    _cfg = None


def _finish_stop_in_background(worker_rows):
    for _name, worker in worker_rows:
        try:
            if worker.is_alive():
                worker.join()
        except Exception:
            pass

    with _registry_lock:
        _clear_worker_registry()


def stop_simulation(wait_timeout: float = 5.0):
    global _stopping, _stop_reaper

    with _registry_lock:
        if not _running and not _stopping:
            return {
                "stopped": True,
                "stopping": False,
                "alive_workers": [],
            }

        _stopping = True
        worker_rows = []

        if _application_generator_worker is not None:
            worker_rows.append(("task_generator", _application_generator_worker))
        if _status_worker is not None:
            worker_rows.append(("status", _status_worker))
        if _context_worker is not None:
            worker_rows.append(("context", _context_worker))
        if _clock_worker is not None:
            worker_rows.append(("clock", _clock_worker))

        worker_rows.extend(
            (f"vehicle:{index}", worker)
            for index, worker in enumerate(_vehicle_workers, start=1)
        )
        worker_rows.extend(
            (f"rsu:{index}", worker)
            for index, worker in enumerate(_rsu_workers, start=1)
        )

    _set_stop_requested(True)

    for _name, worker in worker_rows:
        try:
            worker.stop()
        except Exception:
            pass

    current = threading.current_thread()
    deadline = monotonic() + max(0.0, float(wait_timeout))

    for _name, worker in worker_rows:
        if worker is current:
            continue

        remaining = deadline - monotonic()
        if remaining <= 0.0:
            break

        try:
            if worker.is_alive():
                worker.join(timeout=remaining)
        except Exception:
            pass

    alive_rows = [
        (name, worker)
        for name, worker in worker_rows
        if worker.is_alive()
    ]

    if not alive_rows:
        with _registry_lock:
            _clear_worker_registry()

        return {
            "stopped": True,
            "stopping": False,
            "alive_workers": [],
        }

    with _registry_lock:
        if _stop_reaper is None or not _stop_reaper.is_alive():
            _stop_reaper = threading.Thread(
                target=_finish_stop_in_background,
                args=(alive_rows,),
                daemon=True,
                name="simulation-stop-reaper",
            )
            _stop_reaper.start()

    return {
        "stopped": False,
        "stopping": True,
        "alive_workers": [name for name, _worker in alive_rows],
    }

    # TaskExecution times, energy, and Application completion data are not
    # rewritten during shutdown. They remain available for benchmark reporting.


def simulation_status():
    with _registry_lock:
        snap = dict(_snapshot)
        running = _running
        stopping = _stopping
        v_workers = sum(
            1 for worker in _vehicle_workers
            if worker.is_alive()
        )

        r_workers = sum(
            1 for worker in _rsu_workers
            if worker.is_alive()
        )

        h_ctx = bool(
            _context_worker
            and _context_worker.is_alive()
        )

        h_stat = bool(
            _status_worker
            and _status_worker.is_alive()
        )

        h_clock = bool(
            _clock_worker
            and _clock_worker.is_alive()
        )
        h_generator = bool(
            _application_generator_worker
            and _application_generator_worker.is_alive()
        )
        cfg = _cfg

    context = snap.get("context", {}) or {}

    active_apps = list(
        Application.objects.filter(
            is_progress=True
        ).values(
            "id",
            "vehicle_id_id",
            "application_type_id_id",
            "start_at"
        )
    )

    all_apps = list(
        Application.objects.all().values(
            "id",
            "vehicle_id_id",
            "application_type_id_id",
            "is_progress",
            "start_at",
            "end_at"
        )
    )

    sample_tasks = list(
        Task.objects.all().values(
            "id",
            "index",
            "application_type_id_id",
            "workload_cycles"
        )[:20]
    )

    executions = list(
        TaskExecution.objects.all().values(
            "id",
            "task_id_id",
            "application_id_id",
            "sp_id_id",
            "start_time",
            "end_time"
        )[:20]
    )

    providers = list(
        ServiceProvider.objects.all().values(
            "id",
            "type",
            "rsu_id_id",
            "vehicle_id_id"
        )
    )

    return {
        "running": running,
        "stopping": stopping,

        "workers": {
            "vehicle": v_workers,
            "rsu": r_workers,
            "context": h_ctx,
            "status": h_stat,
            "clock": h_clock,
            "task_generator": h_generator,
        },

        "counts": {
            "vehicles": Vehicle.objects.count(),
            "rsus": RSU.objects.count(),
            "applications": len(all_apps),
            "applications_active": len(active_apps),
            "tasks": Task.objects.count(),
            "taskexecutions": TaskExecution.objects.count(),
            "cache_items": CacheModel.objects.count(),
            "providers": ServiceProvider.objects.count(),
        },

        "application_debug": {
            "active": active_apps,
            "all": all_apps,
        },

        "task_debug": sample_tasks,

        "execution_debug": executions,

        "provider_debug": providers,

        "context": context,

        "cfg": {
            "total_time": int(
                getattr(cfg, "total_time", 0) or 0
            ) if cfg else None,
            "tick_seconds": int(
                getattr(cfg, "tick_seconds", 0) or 0
            ) if cfg else None,
            "vehicle_speed_min_kmh": float(
                getattr(cfg, "vehicle_speed_min_kmh", 0.0) or 0.0
            ) if cfg else None,
            "vehicle_speed_max_kmh": float(
                getattr(cfg, "vehicle_speed_max_kmh", 0.0) or 0.0
            ) if cfg else None,
            "application_rate_per_second": float(
                getattr(cfg, "application_rate_per_second", 0.0) or 0.0
            ) if cfg else None,
            "runtime_batch_interval_s": int(
                getattr(cfg, "runtime_batch_interval_s", 0) or 0
            ) if cfg else None,
            "runtime_batch_size": int(
                getattr(cfg, "runtime_batch_size", 0) or 0
            ) if cfg else None,
            "runtime_mission_vehicle_ids": list(
                getattr(cfg, "runtime_mission_vehicle_ids", []) or []
            ) if cfg else [],
            "runtime_batches_released": int(
                getattr(cfg, "runtime_batches_released", 0) or 0
            ) if cfg else 0,
            "runtime_batches_completed": int(
                getattr(cfg, "runtime_batches_completed", 0) or 0
            ) if cfg else 0,
            "runtime_created_applications": int(
                getattr(cfg, "runtime_created_applications", 0) or 0
            ) if cfg else 0,
            "runtime_skipped_applications": int(
                getattr(cfg, "runtime_skipped_applications", 0) or 0
            ) if cfg else 0,
            "runtime_scheduler_busy": bool(
                getattr(cfg, "runtime_scheduler_busy", None)
                and cfg.runtime_scheduler_busy.is_set()
            ) if cfg else False,
            "runtime_last_error": getattr(
                cfg, "runtime_last_error", None
            ) if cfg else None,
            "runtime_last_batch_metrics": getattr(
                cfg, "runtime_last_batch_metrics", None
            ) if cfg else None,
            "tmax": int(
                getattr(cfg, "tmax", 10) or 10
            ) if cfg else None,
        },
        "simulation_clock": {
                "sim_time_s": _get_sim_time_s(),
                "total_time_s": int(getattr(cfg, "total_time", 0) or 0)
                if cfg else None,
                "progress": (
                    float(_get_sim_time_s()) / float(cfg.total_time)
                    if cfg and cfg.total_time
                    else 0
                ),
            },
        "snapshot_ts": snap.get("ts"),

        "server_time": timezone.now().isoformat(),
    }