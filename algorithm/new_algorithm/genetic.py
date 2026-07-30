"""Compatibility wrappers for the canonical GAC-DJaya genetic operators."""

from __future__ import annotations

import random
from typing import Sequence

from .core import (
    Nest,
    create_child as _create_child,
    crossover as _crossover,
    mutation as _mutation,
    selection as _selection,
)
from .main_gac_djaya import _build_runtime_problem


def _rng(value=None):
    return value if isinstance(value, random.Random) else random.Random()


def selection(population, qualities, rng=None):
    return _selection(population, qualities, _rng(rng))


def crossover(parent1, parent2, ctx, rng=None):
    task_order = [int(task_id) for task_id, _provider_id, _rank in parent1]
    problem = _build_runtime_problem(ctx, task_order)
    return _crossover(parent1, parent2, problem, _rng(rng))


def mutation(nest, ctx, rng=None):
    task_order = [int(task_id) for task_id, _provider_id, _rank in nest]
    problem = _build_runtime_problem(ctx, task_order)
    return _mutation(nest, problem, _rng(rng))


def create_child(population, qualities, ctx, rng=None):
    if not population:
        raise ValueError("Population cannot be empty")
    task_order = [
        int(task_id)
        for task_id, _provider_id, _rank in population[0]
    ]
    problem = _build_runtime_problem(ctx, task_order)
    return _create_child(population, qualities, problem, _rng(rng))
