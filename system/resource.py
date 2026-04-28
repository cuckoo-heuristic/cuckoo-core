from resource.models import Resource
from object.models import ServiceProvider


def _i(x, d=0):
    try:
        return int(x)
    except:
        return d


def _f(x, d=0.0):
    try:
        return float(x)
    except:
        return d


def build_resource(ctx, write_db=False):

    available = ctx.get("available_sps", [])

    providers = {}
    sp_types = {}
    sp_cpu = {}
    sp_cache_capacity = {}

    # -----------------------------------------------
    # Only use SPs discovered in build_state !!
    # -----------------------------------------------
    qs = ServiceProvider.objects.filter(id__in=available)

    for sp in qs:
        sid = sp.id
        providers[sid] = 1
        sp_types[sid] = sp.type

        res = Resource.objects.filter(sp_id=sid).first()
        if res:
            sp_cpu[sid] = _f(res.cpu_capacity)
            sp_cache_capacity[sid] = _i(res.cache_capacity)
        else:
            sp_cpu[sid] = 1e9
            sp_cache_capacity[sid] = 10**9

    ctx["service_providers"] = providers
    ctx["sp_types"] = sp_types
    ctx["sp_cpu_freq"] = sp_cpu
    ctx["sp_cache_capacity"] = sp_cache_capacity

    return ctx
