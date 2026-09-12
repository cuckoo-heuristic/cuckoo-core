from __future__ import annotations

from math import ceil
from typing import Any, Dict, Iterable, List, Optional, Set

from cuckoo_library.model import policy


def _task_type_ids(ctx) -> List[int]:
    return sorted(int(x) for x in set(ctx["task_type_ids"].values()) if x is not None)


def _cache_size(ctx, task_type_id: int) -> int:
    for key in ("service_size_cache", "service_size_bytes", "task_type_size_cache"):
        value = ctx.get(key, {}).get(task_type_id)
        if value is not None:
            return int(value)

    bits = ctx.get("service_size_bits", {}).get(task_type_id, ctx.get("task_type_size_bits", {}).get(task_type_id, 0))
    return int(ceil(float(bits) / 8.0))


def _cache_capacity(ctx, sp_id: int) -> int:
    for key in ("cache_capacity_cache", "cache_capacity_bytes", "sp_cache_capacity", "cache_capacity"):
        value = ctx.get(key, {}).get(sp_id)
        if value is not None:
            return int(value)

    return 0


def _remaining_tasks(ctx, remaining_task_ids: Optional[Iterable[int]]) -> List[int]:
    if remaining_task_ids is not None:
        return [int(t) for t in remaining_task_ids]

    compact = ctx.get("z", {}).get("compact", {})
    if compact:
        return [int(tid) for tid in ctx.get("task_ids", []) if compact.get(tid, {}).get("provider") is None]

    return list(ctx.get("task_ids", []))


def _mu(ctx, sp_id: int, task_type_id: int) -> float:
    if not ctx.get("use_caching", True):
        return 0.0

    # In Eq. (40), mu_kj is the number of OTHER service providers
    # that already cache the same service type. The provider whose
    # cache is currently being updated must not be counted.
    return float(
        sum(
            1
            for other_sp_id, cached in ctx.get("cache", {}).items()
            if int(other_sp_id) != int(sp_id) and task_type_id in cached
        )
    )


def cache_value(ctx, sp_id: int, task_type_id: int, candidates: Iterable[int], remaining_task_ids: Optional[Iterable[int]] = None) -> float:
    psi = _remaining_tasks(ctx, remaining_task_ids)
    candidate_set: Set[int] = set(int(x) for x in candidates)

    cpu_cycles_list = [float(ctx["cpu_cycles"][tid]) for tid in psi]
    v_kj_list = [1.0 if ctx["task_type_ids"].get(tid) == task_type_id else 0.0 for tid in psi]
    denom_v_kj_list = [1.0 if ctx["task_type_ids"].get(tid) in candidate_set else 0.0 for tid in psi]

    return policy.cache_service_value_score(
        cpu_cycles_list=cpu_cycles_list,
        v_kj_list=v_kj_list,
        mu_kj=_mu(ctx, sp_id, task_type_id),
        denom_cpu_cycles_list=cpu_cycles_list,
        denom_v_kj_list=denom_v_kj_list,
    )


def cache_knapsack_dp(values: Dict[Any, float], weights: Dict[Any, int], capacity: int, items: List[Any]) -> List[Any]:
    capacity = int(capacity)

    if capacity <= 0:
        return []

    dp = {0: (0.0, [])}

    for item in items:
        weight = int(weights[item])
        value = float(values[item])

        if weight > capacity:
            continue

        new_dp = dict(dp)

        for used, (score, selected) in dp.items():
            new_used = used + weight

            if new_used > capacity:
                continue

            new_score = score + value
            candidate_items = selected + [item]
            existing = new_dp.get(new_used)

            if existing is None or new_score > existing[0] or (new_score == existing[0] and len(candidate_items) > len(existing[1])):
                new_dp[new_used] = (new_score, candidate_items)

        dp = new_dp

    if not dp:
        return []

    _, best = max(dp.items(), key=lambda entry: (entry[1][0], len(entry[1][1]), -entry[0]))
    return list(best[1])


def update_cache(ctx, sp_id: int, task_id: int, remaining_task_ids: Optional[Iterable[int]] = None):
    if not ctx.get("use_caching", True):
        ctx.setdefault("cache", {})
        ctx["cache"][sp_id] = set()
        return {"updated": False, "items": []}

    task_type_id = ctx["task_type_ids"].get(task_id)

    if task_type_id is None:
        return {"updated": False}

    task_type_id = int(task_type_id)
    current_cached = set(ctx.get("cache", {}).get(sp_id, set()))

    if task_type_id in current_cached:
        ctx.setdefault("cache", {})
        ctx["cache"][sp_id] = set(current_cached)
        return {"updated": False, "items": sorted(current_cached)}

    candidates = sorted(current_cached | {task_type_id})
    capacity = _cache_capacity(ctx, sp_id)
    values = {item: cache_value(ctx, sp_id, item, candidates, remaining_task_ids) for item in candidates}
    weights = {item: _cache_size(ctx, item) for item in candidates}
    selected = cache_knapsack_dp(values, weights, capacity, candidates)

    ctx["cache"][sp_id] = set(selected)
    return {"updated": True, "items": selected}