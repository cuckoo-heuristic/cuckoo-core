from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence, Tuple

from parameter.services import load_params_obj
from run.benchmark.evaluator import evaluate_joint_nest, evaluate_joint_nest_total
from run.benchmark.schemes import get_joint_scheme
from run.benchmark.search import (
    _build_search_static_cache,
    _domain,
    _prepare_joint_context_seed,
    _rebuild_nest,
    greedy_initial_population,
    task_order_for_scheme,
)

from .core import GACDJayaProblem, GACDJayaCoreResult, run_gac_djaya_core


def run_joint_gac_djaya(
    joint_ctx: Dict[str, Any],
    *,
    seed: int,
    tmax: int,
    population_size: int | None = None,
):
    """Execute the same canonical GAC-DJaya engine on a joint benchmark.

    The benchmark supplies only its joint evaluator and domain adapter.  All
    initialization, GA assistance, discrete Jaya transformations, randomness,
    convergence history and small-space handling live in ``core.py``.
    """
    _prepare_joint_context_seed(joint_ctx, int(seed))
    scheme = get_joint_scheme("gac_djaya")
    search_cache = _build_search_static_cache(joint_ctx)
    params = load_params_obj()
    resolved_population_size = int(
        population_size if population_size is not None else params.S
    )
    if resolved_population_size < 2:
        raise ValueError("population_size must be at least 2")

    task_order = tuple(
        int(task_id)
        for task_id in task_order_for_scheme(
            joint_ctx,
            scheme,
            search_cache,
        )
    )

    problem = GACDJayaProblem(
        task_order=task_order,
        task_type_ids={
            int(task_id): task_type_id
            for task_id, task_type_id in joint_ctx.get(
                "task_type_ids",
                {},
            ).items()
        },
        initial_cache={
            int(provider_id): set(task_types)
            for provider_id, task_types in joint_ctx.get(
                "initial_cache",
                {},
            ).items()
        },
        domain_for_task=lambda task_id: _domain(
            joint_ctx,
            int(task_id),
            scheme,
            search_cache,
        ),
        rebuild_nest=lambda provider_map: _rebuild_nest(
            joint_ctx,
            task_order,
            {
                int(task_id): int(provider_id)
                for task_id, provider_id in provider_map.items()
            },
            search_cache,
        ),
        evaluate_total=lambda nest: evaluate_joint_nest_total(
            joint_ctx,
            nest,
            task_order,
            use_caching=scheme.use_caching,
            v2i_only=scheme.v2i_only,
        ),
        greedy_population=lambda size, rng: greedy_initial_population(
            joint_ctx,
            scheme=scheme,
            population_size=int(size),
            rng=rng,
            search_cache=search_cache,
        ),
    )

    core_result: GACDJayaCoreResult = run_gac_djaya_core(
        problem,
        seed=int(seed),
        tmax=max(1, int(tmax)),
        population_size=resolved_population_size,
    )
    best_evaluation = evaluate_joint_nest(
        joint_ctx,
        core_result.best_nest,
        task_order,
        use_caching=scheme.use_caching,
        v2i_only=scheme.v2i_only,
    )
    return core_result.best_nest, best_evaluation, core_result.history
