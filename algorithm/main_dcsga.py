import copy
import random
from typing import Dict, List

from parameter.services import load_params_for_lib, load_params_obj
from .greedy_nests import (
    procedure1_greedy_initialization,
    compute_Q1,
    rate,
    _providers,
    _empty_state,
    _reset_assignment,
    _apply_assignment,
    _entry_task_id,
    _apply_entry_task,
    t_comp,
    link_rate,
)
from .procedure3_generate_new_solution import procedure3_generate_new_solution
from .dcsga_core import run_population_search
from . import greedy_nests as greedy_nests_module
from . import low_complexity as low_complexity_module
from . import procedure3_generate_new_solution as procedure3_module
from .update_service_cache import update_cache
from monarch_pylib.model import task_ranking

params = load_params_obj()


def _refresh_algorithm_params():
    """Load one consistent DB parameter snapshot for the whole DCSGA run."""
    current_params = load_params_obj()
    current_params_lib = load_params_for_lib()

    global params
    params = current_params

    greedy_nests_module.params = current_params
    greedy_nests_module.params_lib = current_params_lib

    low_complexity_module.params = current_params
    low_complexity_module.params_lib = current_params_lib

    procedure3_module.params = current_params
    procedure3_module.levy_lambda = float(current_params.levy_lambda)




class AlgorithmCancelled(RuntimeError):
    pass


def _raise_if_cancelled(ctx):
    cancel_event = ctx.get("cancel_event") if isinstance(ctx, dict) else None

    if cancel_event is not None and cancel_event.is_set():
        raise AlgorithmCancelled("Algorithm execution was cancelled")


class _DCSGAContext(dict):
    """Use lightweight copies for per-solution mutable scheduling state."""

    def __deepcopy__(self, memo):
        clone = type(self)(self)
        memo[id(self)] = clone
        clone["cache"] = {int(sp_id): set(items) for sp_id, items in self.get("cache", {}).items()}
        _reset_assignment(clone)
        return clone


def _nest_key(nest):
    return tuple((int(task_id), int(provider_id), int(rank)) for task_id, provider_id, rank in nest)


def compute_local_ranks(ctx):
    children = ctx["children"]
    cpu_cycles = ctx["cpu_cycles"]
    sizes_bits = ctx.get("task_output_size_bits", ctx.get("output_size", {}))
    edge_data_bits = ctx.get("edge_data_bits", {})
    all_tasks = [int(task_id) for task_id in ctx["tasks"]["all"]]
    providers = [int(sp_id) for sp_id in _providers(ctx)]
    ranks = {}

    if not providers:
        raise ValueError("At least one service provider is required")

    average_compute_time = {}
    for task_id in all_tasks:
        samples = [float(t_comp(ctx, sp_id, task_id)) for sp_id in providers]
        average_compute_time[task_id] = sum(samples) / len(samples)

    average_link_rates = []
    for src_sp_id in providers:
        for dst_sp_id in providers:
            if src_sp_id == dst_sp_id:
                average_link_rates.append(None)
                continue

            if ctx.get("sp_types", {}).get(src_sp_id) == "rsu" and ctx.get("sp_types", {}).get(dst_sp_id) == "rsu":
                average_link_rates.append(None)
                continue

            rate_value = float(link_rate(ctx, src_sp_id, dst_sp_id))
            if rate_value > 0.0:
                average_link_rates.append(rate_value)

    for task_id in reversed(all_tasks):
        successors = [int(value) for value in children[task_id]]

        if not successors:
            ranks[task_id] = average_compute_time[task_id]
            continue

        comm_times = []
        successor_ranks = []

        for successor_id in successors:
            data_bits = edge_data_bits.get(task_id, {}).get(successor_id, sizes_bits.get(task_id, 0.0))
            transfer_samples = [
                float(data_bits) / rate_value
                for rate_value in average_link_rates
                if rate_value is not None and rate_value > 0.0
            ]
            average_transfer_time = sum(transfer_samples) / len(transfer_samples) if transfer_samples else 0.0
            comm_times.append(average_transfer_time)
            successor_ranks.append(ranks[successor_id])

        ranks[task_id] = task_ranking.heft_task_local_rank(
            task_time_s=average_compute_time[task_id],
            succ_comm_times_s=comm_times,
            succ_ranks_s=successor_ranks,
        )

    return ranks


def compute_global_ranks(ctx, local_ranks):
    return {
        task_id: task_ranking.heft_task_global_rank(
            local_rank_s=float(local_rank),
            max_deadline_s=float(ctx["deadline_max_s"]),
            app_deadline_s=float(ctx["deadline_s"]),
        )
        for task_id, local_rank in local_ranks.items()
    }


def get_task_order(global_ranks):
    return [task_id for task_id, _ in sorted(global_ranks.items(), key=lambda item: item[1], reverse=True)]


def _natural_topological_order(ctx) -> List[int]:
    task_ids = [int(task_id) for task_id in ctx.get("task_ids", ctx.get("tasks", {}).get("all", []))]
    dependencies = {
        int(task_id): [int(predecessor) for predecessor in ctx.get("dependencies", {}).get(task_id, [])]
        for task_id in task_ids
    }
    indegree = {task_id: 0 for task_id in task_ids}
    children: Dict[int, List[int]] = {task_id: [] for task_id in task_ids}

    for task_id, predecessors in dependencies.items():
        for predecessor in predecessors:
            if predecessor in indegree:
                indegree[task_id] += 1
                children.setdefault(predecessor, []).append(task_id)

    ready = sorted(task_id for task_id in task_ids if indegree.get(task_id, 0) == 0)
    order = []

    while ready:
        task_id = ready.pop(0)
        order.append(task_id)

        for child_id in sorted(children.get(task_id, [])):
            indegree[child_id] -= 1

            if indegree[child_id] == 0:
                ready.append(child_id)
                ready.sort()

    if len(order) != len(task_ids):
        raise ValueError("Task graph is not a DAG")

    return order


def dcsga_compute_ranks_and_order(ctx):
    entry_task_id = _entry_task_id(ctx)

    if ctx.get("use_ranking", True) is False:
        order = _natural_topological_order(ctx)
    else:
        local_ranks = compute_local_ranks(ctx)
        global_ranks = compute_global_ranks(ctx, local_ranks)
        order = get_task_order(global_ranks)

    return [int(task_id) for task_id in order if int(task_id) != entry_task_id]


def evaluate_solution_quality(base_ctx, nest, task_order):
    _raise_if_cancelled(base_ctx)
    work_ctx = copy.deepcopy(base_ctx)
    _reset_assignment(work_ctx)
    work_ctx["_schedule_state"] = _empty_state(work_ctx)

    entry_task_id = _entry_task_id(work_ctx)
    local_sp_id = work_ctx.get("local_sp_id")

    if local_sp_id is None:
        raise ValueError("Local service provider is required for the entry task")

    local_sp_id = int(local_sp_id)
    normalized_order = [int(task_id) for task_id in task_order if int(task_id) != entry_task_id]
    task_provider = {int(task_id): int(sp_id) for task_id, sp_id, _ in nest}

    if entry_task_id in task_provider and task_provider[entry_task_id] != local_sp_id:
        raise ValueError("Entry task must be assigned to the local service provider")

    expected_tasks = set(normalized_order)
    provided_tasks = set(task_provider) - {entry_task_id}
    missing_tasks = sorted(expected_tasks - provided_tasks)
    unexpected_tasks = sorted(provided_tasks - expected_tasks)

    if missing_tasks:
        raise ValueError(f"Nest is missing tasks: {missing_tasks}")

    if unexpected_tasks:
        raise ValueError(f"Nest contains unexpected tasks: {unexpected_tasks}")

    rank_counter = {sp_id: 0 for sp_id in _providers(work_ctx)}
    local_sp_id = work_ctx.get("local_sp_id")

    if local_sp_id is not None:
        rank_counter.setdefault(int(local_sp_id), 0)

    _apply_entry_task(work_ctx, work_ctx["_schedule_state"], rank_counter)

    for index, task_id in enumerate(normalized_order):
        _raise_if_cancelled(work_ctx)
        sp_id = task_provider[task_id]
        rank_counter[sp_id] += 1
        _apply_assignment(work_ctx, work_ctx["_schedule_state"], task_id, sp_id, rank_counter[sp_id])

        if work_ctx.get("use_caching", True):
            update_cache(work_ctx, sp_id, task_id, remaining_task_ids=normalized_order[index + 1:])

    return compute_Q1(work_ctx), work_ctx["cache"], work_ctx


def sort_population(ctx, population, task_order, evaluation_cache=None):
    if evaluation_cache is None:
        evaluation_cache = {}

    evaluated = []
    for nest in population:
        _raise_if_cancelled(ctx)
        key = _nest_key(nest)
        cached = evaluation_cache.get(key)

        if cached is None:
            quality, cache_state, _ = evaluate_solution_quality(ctx, nest, task_order)
            cached = (quality, cache_state)
            evaluation_cache[key] = cached

        evaluated.append((nest, cached[0], cached[1]))

    evaluated.sort(key=lambda item: item[1], reverse=True)
    population = [item[0] for item in evaluated]
    qualities = [item[1] for item in evaluated]
    caches = [item[2] for item in evaluated]

    return population, qualities, caches


def _materialize_solution(ctx, nest, task_order):
    quality, cache_state, scheduled_ctx = evaluate_solution_quality(ctx, nest, task_order)
    entry_task_id = _entry_task_id(scheduled_ctx)
    ordered_task_ids = [entry_task_id] + [int(task_id) for task_id in task_order if int(task_id) != entry_task_id]
    compact = scheduled_ctx.get("z", {}).get("compact", {})
    solution = []

    for task_id in ordered_task_ids:
        assignment = compact.get(task_id, {})
        provider_id = assignment.get("provider")
        rank = assignment.get("rank")

        if provider_id is None or rank is None:
            raise ValueError(f"Task {task_id} has no finalized assignment")

        solution.append((int(task_id), int(provider_id), int(rank)))

    return solution, quality, cache_state


def dcsga_run(ctx):
    _refresh_algorithm_params()
    ctx = _DCSGAContext(ctx)
    _raise_if_cancelled(ctx)

    seed = ctx.get("seed")
    if seed is not None:
        random.seed(seed)

    tmax = int(ctx.get("tmax", 10))
    S = int(params.S)
    ctx["rates"] = {sp_id: rate(ctx, sp_id) for sp_id in _providers(ctx)}
    task_order = dcsga_compute_ranks_and_order(ctx)
    initial_population = procedure1_greedy_initialization(
        S=S,
        task_order=task_order,
        ctx=ctx,
    )
    _raise_if_cancelled(ctx)
    evaluation_cache = {}

    def evaluate_population(population):
        ranked, qualities, _caches = sort_population(
            ctx,
            list(population),
            task_order,
            evaluation_cache,
        )
        return list(zip(ranked, qualities))

    def generate(source_nest, best_nest):
        return procedure3_generate_new_solution(
            source_nest,
            best_nest,
            copy.deepcopy(ctx),
        )

    _population, best_nest, _evaluated = run_population_search(
        initial_population,
        population_size=S,
        tmax=tmax,
        initial_discard_probability=float(params.p_discard_init),
        rng=random,
        generate_new_solution=generate,
        evaluate_population=evaluate_population,
        cancel_check=lambda: _raise_if_cancelled(ctx),
    )
    return _materialize_solution(ctx, best_nest, task_order)
