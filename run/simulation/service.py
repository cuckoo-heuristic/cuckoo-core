import threading
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from parameter.services import load_params_obj

from object.models import RSU, RSUVehicle, Vehicle
from cache.models import cache as CacheModel
from resource.models import Resource
from dag.models import Task
from execution.models import TaskExecution
from application.models import Application

from run.worker.vehicle import VehicleWorker, SimulationConfig
from run.worker.rsu import RSUWorker
from system.build_context import MiniSystemContextBuilder as build_context


_registry_lock = threading.Lock()

_vehicle_workers = []
_rsu_workers = []
_status_worker = None
_context_worker = None
_clock_worker = None
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
    total_time = _safe_int(getattr(params, "simulate_time", None), "simulate_time")
    scheduling_tick = _safe_int(getattr(params, "taking_task_time", None), "taking_task_time")
    cell_radius_rsu = _safe_float(getattr(params, "cell_radius_rsu", None), "cell_radius_rsu")

    if total_time <= 0:
        raise ValueError(f"Invalid parameter: simulate_time={total_time}")
    if scheduling_tick <= 0:
        raise ValueError(f"Invalid parameter: taking_task_time={scheduling_tick}")
    if cell_radius_rsu <= 0.0:
        raise ValueError(f"Invalid parameter: cell_radius_rsu={cell_radius_rsu}")

    if scheduling_tick > total_time:
        raise ValueError(f"Invalid parameters: taking_task_time({scheduling_tick}) > simulate_time({total_time})")

    base_time = timezone.now()

    cfg = SimulationConfig(
        total_time=total_time,
        tick_seconds=scheduling_tick,   # این همان app_interval در VehicleWorker است
        cell_radius_rsu=cell_radius_rsu,
        base_time=base_time,
    )

    cfg.clock_tick_seconds = 1
    cfg.motion_tick_seconds = 1

    return cfg


def _close_open_applications() -> None:
    now = timezone.now()
    Application.objects.filter(is_progress=True).update(is_progress=False, end_at=now)


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
            running_ids.append(int(tid))
            continue

        try:
            if st <= now_dt < et:
                running_ids.append(int(tid))
                continue
            if et <= now_dt:
                done_ids.append(int(tid))
        except Exception:
            continue

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

    has_application = app_id is not None

    return {
        "sim_time_s": float(sim_time_s),
        "vehicle_id": int(vehicle_id),
        "rsu_id": actor.get("rsu_id"),
        "neighbors": len(actor.get("neighbor_vehicle_ids") or []),
        "has_application": bool(has_application),
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
        if clock_tick <= 0:
            raise ValueError(f"Invalid cfg.clock_tick_seconds={clock_tick}")
        if total_time <= 0:
            raise ValueError(f"Invalid cfg.total_time={total_time}")

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
        if clock_tick <= 0:
            raise ValueError(f"Invalid cfg.clock_tick_seconds={clock_tick}")

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

    def stop(self):
        self._stop_flag.set()

    def run(self):
        close_old_connections()
        clock_tick = int(getattr(self.cfg, "clock_tick_seconds", 1) or 1)
        if clock_tick <= 0:
            raise ValueError(f"Invalid cfg.clock_tick_seconds={clock_tick}")

        total_time = int(getattr(self.cfg, "total_time", 0) or 0)
        if total_time <= 0:
            raise ValueError(f"Invalid cfg.total_time={total_time}")

        while not self._stop_flag.is_set():
            close_old_connections()

            t = _get_sim_time_s()
            if t > float(total_time):
                t = float(total_time)

            ok = 0
            fail = 0
            sample = None
            last_error = None
            vehicle_summaries = []

            vehicle_ids = list(Vehicle.objects.values_list("id", flat=True))
            for vid in vehicle_ids:
                if self._stop_flag.is_set():
                    break
                try:
                    base = {
                        "actor": {"vehicle_id": int(vid)},
                        "sim_time_s": float(t),
                        "base_time": self.cfg.base_time,
                    }
                    ctx = build_context(base, write_db=False)
                    ok += 1

                    cur_sample = _summarize_ctx(ctx=ctx, vehicle_id=int(vid), sim_time_s=float(t))
                    vehicle_summaries.append(cur_sample)

                    if sample is None:
                        sample = cur_sample
                    else:
                        if (not sample.get("has_application")) and cur_sample.get("has_application"):
                            sample = cur_sample
                except Exception as e:
                    fail += 1
                    last_error = str(e)

            with _registry_lock:
                _snapshot["context"] = {
                    "ok": ok,
                    "fail": fail,
                    "sample": sample,
                    "vehicles": vehicle_summaries,
                    "sim_time_s": float(t),
                    "base_time": self.cfg.base_time,
                    "base_time_type": type(self.cfg.base_time).__name__ if self.cfg.base_time is not None else None,
                    "last_error": last_error,
                }

            if _get_stop_requested() and float(t) >= float(total_time):
                try:
                    stop_simulation()
                except Exception:
                    pass
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


def run_simulation(a1: int = 1, a2: int = 1, a3: int = 1):
    global _running, _vehicle_workers, _rsu_workers, _status_worker, _context_worker, _clock_worker, _cfg

    with _registry_lock:
        if _running:
            return
        _running = True
        _stop_requested = False

    params = load_params_obj()
    cfg = _build_cfg(params)
    _cfg = cfg
    _set_sim_time_s(0.0)
    _set_stop_requested(False)

    _clock_worker = ClockWorker(cfg=cfg)
    _vehicle_workers = [VehicleWorker(vehicle_id=v.id, cfg=cfg) for v in Vehicle.objects.all()]
    _rsu_workers = [RSUWorker(rsu_id=r.id, cfg=cfg) for r in RSU.objects.all()]

    _status_worker = StatusWorker(cfg=cfg)
    _context_worker = ContextWorker(cfg=cfg)

    _clock_worker.start()

    for w in _vehicle_workers + _rsu_workers:
        w.start()

    _status_worker.start()
    _context_worker.start()


def stop_simulation():
    global _running

    with _registry_lock:
        if not _running:
            return

        workers = list(_vehicle_workers + _rsu_workers)
        status_w = _status_worker
        ctx_w = _context_worker
        clock_w = _clock_worker
        cfg = _cfg
        sim_time_s = float(_sim_time_s)

    if status_w is not None:
        status_w.stop()
    if ctx_w is not None:
        ctx_w.stop()
    if clock_w is not None:
        clock_w.stop()

    for w in workers:
        w.stop()

    cur = threading.current_thread()

    if status_w is not None and status_w is not cur:
        status_w.join()
    if ctx_w is not None and ctx_w is not cur:
        ctx_w.join()
    if clock_w is not None and clock_w is not cur:
        clock_w.join()

    for w in workers:
        if w is not cur:
            w.join()

    with _registry_lock:
        _running = False

    if cfg is not None:
        total_time = int(getattr(cfg, "total_time", 0) or 0)
        if total_time > 0:
            sim_time_s = float(total_time)

        horizon_dt = _sim_now_dt(getattr(cfg, "base_time", None), float(sim_time_s))
        try:
            with transaction.atomic():
                qs = TaskExecution.objects.filter(start_time__lte=horizon_dt).filter(
                    Q(end_time__isnull=True) | Q(end_time__gt=horizon_dt)
                )
                for te in qs.select_related("application_id", "task_id", "sp_id"):
                    te.end_time = horizon_dt
                    try:
                        if te.start_time is not None and te.end_time is not None:
                            te.exec_time = float((te.end_time - te.start_time).total_seconds())
                    except Exception:
                        pass
                    te.save(update_fields=["end_time", "exec_time"])
        except Exception:
            pass

    _close_open_applications()


def simulation_status():
    with _registry_lock:
        snap = dict(_snapshot)
        running = _running
        vehicle_workers = len(_vehicle_workers)
        rsu_workers = len(_rsu_workers)
        has_context = _context_worker is not None
        has_status = _status_worker is not None
        cfg = _cfg

    context = snap.get("context", {}) or {}
    sample = context.get("sample") or {}

    cfg_info = None
    if cfg is not None:
        cfg_info = {
            "total_time": int(getattr(cfg, "total_time", 0) or 0),
            "tick_seconds": int(getattr(cfg, "tick_seconds", 0) or 0),
            "cell_radius_rsu": float(getattr(cfg, "cell_radius_rsu", 0.0) or 0.0),
        }

    return {
        "running": running,
        "workers": {
            "vehicle": vehicle_workers,
            "rsu": rsu_workers,
            "task_generator": False,  # دیگر worker جداگانه‌ای برای task/app نداریم
            "context": has_context,
            "status": has_status,
        },
        "counts": {
            "vehicles": Vehicle.objects.count(),
            "rsus": RSU.objects.count(),
            "rsu_vehicle_total": RSUVehicle.objects.count(),
            "rsu_vehicle_open": RSUVehicle.objects.filter(end_time__isnull=True).count(),
            "applications": Application.objects.count(),
            "applications_in_progress": Application.objects.filter(is_progress=True).count(),
            "tasks": Task.objects.count(),
            "taskexecutions": TaskExecution.objects.count(),
            "cache_items": CacheModel.objects.count(),
        },
        "context": {
            "ok": context.get("ok", 0),
            "fail": context.get("fail", 0),
            "sample": sample,
            "vehicles": context.get("vehicles") or [],
            "sim_time_s": context.get("sim_time_s"),
            "base_time": context.get("base_time"),
            "base_time_type": context.get("base_time_type"),
            "last_error": context.get("last_error"),
        },
        "cfg": cfg_info,
        "sanity": {
            "ctx_running": context.get("ok", 0) > 0,
            "ctx_no_error": context.get("fail", 0) == 0,
            "has_application": bool(sample.get("has_application")),
            "has_ready_tasks": (sample.get("ready_tasks", 0) > 0)
            if "ready_tasks" in sample
            else (sample.get("ready_tasks_count", 0) > 0),
            "ready_task_ids_sample": sample.get("ready_task_ids") or [],
            "done_task_ids_sample": sample.get("done_task_ids") or [],
            "blocked_task_ids_sample": sample.get("blocked_task_ids") or [],
            "db_debug_sample": (sample.get("db_debug") or {}),
        },
        "snapshot_ts": snap.get("ts"),
    }
