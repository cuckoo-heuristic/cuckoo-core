from application.models import Application
from dag.models import Task, TaskDependency, TaskType
from execution.models import TaskExecution
from django.db.models import Max
import json


def _i(x, d=0):
    try:
        return int(x)
    except:
        try:
            return int(float(x))
        except:
            return d


def _f(x, d=0.0):
    try:
        return float(x)
    except:
        try:
            return float(str(x))
        except:
            return d


def _bits(x):
    v = _f(x, 0.0)
    return int(v * 8)


def _as_dict(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except:
            return {}
    return {}


def _size_to_bits(sz):
    v = _i(sz, 0)
    if v <= 0:
        return 0
    if v < 1024 * 1024:
        return v * 8
    return v


def build_application(ctx, write_db=False):
    application_id = ctx.get("application_id")
    if not application_id:
        ctx["fail_reason"] = "missing_application_id"
        ctx["tasks"] = {"all": [], "ready": []}
        return ctx

    app = Application.objects.select_related("application_type_id").get(id=application_id)
    app_type = app.application_type_id

    deadline_s = _f(app_type.deadline)
    max_deadline = (
        Application.objects.aggregate(Max("application_type_id__deadline"))
    )["application_type_id__deadline__max"]

    ctx["application"] = {
        "id": int(app.id),
        "application_type_id": int(app_type.id),
        "deadline_ms": _i(app_type.deadline * 1000),
    }

    ctx["t_ddl_s"] = deadline_s
    ctx["deadline_s"] = deadline_s
    ctx["deadline_max_s"] = _f(max_deadline, deadline_s)

    qs = Task.objects.filter(
        application_type_id=app.application_type_id
    ).select_related("task_type_id").order_by("id")

    tids = []
    cpu_cycles = {}
    task_type_ids = {}
    sizes_bits = {}

    for t in qs:
        tids.append(t.id)
        cpu_cycles[t.id] = _f(t.workload_cycles, 0.0)

        if t.task_type_id:
            tt = t.task_type_id
            task_type_ids[t.id] = tt.id
            sizes_bits[t.id] = _size_to_bits(tt.size)
        else:
            task_type_ids[t.id] = None
            sizes_bits[t.id] = 0

    ctx["task_ids"] = tids
    ctx["cpu_cycles"] = cpu_cycles
    ctx["task_type_ids"] = task_type_ids
    ctx["task_type_size_bits"] = sizes_bits

    deps = {tid: [] for tid in tids}
    ch = {tid: [] for tid in tids}

    dependency_rows = TaskDependency.objects.filter(
        parent_task_id_id__in=tids,
        child_task_id_id__in=tids,
    ).values("parent_task_id_id", "child_task_id_id", "initial_snapshot")

    intermediate_bits = {}

    for row in dependency_rows:
        p = row["parent_task_id_id"]
        c = row["child_task_id_id"]

        deps[c].append(p)
        ch[p].append(c)

        snap = _as_dict(row.get("initial_snapshot"))
        v = snap.get("data_bits") or snap.get("data_size_bits") or snap.get("intermediate_data_bits")

        intermediate_bits[(p, c)] = _f(v, 0.0)

    ctx["dependencies"] = deps
    ctx["children"] = ch
    ctx["intermediate_data_bits"] = intermediate_bits

    ready = [t for t in tids if not deps[t]]

    ctx["tasks"] = {
        "all": tids,
        "ready": ready,
    }

    execs = TaskExecution.objects.filter(application_id_id=app.id).values()
    ctx["task_executions"] = list(execs)

    done_ids = set(
        TaskExecution.objects.filter(
            application_id_id=app.id,
            end_time__isnull=False
        ).values_list("task_id_id", flat=True)
    )
    running_ids = set(
        TaskExecution.objects.filter(
            application_id_id=app.id,
            end_time__isnull=True
        ).values_list("task_id_id", flat=True)
    )

    ready_true = []
    for tid in tids:
        if tid in done_ids or tid in running_ids:
            continue
        parents = deps.get(tid, [])
        if all(p in done_ids for p in parents):
            ready_true.append(tid)

    ctx["tasks"]["ready"] = ready_true

    cw = {tt_id: 1e6 for tt_id in set(task_type_ids.values()) if tt_id}
    ctx["compile_workloads"] = cw

    providers = list(ctx.get("sp_cpu_freq", {}).keys())

    z_compact = {tid: {"provider": None, "rank": None} for tid in tids}
    z_binary = {sp: {} for sp in providers}

    ctx["z"] = {
        "compact": z_compact,
        "binary": z_binary,
    }

    ctx["X"] = {tid: None for tid in tids}

    return ctx
