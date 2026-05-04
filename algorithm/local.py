import random
from datetime import timedelta
from collections import defaultdict, deque
from django.utils import timezone
from django.db import transaction

from application.models import Application
from dag.models import Task, TaskDependency
from execution.models import TaskExecution
from object.models import ServiceProvider, Vehicle
from cache.models import cache
from resource.models import Resource
from state.models import State

from monarch_pylib.model import offloading_efficiency


def get_application_tasks_dag(application):
    tasks = list(Task.objects.filter(application_type_id=application.application_type_id))
    task_map = {t.id: t for t in tasks}
    deps = TaskDependency.objects.filter(parent_task_id__in=tasks, child_task_id__in=tasks)
    graph = defaultdict(list)
    indegree = defaultdict(int)
    for d in deps:
        if d.parent_task_id_id and d.child_task_id_id:
            graph[d.parent_task_id_id].append(d.child_task_id_id)
            indegree[d.child_task_id_id] += 1
    q = deque()
    for t in tasks:
        if indegree[t.id] == 0:
            q.append(t.id)
    order = []
    while q:
        node = q.popleft()
        order.append(task_map[node])
        for nxt in graph[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                q.append(nxt)
    return order


def compute_local_exec_time(task, vehicle, context=None, params=None):
    context = context or {}
    params = params or {}
    cpu_cycles = context.get("cpu_cycles") or task.workload_cycles
    fmax = context.get("fmax_vehicle_hz") or params.get("fmax_vehicle_hz") or vehicle.cpu_capacity
    res = offloading_efficiency.all_local_execution_time(
        cpu_cycles_list=[cpu_cycles],
        f_max_local_hz=float(fmax),
    )
    return float(res[0])


def compute_local_energy(task, vehicle, context=None, params=None):
    context = context or {}
    params = params or {}
    cpu_cycles = context.get("cpu_cycles") or task.workload_cycles
    fmax = context.get("fmax_vehicle_hz") or params.get("fmax_vehicle_hz") or vehicle.cpu_capacity
    kappa = params.get("k", 1e-25)
    res = offloading_efficiency.all_local_execution_energy(
        kappa=float(kappa),
        cpu_cycles_list=[cpu_cycles],
        f_max_local_hz=float(fmax),
    )
    return float(res[0])


def execute_task_locally(application, task, vehicle, start_time, context=None, params=None):
    exec_time = compute_local_exec_time(task, vehicle, context, params)
    energy = compute_local_energy(task, vehicle, context, params)
    end_time = start_time + timedelta(seconds=exec_time)
    sp = ServiceProvider.objects.get(vehicle_id=vehicle, type="vehicle")
    te = TaskExecution.objects.create(
        application_id=application,
        task_id=task,
        sp_id=sp,
        start_time=start_time,
        end_time=end_time,
        energy=energy,
        initial_snapshot={"mode": "local", "workload_cycles": task.workload_cycles},
    )
    return te


def create_state_record(task_execution, vehicle, time_step):
    State.objects.create(
        time_step=time_step,
        task_execution_id=task_execution,
        from_vehicle_id=vehicle,
        to_vehicle_id=vehicle,
        gain=0.0,
        distance=0.0,
        rate=0.0,
        initial_snapshot={"execution": "local"}
    )


def try_cache_task(sp, task, probability=0.5):
    if random.random() > probability:
        return False
    cache.objects.create(
        sp_id=sp,
        task_type_id=task.task_type_id,
        initial_snapshot={"cached_randomly": True}
    )
    return True


def update_local_resource(vehicle, cpu_used, cache_used):
    sp = ServiceProvider.objects.get(vehicle_id=vehicle, type="vehicle")
    Resource.objects.update_or_create(
        sp_id=sp,
        defaults={
            "cpu_used": cpu_used,
            "cache_used": cache_used,
        }
    )


def run_local_execution(application_id, context=None, params=None, cache_probability=0.5):
    context = context or {}
    params = params or {}

    application = Application.objects.get(id=application_id)
    vehicle = application.vehicle_id
    tasks = get_application_tasks_dag(application)

    current_time = application.start_at or timezone.now()
    time_step = 0
    sp = ServiceProvider.objects.get(vehicle_id=vehicle, type="vehicle")
    cpu_used_total = 0
    cache_used_total = 0

    with transaction.atomic():
        for task in tasks:
            te = execute_task_locally(
                application=application,
                task=task,
                vehicle=vehicle,
                start_time=current_time,
                context=context,
                params=params
            )
            create_state_record(te, vehicle, time_step)
            cpu_used = task.workload_cycles
            cached = try_cache_task(sp, task, probability=cache_probability)
            cache_used = getattr(task.task_type_id, "size", 0) if cached else 0
            cpu_used_total += cpu_used
            cache_used_total += cache_used
            update_local_resource(
                vehicle=vehicle,
                cpu_used=cpu_used_total,
                cache_used=cache_used_total
            )
            current_time = te.end_time
            time_step += 1

        application.is_progress = False
        application.end_at = current_time
        application.save(update_fields=["is_progress", "end_at"])
