import threading
from datetime import timedelta
import traceback
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
    if cell_radius_rsu <= 0.0:
        raise ValueError(
            f"Invalid parameter: cell_radius_rsu={cell_radius_rsu}"
        )
    base_time = timezone.now()

    cfg = SimulationConfig(
        total_time=total_time,
        tick_seconds=1,
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

    return cfg
def _sim_now_dt(base_time, sim_time_s: float):
    bt = base_time or timezone.now()
    return bt + timedelta(seconds=float(sim_time_s))


def _get_sim_time_s() -> float:
    with _registry_lock:
        return float(_sim_time_s)


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
        while (not self._stop_flag.is_set()) and (t < float(total_time)):
            if self._stop_flag.wait(clock_tick):
                break
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
    global _running, _vehicle_workers, _rsu_workers, _status_worker, _context_worker, _clock_worker, _application_generator_worker, _cfg

    with _registry_lock:
        if _running:
            return
        _running = True

    try:
        params = load_params_obj()
        cfg = _build_cfg(params)
        cfg.tmax = int(tmax)
        cfg.get_sim_time_s = _get_sim_time_s
        _cfg = cfg

        _set_sim_time_s(0.0)
        _set_stop_requested(False)
        ensure_service_providers()

        _clock_worker = ClockWorker(cfg=cfg)
        _vehicle_workers = [
            VehicleWorker(vehicle_id=vehicle.id, cfg=cfg)
            for vehicle in Vehicle.objects.all()
        ]
        _application_generator_worker = ApplicationGeneratorWorker(cfg=cfg)
        _rsu_workers = [
            RSUWorker(rsu_id=rsu.id, cfg=cfg)
            for rsu in RSU.objects.order_by("id")
        ]
        _status_worker = StatusWorker(cfg=cfg)
        _context_worker = ContextWorker(cfg=cfg)

        _clock_worker.start()

        for worker in _vehicle_workers:
            worker.start()

        threading.Event().wait(cfg.motion_tick_seconds)
        _application_generator_worker.start()

        for worker in _rsu_workers:
            worker.start()

        _status_worker.start()
        _context_worker.start()

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


def stop_simulation():
    global _running
    with _registry_lock:
        if not _running:
            return
        workers = list(_vehicle_workers + _rsu_workers)
        generator_w = _application_generator_worker
        status_w = _status_worker
        ctx_w = _context_worker
        clock_w = _clock_worker
    if generator_w:
        generator_w.stop()
    if status_w:
        status_w.stop()
    if ctx_w:
        ctx_w.stop()
    if clock_w:
        clock_w.stop()
    for w in workers:
        w.stop()
    cur = threading.current_thread()
    if generator_w and generator_w is not cur:
        generator_w.join()
    if status_w and status_w is not cur:
        status_w.join()
    if ctx_w and ctx_w is not cur:
        ctx_w.join()
    if clock_w and clock_w is not cur:
        clock_w.join()
    for w in workers:
        if w is not cur:
            w.join()
    with _registry_lock:
        _running = False

    # Do not rewrite TaskExecution times, energy, or Application completion data
    # during shutdown. Those values are outputs of the scheduling model and must
    # remain unchanged for later verification and benchmark reporting.


def simulation_status():
    with _registry_lock:
        snap = dict(_snapshot)
        running = _running
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