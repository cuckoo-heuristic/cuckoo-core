from __future__ import annotations

import threading
import time
import traceback
from datetime import timedelta
from typing import Dict, Any, List, Iterable

from django.db import close_old_connections, transaction, connection
from django.db.models import Max
from django.db.utils import OperationalError
from django.utils import timezone

from object.models import RSUVehicle, ServiceProvider
from execution.models import TaskExecution
from application.models import Application
from cache.models import cache as CacheModel
from resource.models import Resource
from state.models import State
from dag.models import TaskType

from system.build_context import MiniSystemContextBuilder

from algorithm.main_dcsga import dcsga_run, evaluate_solution_quality
from algorithm.greedy_nests import rate
from algorithm.low_complexity import channel_gain

_APP_LOCK_NAMESPACE = 742031
_RUNTIME_SCHEDULER_LOCK_NAMESPACE = 742032
_RUNTIME_SCHEDULER_LOCK_KEY = 1
_MAX_TRANSACTION_RETRIES = 3


def _try_lock_application(application_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s, %s)",
            [_APP_LOCK_NAMESPACE, int(application_id)],
        )
        return bool(cursor.fetchone()[0])


def _unlock_application(application_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s, %s)",
            [_APP_LOCK_NAMESPACE, int(application_id)],
        )


def _lock_runtime_scheduler() -> None:
    """Serialize runtime scheduling so queue and cache snapshots stay consistent."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_lock(%s, %s)",
            [
                _RUNTIME_SCHEDULER_LOCK_NAMESPACE,
                _RUNTIME_SCHEDULER_LOCK_KEY,
            ],
        )


def _unlock_runtime_scheduler() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s, %s)",
            [
                _RUNTIME_SCHEDULER_LOCK_NAMESPACE,
                _RUNTIME_SCHEDULER_LOCK_KEY,
            ],
        )


def _is_deadlock(error: BaseException) -> bool:
    current = error
    visited = set()

    while current is not None and id(current) not in visited:
        visited.add(id(current))

        if getattr(current, "sqlstate", None) == "40P01":
            return True

        if getattr(current, "pgcode", None) == "40P01":
            return True

        current = current.__cause__ or current.__context__

    return False


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

        total_time = float(
            getattr(
                self.cfg,
                "total_time",
                120,
            )
        )

        get_sim_time = getattr(
            self.cfg,
            "get_sim_time_s",
            None,
        )

        fallback_time = 0.0
        last_scan_time = None

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
                t = min(
                    total_time,
                    fallback_time,
                )
                fallback_time += 1.0

            current_time = int(t)

            if (
                last_scan_time is not None
                and current_time == last_scan_time
            ):
                if self._stop_flag.wait(0.1):
                    break
                continue

            last_scan_time = current_time

            try:
                vehicle_ids = list(
                    RSUVehicle.objects.filter(
                        rsu_id_id=self.rsu_id,
                        end_time__isnull=True,
                        is_current=True,
                    ).values_list(
                        "vehicle_id_id",
                        flat=True,
                    )
                )
            except Exception:
                vehicle_ids = []

            for vehicle_id in vehicle_ids:
                if self._stop_flag.is_set():
                    break

                self._handle_vehicle(
                    vehicle_id,
                    current_time,
                )

            if self._stop_flag.wait(0.1):
                break
    def _handle_vehicle(self, vehicle_id: int, t: int):
        try:
            app_ids = list(
                Application.objects.filter(
                    vehicle_id_id=vehicle_id,
                    is_progress=True,
                ).values_list("id", flat=True)
            )

            for app_id in app_ids:
                if self._stop_flag.is_set():
                    break

                if not _try_lock_application(app_id):
                    continue

                scheduler_locked = False

                try:
                    _lock_runtime_scheduler()
                    scheduler_locked = True

                    app = Application.objects.filter(
                        id=app_id,
                        is_progress=True,
                    ).first()

                    if app is None:
                        continue

                    snapshot_time_step = self._current_sim_time_step(t)

                    ctx = MiniSystemContextBuilder(
                        application_id=app.id
                    ).build_context()
                    ctx["tmax"] = int(
                        getattr(self.cfg, "tmax", 10)
                    )
                    ctx["seed"] = int(
                        getattr(self.cfg, "simulation_seed", 1)
                    )
                    self._apply_runtime_queue_state(
                        ctx,
                        app,
                        snapshot_time_step,
                    )

                    best_solution, quality, cache_state = dcsga_run(ctx)

                    from algorithm.main_dcsga import dcsga_compute_ranks_and_order

                    task_order = dcsga_compute_ranks_and_order(ctx)

                    _, evaluated_cache, scheduled_ctx = evaluate_solution_quality(
                        ctx,
                        best_solution,
                        task_order,
                    )

                    final_cache_state = (
                        evaluated_cache
                        if evaluated_cache is not None
                        else cache_state
                    )

                    entry_task_id = int(scheduled_ctx["entry_task_id"])
                    assigned_provider_ids = sorted({
                        int(provider_id)
                        for _, provider_id, _ in best_solution
                    })
                    cache_provider_ids = sorted({
                        int(provider_id)
                        for task_id, provider_id, _ in best_solution
                        if int(task_id) != entry_task_id
                    })
                    lock_provider_ids = sorted(
                        set(assigned_provider_ids) | set(cache_provider_ids)
                    )

                    self._persist_application(
                        app_id=app_id,
                        best_solution=best_solution,
                        scheduled_ctx=scheduled_ctx,
                        final_cache_state=final_cache_state,
                        cache_provider_ids=cache_provider_ids,
                        lock_provider_ids=lock_provider_ids,
                        time_step=snapshot_time_step,
                    )

                except Exception:
                    traceback.print_exc()

                finally:
                    try:
                        if scheduler_locked:
                            _unlock_runtime_scheduler()
                    finally:
                        _unlock_application(app_id)

        except Exception:
            traceback.print_exc()

    def _current_sim_time_step(self, fallback_time_step: int) -> int:
        get_sim_time = getattr(
            self.cfg,
            "get_sim_time_s",
            None,
        )
        total_time = max(
            0.0,
            float(getattr(self.cfg, "total_time", 120)),
        )

        if callable(get_sim_time):
            value = float(get_sim_time())
        else:
            value = float(fallback_time_step)

        return int(
            min(
                total_time,
                max(0.0, value),
            )
        )

    def _apply_runtime_queue_state(
        self,
        ctx: Dict[str, Any],
        app: Application,
        time_step: int,
    ) -> None:
        """Seed DCSGA with current simulation waiting and provider availability."""
        base_time = getattr(self.cfg, "base_time", None) or timezone.now()
        snapshot_time = base_time + timedelta(seconds=int(time_step))
        reference_time = app.start_at or snapshot_time
        scheduling_time = max(reference_time, snapshot_time)
        elapsed_wait = max(
            0.0,
            float((scheduling_time - reference_time).total_seconds()),
        )

        provider_ids = sorted({
            int(provider_id)
            for provider_id in ctx.get("provider_ids", [])
        })
        provider_initial_finish = {
            provider_id: elapsed_wait
            for provider_id in provider_ids
        }

        if provider_ids:
            latest_rows = (
                TaskExecution.objects
                .filter(
                    sp_id_id__in=provider_ids,
                    end_time__isnull=False,
                    end_time__gt=scheduling_time,
                )
                .exclude(application_id_id=app.id)
                .values("sp_id_id")
                .annotate(latest_end=Max("end_time"))
            )

            for row in latest_rows:
                provider_id = int(row["sp_id_id"])
                latest_end = row["latest_end"]

                if latest_end is None:
                    continue

                provider_initial_finish[provider_id] = max(
                    elapsed_wait,
                    float((latest_end - reference_time).total_seconds()),
                )

        ctx["runtime_snapshot_time_step"] = int(time_step)
        ctx["runtime_waiting_time_s"] = float(elapsed_wait)
        ctx["provider_initial_finish"] = provider_initial_finish

    def _persist_application(
        self,
        app_id: int,
        best_solution: List,
        scheduled_ctx: Dict,
        final_cache_state: Dict[int, Any],
        cache_provider_ids: List[int],
        lock_provider_ids: List[int],
        time_step: int,
    ) -> None:
        for attempt in range(_MAX_TRANSACTION_RETRIES):
            try:
                with transaction.atomic():
                    app = Application.objects.select_for_update().filter(
                        id=app_id,
                        is_progress=True,
                    ).first()

                    if app is None:
                        return
                    effective_time_step = max(0, int(time_step))
                    resources = self._lock_resources(lock_provider_ids)

                    TaskExecution.objects.filter(
                        application_id=app
                    ).delete()

                    max_finish_time = self.apply_offloading(
                        app,
                        best_solution,
                        scheduled_ctx,
                        effective_time_step,
                        resources,
                    )

                    self.apply_cache(
                        final_cache_state,
                        cache_provider_ids,
                        resources,
                    )

                    self._finalize_application(
                        app,
                        effective_time_step,
                        max_finish_time,
                    )

                return

            except OperationalError as error:
                if not _is_deadlock(error) or attempt + 1 >= _MAX_TRANSACTION_RETRIES:
                    raise

                time.sleep(0.05 * (attempt + 1))

    def _lock_resources(
        self,
        provider_ids: Iterable[int],
    ) -> Dict[int, Resource]:
        normalized_ids = sorted({int(provider_id) for provider_id in provider_ids})

        if not normalized_ids:
            return {}

        rows = list(
            Resource.objects.select_for_update()
            .filter(sp_id_id__in=normalized_ids)
            .order_by("sp_id_id", "id")
        )

        resources = {}
        duplicates = []

        for resource in rows:
            sp_id = int(resource.sp_id_id)

            if sp_id in resources:
                duplicates.append(sp_id)
                continue

            resources[sp_id] = resource

        if duplicates:
            raise ValueError(
                f"Duplicate resource rows for providers: {sorted(set(duplicates))}"
            )

        missing = sorted(set(normalized_ids) - set(resources))

        if missing:
            raise ValueError(
                f"Missing resource rows for providers: {missing}"
            )

        return resources

    def apply_offloading(
        self,
        app: Application,
        best_solution: List,
        ctx: Dict,
        time_step: int,
        resources: Dict[int, Resource],
    ) -> float:
        sim_now = app.start_at

        if sim_now is None:
            base_time = getattr(
                self.cfg,
                "base_time",
                timezone.now(),
            )
            sim_now = base_time + timedelta(seconds=time_step)

        schedule_state = ctx.get("_schedule_state", {})
        task_start = schedule_state.get("task_start", {})
        task_finish = schedule_state.get("task_finish", {})
        task_energy = schedule_state.get("task_energy", {})

        solution_task_ids = [
            int(task_id)
            for task_id, _, _ in best_solution
        ]

        missing_start = [
            task_id
            for task_id in solution_task_ids
            if task_id not in task_start
        ]
        missing_finish = [
            task_id
            for task_id in solution_task_ids
            if task_id not in task_finish
        ]

        if missing_start or missing_finish:
            raise ValueError(
                f"Incomplete schedule state: missing_start={missing_start}, "
                f"missing_finish={missing_finish}"
            )

        provider_ids = sorted({
            int(provider_id)
            for _, provider_id, _ in best_solution
        })
        providers = ServiceProvider.objects.select_related(
            "vehicle_id",
            "rsu_id",
        ).in_bulk(provider_ids)

        missing_providers = sorted(
            set(provider_ids) - set(providers)
        )
        if missing_providers:
            raise ValueError(
                f"Missing service providers: {missing_providers}"
            )

        missing_resources = sorted(
            set(provider_ids) - set(resources)
        )
        if missing_resources:
            raise ValueError(
                f"Missing locked resources: {missing_resources}"
            )

        overall_max_t = 0.0
        local_sp_id = ctx.get("local_sp_id")
        cpu_increments = {provider_id: 0 for provider_id in provider_ids}

        for task_id, provider_id, rank in best_solution:
            task_id = int(task_id)
            provider_id = int(provider_id)
            sp = providers[provider_id]

            start_time = float(task_start[task_id])
            finish_time = float(task_finish[task_id])
            energy_value = float(task_energy.get(task_id, 0.0))

            if start_time < 0.0 or finish_time < start_time:
                raise ValueError(
                    f"Invalid schedule for task {task_id}: "
                    f"start={start_time}, finish={finish_time}"
                )

            exec_time = finish_time - start_time
            overall_max_t = max(overall_max_t, finish_time)

            gain_value = 0.0
            rate_value = 0.0

            if local_sp_id is None or provider_id != int(local_sp_id):
                gain_value = float(
                    channel_gain(ctx, provider_id)
                )
                rate_value = float(
                    rate(ctx, provider_id)
                )

            distance_value = 0.0
            if local_sp_id is None or provider_id != int(local_sp_id):
                distance_value = float(
                    ctx.get("distance", {}).get(provider_id, 0.0)
                )

            te = TaskExecution.objects.create(
                application_id=app,
                sp_id=sp,
                task_id_id=task_id,
                start_time=sim_now + timedelta(seconds=start_time),
                end_time=sim_now + timedelta(seconds=finish_time),
                exec_time=exec_time,
                energy=energy_value,
            )

            State.objects.create(
                time_step=time_step,
                task_execution_id=te,
                from_vehicle_id=app.vehicle_id,
                to_vehicle_id=(
                    sp.vehicle_id
                    if sp.vehicle_id_id
                    else None
                ),
                to_rsu_id=(
                    sp.rsu_id
                    if sp.rsu_id_id
                    else None
                ),
                gain=gain_value,
                distance=distance_value,
                rate=rate_value,
            )

            cpu_increments[provider_id] += int(
                ctx["cpu_cycles"].get(task_id, 0)
            )

        for provider_id in provider_ids:
            resource = resources[provider_id]
            resource.cpu_used = int(resource.cpu_used or 0) + int(
                cpu_increments[provider_id]
            )
            resource.save(update_fields=["cpu_used"])

        return overall_max_t

    def apply_cache(
        self,
        cache_state: Dict[int, Any],
        provider_ids: Iterable[int],
        resources: Dict[int, Resource],
    ) -> None:
        normalized_provider_ids = sorted({
            int(provider_id)
            for provider_id in provider_ids
        })

        if not normalized_provider_ids:
            return

        normalized_cache = {
            sp_id: sorted({
                int(task_type_id)
                for task_type_id in (cache_state or {}).get(sp_id, set())
            })
            for sp_id in normalized_provider_ids
        }

        providers = ServiceProvider.objects.select_related(
            "vehicle_id",
            "rsu_id",
        ).in_bulk(normalized_provider_ids)

        missing_providers = sorted(
            set(normalized_provider_ids) - set(providers)
        )
        if missing_providers:
            raise ValueError(
                f"Missing cache service providers: {missing_providers}"
            )

        missing_resources = sorted(
            set(normalized_provider_ids) - set(resources)
        )
        if missing_resources:
            raise ValueError(
                f"Missing locked cache resources: {missing_resources}"
            )

        all_task_type_ids = sorted({
            task_type_id
            for task_types in normalized_cache.values()
            for task_type_id in task_types
        })
        task_type_sizes = dict(
            TaskType.objects.filter(
                id__in=all_task_type_ids
            ).values_list("id", "size")
        )

        missing_task_types = sorted(
            set(all_task_type_ids) - set(task_type_sizes)
        )
        if missing_task_types:
            raise ValueError(
                f"Missing cache task types: {missing_task_types}"
            )

        for sp_id in normalized_provider_ids:
            task_type_ids = normalized_cache[sp_id]
            cache_used = sum(
                int(task_type_sizes[task_type_id] or 0)
                for task_type_id in task_type_ids
            )
            resource = resources[sp_id]

            if cache_used > int(resource.cache_capacity or 0):
                raise ValueError(
                    f"Cache capacity exceeded for provider {sp_id}: "
                    f"used={cache_used}, capacity={resource.cache_capacity}"
                )

            CacheModel.objects.filter(sp_id_id=sp_id).delete()
            CacheModel.objects.bulk_create([
                CacheModel(
                    sp_id_id=sp_id,
                    task_type_id_id=task_type_id,
                )
                for task_type_id in task_type_ids
            ])

            resource.cache_used = int(cache_used)
            resource.save(update_fields=["cache_used"])

    def _finalize_application(
        self,
        app: Application,
        current_t: int,
        duration: float,
    ):
        start_dt = app.start_at

        if start_dt is None:
            base_time = getattr(
                self.cfg,
                "base_time",
                timezone.now(),
            )
            start_dt = base_time + timedelta(seconds=current_t)

        app.is_progress = False
        app.end_at = start_dt + timedelta(
            seconds=max(0.0, float(duration))
        )
        app.save(update_fields=["is_progress", "end_at"])