from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .. import main_dcsga
from ..greedy_nests import (
    _apply_assignment,
    _apply_entry_task,
    _empty_state,
    _providers,
    _reset_assignment,
    compute_Q,
    compute_Q1,
    rate,
)
from ..update_service_cache import update_cache
from .core import GACDJayaProblem, GACDJayaCoreResult, Nest, run_gac_djaya_core


def _task_domain(ctx: Dict[str, Any], task_id: int) -> List[int]:
    """Return the actual feasible provider domain for one runtime task."""
    providers = [int(provider_id) for provider_id in _providers(ctx)]
    declared = ctx.get("task_domains", {}).get(int(task_id))

    if declared:
        declared_ids = {int(provider_id) for provider_id in declared}
        providers = [
            provider_id
            for provider_id in providers
            if provider_id in declared_ids
        ]

    if not providers:
        raise ValueError(f"Task {task_id} has no feasible providers")
    return providers


def _rebuild_runtime_nest(
    ctx: Dict[str, Any],
    task_order: Sequence[int],
    provider_map: Mapping[int, int],
) -> Nest:
    ranks = {int(provider_id): 0 for provider_id in _providers(ctx)}
    local_sp_id = ctx.get("local_sp_id")
    if local_sp_id is not None:
        local_sp_id = int(local_sp_id)
        ranks.setdefault(local_sp_id, 0)
        # The entry task is fixed locally and occupies the first local rank.
        ranks[local_sp_id] += 1

    nest: Nest = []
    for task_id in task_order:
        task_id = int(task_id)
        provider_id = int(provider_map[task_id])
        if provider_id not in _task_domain(ctx, task_id):
            raise ValueError(
                f"Provider {provider_id} is outside task {task_id} domain"
            )
        ranks.setdefault(provider_id, 0)
        ranks[provider_id] += 1
        nest.append((task_id, provider_id, ranks[provider_id]))
    return nest


def _greedy_population(
    ctx: Dict[str, Any],
    task_order: Sequence[int],
    population_size: int,
    rng: random.Random,
) -> List[Nest]:
    """Runtime equivalent of the benchmark greedy constructor.

    It uses the same one-best-plus-one-controlled-mutation structure while
    keeping all randomness local to this GAC-DJaya run.
    """
    if not task_order:
        raise ValueError("GAC-DJaya requires at least one non-entry task")

    solutions: List[Tuple[Nest, float]] = []

    for solution_index in range(int(population_size)):
        main_dcsga._raise_if_cancelled(ctx)
        work_ctx = copy.deepcopy(ctx)
        _reset_assignment(work_ctx)
        work_ctx["_schedule_state"] = _empty_state(work_ctx)

        rank_counter = {
            int(provider_id): 0
            for provider_id in _providers(work_ctx)
        }
        local_sp_id = work_ctx.get("local_sp_id")
        if local_sp_id is not None:
            rank_counter.setdefault(int(local_sp_id), 0)

        _apply_entry_task(
            work_ctx,
            work_ctx["_schedule_state"],
            rank_counter,
        )

        mutation_index = rng.randrange(len(task_order))
        provider_map: Dict[int, int] = {}

        for index, task_id in enumerate(task_order):
            main_dcsga._raise_if_cancelled(work_ctx)
            task_id = int(task_id)
            remaining = [int(value) for value in task_order[index + 1 :]]
            candidate_rows = [
                (float(compute_Q(work_ctx, provider_id, task_id)), provider_id)
                for provider_id in _task_domain(work_ctx, task_id)
            ]
            candidate_rows.sort(key=lambda row: (-row[0], row[1]))

            if solution_index == 0:
                selected_provider = int(candidate_rows[0][1])
            elif index == mutation_index and len(candidate_rows) > 1:
                selected_provider = int(candidate_rows[1][1])
            else:
                selected_provider = int(candidate_rows[0][1])

            rank_counter.setdefault(selected_provider, 0)
            rank_counter[selected_provider] += 1
            _apply_assignment(
                work_ctx,
                work_ctx["_schedule_state"],
                task_id,
                selected_provider,
                rank_counter[selected_provider],
            )

            if work_ctx.get("use_caching", True):
                update_cache(
                    work_ctx,
                    selected_provider,
                    task_id,
                    remaining_task_ids=remaining,
                )

            provider_map[task_id] = selected_provider

        nest = _rebuild_runtime_nest(work_ctx, task_order, provider_map)
        solutions.append((nest, float(compute_Q1(work_ctx))))

    solutions.sort(key=lambda row: row[1], reverse=True)
    return [list(nest) for nest, _quality in solutions]


def _build_runtime_problem(
    ctx: Dict[str, Any],
    task_order: Sequence[int],
) -> GACDJayaProblem:
    normalized_order = tuple(int(task_id) for task_id in task_order)

    def evaluate_total(nest: Sequence[Tuple[int, int, int]]) -> float:
        quality, _cache_state, _scheduled_ctx = (
            main_dcsga.evaluate_solution_quality(
                ctx,
                list(nest),
                list(normalized_order),
            )
        )
        return float(quality)

    return GACDJayaProblem(
        task_order=normalized_order,
        task_type_ids={
            int(task_id): task_type_id
            for task_id, task_type_id in ctx.get("task_type_ids", {}).items()
        },
        initial_cache={
            int(provider_id): set(task_types)
            for provider_id, task_types in ctx.get("cache", {}).items()
        },
        domain_for_task=lambda task_id: _task_domain(ctx, int(task_id)),
        rebuild_nest=lambda provider_map: _rebuild_runtime_nest(
            ctx,
            normalized_order,
            provider_map,
        ),
        evaluate_total=evaluate_total,
        greedy_population=lambda size, rng: _greedy_population(
            ctx,
            normalized_order,
            size,
            rng,
        ),
        check_cancelled=lambda: main_dcsga._raise_if_cancelled(ctx),
    )


def gac_djaya_run_with_history(
    ctx: Dict[str, Any],
) -> Tuple[List[Tuple[int, int, int]], float, Dict[int, set[int]], List[Dict[str, Any]]]:
    """Execute the canonical GAC-DJaya engine for one runtime application."""
    main_dcsga._refresh_algorithm_params()
    ctx = main_dcsga._DCSGAContext(ctx)
    main_dcsga._raise_if_cancelled(ctx)

    seed_value = ctx.get("seed")
    seed = (
        int(seed_value)
        if seed_value is not None
        else random.SystemRandom().randrange(0, 2**63)
    )
    tmax = max(1, int(ctx.get("tmax", 10)))
    population_size = int(
        ctx.get("population_size", main_dcsga.params.S)
    )
    if population_size < 2:
        raise ValueError("Population size must be at least 2")

    ctx["rates"] = {
        int(provider_id): rate(ctx, int(provider_id))
        for provider_id in _providers(ctx)
    }
    task_order = main_dcsga.dcsga_compute_ranks_and_order(ctx)
    problem = _build_runtime_problem(ctx, task_order)
    core_result: GACDJayaCoreResult = run_gac_djaya_core(
        problem,
        seed=seed,
        tmax=tmax,
        population_size=population_size,
    )

    solution, quality, cache_state = main_dcsga._materialize_solution(
        ctx,
        core_result.best_nest,
        task_order,
    )
    return solution, float(quality), cache_state, core_result.history


def gac_djaya_run(ctx: Dict[str, Any]):
    """Backward-compatible runtime entry point."""
    solution, quality, cache_state, _history = gac_djaya_run_with_history(ctx)
    return solution, quality, cache_state
