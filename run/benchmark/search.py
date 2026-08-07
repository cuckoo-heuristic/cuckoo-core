from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from parameter.services import load_params_obj
from algorithm.main_dcsga import compute_local_ranks
from algorithm.dcsga_core import mutate_provider_map, run_population_search

from .evaluator import (
    JointEvaluation,
    JointScheduleState,
    NestItem,
    evaluate_joint_nest,
    evaluate_joint_nest_total,
)
from .schemes import (
    SUPPORTED_JOINT_ALGORITHMS,
    JointScheme,
    get_joint_scheme,
)


@dataclass
class _SearchStaticCache:
    """Per-run immutable lookup cache for search-only structural data.

    The cached values are derived from the seeded joint scenario before the
    first nest is generated. They remain fixed during one run and do not
    depend on the current nest, cache contents, queues, or other mutable
    scheduling state.
    """

    ranked_task_ids: Tuple[int, ...]
    unranked_task_ids: Tuple[int, ...]
    initial_provider_ranks: Dict[int, int]
    domains: Dict[Tuple[str, int], List[int]] = field(default_factory=dict)
    modes: Dict[Tuple[int, int], str] = field(default_factory=dict)


def _build_search_static_cache(
    joint_ctx: Dict[str, Any],
) -> _SearchStaticCache:
    ranks = {
        int(sp_id): 0
        for sp_id in joint_ctx["provider_ids"]
    }
    for app_id in joint_ctx["application_ids"]:
        local_sp_id = int(
            joint_ctx["applications"][app_id]["local_sp_id"]
        )
        ranks[local_sp_id] = ranks.get(local_sp_id, 0) + 1

    return _SearchStaticCache(
        ranked_task_ids=tuple(
            int(task_id)
            for task_id in joint_ctx["ranked_task_ids"]
        ),
        unranked_task_ids=tuple(
            int(task_id)
            for task_id in joint_ctx["unranked_task_ids"]
        ),
        initial_provider_ranks=ranks,
    )


def _prepare_joint_context_seed(
    joint_ctx: Dict[str, Any],
    seed: int,
) -> None:
    seed = int(seed)
    joint_ctx["seed"] = seed
    for app_ctx in joint_ctx.get("applications", {}).values():
        app_ctx["seed"] = seed
        app_ctx.pop("_link_fading", None)
        app_ctx.pop("_channel_gain_cache", None)
        app_ctx.pop("_tx_power_cache", None)
        app_ctx.pop("_link_rate_cache", None)
        app_ctx.pop("_tx_time_energy_cache", None)
        app_ctx.pop("_service_program_energy_cache", None)
        app_ctx.pop("_t_loc_s_cache", None)
        app_ctx.pop("_e_loc_j_cache", None)
        app_ctx.pop("_t_ref_s_cache", None)


def _seed_aligned_dcsga_ranked_task_ids(
    joint_ctx: Dict[str, Any],
) -> Tuple[int, ...]:
    """Recompute DCSGA ranks after installing the benchmark run seed.

    The former paper-benchmark path calculated DCSGA ranks while building the
    joint context, before a run seed existed. Rank calculation uses stochastic
    channel rates, whereas nest fitness was later evaluated with the requested
    seed. DTOSC already installs its seed before calculating its own ranks.

    DCSGA searches provider assignments only; it cannot repair a stale task
    order. This helper puts ranking, greedy initialization, Levy search and
    final fitness on the same channel realization.
    """

    max_deadline_s = max(
        float(joint_ctx["applications"][int(app_id)]["deadline_s"])
        for app_id in joint_ctx["application_ids"]
    )
    ranked_rows: List[Tuple[int, float]] = []

    for app_id in joint_ctx["application_ids"]:
        app_id = int(app_id)
        app_ctx = joint_ctx["applications"][app_id]
        local_ranks = compute_local_ranks(app_ctx)
        urgency = max_deadline_s - float(app_ctx["deadline_s"])

        for joint_task_id, ref in joint_ctx["task_refs"].items():
            if int(ref.application_id) != app_id or bool(ref.is_entry):
                continue
            original_task_id = int(ref.task_id)
            ranked_rows.append(
                (
                    int(joint_task_id),
                    float(local_ranks[original_task_id]) + urgency,
                )
            )

    ranked_task_ids = tuple(
        int(joint_task_id)
        for joint_task_id, _rank in sorted(
            ranked_rows,
            key=lambda row: (-row[1], row[0]),
        )
    )

    expected = {int(value) for value in joint_ctx["optimized_task_ids"]}
    actual = set(ranked_task_ids)
    if actual != expected or len(ranked_task_ids) != len(expected):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(
            f"DCSGA seeded rank order mismatch; missing={missing}, extra={extra}"
        )

    positions = {task_id: index for index, task_id in enumerate(ranked_task_ids)}
    reverse_refs = joint_ctx["reverse_task_refs"]
    for app_id in joint_ctx["application_ids"]:
        app_id = int(app_id)
        app_ctx = joint_ctx["applications"][app_id]
        entry_task_id = int(app_ctx["entry_task_id"])
        for child_id, predecessors in app_ctx.get("dependencies", {}).items():
            child_id = int(child_id)
            if child_id == entry_task_id:
                continue
            child_joint = int(reverse_refs[(app_id, child_id)])
            for predecessor_id in predecessors:
                predecessor_id = int(predecessor_id)
                if predecessor_id == entry_task_id:
                    continue
                predecessor_joint = int(reverse_refs[(app_id, predecessor_id)])
                if positions[predecessor_joint] >= positions[child_joint]:
                    raise ValueError(
                        "Seed-aligned DCSGA ranking produced a dependency-invalid "
                        f"order: application={app_id}, predecessor={predecessor_id}, "
                        f"child={child_id}"
                    )

    return ranked_task_ids


def task_order_for_scheme(
    joint_ctx: Dict[str, Any],
    scheme: JointScheme,
    search_cache: _SearchStaticCache | None = None,
) -> List[int]:
    if search_cache is not None:
        source = (
            search_cache.ranked_task_ids
            if scheme.use_ranking
            else search_cache.unranked_task_ids
        )
        return list(source)

    key = "ranked_task_ids" if scheme.use_ranking else "unranked_task_ids"
    return [int(task_id) for task_id in joint_ctx[key]]


def _mode_for_task(
    joint_ctx: Dict[str, Any],
    joint_task_id: int,
    provider_id: int,
    search_cache: _SearchStaticCache | None = None,
) -> str:
    joint_task_id = int(joint_task_id)
    provider_id = int(provider_id)
    cache_key = (joint_task_id, provider_id)

    if search_cache is not None:
        cached = search_cache.modes.get(cache_key)
        if cached is not None:
            return cached

    ref = joint_ctx["task_refs"][joint_task_id]
    app_ctx = joint_ctx["applications"][ref.application_id]
    mode = str(app_ctx.get("sp_modes", {}).get(provider_id, "unknown"))

    if search_cache is not None:
        search_cache.modes[cache_key] = mode
    return mode


def _domain(
    joint_ctx: Dict[str, Any],
    joint_task_id: int,
    scheme: JointScheme,
    search_cache: _SearchStaticCache | None = None,
) -> List[int]:
    joint_task_id = int(joint_task_id)
    cache_key = (str(scheme.name), joint_task_id)

    if search_cache is not None:
        cached = search_cache.domains.get(cache_key)
        if cached is not None:
            return cached

    ref = joint_ctx["task_refs"][joint_task_id]
    app_ctx = joint_ctx["applications"][ref.application_id]
    providers = [
        int(sp_id)
        for sp_id in joint_ctx["task_domains"][joint_task_id]
    ]

    if scheme.provider_scope == "rsu_only":
        providers = [
            sp_id
            for sp_id in providers
            if app_ctx.get("sp_types", {}).get(sp_id) == "rsu"
        ]
    elif scheme.provider_scope == "local_and_rsu":
        local_sp_id = int(app_ctx["local_sp_id"])
        providers = [
            sp_id
            for sp_id in providers
            if sp_id == local_sp_id
            or app_ctx.get("sp_types", {}).get(sp_id) == "rsu"
        ]

    if not providers:
        raise ValueError(
            f"Joint task {joint_task_id} has no feasible providers"
        )

    if search_cache is not None:
        search_cache.domains[cache_key] = providers
    return providers


def _initial_provider_ranks(
    joint_ctx: Dict[str, Any],
    search_cache: _SearchStaticCache | None = None,
) -> Dict[int, int]:
    if search_cache is not None:
        return dict(search_cache.initial_provider_ranks)

    ranks = {int(sp_id): 0 for sp_id in joint_ctx["provider_ids"]}
    for app_id in joint_ctx["application_ids"]:
        local_sp_id = int(joint_ctx["applications"][app_id]["local_sp_id"])
        ranks[local_sp_id] = ranks.get(local_sp_id, 0) + 1
    return ranks


def _rebuild_nest(
    joint_ctx: Dict[str, Any],
    task_order: Sequence[int],
    provider_map: Dict[int, int],
    search_cache: _SearchStaticCache | None = None,
) -> List[NestItem]:
    ranks: Dict[int, int] = _initial_provider_ranks(
        joint_ctx,
        search_cache,
    )
    nest: List[NestItem] = []
    for joint_task_id in task_order:
        provider_id = int(provider_map[int(joint_task_id)])
        ranks[provider_id] = ranks.get(provider_id, 0) + 1
        nest.append((int(joint_task_id), provider_id, ranks[provider_id]))
    return nest


def greedy_initial_population(
    joint_ctx: Dict[str, Any],
    *,
    scheme: JointScheme,
    population_size: int,
    rng: random.Random,
    search_cache: _SearchStaticCache | None = None,
    evaluation_memo: Dict[Tuple[int, ...], float] | None = None,
) -> List[List[NestItem]]:
    if search_cache is None:
        search_cache = _build_search_static_cache(joint_ctx)

    task_order = task_order_for_scheme(
        joint_ctx,
        scheme,
        search_cache,
    )
    if not task_order:
        raise ValueError("Joint scenario has no non-entry tasks")

    solutions: List[Tuple[List[NestItem], float]] = []

    for solution_index in range(population_size):
        state = JointScheduleState(
            joint_ctx,
            use_caching=scheme.use_caching,
            v2i_only=scheme.v2i_only,
            record_schedule=False,
        )
        state.assign_entry_tasks()
        mutation_index = rng.randrange(len(task_order))
        provider_map: Dict[int, int] = {}

        for index, joint_task_id in enumerate(task_order):
            remaining = task_order[index + 1 :]
            candidate_rows: List[Tuple[float, int]] = []

            for provider_id in _domain(
                joint_ctx,
                joint_task_id,
                scheme,
                search_cache,
            ):
                candidate_rows.append(
                    (state.candidate_provider_score(joint_task_id, provider_id), provider_id)
                )

            candidate_rows.sort(key=lambda row: (-row[0], row[1]))
            if solution_index == 0:
                selected_provider = candidate_rows[0][1]
            elif index == mutation_index and len(candidate_rows) > 1:
                selected_provider = candidate_rows[1][1]
            else:
                selected_provider = candidate_rows[0][1]

            state.assign_task(
                joint_task_id,
                selected_provider,
                remaining_task_ids=remaining,
            )
            provider_map[joint_task_id] = selected_provider

        total_efficiency = float(state.total_efficiency())
        nest = _rebuild_nest(
            joint_ctx,
            task_order,
            provider_map,
            search_cache,
        )
        solutions.append((nest, total_efficiency))

        # The greedy constructor has already evaluated this exact assignment
        # while building it.  Seed the per-run objective memo so the same nest
        # is not scheduled and evaluated a second time immediately after
        # initialization.  The signature is identical to _evaluate_population,
        # therefore this changes runtime only and cannot change ordering,
        # randomness, or the numerical result.
        if evaluation_memo is not None:
            signature = tuple(
                int(provider_map[int(task_id)])
                for task_id in task_order
            )
            evaluation_memo.setdefault(signature, total_efficiency)

    solutions.sort(key=lambda row: row[1], reverse=True)
    return [nest for nest, _quality in solutions]


def generate_new_solution(
    joint_ctx: Dict[str, Any],
    source_nest: Sequence[NestItem],
    best_nest: Sequence[NestItem] | None,
    *,
    scheme: JointScheme,
    levy_lambda: float,
    rng: random.Random,
    search_cache: _SearchStaticCache | None = None,
) -> List[NestItem]:
    """Joint-benchmark adapter for the shared canonical Procedure 3 kernel."""
    task_order = [int(task_id) for task_id, _provider_id, _rank in source_nest]
    source = {
        int(task_id): int(provider_id)
        for task_id, provider_id, _rank in source_nest
    }
    best = (
        {
            int(task_id): int(provider_id)
            for task_id, provider_id, _rank in best_nest
        }
        if best_nest is not None
        else None
    )

    provider_map = mutate_provider_map(
        task_order,
        source,
        best,
        levy_lambda=float(levy_lambda),
        rng=rng,
        domain_for_task=lambda task_id: _domain(
            joint_ctx,
            int(task_id),
            scheme,
            search_cache,
        ),
        mode_for_task_provider=lambda task_id, provider_id: _mode_for_task(
            joint_ctx,
            int(task_id),
            int(provider_id),
            search_cache,
        ),
    )
    return _rebuild_nest(
        joint_ctx,
        task_order,
        provider_map,
        search_cache,
    )

def _evaluate_population(
    joint_ctx: Dict[str, Any],
    population: Iterable[Sequence[NestItem]],
    *,
    task_order: Sequence[int],
    scheme: JointScheme,
    memo: Dict[Tuple[int, ...], float] | None = None,
) -> List[Tuple[List[NestItem], float]]:
    """Rank intermediate nests using the exact objective-only evaluator.

    The complete schedule/report is intentionally materialized only once for
    the final winning nest in ``run_joint_dcsga``.  This changes neither the
    objective value nor the population ordering; it only skips report-object
    construction for nests that the optimizer uses solely as scalar fitness.
    """

    evaluated: List[Tuple[List[NestItem], float]] = []
    if memo is None:
        memo = {}

    for nest in population:
        provider_by_task = {
            int(task_id): int(provider_id)
            for task_id, provider_id, _rank in nest
        }
        signature = tuple(provider_by_task[int(task_id)] for task_id in task_order)
        if signature in memo:
            total_efficiency = memo[signature]
        else:
            total_efficiency = evaluate_joint_nest_total(
                joint_ctx,
                nest,
                task_order,
                use_caching=scheme.use_caching,
                v2i_only=scheme.v2i_only,
            )
            memo[signature] = total_efficiency
        evaluated.append((list(nest), float(total_efficiency)))

    evaluated.sort(key=lambda row: row[1], reverse=True)
    return evaluated


def _history_row(
    iteration: int,
    evaluated: List[Tuple[List[NestItem], float]],
    function_evaluations: int | None = None,
) -> Dict[str, Any]:
    population = [float(row[1]) for row in evaluated]
    row = {
        "iteration": float(iteration),
        "best_total_efficiency": float(max(population)),
        "population_total_efficiencies": population,
    }

    if function_evaluations is not None:
        row["function_evaluations"] = int(function_evaluations)

    return row


def run_joint_dcsga(
    joint_ctx: Dict[str, Any],
    *,
    algorithm: str,
    seed: int,
    tmax: int,
    population_size: int | None = None,
) -> Tuple[List[NestItem], JointEvaluation, List[Dict[str, Any]]]:
    _prepare_joint_context_seed(joint_ctx, seed)
    scheme = get_joint_scheme(algorithm)
    if scheme.use_ranking:
        joint_ctx["ranked_task_ids"] = list(
            _seed_aligned_dcsga_ranked_task_ids(joint_ctx)
        )
        joint_ctx["dcsga_rank_seed"] = int(seed)
        joint_ctx["dcsga_rank_seed_aligned"] = True
    search_cache = _build_search_static_cache(joint_ctx)
    if scheme.name == "dtosc":
        raise ValueError("DTOSC must be executed with run_joint_dtosc")

    params = load_params_obj()
    S = int(population_size if population_size is not None else params.S)
    if S < 2:
        raise ValueError("population_size must be at least 2")
    tmax = max(1, int(tmax))
    rng = random.Random(int(seed))
    levy_lambda = float(params.levy_lambda)
    task_order = task_order_for_scheme(
        joint_ctx,
        scheme,
        search_cache,
    )

    evaluation_memo: Dict[Tuple[int, ...], float] = {}
    initial_population = greedy_initial_population(
        joint_ctx,
        scheme=scheme,
        population_size=S,
        rng=rng,
        search_cache=search_cache,
        evaluation_memo=evaluation_memo,
    )
    history: List[Dict[str, Any]] = []

    def evaluate_population(population):
        return _evaluate_population(
            joint_ctx,
            population,
            task_order=task_order,
            scheme=scheme,
            memo=evaluation_memo,
        )

    def generate(source_nest, best_nest):
        return generate_new_solution(
            joint_ctx,
            source_nest,
            best_nest,
            scheme=scheme,
            levy_lambda=levy_lambda,
            rng=rng,
            search_cache=search_cache,
        )

    def record_history(iteration, evaluated):
        history.append(
            _history_row(
                iteration,
                evaluated,
                function_evaluations=len(evaluation_memo),
            )
        )

    _population, best_nest, _evaluated = run_population_search(
        initial_population,
        population_size=S,
        tmax=tmax,
        initial_discard_probability=float(params.p_discard_init),
        rng=rng,
        generate_new_solution=generate,
        evaluate_population=evaluate_population,
        on_iteration=record_history,
    )

    # Materialize the full, externally visible result exactly once for the
    # final winner. CSV/JSON/XLSX rows, cache state, schedule rows, delays,
    # energies and completion metrics still come from the unchanged evaluator.
    best_evaluation = evaluate_joint_nest(
        joint_ctx,
        best_nest,
        task_order,
        use_caching=scheme.use_caching,
        v2i_only=scheme.v2i_only,
    )
    return best_nest, best_evaluation, history


@dataclass
class _JointDTOSCDPNode:
    state: JointScheduleState
    cumulative_utility: float
    provider_path: Tuple[int, ...]


def _dtosc_application_order(
    joint_ctx: Dict[str, Any],
    ranked_task_order: Sequence[int],
) -> List[int]:
    """Order applications by their first globally ranked non-entry task."""

    first_position: Dict[int, int] = {}
    for position, joint_task_id in enumerate(ranked_task_order):
        ref = joint_ctx["task_refs"][int(joint_task_id)]
        first_position.setdefault(int(ref.application_id), int(position))

    return sorted(
        (int(app_id) for app_id in joint_ctx["application_ids"]),
        key=lambda app_id: (
            first_position.get(app_id, len(ranked_task_order)),
            float(joint_ctx["applications"][app_id]["deadline_s"]),
            app_id,
        ),
    )


def _joint_dtosc_numeric_key(
    node: _JointDTOSCDPNode,
    application_id: int,
    *,
    final: bool,
) -> Tuple[float, ...]:
    efficiency = node.state.application_efficiency(application_id)
    finish = node.state.application_finish_time(application_id)
    energy = node.state.application_energy(application_id)

    if final:
        return (
            float(efficiency),
            float(node.cumulative_utility),
            -float(finish),
            -float(energy),
        )

    return (
        float(node.cumulative_utility),
        float(efficiency),
        -float(finish),
        -float(energy),
    )


def _joint_dtosc_is_better(
    candidate: _JointDTOSCDPNode,
    incumbent: _JointDTOSCDPNode | None,
    application_id: int,
    *,
    final: bool,
) -> bool:
    if incumbent is None:
        return True

    candidate_key = _joint_dtosc_numeric_key(
        candidate,
        application_id,
        final=final,
    )
    incumbent_key = _joint_dtosc_numeric_key(
        incumbent,
        application_id,
        final=final,
    )
    if candidate_key != incumbent_key:
        return candidate_key > incumbent_key
    return candidate.provider_path < incumbent.provider_path


def _dtosc_nest_from_state(state: JointScheduleState) -> List[NestItem]:
    nest = [
        (
            int(row["joint_task_id"]),
            int(row["provider_id"]),
            int(row["rank"]),
        )
        for row in state.schedule_rows
        if not bool(row.get("is_entry", False))
    ]
    expected = set(int(value) for value in state.joint_ctx["optimized_task_ids"])
    actual = {int(task_id) for task_id, _provider_id, _rank in nest}
    if actual != expected or len(nest) != len(expected):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(
            f"DTOSC DP nest mismatch; missing={missing}, extra={extra}"
        )
    return nest


def run_joint_dtosc(
    joint_ctx: Dict[str, Any],
    *,
    seed: int,
) -> Tuple[List[NestItem], JointEvaluation, List[Dict[str, Any]]]:
    """Run semi-distributed DTOSC with stage-wise dynamic programming.

    Applications are processed in global-priority order. Inside each
    application, the Bellman frontier retains the best partial schedule for
    every provider of the current task. All transitions use the common
    evaluator, therefore provider queues, dependency transfers, energy and
    cache changes remain fully compatible with DCSGA and the other baselines.
    """

    _prepare_joint_context_seed(joint_ctx, seed)
    scheme = get_joint_scheme("dtosc")
    search_cache = _build_search_static_cache(joint_ctx)
    ranked_task_order = task_order_for_scheme(
        joint_ctx,
        scheme,
        search_cache,
    )
    application_order = _dtosc_application_order(joint_ctx, ranked_task_order)
    tasks_by_application: Dict[int, List[int]] = {
        app_id: [
            int(joint_task_id)
            for joint_task_id in ranked_task_order
            if int(joint_ctx["task_refs"][int(joint_task_id)].application_id)
            == app_id
        ]
        for app_id in application_order
    }
    dtosc_task_order = [
        joint_task_id
        for app_id in application_order
        for joint_task_id in tasks_by_application[app_id]
    ]
    task_position = {
        int(joint_task_id): int(position)
        for position, joint_task_id in enumerate(dtosc_task_order)
    }

    state = JointScheduleState(
        joint_ctx,
        use_caching=scheme.use_caching,
        v2i_only=False,
    )
    state.assign_entry_tasks()

    transitions = 0
    stages = 0
    peak_frontier = 1

    for application_id in application_order:
        app_tasks = tasks_by_application[application_id]
        if not app_tasks:
            continue

        frontier: List[_JointDTOSCDPNode] = [
            _JointDTOSCDPNode(
                state=state,
                cumulative_utility=0.0,
                provider_path=(),
            )
        ]

        for joint_task_id in app_tasks:
            stages += 1
            position = task_position[int(joint_task_id)]
            remaining = dtosc_task_order[position + 1 :]
            best_by_provider: Dict[int, _JointDTOSCDPNode] = {}

            for node in frontier:
                for provider_id in _domain(
                    joint_ctx,
                    joint_task_id,
                    scheme,
                    search_cache,
                ):
                    transitions += 1
                    stage_utility = float(
                        node.state.candidate_provider_score(
                            joint_task_id,
                            provider_id,
                        )
                    )
                    child_state = node.state.clone_for_application(
                        application_id
                    )
                    child_state.assign_task(
                        joint_task_id,
                        provider_id,
                        remaining_task_ids=remaining,
                    )
                    candidate = _JointDTOSCDPNode(
                        state=child_state,
                        cumulative_utility=float(
                            node.cumulative_utility + stage_utility
                        ),
                        provider_path=(
                            node.provider_path + (int(provider_id),)
                        ),
                    )
                    incumbent = best_by_provider.get(int(provider_id))
                    if _joint_dtosc_is_better(
                        candidate,
                        incumbent,
                        application_id,
                        final=False,
                    ):
                        best_by_provider[int(provider_id)] = candidate

            if not best_by_provider:
                raise RuntimeError(
                    "DTOSC dynamic-programming frontier became empty for "
                    f"application {application_id}, task {joint_task_id}"
                )

            frontier = [
                best_by_provider[provider_id]
                for provider_id in sorted(best_by_provider)
            ]
            peak_frontier = max(peak_frontier, len(frontier))

        best_node: _JointDTOSCDPNode | None = None
        for candidate in frontier:
            if _joint_dtosc_is_better(
                candidate,
                best_node,
                application_id,
                final=True,
            ):
                best_node = candidate

        if best_node is None:
            raise RuntimeError(
                f"DTOSC produced no final state for application {application_id}"
            )
        # Commit the best application-level DP path before the next RSU/app
        # subproblem, which is the semi-distributed decomposition of DTOSC.
        state = best_node.state

    nest = _dtosc_nest_from_state(state)
    evaluation = state.final_evaluation()
    history = [
        {
            "iteration": 0.0,
            "best_total_efficiency": float(evaluation.total_efficiency),
            "dp_applications": float(len(application_order)),
            "dp_stages": float(stages),
            "dp_transitions": float(transitions),
            "dp_peak_frontier": float(peak_frontier),
        }
    ]
    return nest, evaluation, history