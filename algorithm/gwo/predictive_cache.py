from __future__ import annotations

from bisect import bisect_right
from collections import deque
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from algorithm.update_service_cache import (
    _cache_capacity,
    _cache_size,
    cache_knapsack_dp,
    cache_value,
)

# One compact problem-aware cache mechanism.
DEFAULT_LOOKAHEAD = 5
DEFAULT_PREDICTIVE_WEIGHT = 1.0
DEFAULT_RANK_AWARE = True
DEFAULT_DAG_AWARE = True
DEFAULT_PROVIDER_GUIDANCE_WEIGHT = 0.40

# Legacy B4 benchmark imports these names.  Regional generation memory is
# intentionally retired in the lean optimizer and therefore hard-disabled.
DEFAULT_REGIONAL_CACHE_ENABLED = False
DEFAULT_REGIONAL_CACHE_SHARE = 0.0
DEFAULT_REGIONAL_ELITE_RATIO = 0.0


def _context_value(context: Any, key: str, default=None):
    if isinstance(context, dict):
        return context.get(key, default)
    return getattr(context, key, default)


def build_joint_dag_distance_map(joint_ctx) -> Dict[Tuple[int, int], int]:
    """Precompute shortest descendant distance once for all joint DAG tasks."""
    reverse_refs = joint_ctx.get("reverse_task_refs", {})
    result: Dict[Tuple[int, int], int] = {}

    for app_id, app_ctx in joint_ctx.get("applications", {}).items():
        app_id = int(app_id)
        children = {
            int(task_id): [int(child_id) for child_id in values]
            for task_id, values in app_ctx.get("children", {}).items()
        }
        for source_task_id in [int(t) for t in app_ctx.get("task_ids", [])]:
            source_joint = reverse_refs.get((app_id, source_task_id))
            if source_joint is None:
                continue
            queue = deque((child, 1) for child in children.get(source_task_id, []))
            visited = set()
            while queue:
                target_task_id, distance = queue.popleft()
                target_task_id = int(target_task_id)
                if target_task_id in visited:
                    continue
                visited.add(target_task_id)
                target_joint = reverse_refs.get((app_id, target_task_id))
                if target_joint is not None:
                    result[(int(source_joint), int(target_joint))] = int(distance)
                for child in children.get(target_task_id, []):
                    if int(child) not in visited:
                        queue.append((int(child), int(distance) + 1))
    return result


def _provider_future_tasks(
    remaining_task_ids: Optional[Iterable[int]],
    provider_map: Dict[int, int],
    provider_id: int,
    lookahead: int,
) -> list[int]:
    if remaining_task_ids is None or int(lookahead) <= 0:
        return []
    result = []
    for task_id in remaining_task_ids:
        task_id = int(task_id)
        if int(provider_map.get(task_id, -1)) != int(provider_id):
            continue
        result.append(task_id)
        if len(result) >= int(lookahead):
            break
    return result


def _matching_future_tasks(ctx, task_type_id: int, future_tasks: Iterable[int]) -> list[int]:
    task_types = _context_value(ctx, "task_type_ids", {}) or {}
    task_type_id = int(task_type_id)
    return [
        int(task_id)
        for task_id in future_tasks
        if task_types.get(int(task_id)) is not None
        and int(task_types[int(task_id)]) == task_type_id
    ]


def _rank_factor(ctx, matching_tasks: Iterable[int]) -> float:
    if not bool(_context_value(ctx, "predictive_cache_rank_aware", DEFAULT_RANK_AWARE)):
        return 1.0
    normalized = _context_value(ctx, "predictive_rank_weight", {}) or {}
    values = [
        max(0.0, min(1.0, float(normalized.get(int(task_id), 0.0))))
        for task_id in matching_tasks
    ]
    if not values:
        return 1.0
    return 0.5 + 0.5 * (sum(values) / len(values))


def _dag_factor(ctx, current_task_id: int, matching_tasks: Iterable[int]) -> float:
    if not bool(_context_value(ctx, "predictive_cache_dag_aware", DEFAULT_DAG_AWARE)):
        return 1.0
    distances = _context_value(ctx, "predictive_dag_distance", {}) or {}
    factors = []
    for task_id in matching_tasks:
        distance = distances.get((int(current_task_id), int(task_id)))
        factors.append(
            1.0 if distance is None or int(distance) <= 0
            else 1.0 + 1.0 / float(distance)
        )
    return sum(factors) / len(factors) if factors else 1.0


def build_provider_future_index(context: Any, provider_map: Dict[int, int]) -> Dict[str, Any]:
    """Index structural future assignments once per wolf move."""
    order = tuple(int(t) for t in (_context_value(context, "task_order", []) or []))
    positions = {task_id: index for index, task_id in enumerate(order)}
    provider_tasks: Dict[int, list[int]] = {}
    provider_positions: Dict[int, list[int]] = {}
    for task_id in order:
        provider_id = provider_map.get(int(task_id))
        if provider_id is None:
            continue
        provider_id = int(provider_id)
        provider_tasks.setdefault(provider_id, []).append(int(task_id))
        provider_positions.setdefault(provider_id, []).append(int(positions[task_id]))
    return {
        "positions": positions,
        "provider_tasks": {k: tuple(v) for k, v in provider_tasks.items()},
        "provider_positions": {k: tuple(v) for k, v in provider_positions.items()},
    }


def provider_reuse_guidance(
    context: Any,
    task_id: int,
    provider_id: int,
    provider_map: Dict[int, int],
    *,
    future_index: Optional[Dict[str, Any]] = None,
    lookahead: Optional[int] = None,
) -> float:
    """Search-only future same-provider reuse signal; never a fitness bonus."""
    task_id = int(task_id)
    provider_id = int(provider_id)
    task_types = _context_value(context, "task_type_ids", {}) or {}
    task_type_id = task_types.get(task_id)
    if task_type_id is None:
        return 0.0

    future_index = future_index or build_provider_future_index(context, provider_map)
    current_position = future_index.get("positions", {}).get(task_id)
    if current_position is None:
        return 0.0

    positions: Sequence[int] = future_index.get("provider_positions", {}).get(provider_id, ())
    tasks: Sequence[int] = future_index.get("provider_tasks", {}).get(provider_id, ())
    if not positions or not tasks:
        return 0.0

    limit = max(
        0,
        int(
            lookahead
            if lookahead is not None
            else _context_value(context, "predictive_cache_lookahead", DEFAULT_LOOKAHEAD)
        ),
    )
    if limit <= 0:
        return 0.0

    start = bisect_right(positions, int(current_position))
    future_tasks = [int(task) for task in tasks[start : start + limit]]
    matching = _matching_future_tasks(context, int(task_type_id), future_tasks)
    return float(
        sum(
            _rank_factor(context, [future_task])
            * _dag_factor(context, task_id, [future_task])
            for future_task in matching
        )
    )


def normalized_provider_reuse_guidance(
    context: Any,
    task_id: int,
    providers: Iterable[int],
    provider_map: Dict[int, int],
    *,
    future_index: Optional[Dict[str, Any]] = None,
) -> Dict[int, float]:
    provider_ids = list(dict.fromkeys(int(p) for p in providers))
    if not provider_ids:
        return {}
    future_index = future_index or build_provider_future_index(context, provider_map)
    raw = {
        provider_id: provider_reuse_guidance(
            context,
            int(task_id),
            provider_id,
            provider_map,
            future_index=future_index,
        )
        for provider_id in provider_ids
    }
    lo, hi = min(raw.values()), max(raw.values())
    if hi <= 0.0 or hi <= lo:
        return {provider_id: 0.0 for provider_id in provider_ids}
    return {
        provider_id: max(0.0, min(1.0, (value - lo) / (hi - lo)))
        for provider_id, value in raw.items()
    }


def update_predictive_cache(
    ctx,
    sp_id: int,
    task_id: int,
    *,
    remaining_task_ids: Optional[Iterable[int]] = None,
    provider_map: Optional[Dict[int, int]] = None,
    lookahead: int = DEFAULT_LOOKAHEAD,
    predictive_weight: float = DEFAULT_PREDICTIVE_WEIGHT,
):
    """Provider-specific, rank/DAG-aware predictive extension of paper cache.

    All base cache values and final packing are delegated to the paper cache
    implementation.  No prefetch and no fitness bonus are introduced.
    ``predictive_weight=0`` reduces to the paper cache ranking/knapsack path.
    """
    if not ctx.get("use_caching", True):
        ctx.setdefault("cache", {})
        ctx["cache"][int(sp_id)] = set()
        return {"updated": False, "items": []}

    sp_id = int(sp_id)
    task_id = int(task_id)
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
    base_values = {
        item: cache_value(ctx, sp_id, item, candidates, remaining_task_ids)
        for item in candidates
    }

    future_tasks = _provider_future_tasks(
        remaining_task_ids,
        provider_map or {},
        sp_id,
        int(lookahead),
    )
    weight = max(0.0, float(predictive_weight))

    if weight > 0.0 and future_tasks:
        predictive_values = {
            item: cache_value(ctx, sp_id, item, candidates, future_tasks)
            for item in candidates
        }
        values = {}
        for item in candidates:
            matching = _matching_future_tasks(ctx, int(item), future_tasks)
            importance = _rank_factor(ctx, matching) * _dag_factor(ctx, task_id, matching)
            values[item] = float(base_values[item]) + (
                weight * float(predictive_values[item]) * float(importance)
            )
    else:
        values = base_values

    selected = cache_knapsack_dp(
        values,
        {item: _cache_size(ctx, item) for item in candidates},
        _cache_capacity(ctx, sp_id),
        candidates,
    )
    ctx.setdefault("cache", {})
    ctx["cache"][sp_id] = set(selected)
    return {
        "updated": True,
        "items": selected,
        "provider_future_tasks": future_tasks,
        "rank_aware": bool(ctx.get("predictive_cache_rank_aware", DEFAULT_RANK_AWARE)),
        "dag_aware": bool(ctx.get("predictive_cache_dag_aware", DEFAULT_DAG_AWARE)),
    }


# ---------------------------------------------------------------------------
# Retired regional-cache compatibility surface for the current B4 benchmark.
# The names remain so the existing benchmark files do not need to be replaced
# together with these five optimizer files.  All behavior is deliberately inert.
# ---------------------------------------------------------------------------
def build_joint_regional_provider_maps(joint_ctx):
    return {}, {}


def build_regional_rsu_service_demand(solution, task_type_ids, provider_rsu_ids, provider_types):
    return {}


class RegionalCacheMemory:
    def __init__(self, provider_rsu_ids=None, provider_types=None, *, elite_ratio=0.0):
        self.elite_ratio = 0.0
        self.rounds = 0
        self.version = 0

    def elite_count(self, population_size: int) -> int:
        return 0

    def update_from_observations(self, cache_states, demand_states=None) -> bool:
        return False

    def profile(self):
        return {}

    def prevalence_profile(self):
        return {}

    def demand_profile(self):
        return {}
