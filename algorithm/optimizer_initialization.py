from __future__ import annotations

import math
import random
from typing import Callable, Sequence


DEFAULT_GREEDY_RATIO = 1.00


def _context_value(context, key, default=None):
    if isinstance(context, dict) and key in context:
        return context.get(key, default)
    return getattr(context, key, default)


def _task_order(context) -> list[int]:
    for key in ("task_order", "ranked_task_ids"):
        order = _context_value(context, key, None)
        if order:
            return [int(value) for value in order]
    return []


def _valid_providers(context, task: int) -> list[int]:
    validator = getattr(context, "valid_provider", None)
    if callable(validator):
        return list(dict.fromkeys(int(value) for value in (validator(task) or [])))
    domains = _context_value(context, "task_domains", None)
    if domains is None:
        domains = _context_value(context, "providers", {})
    if isinstance(domains, dict):
        values = domains.get(int(task), domains.get(str(int(task)), []))
        if isinstance(values, dict):
            values = values.keys()
        return list(dict.fromkeys(int(value) for value in (values or [])))
    return []


def solution_key(solution: Sequence) -> tuple[tuple[int, int], ...]:
    return tuple(
        (int(gene[0]), int(gene[1]))
        for gene in solution
        if isinstance(gene, (tuple, list)) and len(gene) >= 2
    )


def random_solution(context, rng: random.Random, repair: Callable) -> list:
    order = _task_order(context)
    if not order:
        raise RuntimeError("Optimizer initialization requires a non-empty task order")
    raw = []
    for position, task in enumerate(order):
        providers = _valid_providers(context, int(task))
        if not providers:
            raise ValueError(f"Task {task} has no valid provider")
        raw.append((int(task), int(rng.choice(providers)), int(position)))
    return repair(raw, context)


def _greedy_population(context, count: int, repair: Callable) -> list:
    generator = getattr(context, "greedy_population", None)
    if callable(generator):
        raw = generator(max(1, int(count)))
    elif isinstance(context, dict):
        from algorithm.greedy_nests import procedure1_greedy_initialization

        raw = procedure1_greedy_initialization(
            S=max(1, int(count)),
            task_order=_task_order(context),
            ctx=context,
        )
    else:
        raise TypeError(
            "Context must expose greedy_population(count) or be a DCSGA dictionary"
        )
    return [candidate for candidate in (repair(item, context) for item in raw or []) if candidate]


def _near_greedy_candidate(
    base: Sequence,
    context,
    rng: random.Random,
    repair: Callable,
    *,
    strength: float,
) -> list:
    """Create a feasible, low-Hamming-distance alternative to a greedy seed."""
    result = [tuple(int(value) for value in gene[:3]) for gene in base]
    mutable = []
    ranks = _context_value(context, "task_rank", None) or _context_value(
        context, "global_ranks", {}
    )
    rank_values = [float(value) for value in ranks.values()] if isinstance(ranks, dict) else []
    lo = min(rank_values) if rank_values else 0.0
    hi = max(rank_values) if rank_values else 0.0
    span = max(1e-12, hi - lo)
    for index, (task, provider, _position) in enumerate(result):
        alternatives = [
            value
            for value in _valid_providers(context, int(task))
            if int(value) != int(provider)
        ]
        if not alternatives:
            continue
        raw_rank = 0.0
        if isinstance(ranks, dict):
            raw_rank = float(ranks.get(int(task), ranks.get(str(int(task)), lo)))
        normalized_rank = (raw_rank - lo) / span if rank_values else 0.5
        # Lower-priority tasks are safer diversity coordinates.
        mutable.append((index, alternatives, 0.25 + 0.75 * (1.0 - normalized_rank)))
    if not mutable:
        return repair(result, context)

    dimension = max(1, len(result))
    change_count = max(
        1,
        min(
            len(mutable),
            int(math.ceil(math.sqrt(dimension) * max(0.02, float(strength)))),
        ),
    )
    pool = list(mutable)
    selected = []
    while pool and len(selected) < change_count:
        total = sum(item[2] for item in pool)
        threshold = rng.random() * total
        cumulative = 0.0
        chosen = len(pool) - 1
        for index, item in enumerate(pool):
            cumulative += item[2]
            if threshold <= cumulative:
                chosen = index
                break
        selected.append(pool.pop(chosen))
    for index, alternatives, _weight in selected:
        task, _provider, position = result[index]
        result[index] = (int(task), int(rng.choice(alternatives)), int(position))
    return repair(result, context)


def create_shared_initial_population(
    context,
    size: int,
    rng: random.Random,
    repair: Callable,
    *,
    greedy_ratio: float = DEFAULT_GREEDY_RATIO,
) -> list:
    """Build a strong common initializer for added discrete optimizers.

    The requested candidates use the same paper-aligned greedy constructor as
    DCSGA, with the same seed. Sparse feasible perturbations are used only when
    repair/deduplication leaves an empty slot; full random schedules are a final
    degenerate-domain fallback. This makes the initial population common across
    all four searches instead of confounding initialization with the operator.
    """
    size = max(1, int(size))
    ratio = max(0.0, min(1.0, float(greedy_ratio)))
    greedy_target = max(1, min(size, int(round(size * ratio))))
    raw_greedy = _greedy_population(context, greedy_target, repair)
    if not raw_greedy:
        raise RuntimeError("The shared greedy initializer returned no solution")

    population = []
    seen = set()
    for candidate in raw_greedy:
        key = solution_key(candidate)
        if key and key not in seen:
            seen.add(key)
            population.append(candidate)

    attempts = 0
    max_attempts = max(200, size * 50)
    while len(population) < size and attempts < max_attempts:
        attempts += 1
        base = raw_greedy[attempts % len(raw_greedy)]
        candidate = _near_greedy_candidate(
            base,
            context,
            rng,
            repair,
            strength=min(0.25, 0.06 + 0.01 * (attempts // max(1, size))),
        )
        key = solution_key(candidate)
        if key and key not in seen:
            seen.add(key)
            population.append(candidate)

    # Only an extremely small/degenerate domain should reach this fallback.
    while len(population) < size and attempts < max_attempts * 2:
        attempts += 1
        candidate = random_solution(context, rng, repair)
        key = solution_key(candidate)
        if key and key not in seen:
            seen.add(key)
            population.append(candidate)

    if len(population) != size:
        raise RuntimeError(
            f"Could create only {len(population)} unique feasible initial solutions; expected {size}"
        )
    return population


def create_mixed_initial_population(
    context,
    size: int,
    rng: random.Random,
    repair: Callable,
    diverse_sampler: Callable[[int], Sequence],
    *,
    greedy_ratio: float,
) -> list:
    """Build a real greedy/DLHS mixture with deterministic de-duplication."""
    size = max(1, int(size))
    ratio = max(0.0, min(1.0, float(greedy_ratio)))
    greedy_target = min(size, max(1, int(round(size * ratio))))
    diverse_target = max(0, size - greedy_target)
    raw_greedy = _greedy_population(context, greedy_target, repair)
    if not raw_greedy:
        raise RuntimeError("The greedy initializer returned no solution")
    raw_diverse = list(diverse_sampler(diverse_target) or [])
    population, seen = [], set()
    branches = (list(raw_greedy), list(raw_diverse))
    for index in range(max((len(branch) for branch in branches), default=0)):
        for branch in branches:
            if index >= len(branch):
                continue
            candidate = repair(branch[index], context)
            key = solution_key(candidate)
            if key and key not in seen:
                seen.add(key)
                population.append(candidate)
            if len(population) >= size:
                return population[:size]
    attempts, max_attempts = 0, max(200, size * 50)
    while len(population) < size and attempts < max_attempts:
        attempts += 1
        candidate = _near_greedy_candidate(
            raw_greedy[attempts % len(raw_greedy)], context, rng, repair,
            strength=min(0.35, 0.05 + 0.01 * (attempts // max(1, size))),
        )
        key = solution_key(candidate)
        if key and key not in seen:
            seen.add(key)
            population.append(candidate)
    while len(population) < size and attempts < max_attempts * 2:
        attempts += 1
        candidate = random_solution(context, rng, repair)
        key = solution_key(candidate)
        if key and key not in seen:
            seen.add(key)
            population.append(candidate)
    if len(population) != size:
        raise RuntimeError(
            f"Could create only {len(population)} unique feasible initial solutions; expected {size}"
        )
    return population
