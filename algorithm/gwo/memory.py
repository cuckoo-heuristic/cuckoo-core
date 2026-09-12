from __future__ import annotations

from typing import Mapping, Sequence


TAU_MIN = 0.05
TAU_MAX = 5.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def initialize_pheromone(
    pheromone: dict[tuple[int, int], float],
    task_domains: Mapping[int, Sequence[int]],
    *,
    initial: float = 1.0,
    tau_min: float = TAU_MIN,
    tau_max: float = TAU_MAX,
) -> dict[tuple[int, int], float]:
    """Create the complete bounded ACO task-provider memory once."""
    value = _clamp(initial, tau_min, tau_max)
    for task, providers in task_domains.items():
        for provider in providers:
            pheromone.setdefault((int(task), int(provider)), value)
    return pheromone


def update_pheromone(
    pheromone: dict[tuple[int, int], float],
    evaluated,
    *,
    evaporation: float = 0.10,
    elite_ratio: float = 0.20,
    q: float = 1.0,
    tau_min: float = TAU_MIN,
    tau_max: float = TAU_MAX,
    stagnation: int = 0,
) -> dict[tuple[int, int], float]:
    """Evaporate globally and reinforce only the elite schedules.

    This is optimizer memory only.  It never changes the benchmark objective.
    Values remain bounded so an old assignment cannot permanently dominate.
    """
    evaporation = _clamp(
        float(evaporation) + min(0.10, max(0, int(stagnation)) * 0.015),
        0.0,
        0.95,
    )

    for key in list(pheromone):
        pheromone[key] = _clamp(
            float(pheromone[key]) * (1.0 - evaporation),
            tau_min,
            tau_max,
        )

    rows = sorted(list(evaluated or []), key=lambda row: float(row[1]), reverse=True)
    if not rows:
        return pheromone

    elite_count = max(1, min(len(rows), int(round(len(rows) * float(elite_ratio)))))
    elite = rows[:elite_count]
    scores = [float(score) for _, score in elite]
    lo, hi = min(scores), max(scores)

    for rank, (solution, score) in enumerate(elite):
        quality = 1.0 if hi <= lo else (float(score) - lo) / (hi - lo)
        rank_weight = 1.0 - (float(rank) / float(max(1, elite_count)))
        deposit = float(q) * (0.25 + 0.75 * quality) * (0.50 + 0.50 * rank_weight)
        deposit /= float(max(1, elite_count))

        for gene in solution:
            if not isinstance(gene, (tuple, list)) or len(gene) < 2:
                continue
            key = (int(gene[0]), int(gene[1]))
            pheromone[key] = _clamp(
                float(pheromone.get(key, 1.0)) + deposit,
                tau_min,
                tau_max,
            )

    return pheromone


def _valid_providers(context, task: int) -> list[int]:
    validator = getattr(context, "valid_provider", None)
    if callable(validator):
        return list(dict.fromkeys(int(p) for p in (validator(int(task)) or [])))

    if isinstance(context, dict):
        domains = context.get("task_domains", context.get("providers", {}))
        if isinstance(domains, dict):
            values = domains.get(int(task), [])
            if isinstance(values, dict):
                values = values.keys()
            return list(dict.fromkeys(int(p) for p in (values or [])))
    return []


def _task_order(context) -> list[int]:
    order = getattr(context, "task_order", None)
    if order:
        return [int(x) for x in order]
    if isinstance(context, dict) and context.get("task_order"):
        return [int(x) for x in context["task_order"]]
    return []


def repair_solution(solution, context):
    """Canonicalize task order and project only invalid providers.

    Valid assignments are never changed.  This is a defensive boundary rather
    than another search heuristic.
    """
    if not solution:
        return []

    by_task: dict[int, int] = {}
    for gene in solution:
        if isinstance(gene, (tuple, list)) and len(gene) >= 2:
            by_task.setdefault(int(gene[0]), int(gene[1]))
        elif isinstance(gene, dict):
            task = gene.get("task")
            provider = gene.get("provider")
            if task is not None and provider is not None:
                by_task.setdefault(int(task), int(provider))

    order = _task_order(context) or list(by_task)
    repaired = []
    for task in order:
        providers = _valid_providers(context, int(task))
        if not providers:
            continue
        provider = int(by_task.get(int(task), providers[0]))
        if provider not in providers:
            provider = int(providers[0])
        repaired.append((int(task), int(provider), len(repaired)))

    return repaired
