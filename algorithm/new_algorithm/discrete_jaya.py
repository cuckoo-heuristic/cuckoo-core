"""Compatibility wrappers for canonical discrete-Jaya transformations."""

from __future__ import annotations

import random
from collections import Counter

from .core import (
    cache_aware_trial,
    guided_jaya_trial,
    jaya_move_limit,
)
from .main_gac_djaya import _build_runtime_problem, _task_domain


def _jaya_move_limit(difference_count):
    return jaya_move_limit(int(difference_count))


def generate_guided_candidate(
    current_nest,
    best_nest,
    worst_nest,
    ctx,
    rng=None,
):
    task_order = [
        int(task_id)
        for task_id, _provider_id, _rank in current_nest
    ]
    problem = _build_runtime_problem(ctx, task_order)
    local_rng = rng if isinstance(rng, random.Random) else random.Random()
    return guided_jaya_trial(
        current_nest,
        best_nest,
        worst_nest,
        problem,
        local_rng,
    )


def generate_cache_aware_candidate(
    base_nest,
    best_nest,
    worst_nest,
    population,
    ctx,
    rng=None,
):
    task_order = [
        int(task_id)
        for task_id, _provider_id, _rank in base_nest
    ]
    problem = _build_runtime_problem(ctx, task_order)
    type_counts = Counter(
        problem.task_type_ids.get(task_id)
        for task_id in problem.task_order
        if problem.task_type_ids.get(task_id) is not None
    )
    local_rng = rng if isinstance(rng, random.Random) else random.Random()
    elite_count = max(2, (len(population) + 1) // 2)
    return cache_aware_trial(
        base_nest,
        best_nest,
        worst_nest,
        list(population[:elite_count]),
        problem,
        local_rng,
        type_counts,
    )


def generate_jaya_candidate(current_nest, best_nest, worst_nest, ctx):
    return generate_guided_candidate(
        current_nest,
        best_nest,
        worst_nest,
        ctx,
    )
