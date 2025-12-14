import math
from typing import Dict, List, Optional

from rsu.models import RSU
from vehicle.models import Vehicle

from .policies.base import PolicyBase, RSUState, Task, VehicleState
from .scenario import Scenario


def _pt(p):
    if isinstance(p, dict):
        if "x" in p and "y" in p:
            return float(p["x"]), float(p["y"])
        if "lng" in p and "lat" in p:
            return float(p["lng"]), float(p["lat"])
        if "lon" in p and "lat" in p:
            return float(p["lon"]), float(p["lat"])
        raise ValueError(f"Bad point dict: {p}")
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return float(p[0]), float(p[1])
    raise ValueError(f"Bad point: {p}")


def _path_geom(path):
    if not path or len(path) < 2:
        return [], [0.0]
    pts = [_pt(p) for p in path]
    cum = [0.0]
    total = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        total += math.hypot(x2 - x1, y2 - y1)
        cum.append(total)
    return pts, cum


def _interp(pts, cum, d):
    if not pts:
        return None, None
    L = cum[-1]
    if L <= 0 or d <= 0:
        return pts[0]
    if d >= L:
        return pts[-1]
    for i in range(len(cum) - 1):
        a, b = cum[i], cum[i + 1]
        if a <= d <= b:
            seg = b - a
            r = 0.0 if seg <= 0 else (d - a) / seg
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            return x1 + r * (x2 - x1), y1 + r * (y2 - y1)
    return pts[-1]


def _serving_rsu(x, y, rsus: List[RSUState], radius: float) -> Optional[int]:
    if x is None or y is None:
        return None
    best_id, best_d = None, None
    for r in rsus:
        d = math.hypot(r.x - x, r.y - y)
        if d <= radius and (best_d is None or d < best_d):
            best_d, best_id = d, r.id
    return best_id


def _neighbors(v: VehicleState, vs: List[VehicleState], r: float) -> List[VehicleState]:
    if v.x is None or v.y is None:
        return []
    out = []
    for u in vs:
        if u.id == v.id or u.x is None or u.y is None:
            continue
        if math.hypot(u.x - v.x, u.y - v.y) <= r:
            out.append(u)
    out.sort(key=lambda u: math.hypot(u.x - v.x, u.y - v.y))
    return out


def _exec_time(req: int, cap: int) -> float:
    capf = float(cap)
    return float("inf") if capf <= 0 else float(req) / capf


def _schedule(created_at: float, req: int, cap: int, busy_until: float) -> Optional[dict]:
    et = _exec_time(req, cap)
    if et == float("inf"):
        return None
    s = max(float(created_at), float(busy_until))
    e = s + et
    return {"start_at": s, "end_at": e, "exec_time": et, "queue_delay": s - float(created_at)}


def _req_cpu(cap: int, mod3: int) -> int:
    cap = int(cap)
    if cap <= 0:
        return 0
    if mod3 == 0:
        return int(cap * 0.3)
    if mod3 == 1:
        return int(cap * 0.9)
    return int(cap * 1.3)


def simulate(scenario: Scenario, policy: PolicyBase, output_mode: str = "timeline") -> Dict[str, object]:
    vehicles_qs = Vehicle.objects.filter(id__in=scenario.vehicle_ids)
    found_ids = list(vehicles_qs.values_list("id", flat=True))
    missing_ids = [vid for vid in scenario.vehicle_ids if vid not in found_ids]

    rsus = [
        RSUState(id=r.id, x=float(r.x_coord), y=float(r.y_coord), cpu_capacity=int(r.cpu_capacity))
        for r in RSU.objects.all()
    ]

    sim_vehicles = []
    for v in vehicles_qs:
        pts, cum = _path_geom(v.path or [])
        L = cum[-1] if cum else 0.0
        speed = (L / float(scenario.time_simulate)) if L > 0 else 0.0
        sim_vehicles.append(
            {"id": v.id, "pts": pts, "cum": cum, "L": L, "speed": speed, "cpu": int(v.cpu_capacity)}
        )

    v_busy: Dict[int, float] = {sv["id"]: 0.0 for sv in sim_vehicles}
    r_busy: Dict[int, float] = {r.id: 0.0 for r in rsus}

    scheduled_ok: List[dict] = []
    timeline: List[dict] = []
    last_frame = None
    t, prev_t = 0, -1

    def pick_task(vehicle_id: int, now_t: float) -> Optional[dict]:
        active = [
            tt for tt in scheduled_ok
            if int(tt["vehicle_id"]) == int(vehicle_id)
            and float(tt["start_at"]) <= now_t < float(tt["end_at"])
        ]
        if active:
            active.sort(key=lambda z: float(z["start_at"]), reverse=True)
            return active[0]
        done = [tt for tt in scheduled_ok if int(tt["vehicle_id"]) == int(vehicle_id) and float(tt["end_at"]) <= now_t]
        if done:
            done.sort(key=lambda z: float(z["created_at"]), reverse=True)
            return done[0]
        return None

    while t <= scenario.time_simulate:
        vs: List[VehicleState] = []
        for sv in sim_vehicles:
            if not sv["pts"] or sv["L"] <= 0:
                x, y = None, None
            else:
                x, y = _interp(sv["pts"], sv["cum"], sv["speed"] * t)
            rsu_id = _serving_rsu(x, y, rsus, scenario.rsu_radius)
            vs.append(VehicleState(id=sv["id"], x=x, y=y, rsu_id=rsu_id, cpu_capacity=sv["cpu"]))

        task_times = []
        k = 0
        while True:
            tt = k * scenario.time_task
            if tt > scenario.time_simulate:
                break
            if prev_t < tt <= t:
                task_times.append(tt)
            k += 1

        tasks_in_frame: List[dict] = []
        frame_task_by_vehicle: Dict[int, dict] = {}

        for created_at in task_times:
            idx = int(created_at // scenario.time_task) if scenario.time_task > 0 else 0
            mod3 = idx % 3
            ca = float(created_at)
            ca_tag = str(int(created_at)) if float(created_at).is_integer() else str(created_at)

            for v in vs:
                req = _req_cpu(v.cpu_capacity, mod3)
                task = Task(task_id=f"task-{v.id}-{ca_tag}", vehicle_id=v.id, created_at=ca, required_cpu=int(req))
                neigh = _neighbors(v, vs, scenario.v2v_radius)
                dec = policy.decide(task, v, rsus, neigh, now=float(t))

                rec = {
                    "task_id": task.task_id,
                    "vehicle_id": task.vehicle_id,
                    "created_at": task.created_at,
                    "required_cpu": task.required_cpu,
                    "decision": dec.type,
                    "assigned_to": None,
                    "rsu_context": v.rsu_id,
                }

                timing = None
                if dec.type == "local":
                    timing = _schedule(task.created_at, task.required_cpu, v.cpu_capacity, v_busy[v.id])
                    if timing:
                        v_busy[v.id] = timing["end_at"]
                        rec["assigned_to"] = {"type": "vehicle", "id": v.id}
                elif dec.type == "rsu" and dec.target_id is not None:
                    r_id = dec.target_id
                    rsu_state = next((rr for rr in rsus if rr.id == r_id), None)
                    if rsu_state:
                        timing = _schedule(task.created_at, task.required_cpu, rsu_state.cpu_capacity, r_busy[r_id])
                        if timing:
                            r_busy[r_id] = timing["end_at"]
                            rec["assigned_to"] = {"type": "rsu", "id": r_id}
                elif dec.type == "v2v" and dec.target_id is not None:
                    n_id = dec.target_id
                    nb = next((u for u in vs if u.id == n_id), None)
                    if nb:
                        timing = _schedule(task.created_at, task.required_cpu, nb.cpu_capacity, v_busy[n_id])
                        if timing:
                            v_busy[n_id] = timing["end_at"]
                            rec["assigned_to"] = {"type": "vehicle", "id": n_id}

                if timing is None:
                    if dec.type != "dropped":
                        rec["decision"] = "dropped"
                    rec["start_at"], rec["end_at"] = None, None
                else:
                    rec.update(timing)
                    scheduled_ok.append(rec)

                tasks_in_frame.append(rec)

                frame_task_by_vehicle[v.id] = {
                    "task_id": rec["task_id"],
                    "created_at": rec["created_at"],
                    "required_cpu": rec["required_cpu"],
                    "decision": rec["decision"],
                    "assigned_to": rec.get("assigned_to"),
                    "start_at": rec.get("start_at"),
                    "end_at": rec.get("end_at"),
                }

        rsu_active: Dict[int, int] = {r.id: 0 for r in rsus}
        for v in vs:
            if v.rsu_id is not None:
                rsu_active[int(v.rsu_id)] += 1

        rsus_out = [
            {"id": r.id, "is_active": rsu_active[r.id] > 0, "active_vehicle_count": rsu_active[r.id], "busy_until": r_busy[r.id]}
            for r in rsus
        ]

        vehicles_out = []
        for v in vs:
            vt = frame_task_by_vehicle.get(v.id) or (pick_task(v.id, float(t)) if output_mode == "snapshot" else None)
            vehicles_out.append(
                {"id": v.id, "x": v.x, "y": v.y, "rsu_id": v.rsu_id, "is_current": v.rsu_id is not None, "task": vt}
            )

        frame = {"time": t, "vehicles": vehicles_out, "rsus": rsus_out, "tasks": tasks_in_frame}
        last_frame = frame
        if output_mode == "timeline":
            timeline.append(frame)

        prev_t = t
        t += scenario.time_step

    base = {
        "db_check": {"found_vehicle_ids": found_ids, "missing_vehicle_ids": missing_ids, "vehicle_count": len(found_ids)},
        "rsu_info": {"coverage_radius": scenario.rsu_radius, "rsu_count": len(rsus)},
        "v2v_info": {"v2v_radius": scenario.v2v_radius},
    }

    if output_mode == "snapshot":
        if last_frame:
            last_frame = dict(last_frame)
            last_frame.pop("tasks", None)
        return {**base, "state": last_frame}

    return {**base, "timeline": timeline}
