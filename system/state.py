from state.models import State
from object.models import Vehicle, RSU, ServiceProvider
from django.db.models import F
from math import sqrt


def _f(x, d=0.0):
    try:
        return float(x)
    except:
        return d


def dist(a, b):
    return sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)


def build_state(ctx, write_db=False):

    application_id = ctx.get("application_id")
    if not application_id:
        ctx["fail_reason"] = "missing_application_id"
        return ctx

    # ---------------------------------------------------------
    # 1) Load radio state (gain + rate)
    # ---------------------------------------------------------
    st = State.objects.filter(
        task_execution_id__application_id=application_id
    ).order_by("-id")

    if st.exists():
        s = st.first()
        g = _f(s.gain, 1e-6)
        r = _f(s.rate, 0.0)
    else:
        g, r = 1e-6, 0.0

    tids = ctx.get("task_ids", [])
    ctx["channel_gains"] = {t: g for t in tids}
    ctx["rates"] = {t: r for t in tids}

    # ---------------------------------------------------------
    # 2) Discover available SPs for this application's Vehicle
    # ---------------------------------------------------------

    # Find the Vehicle for this application:
    vehicle = Vehicle.objects.filter(
        taskexecution__application_id=application_id
    ).distinct().first()

    if not vehicle:
        ctx["available_sps"] = []
        return ctx

    vx, vy = _f(vehicle.x_coord), _f(vehicle.y_coord)

    rsu_range = 300.0
    v2v_range = 100.0

    available = []

    # ---------- RSUs ----------
    for rsu in RSU.objects.all():
        if rsu.x_coord is None or rsu.y_coord is None:
            continue
        d = dist((vx, vy), (rsu.x_coord, rsu.y_coord))
        if d <= rsu_range:
            sp = ServiceProvider.objects.filter(rsu_id=rsu).first()
            if sp:
                available.append(sp.id)

    # ---------- Vehicles ----------
    for v in Vehicle.objects.exclude(id=vehicle.id):
        if v.x_coord is None or v.y_coord is None:
            continue
        d = dist((vx, vy), (v.x_coord, v.y_coord))
        if d <= v2v_range:
            sp = ServiceProvider.objects.filter(vehicle_id=v).first()
            if sp:
                available.append(sp.id)

    ctx["available_sps"] = available

    return ctx
