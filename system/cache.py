from cache.models import cache as Cache
from resource.models import Resource
from object.models import ServiceProvider
from dag.models import TaskType
from django.db import transaction
from cache.models import cache as Cache
from resource.models import Resource

# def apply_final_cache_and_resource(ctx):
#     """
#     This function is called after the completion of the DCSGA algorithm.
#     ctx["cache"] contains the final best cache state.
#     This function updates the database in one atomic transaction.
#     """

#     final_cache = ctx.get("cache", {})
#     task_sizes = ctx.get("task_type_size_bits", {})
#     sp_capacity = ctx.get("sp_cache_capacity", {})

#     with transaction.atomic():

#         for sp_id, items in final_cache.items():

#             # 1) Remove previous cache entries
#             Cache.objects.filter(sp_id_id=sp_id).delete()

#             # 2) Insert new cache entries
#             for ttype_id in items:
#                 Cache.objects.create(
#                     sp_id_id=sp_id,
#                     task_type_id_id=ttype_id
#                 )

#             # 3) Calculate actual cache usage
#             used_bits = sum(task_sizes.get(int(ttype), 0) for ttype in items)

#             # 4) Update resource usage safely
#             r, created = Resource.objects.get_or_create(
#                 sp_id_id=sp_id,
#                 defaults={
#                     "cpu_used": 0,
#                     "cache_used": 0,
#                 }
#             )

#             r.cache_used = used_bits
#             r.save()

#     return True
from django.db import transaction
from cache.models import cache as Cache
from resource.models import Resource

def apply_final_cache_and_resource(ctx):
    final_cache = ctx.get("cache", {})
    task_sizes = ctx.get("task_type_size_bits", {})

    with transaction.atomic():
        for sp_id, items in final_cache.items():
            Cache.objects.filter(sp_id_id=sp_id).delete()

            for ttype_id in items:
                Cache.objects.create(
                    sp_id_id=sp_id,
                    task_type_id_id=ttype_id,
                )

            used_bits = sum(task_sizes.get(int(ttype_id), 0) for ttype_id in items)

            r, _ = Resource.objects.get_or_create(
                sp_id_id=sp_id,
                defaults={"cpu_used": 0, "cache_used": 0},
            )
            r.cache_used = used_bits
            r.save(update_fields=["cache_used"])

    return True


def _safe_float(x, d=0.0):
    try:
        return float(x)
    except:
        return float(d)

def _safe_int(x, d=0):
    try:
        return int(x)
    except:
        try:
            return int(float(x))
        except:
            return d

def _size_to_bits(sz):
    v = _safe_int(sz, 0)
    if v <= 0:
        return 0
    if v < 1024 * 1024:
        return v * 8
    return v

def build_cache_state(ctx, write_db=False):
    cache_state = {}
    sp_cap = {}

    sizes = {}
    for tt_id, sz in TaskType.objects.all().values_list("id", "size"):
        sizes[int(tt_id)] = _size_to_bits(sz)

    for sp in ServiceProvider.objects.select_related("rsu_id", "vehicle_id").all():
        sp_id = int(sp.id)
        items = set(Cache.objects.filter(sp_id_id=sp_id).values_list("task_type_id_id", flat=True))
        cache_state[sp_id] = items

        cap = 0
        if Resource.objects.filter(sp_id_id=sp_id).exists():
            r = Resource.objects.get(sp_id_id=sp_id)
            cap = _size_to_bits(getattr(r, "cache_capacity", 0))
        else:
            if getattr(sp, "rsu_id_id", None):
                cap = _size_to_bits(getattr(sp.rsu_id, "cache_capacity", 0))
            elif getattr(sp, "vehicle_id_id", None):
                cap = _size_to_bits(getattr(sp.vehicle_id, "cache_capacity", 0))

        sp_cap[sp_id] = cap

    ctx["cache"] = cache_state
    ctx["sp_cache_capacity"] = sp_cap
    return ctx
