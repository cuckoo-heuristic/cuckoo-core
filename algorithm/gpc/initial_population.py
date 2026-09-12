from __future__ import annotations

import random
from typing import Sequence

from .memory import repair_solution


GREEDY_RATIO = .70
DIVERSE_RATIO = 0.30


def _task_order(context) -> list[int]:
    order = getattr(context, "task_order", None)
    if order:
        return [int(x) for x in order]
    if isinstance(context, dict) and context.get("task_order"):
        return [int(x) for x in context["task_order"]]
    return []


def _valid_providers(context, task: int) -> list[int]:
    validator = getattr(context, "valid_provider", None)
    if callable(validator):
        return list(dict.fromkeys(int(x) for x in (validator(int(task)) or [])))

    if isinstance(context, dict):
        domains = context.get("task_domains", context.get("providers", {}))
        if isinstance(domains, dict):
            values = domains.get(int(task), [])
            if isinstance(values, dict):
                values = values.keys()
            return list(dict.fromkeys(int(x) for x in (values or [])))

    return []


def _signature(solution: Sequence) -> tuple[tuple[int, int], ...]:
    return tuple(
        (int(g[0]), int(g[1]))
        for g in solution
        if isinstance(g, (tuple, list)) and len(g) >= 2
    )


def _greedy_population(context, count: int) -> list:
    generator = getattr(context, "greedy_population", None)

    if callable(generator):
        raw = generator(max(1, int(count)))

    elif isinstance(context, dict):
        from algorithm.greedy_nests import procedure1_greedy_initialization

        order = _task_order(context)
        if not order:
            raise ValueError("Task order is empty")

        raw = procedure1_greedy_initialization(
            S=max(1, int(count)),
            task_order=order,
            ctx=context,
        )

    else:
        raise TypeError(
            "Context must expose greedy_population(count) or be a DCSGA dict context"
        )

    result = []
    for solution in raw or []:
        repaired = repair_solution(solution, context)
        if repaired:
            result.append(repaired)

    return result


def _balanced_choices(providers: Sequence[int], count: int, rng: random.Random) -> list[int]:
    domain = list(dict.fromkeys(int(x) for x in providers))
    if not domain:
        return []

    q, r = divmod(int(count), len(domain))

    values = []
    for provider in domain:
        values.extend([provider] * q)

    extra = list(domain)
    rng.shuffle(extra)
    values.extend(extra[:r])

    rng.shuffle(values)
    return values


def _dlhs_population(context, count: int, rng: random.Random) -> list:
    count = max(0, int(count))
    if count == 0:
        return []

    tasks = _task_order(context)
    if not tasks:
        raise ValueError("Task order is empty")

    plans = {}

    for task in tasks:
        providers = _valid_providers(context, task)

        if not providers:
            raise ValueError(f"Task {task} has no valid provider")

        plans[task] = _balanced_choices(providers, count, rng)

    population = []

    for i in range(count):
        solution = [
            (int(task), int(plans[task][i]), pos)
            for pos, task in enumerate(tasks)
        ]

        repaired = repair_solution(solution, context)

        if repaired:
            population.append(repaired)

    return population


def _random_solution(context, rng: random.Random) -> list:
    tasks = _task_order(context)
    solution = []

    for pos, task in enumerate(tasks):
        providers = _valid_providers(context, task)

        if not providers:
            raise ValueError(f"Task {task} has no valid provider")

        solution.append(
            (int(task), int(rng.choice(providers)), pos)
        )

    return repair_solution(solution, context)


def create_random_solution(context, rng: random.Random) -> list:
    """Public feasible sampler used by bounded GPC stagnation restarts."""
    from algorithm.optimizer_initialization import random_solution

    return random_solution(context, rng, repair_solution)


def create_initial_population(context, size: int, rng=None):
    from algorithm.optimizer_initialization import create_mixed_initial_population

    rng = rng or random.Random()
    return create_mixed_initial_population(
        context,
        size,
        rng,
        repair_solution,
        lambda count: _dlhs_population(context, count, rng),
        greedy_ratio=GREEDY_RATIO,
    )
