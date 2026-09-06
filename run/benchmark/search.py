from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from parameter.services import load_params_obj
from algorithm.main_dcsga import compute_global_ranks, compute_local_ranks
from algorithm.dcsga_core import mutate_provider_map, run_population_search

from .evaluator import (
    JointEvaluation,
    JointScheduleState,
    NestItem,
    evaluate_joint_nest,
    evaluate_joint_nest_cache_state,
    evaluate_joint_nest_total,
    evaluate_joint_nest_total_and_cache,
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


def _seed_aligned_dcsga_rank_data(
    joint_ctx: Dict[str, Any],
) -> Tuple[Tuple[int, ...], Dict[int, float]]:
    """Return the seeded DCSGA joint order and its numeric global ranks.

    Rank computation is performed after the benchmark seed is installed, so
    ranking, greedy initialization, search, and fitness all use the same
    channel realization.  The global-rank formula itself is delegated to the
    shared DCSGA implementation instead of being reproduced here.
    """

    max_deadline_s = max(
        float(joint_ctx["applications"][int(app_id)]["deadline_s"])
        for app_id in joint_ctx["application_ids"]
    )
    rank_by_joint_task: Dict[int, float] = {}

    for app_id in joint_ctx["application_ids"]:
        app_id = int(app_id)
        app_ctx = joint_ctx["applications"][app_id]
        local_ranks = compute_local_ranks(app_ctx)
        global_ranks = compute_global_ranks(
            {
                "deadline_max_s": float(max_deadline_s),
                "deadline_s": float(app_ctx["deadline_s"]),
            },
            local_ranks,
        )

        for joint_task_id, ref in joint_ctx["task_refs"].items():
            if int(ref.application_id) != app_id or bool(ref.is_entry):
                continue
            original_task_id = int(ref.task_id)
            rank_by_joint_task[int(joint_task_id)] = float(
                global_ranks[original_task_id]
            )

    ranked_task_ids = tuple(
        int(joint_task_id)
        for joint_task_id, _rank in sorted(
            rank_by_joint_task.items(),
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

    return ranked_task_ids, rank_by_joint_task


def _seed_aligned_dcsga_ranked_task_ids(
    joint_ctx: Dict[str, Any],
) -> Tuple[int, ...]:
    """Compatibility wrapper returning only the seeded task order."""

    ranked_task_ids, _task_ranks = _seed_aligned_dcsga_rank_data(joint_ctx)
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
    evaluation_counter: Dict[str, int] | None = None,
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
        if evaluation_counter is not None:
            evaluation_counter["count"] = int(
                evaluation_counter.get("count", 0)
            ) + 1
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
    evaluation_counter: Dict[str, int] | None = None,
    max_function_evaluations: int | None = None,
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
            if (
                max_function_evaluations is not None
                and evaluation_counter is not None
                and int(evaluation_counter.get("count", 0))
                >= int(max_function_evaluations)
            ):
                break
            total_efficiency = evaluate_joint_nest_total(
                joint_ctx,
                nest,
                task_order,
                use_caching=scheme.use_caching,
                v2i_only=scheme.v2i_only,
            )
            memo[signature] = total_efficiency
            if evaluation_counter is not None:
                evaluation_counter["count"] = int(
                    evaluation_counter.get("count", 0)
                ) + 1
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




def run_joint_gwo_aco(
    joint_ctx: Dict[str, Any],
    *,
    algorithm: str,
    seed: int,
    tmax: int,
    population_size: int | None = None,
    max_function_evaluations: int | None = None,
):
    """Run the discrete GWO-ACO search on the joint paper benchmark.

    The adapter exposes the exact run seed and the numeric seeded DCSGA rank
    map to the optimizer.  Intermediate wolves use the same objective-only
    evaluator as DCSGA; the full schedule is materialized only for the winner.
    """
    from algorithm.gwo.core import run_gwo_aco
    from algorithm.gwo.predictive_cache import (
        DEFAULT_DAG_AWARE,
        DEFAULT_LOOKAHEAD,
        DEFAULT_PREDICTIVE_WEIGHT,
        DEFAULT_PROVIDER_GUIDANCE_WEIGHT,
        DEFAULT_RANK_AWARE,
        DEFAULT_REGIONAL_CACHE_ENABLED,
        DEFAULT_REGIONAL_CACHE_SHARE,
        DEFAULT_REGIONAL_ELITE_RATIO,
        RegionalCacheMemory,
        build_joint_dag_distance_map,
        build_joint_regional_provider_maps,
        build_regional_rsu_service_demand,
    )
    from algorithm.gwo.operators import _rank_weight

    _prepare_joint_context_seed(joint_ctx, seed)
    scheme = get_joint_scheme(algorithm)
    ranked_task_ids, task_rank = _seed_aligned_dcsga_rank_data(joint_ctx)
    joint_ctx["ranked_task_ids"] = list(ranked_task_ids)
    joint_ctx["task_rank"] = dict(task_rank)
    joint_ctx["dcsga_rank_seed"] = int(seed)
    joint_ctx["dcsga_rank_seed_aligned"] = True

    # Reuse the optimizer's canonical rank normalizer; do not maintain a
    # second ranking formula for predictive caching.
    joint_ctx["predictive_rank_weight"] = {
        int(task_id): float(_rank_weight(int(task_id), task_rank))
        for task_id in task_rank
    }
    # The DAG structure is fixed for the whole run, so compute shortest
    # descendant distances once instead of rebuilding them per wolf.
    joint_ctx["predictive_dag_distance"] = build_joint_dag_distance_map(joint_ctx)

    predictive_lookahead = max(
        0,
        int(
            joint_ctx.get(
                "predictive_cache_lookahead",
                DEFAULT_LOOKAHEAD,
            )
        ),
    )
    predictive_weight = max(
        0.0,
        float(
            joint_ctx.get(
                "predictive_cache_weight",
                DEFAULT_PREDICTIVE_WEIGHT,
            )
        ),
    )
    predictive_rank_aware = bool(
        joint_ctx.get("predictive_cache_rank_aware", DEFAULT_RANK_AWARE)
    )
    predictive_dag_aware = bool(
        joint_ctx.get("predictive_cache_dag_aware", DEFAULT_DAG_AWARE)
    )
    provider_guidance_weight = max(
        0.0,
        float(
            joint_ctx.get(
                "predictive_provider_guidance_weight",
                DEFAULT_PROVIDER_GUIDANCE_WEIGHT,
            )
        ),
    )
    regional_cache_enabled = bool(
        joint_ctx.get("regional_cache_enabled", DEFAULT_REGIONAL_CACHE_ENABLED)
    )
    regional_cache_share = max(
        0.0,
        min(
            1.0,
            float(
                joint_ctx.get(
                    "regional_cache_share",
                    DEFAULT_REGIONAL_CACHE_SHARE,
                )
            ),
        ),
    )
    regional_elite_ratio = max(
        0.0,
        min(
            1.0,
            float(
                joint_ctx.get(
                    "regional_cache_elite_ratio",
                    DEFAULT_REGIONAL_ELITE_RATIO,
                )
            ),
        ),
    )
    regional_provider_rsu_ids, regional_provider_types = (
        build_joint_regional_provider_maps(joint_ctx)
    )
    regional_memory = RegionalCacheMemory(
        regional_provider_rsu_ids,
        regional_provider_types,
        elite_ratio=regional_elite_ratio,
    )
    regional_profile_evaluations = {"count": 0}
    # Objective evaluation already materializes the final cache state.  Keep
    # that tiny by-product for the current regional-memory version so elite
    # observations do not schedule the same wolf a second time.
    regional_cache_state_memo: Dict[
        Tuple[int, Tuple[Tuple[int, int], ...]],
        Dict[int, set[int]],
    ] = {}

    def regional_solution_key(solution) -> Tuple[Tuple[int, int], ...]:
        return tuple(
            (int(gene[0]), int(gene[1]))
            for gene in solution
            if isinstance(gene, (tuple, list)) and len(gene) >= 2
        )

    # Search guidance may estimate future service reuse, but fitness must use
    # the exact same paper cache/evaluator as DCSGA.  Giving GWO a different
    # cache policy would change the problem instead of improving the optimizer.
    joint_ctx["predictive_cache_enabled"] = False
    joint_ctx["predictive_cache_policy"] = "paper"
    joint_ctx["predictive_cache_lookahead"] = predictive_lookahead
    joint_ctx["predictive_cache_weight"] = predictive_weight
    joint_ctx["predictive_cache_rank_aware"] = predictive_rank_aware
    joint_ctx["predictive_cache_dag_aware"] = predictive_dag_aware
    joint_ctx["predictive_provider_guidance_weight"] = provider_guidance_weight
    joint_ctx["regional_cache_enabled"] = False
    joint_ctx["regional_cache_share"] = float(regional_cache_share)
    joint_ctx["regional_cache_elite_ratio"] = float(regional_elite_ratio)
    joint_ctx["regional_provider_rsu_ids"] = dict(regional_provider_rsu_ids)
    joint_ctx["regional_provider_types"] = dict(regional_provider_types)
    joint_ctx["regional_rsu_vehicle_cache_prevalence"] = {}
    joint_ctx["regional_rsu_assignment_demand"] = {}
    joint_ctx["regional_rsu_service_popularity"] = {}
    joint_ctx["regional_cache_version"] = 0

    search_cache = _build_search_static_cache(joint_ctx)
    initial_evaluation_memo: Dict[Tuple[Tuple[int, int], ...], float] = {}
    initial_evaluation_counter = {"count": 0}

    def evaluator(solution):
        return float(evaluate_joint_nest_total(
            joint_ctx,
            solution,
            joint_ctx["ranked_task_ids"],
            use_caching=scheme.use_caching,
            v2i_only=scheme.v2i_only,
        ))

    class ContextAdapter:
        """Adapter between the joint benchmark and the standalone GWO engine."""

        @property
        def seed(self):
            return int(joint_ctx["seed"])

        @property
        def initial_evaluation_memo(self):
            return initial_evaluation_memo

        @property
        def initial_function_evaluations(self):
            return int(initial_evaluation_counter["count"])

        @property
        def task_rank(self):
            return joint_ctx.get("task_rank", {})

        @property
        def task_type_ids(self):
            return joint_ctx.get("task_type_ids", {})

        @property
        def predictive_rank_weight(self):
            return joint_ctx.get("predictive_rank_weight", {})

        @property
        def predictive_dag_distance(self):
            return joint_ctx.get("predictive_dag_distance", {})

        @property
        def predictive_cache_rank_aware(self):
            return bool(joint_ctx.get("predictive_cache_rank_aware", True))

        @property
        def predictive_cache_dag_aware(self):
            return bool(joint_ctx.get("predictive_cache_dag_aware", True))

        @property
        def predictive_cache_lookahead(self):
            return int(joint_ctx.get("predictive_cache_lookahead", DEFAULT_LOOKAHEAD))

        @property
        def predictive_provider_guidance_weight(self):
            return float(
                joint_ctx.get(
                    "predictive_provider_guidance_weight",
                    DEFAULT_PROVIDER_GUIDANCE_WEIGHT,
                )
            )

        @property
        def regional_cache_version(self):
            return int(joint_ctx.get("regional_cache_version", 0))

        @property
        def regional_profile_evaluations(self):
            return int(regional_profile_evaluations["count"])

        def update_regional_cache_memory(self, evaluated_rows):
            if not bool(joint_ctx.get("regional_cache_enabled", False)):
                return False

            ranked_rows = sorted(
                list(evaluated_rows or []),
                key=lambda row: float(row[1]),
                reverse=True,
            )
            elite_count = regional_memory.elite_count(len(ranked_rows))
            if elite_count <= 0:
                return False

            cache_states = []
            demand_states = []
            version = int(joint_ctx.get("regional_cache_version", 0))
            for solution, _score in ranked_rows[:elite_count]:
                memo_key = (version, regional_solution_key(solution))
                cache_state = regional_cache_state_memo.get(memo_key)
                if cache_state is None:
                    # Defensive fallback for externally supplied/pre-evaluated
                    # wolves.  Normal GWO evaluations always populate the memo.
                    cache_state = evaluate_joint_nest_cache_state(
                        joint_ctx,
                        solution,
                        joint_ctx["ranked_task_ids"],
                        use_caching=scheme.use_caching,
                        v2i_only=scheme.v2i_only,
                        cache_policy="provider_predictive",
                        predictive_lookahead=predictive_lookahead,
                        predictive_weight=predictive_weight,
                    )
                    regional_profile_evaluations["count"] += 1
                cache_states.append(cache_state)
                demand_states.append(
                    build_regional_rsu_service_demand(
                        solution,
                        joint_ctx.get("task_type_ids", {}),
                        regional_provider_rsu_ids,
                        regional_provider_types,
                    )
                )

            changed = regional_memory.update_from_observations(
                cache_states,
                demand_states,
            )
            joint_ctx["regional_rsu_vehicle_cache_prevalence"] = (
                regional_memory.prevalence_profile()
            )
            joint_ctx["regional_rsu_assignment_demand"] = (
                regional_memory.demand_profile()
            )
            joint_ctx["regional_rsu_service_popularity"] = regional_memory.profile()
            joint_ctx["regional_cache_version"] = int(regional_memory.version)
            joint_ctx["regional_cache_rounds"] = int(regional_memory.rounds)
            if changed:
                # Scores and cache states from the previous profile must never
                # leak into the next generation; core.py separately versions
                # the scalar objective memo using the same version counter.
                regional_cache_state_memo.clear()
            return bool(changed)

        def evaluate(self, solution):
            return evaluator(solution)

        def repair_solution(self, solution):
            from algorithm.gwo.memory import repair_solution as gwo_repair

            return gwo_repair(solution, self)

        @property
        def task_order(self):
            return joint_ctx.get("ranked_task_ids", [])

        @property
        def providers(self):
            # Compatibility view for the standalone optimizer. The joint
            # benchmark stores feasibility per task in task_domains.
            return joint_ctx.get("task_domains", {})

        def valid_provider(self, task):
            domains = joint_ctx.get("task_domains", {})
            if isinstance(domains, dict):
                return list(domains.get(int(task), []) or [])
            return []

        def greedy_population(self, count):
            provider_memo = {}
            population = greedy_initial_population(
                joint_ctx,
                scheme=scheme,
                population_size=count,
                rng=random.Random(int(joint_ctx["seed"])),
                search_cache=search_cache,
                evaluation_memo=provider_memo,
                evaluation_counter=initial_evaluation_counter,
            )
            for solution in population:
                provider_map = {
                    int(gene[0]): int(gene[1]) for gene in solution
                }
                signature = tuple(
                    provider_map[int(task_id)] for task_id in ranked_task_ids
                )
                score = provider_memo.get(signature)
                if score is not None:
                    initial_evaluation_memo[
                        tuple((int(gene[0]), int(gene[1])) for gene in solution)
                    ] = float(score)
            return population

    best_solution, _best_score, history = run_gwo_aco(
        ContextAdapter(),
        population_size=(
            int(population_size)
            if population_size is not None
            else int(load_params_obj().S)
        ),
        iterations=max(0, int(tmax) - 1),
        initial_discard_probability=float(load_params_obj().p_discard_init),
        max_function_evaluations=max_function_evaluations,
    )

    best_evaluation = evaluate_joint_nest(
        joint_ctx,
        best_solution,
        joint_ctx["ranked_task_ids"],
        use_caching=scheme.use_caching,
        v2i_only=scheme.v2i_only,
    )

    return best_solution, best_evaluation, history



def run_joint_pso(
    joint_ctx: Dict[str, Any],
    *,
    algorithm: str,
    seed: int,
    tmax: int,
    population_size: int | None = None,
    max_function_evaluations: int | None = None,
):
    """Run discrete PSO using the same joint benchmark evaluator as DCSGA."""
    from algorithm.pso.core import run_pso

    _prepare_joint_context_seed(joint_ctx, seed)
    scheme = get_joint_scheme(algorithm)
    ranked_task_ids, task_rank = _seed_aligned_dcsga_rank_data(joint_ctx)
    joint_ctx["ranked_task_ids"] = list(ranked_task_ids)
    joint_ctx["task_rank"] = dict(task_rank)

    evaluator = lambda solution: evaluate_joint_nest_total(
        joint_ctx,
        solution,
        joint_ctx["ranked_task_ids"],
        use_caching=scheme.use_caching,
        v2i_only=scheme.v2i_only,
    )

    from algorithm.gwo.memory import repair_solution
    import random
    initial_evaluation_counter = {"count": 0}

    class ContextAdapter(dict):
        def evaluate(self, solution):
            return evaluator(solution)
        def valid_provider(self, task):
            return list(joint_ctx.get("task_domains", {}).get(int(task), []) or [])
        @property
        def task_order(self):
            return joint_ctx.get("ranked_task_ids", [])
        def greedy_population(self, count):
            provider_memo = {}
            population = greedy_initial_population(
                joint_ctx,
                scheme=scheme,
                population_size=count,
                rng=random.Random(seed),
                search_cache=_build_search_static_cache(joint_ctx),
                evaluation_memo=provider_memo,
                evaluation_counter=initial_evaluation_counter,
            )
            optimizer_memo = self.setdefault("initial_evaluation_memo", {})
            for solution in population:
                provider_map = {
                    int(gene[0]): int(gene[1])
                    for gene in solution
                }
                provider_signature = tuple(
                    provider_map[int(task_id)]
                    for task_id in ranked_task_ids
                )
                score = provider_memo.get(provider_signature)
                if score is not None:
                    optimizer_memo[
                        tuple((int(gene[0]), int(gene[1])) for gene in solution)
                    ] = float(score)
            return population
        @property
        def initial_function_evaluations(self):
            return int(initial_evaluation_counter["count"])
        def repair_solution(self, solution):
            return repair_solution(solution, self)

    pso_context = ContextAdapter(
        seed=int(seed),
        task_rank=dict(task_rank),
        global_ranks=dict(task_rank),
        task_order=list(ranked_task_ids),
        task_type_ids=dict(joint_ctx.get("task_type_ids", {})),
        initial_evaluation_memo={},
    )
    best_solution, best_score, history = run_pso(
        pso_context,
        population_size=int(population_size) if population_size is not None else int(load_params_obj().S),
        iterations=max(0, int(tmax)-1),
        max_function_evaluations=max_function_evaluations,
    )
    evaluation = evaluate_joint_nest(joint_ctx, best_solution, joint_ctx["ranked_task_ids"], use_caching=scheme.use_caching, v2i_only=scheme.v2i_only)
    return best_solution, evaluation, history


def run_joint_dcsga(
    joint_ctx: Dict[str, Any],
    *,
    algorithm: str,
    seed: int,
    tmax: int,
    population_size: int | None = None,
    max_function_evaluations: int | None = None,
) -> Tuple[List[NestItem], JointEvaluation, List[Dict[str, Any]]]:
    _prepare_joint_context_seed(joint_ctx, seed)
    scheme = get_joint_scheme(algorithm)
    if scheme.use_ranking:
        ranked_task_ids, task_rank = _seed_aligned_dcsga_rank_data(joint_ctx)
        joint_ctx["ranked_task_ids"] = list(ranked_task_ids)
        joint_ctx["task_rank"] = dict(task_rank)
        joint_ctx["dcsga_rank_seed"] = int(seed)
        joint_ctx["dcsga_rank_seed_aligned"] = True
    search_cache = _build_search_static_cache(joint_ctx)
    if scheme.name == "dtosc":
        raise ValueError("DTOSC must be executed with run_joint_dtosc")

    params = load_params_obj()
    S = int(population_size if population_size is not None else params.S)
    if S < 2:
        raise ValueError("population_size must be at least 2")
    if (
        max_function_evaluations is not None
        and int(max_function_evaluations) < S
    ):
        raise ValueError(
            "max_function_evaluations must be at least population_size"
        )
    tmax = max(1, int(tmax))
    rng = random.Random(int(seed))
    levy_lambda = float(params.levy_lambda)
    task_order = task_order_for_scheme(
        joint_ctx,
        scheme,
        search_cache,
    )

    evaluation_memo: Dict[Tuple[int, ...], float] = {}
    evaluation_counter = {"count": 0}
    initial_population = greedy_initial_population(
        joint_ctx,
        scheme=scheme,
        population_size=S,
        rng=rng,
        search_cache=search_cache,
        evaluation_memo=evaluation_memo,
        evaluation_counter=evaluation_counter,
    )
    history: List[Dict[str, Any]] = []

    def evaluate_population(population):
        return _evaluate_population(
            joint_ctx,
            population,
            task_order=task_order,
            scheme=scheme,
            memo=evaluation_memo,
            evaluation_counter=evaluation_counter,
            max_function_evaluations=max_function_evaluations,
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
                function_evaluations=int(evaluation_counter["count"]),
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
        evaluation_budget_exhausted=(
            None
            if max_function_evaluations is None
            else lambda: int(evaluation_counter["count"])
            >= int(max_function_evaluations)
        ),
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

def run_joint_gpc(
    joint_ctx: Dict[str, Any],
    *,
    algorithm: str,
    seed: int,
    tmax: int,
    population_size: int | None = None,
    max_function_evaluations: int | None = None,
):
    """Run discrete GPC using the common joint benchmark evaluator."""
    from algorithm.gpc.core import run_gpc
    import random

    _prepare_joint_context_seed(joint_ctx, seed)
    scheme = get_joint_scheme(algorithm)

    ranked_task_ids, task_rank = _seed_aligned_dcsga_rank_data(joint_ctx)
    joint_ctx["ranked_task_ids"] = list(ranked_task_ids)
    joint_ctx["task_rank"] = dict(task_rank)
    initial_evaluation_counter = {"count": 0}

    class ContextAdapter(dict):
        def evaluate_solution(self, solution):
            return evaluate_joint_nest_total(
                joint_ctx,
                solution,
                joint_ctx["ranked_task_ids"],
                use_caching=scheme.use_caching,
                v2i_only=scheme.v2i_only,
            )

        def valid_provider(self, task):
            return list(joint_ctx.get("task_domains", {}).get(int(task), []) or [])

        @property
        def task_order(self):
            return joint_ctx.get("ranked_task_ids", [])

        def greedy_population(self, count):
            provider_memo = {}
            population = greedy_initial_population(
                joint_ctx,
                scheme=scheme,
                population_size=count,
                rng=random.Random(seed),
                search_cache=_build_search_static_cache(joint_ctx),
                evaluation_memo=provider_memo,
                evaluation_counter=initial_evaluation_counter,
            )
            optimizer_memo = self.setdefault("initial_evaluation_memo", {})
            for solution in population:
                provider_map = {
                    int(gene[0]): int(gene[1])
                    for gene in solution
                }
                provider_signature = tuple(
                    provider_map[int(task_id)]
                    for task_id in ranked_task_ids
                )
                score = provider_memo.get(provider_signature)
                if score is not None:
                    optimizer_memo[
                        tuple((int(gene[0]), int(gene[1])) for gene in solution)
                    ] = float(score)
            return population

        @property
        def initial_function_evaluations(self):
            return int(initial_evaluation_counter["count"])

    ctx = ContextAdapter(joint_ctx)
    ctx["initial_evaluation_memo"] = {}

    best_solution, best_score, history = run_gpc(
        ctx,
        population_size=(
            int(population_size)
            if population_size is not None
            else int(load_params_obj().S)
        ),
        iterations=max(0, int(tmax) - 1),
        seed=seed,
        max_function_evaluations=max_function_evaluations,
    )

    evaluation = evaluate_joint_nest(
        joint_ctx,
        best_solution,
        joint_ctx["ranked_task_ids"],
        use_caching=scheme.use_caching,
        v2i_only=scheme.v2i_only,
    )
    return best_solution, evaluation, history
