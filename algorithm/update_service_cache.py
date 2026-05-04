from typing import Dict, Any
from monarch_pylib.model import policy


def cache_value(ctx, sp_id, task_type_id):
    return policy.cache_service_value_score(
        cpu_cycles_list=list(ctx["cpu_cycles"].values()),
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


def update_cache(ctx, sp_id, task_id):
    ttype = ctx["task_type_ids"].get(task_id)
    current_cached = ctx["cache"].get(sp_id, set())

    if ttype in current_cached:
        return {"updated": False}

    task_types = list(set(ctx["task_type_ids"].values()) - {None})
    capacity = ctx["sp_cache_capacity"][sp_id]

    values: Dict[Any, float] = {}
    weights: Dict[Any, int] = {}

    for t in task_types:
        values[t] = cache_value(ctx, sp_id, t)
        weights[t] = ctx["task_type_size_bits"][t]

    new_items = cache_knapsack_dp(values, weights, capacity, task_types)

    ctx["cache"][sp_id] = set(new_items)

    return {
        "updated": True,
        "items": new_items
    }
