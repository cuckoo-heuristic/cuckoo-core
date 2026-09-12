from __future__ import annotations

import random
from typing import Sequence

from .memory import repair_solution


GREEDY_RATIO = 0.75
DIVERSE_RATIO = 0.25


def _task_order(context) -> list[int]:
    order = getattr(context, "task_order", None)
    if order:
        return [int(value) for value in order]
    if isinstance(context, dict) and context.get("task_order"):
        return [int(value) for value in context["task_order"]]
    return []


def _valid_providers(context, task: int) -> list[int]:
    validator = getattr(context, "valid_provider", None)
    if callable(validator):
        return list(dict.fromkeys(int(value) for value in (validator(int(task)) or [])))
    if isinstance(context, dict):
        domains = context.get("task_domains", context.get("providers", {}))
        if isinstance(domains, dict):
            values = domains.get(int(task), domains.get(str(int(task)), []))
            if isinstance(values, dict):
                values = values.keys()
            return list(dict.fromkeys(int(value) for value in (values or [])))
    return []


def _balanced_choices(values: Sequence[int], count: int, rng: random.Random):
    domain = list(dict.fromkeys(int(value) for value in values))
    if not domain:
        return []
    quotient, remainder = divmod(max(0, int(count)), len(domain))
    result = []
    for value in domain:
        result.extend([value] * quotient)
    extra = list(domain)
    rng.shuffle(extra)
    result.extend(extra[:remainder])
    rng.shuffle(result)
    return result


def _dlhs_population(context, count: int, rng: random.Random):
    count = max(0, int(count))
    if count == 0:
        return []
    tasks = _task_order(context)
    if not tasks:
        raise ValueError("CPO task order is empty")
    plans = {}
    for task in tasks:
        providers = _valid_providers(context, task)
        if not providers:
            raise ValueError(f"Task {task} has no valid provider")
        plans[task] = _balanced_choices(providers, count, rng)
    return [
        repair_solution(
            [(int(task), int(plans[task][row]), position) for position, task in enumerate(tasks)],
            context,
        )
        for row in range(count)
    ]


def create_initial_population(context, size: int, rng=None):
    """Paper-greedy/DLHS initialization specialized for discrete CPO."""
    from algorithm.optimizer_initialization import create_mixed_initial_population

    rng = rng or random.Random()
    return create_mixed_initial_population(
        context,
        int(size),
        rng,
        repair_solution,
        lambda count: _dlhs_population(context, count, rng),
        greedy_ratio=GREEDY_RATIO,
    )
