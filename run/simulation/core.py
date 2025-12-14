import math
from typing import Dict, List, Optional, Tuple

from vehicle.models import Vehicle
from rsu.models import RSU

from .scenario import Scenario
from .policies.base import PolicyBase, Task, VehicleState, RSUState


# ---------- geometry helpers (همان قبلی‌ها، فقط منتقل شده‌اند) ----------

def _extract_point(p):
    if isinstance(p, dict):
        if "x" in p and "y" in p:
            return float(p["x"]), float(p["y"])
        if "lng" in p and "lat" in p:
            return float(p["lng"]), float(p["lat"])
        if "lon" in p and "lat" in p:
            return float(p["lon"]), float(p["lat"])
        raise ValueError(f"Unsupported dict point format: {p}")

    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return float(p[0]), float(p[1])

    raise ValueError(f"Unsupported path point format: {p}")


def _compute_path_geometry(path):
    if not path or len(path) < 2:
        return [], [0.0]
    points = [_extract_point(p) for p in path]

    cumulative_lengths = [0.0]
    total = 0.0
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        total += seg
        cumulative_lengths.append(total)
    return points, cumulative_lengths


def _interpolate_position(points, cumulative_lengths, distance_along):
    if not points:
        return None, None
    total_length = cumulative_lengths[-1]
    if total_length <= 0:
        return points[0]
    if distance_along <= 0:
        return points[0]
    if distance_along >= total_length:
        return points[-1]

    for i in range(len(cumulative_lengths) - 1):
        d_start = cumulative_lengths[i]
        d_end = cumulative_lengths[i + 1]
        if d_start <= distance_along <= d_end:
            seg_len = d_end - d_start
            ratio = 0.0 if seg_len <= 0 else (distance_along - d_start) / seg_len
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            return (x1 + ratio * (x2 - x1), y1 + ratio * (y2 - y1))
    return points[-1]


def _find_serving_rsu(x, y, rsus: List[RSUState], rsu_radius: float) -> Optional[int]:
    if x is None or y is None:
        return None
    best_id = None
    best_dist = None
    for r in rsus:
        d = math.hypot(r.x - x, r.y - y)
        if d <= rsu_radius:
            if best_dist is None or d < best_dist:
                best_dist = d
                best_id = r.id
    return best_id


def _find_neighbors(vehicle: VehicleState, vehicles: List[VehicleState], v2v_radius: float) -> List[VehicleState]:
    """
    نزدیک‌ترین همسایه‌ها (داخل شعاع) را برمی‌گرداند.
    """
    if vehicle.x is None or vehicle.y is None:
        return []
    out = []
    for v in vehicles:
        if v.id == vehicle.id:
            continue
        if v.x is None or v.y is None:
            continue
        d = math.hypot(v.x - vehicle.x, v.y - vehicle.y)
        if d <= v2v_radius:
            out.append(v)
    # نزدیک‌ترها جلوتر
    out.sort(key=lambda vv: math.hypot(vv.x - vehicle.x, vv.y - vehicle.y))
    return out


# ---------- busy scheduling helpers ----------

def _compute_exec_time(required_cpu: int, cpu_capacity: int) -> float:
    cap = float(cpu_capacity)
    if cap <= 0:
        return float("inf")
    return float(required_cpu) / cap


def _schedule(created_at: float, required_cpu: int, cpu_capacity: int, busy_until: float) -> Optional[dict]:
    exec_time = _compute_exec_time(required_cpu, cpu_capacity)
    if exec_time == float("inf"):
        return None
    start_at = max(float(created_at), float(busy_until))
    end_at = start_at + exec_time
    return {
        "start_at": start_at,
        "end_at": end_at,
        "exec_time": exec_time,
        "queue_delay": start_at - float(created_at),
    }


def _required_cpu_pattern(vehicle_cpu_capacity: int, task_index_mod3: int) -> int:
    cap = int(vehicle_cpu_capacity)
    if cap <= 0:
        return 0
    if task_index_mod3 == 0:
        return int(cap * 0.3)
    if task_index_mod3 == 1:
        return int(cap * 0.9)
    return int(cap * 1.3)


# ---------- public core API ----------

def simulate(scenario: Scenario, policy: PolicyBase, output_mode: str = "snapshot") -> Dict[str, object]:

    # 1) read DB
    vehicles_qs = Vehicle.objects.filter(id__in=scenario.vehicle_ids)
    found_ids = list(vehicles_qs.values_list("id", flat=True))
    missing_ids = [vid for vid in scenario.vehicle_ids if vid not in found_ids]

    rsu_qs = RSU.objects.all()
    rsus = [
        RSUState(id=r.id, x=float(r.x_coord), y=float(r.y_coord), cpu_capacity=int(r.cpu_capacity))
        for r in rsu_qs
    ]

    # 2) prepare movement geometry
    sim_vehicles = []
    for v in vehicles_qs:
        points, cum = _compute_path_geometry(v.path or [])
        total_length = cum[-1] if cum else 0.0
        speed = (total_length / float(scenario.time_simulate)) if total_length > 0 else 0.0
        sim_vehicles.append(
            {
                "id": v.id,
                "points": points,
                "cum": cum,
                "total_length": total_length,
                "speed": speed,
                "cpu_capacity": int(v.cpu_capacity),
            }
        )
        

    # 3) busy trackers (in-memory)
    vehicle_busy_until: Dict[int, float] = {sv["id"]: 0.0 for sv in sim_vehicles}
    rsu_busy_until: Dict[int, float] = {r.id: 0.0 for r in rsus}

    # ⭐ همه taskهای schedule شده را نگه می‌داریم تا “active task” را بفهمیم
    scheduled_tasks_all: List[dict] = []

    timeline = []
    t = 0
    prev_t = -1

    last_frame = None  # برای snapshot

    while t <= scenario.time_simulate:
        # 4.1) build vehicle states at time t
        vehicles_state: List[VehicleState] = []
        for sv in sim_vehicles:
            if not sv["points"] or sv["total_length"] <= 0:
                x, y = None, None
            else:
                dist_along = sv["speed"] * t
                x, y = _interpolate_position(sv["points"], sv["cum"], dist_along)

            rsu_id = _find_serving_rsu(x, y, rsus, scenario.rsu_radius)
            vehicles_state.append(
                VehicleState(
                    id=sv["id"],
                    x=x,
                    y=y,
                    rsu_id=rsu_id,
                    cpu_capacity=sv["cpu_capacity"],
                )
            )

        # 4.2) task times in (prev_t, t]
        task_times = []
        k = 0
        while True:
            tt = k * scenario.time_task
            if tt > scenario.time_simulate:
                break
            if prev_t < tt <= t:
                task_times.append(tt)
            k += 1

        tasks_in_frame = []

        # 4.3) create + decide + schedule each task
        for created_at in task_times:
            idx = int(created_at // scenario.time_task) if scenario.time_task > 0 else 0
            mod3 = idx % 3

            for v in vehicles_state:
                required = _required_cpu_pattern(v.cpu_capacity, mod3)
                task = Task(
                    task_id=f"task-{v.id}-{created_at}",
                    vehicle_id=v.id,
                    created_at=float(created_at),
                    required_cpu=int(required),
                )

                neighbors = _find_neighbors(v, vehicles_state, scenario.v2v_radius)

                decision = policy.decide(task, v, rsus, neighbors, now=float(t))

                record = {
                    "task_id": task.task_id,
                    "vehicle_id": task.vehicle_id,     # مالک/منشأ task
                    "created_at": task.created_at,
                    "required_cpu": task.required_cpu,
                    "decision": decision.type,
                    "assigned_to": None,               # اجراکننده واقعی
                    "rsu_context": v.rsu_id,           # RSU لحظه‌ای مالک task
                }

                timing = None

                if decision.type == "local":
                    timing = _schedule(task.created_at, task.required_cpu, v.cpu_capacity, vehicle_busy_until[v.id])
                    if timing is not None:
                        vehicle_busy_until[v.id] = timing["end_at"]
                        record["assigned_to"] = {"type": "vehicle", "id": v.id}

                elif decision.type == "rsu" and decision.target_id is not None:
                    r_id = decision.target_id
                    rsu_state = next((rr for rr in rsus if rr.id == r_id), None)
                    if rsu_state is not None:
                        timing = _schedule(task.created_at, task.required_cpu, rsu_state.cpu_capacity, rsu_busy_until[r_id])
                        if timing is not None:
                            rsu_busy_until[r_id] = timing["end_at"]
                            record["assigned_to"] = {"type": "rsu", "id": r_id}

                elif decision.type == "v2v" and decision.target_id is not None:
                    n_id = decision.target_id
                    neighbor_state = next((vv for vv in vehicles_state if vv.id == n_id), None)
                    if neighbor_state is not None:
                        timing = _schedule(task.created_at, task.required_cpu, neighbor_state.cpu_capacity, vehicle_busy_until[n_id])
                        if timing is not None:
                            vehicle_busy_until[n_id] = timing["end_at"]
                            record["assigned_to"] = {"type": "vehicle", "id": n_id}

                if timing is None and decision.type != "dropped":
                    record["decision"] = "dropped"
                    record["assigned_to"] = None

                if timing is not None:
                    record.update(timing)
                    # ⭐ برای snapshot: همه تسک‌های schedule شده را نگه می‌داریم
                    scheduled_tasks_all.append(record)

                tasks_in_frame.append(record)

        # derive RSU active
        rsu_active_count: Dict[int, int] = {r.id: 0 for r in rsus}
        for v in vehicles_state:
            if v.rsu_id is not None:
                rsu_active_count[int(v.rsu_id)] += 1

        rsu_frame = [
            {
                "id": r.id,
                "is_active": rsu_active_count[r.id] > 0,
                "active_vehicle_count": rsu_active_count[r.id],
                "busy_until": rsu_busy_until[r.id],
            }
            for r in rsus
        ]

        # ⭐ برای snapshot: “task فعال/آخرین task هر خودرو” را از کل scheduled_tasks_all می‌کشیم بیرون
        def pick_vehicle_task(vehicle_id: int, now_t: float) -> Optional[dict]:
            # active: start_at <= now < end_at
            active = [
                tt for tt in scheduled_tasks_all
                if int(tt["vehicle_id"]) == int(vehicle_id)
                and ("start_at" in tt and "end_at" in tt)
                and float(tt["start_at"]) <= now_t < float(tt["end_at"])
            ]
            if active:
                # اگر چندتا بود (نادر)، نزدیک‌ترین به الآن را بده
                active.sort(key=lambda z: float(z["start_at"]), reverse=True)
                return active[0]

            # اگر active نبود، آخرین task finished شده را بده (برای نمایش “آخرین task”)
            finished = [
                tt for tt in scheduled_tasks_all
                if int(tt["vehicle_id"]) == int(vehicle_id)
                and ("end_at" in tt)
                and float(tt["end_at"]) <= now_t
            ]
            if finished:
                finished.sort(key=lambda z: float(z["created_at"]), reverse=True)
                return finished[0]

            return None

        vehicles_out = []
        for v in vehicles_state:
            vt = pick_vehicle_task(v.id, float(t))
            vehicles_out.append(
                {
                    "id": v.id,
                    "x": v.x,
                    "y": v.y,
                    "rsu_id": v.rsu_id,
                    "is_current": v.rsu_id is not None,

                    # فقط اطلاعاتی که گفتی:
                    "task": None if vt is None else {
                        "task_id": vt["task_id"],
                        "created_at": vt["created_at"],
                        "required_cpu": vt["required_cpu"],
                        "decision": vt["decision"],
                        "assigned_to": vt.get("assigned_to"),
                        "start_at": vt.get("start_at"),
                        "end_at": vt.get("end_at"),
                    }
                }
            )

        frame = {
            "time": t,
            "vehicles": vehicles_out,
            "rsus": rsu_frame,
            "tasks": tasks_in_frame,  # در snapshot می‌تونیم بعداً حذفش کنیم
        }

        last_frame = frame

        if output_mode == "timeline":
            timeline.append(frame)

        prev_t = t
        t += scenario.time_step

    base = {
        "db_check": {
            "found_vehicle_ids": found_ids,
            "missing_vehicle_ids": missing_ids,
            "vehicle_count": len(found_ids),
        },
        "rsu_info": {"coverage_radius": scenario.rsu_radius, "rsu_count": len(rsus)},
        "v2v_info": {"v2v_radius": scenario.v2v_radius},
    }

    if output_mode == "snapshot":
        # ✅ فقط وضعیت نهایی (بدون timeline و metrics)
        # اگر حتی tasks_in_frame هم نمی‌خوای، می‌تونیم اینجا حذفش کنیم
        last_frame.pop("tasks", None)
        return {**base, "state": last_frame}

    return {**base, "timeline": timeline}
