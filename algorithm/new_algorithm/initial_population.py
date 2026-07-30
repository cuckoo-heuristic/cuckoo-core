"""Compatibility entry point for canonical GAC-DJaya initialization."""

from __future__ import annotations

import random

from .core import create_initial_population as _create_initial_population
from .core import get_nest_quality
from .main_gac_djaya import _build_runtime_problem


def calculate_qualities(population, ctx, task_order):
    problem = _build_runtime_problem(ctx, task_order)
    evaluation_cache = {}
    return [
        get_nest_quality(problem, nest, evaluation_cache)
        for nest in population
    ]


def create_initial_population(S, task_order, ctx, rng=None, tmax=None):
    if int(S) < 2:
        raise ValueError("Population size must be at least two")

    local_rng = rng if isinstance(rng, random.Random) else random.Random(
        int(ctx.get("seed", 0) or 0)
    )
    problem = _build_runtime_problem(ctx, task_order)
    population, _diagnostics = _create_initial_population(
        problem,
        int(S),
        max(1, int(tmax if tmax is not None else ctx.get("tmax", 10))),
        local_rng,
        {},
    )
    return population
