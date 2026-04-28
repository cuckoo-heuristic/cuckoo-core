from typing import Dict, Any
from django.db import transaction

from dag.models import Task
from cache.models import cache as Cache
from monarch_pylib.model import policy

def cache_value(ctx, sp_id, task_type_id):
    return policy.cache_service_value_score(
        cpu_cycles_list=ctx["cpu_cycles"],
        v_kj_list=ctx["cache_value_v_kj"].get((sp_id, task_type_id), []),
        mu_kj=ctx["cache_value_mu"].get((sp_id, task_type_id), 0.0),
        denom_cpu_cycles_list=ctx["cache_value_denom_cpu_cycles"].get(sp_id, []),
        denom_v_kj_list=ctx["cache_value_denom_v_kj"].get((sp_id, task_type_id), []),
    )


def cache_knapsack_dp(values, weights, capacity, items):
    n = len(items)
    dp = [[0.0] * (capacity + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        item = items[i - 1]
        w = weights[item]
        v = values[item]

        for cap in range(capacity + 1):
            if w <= cap:
                dp[i][cap] = max(dp[i - 1][cap], dp[i - 1][cap - w] + v)
            else:
                dp[i][cap] = dp[i - 1][cap]

    selected = []
    cap = capacity

    for i in range(n, 0, -1):
        if dp[i][cap] != dp[i - 1][cap]:
            item = items[i - 1]
            selected.append(item)
            cap -= weights[item]
            if cap <= 0:
                break

    return list(reversed(selected))


def update_cache(ctx: Dict[str, Any], sp_id: int, task_id: int):
    task = Task.objects.get(id=task_id)
    ttype = task.task_type_id_id

    current_cached = ctx["cache"].get(sp_id, set())
    if ttype in current_cached:
        return {
            "sp_id": sp_id,
            "updated": False,
            "added": [],
            "removed": [],
            "items": list(current_cached),
        }

    value = cache_value(ctx, sp_id, ttype)
    ctx.setdefault("eta_values", {})
    ctx["eta_values"][(sp_id, ttype)] = value

    task_types = list(set(ctx["task_type_ids"].values()) - {None})
    capacity = ctx["sp_cache_capacity"][sp_id]

    values = {t: ctx["eta_values"].get((sp_id, t), 0.0) for t in task_types}
    weights = {t: ctx["task_type_size_bits"][t] for t in task_types}

    new_items = cache_knapsack_dp(values, weights, capacity, task_types)
    new_items_set = set(new_items)

    removed = [x for x in current_cached if x not in new_items_set]
    added = [x for x in new_items if x not in current_cached]

    ctx["cache"][sp_id] = new_items_set

    return {
        "sp_id": sp_id,
        "updated": True,
        "added": added,
        "removed": removed,
        "items": new_items,
    }


# def update_cache(ctx: Dict[str, Any], sp_id: int, task_id: int):

#     task = Task.objects.get(id=task_id)
#     ttype = task.task_type_id_id

#     current_cached = ctx["cache"].get(sp_id, set())
#     if ttype in current_cached:
#         return {
#             "sp_id": sp_id,
#             "updated": False,
#             "added": [],
#             "removed": [],
#             "items": list(current_cached),
#         }

#     # compute η_kj
#     value = cache_value(ctx, sp_id, ttype)
#     ctx.setdefault("eta_values", {})
#     ctx["eta_values"][(sp_id, ttype)] = value

#     task_types = list(set(ctx["task_type_ids"].values()) - {None})
#     capacity = ctx["sp_cache_capacity"][sp_id]

#     values = {t: ctx["eta_values"].get((sp_id, t), 0.0) for t in task_types}
#     weights = {t: ctx["task_type_size_bits"][t] for t in task_types}

#     new_items = cache_knapsack_dp(values, weights, capacity, task_types)

#     new_items_set = set(new_items)

#     removed = [x for x in current_cached if x not in new_items_set]
#     added = [x for x in new_items if x not in current_cached]

#     with transaction.atomic():
#         Cache.objects.filter(sp_id_id=sp_id).delete()
#         for t in new_items:
#             Cache.objects.create(
#                 sp_id_id=sp_id,
#                 task_type_id_id=t,
#             )

#     ctx["cache"][sp_id] = new_items_set

#     return {
#         "sp_id": sp_id,
#         "updated": True,
#         "added": added,
#         "removed": removed,
#         "items": new_items,
#     }
