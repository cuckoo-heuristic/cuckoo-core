from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Sequence, Tuple

NestItem = Tuple[int, int, int]
Nest = List[NestItem]
Signature = Tuple[int, ...]


@dataclass(frozen=True)
class GACDJayaProblem:
    """Problem adapter consumed by the single canonical GAC-DJaya engine.

    The optimizer owns population construction, genetic assistance, discrete
    Jaya transformations, diagnostics and random-number generation.  Runtime-
    specific and benchmark-specific code provide only the physical problem
    operations through this adapter.
    """

    task_order: Tuple[int, ...]
    task_type_ids: Mapping[int, Any]
    initial_cache: Mapping[int, set[int]]
    domain_for_task: Callable[[int], Sequence[int]]
    rebuild_nest: Callable[[Mapping[int, int]], Nest]
    evaluate_total: Callable[[Sequence[NestItem]], float]
    greedy_population: Callable[[int, random.Random], List[Nest]]
    check_cancelled: Callable[[], None] | None = None

    def domain(self, task_id: int) -> List[int]:
        values = [int(provider_id) for provider_id in self.domain_for_task(int(task_id))]
        if not values:
            raise ValueError(f"Task {task_id} has no feasible providers")
        return list(dict.fromkeys(values))

    def rebuild(self, provider_map: Mapping[int, int]) -> Nest:
        return list(self.rebuild_nest(provider_map))

    def evaluate(self, nest: Sequence[NestItem]) -> float:
        if self.check_cancelled is not None:
            self.check_cancelled()
        return float(self.evaluate_total(nest))

    def check(self) -> None:
        if self.check_cancelled is not None:
            self.check_cancelled()


@dataclass(frozen=True)
class GACDJayaCoreResult:
    best_nest: Nest
    history: List[Dict[str, Any]]
    evaluation_cache: Dict[Signature, float]


def nest_to_map(nest: Sequence[NestItem]) -> Dict[int, int]:
    return {
        int(task_id): int(provider_id)
        for task_id, provider_id, _rank in nest
    }


def nest_signature(nest: Sequence[NestItem], task_order: Sequence[int]) -> Signature:
    provider_map = nest_to_map(nest)
    return tuple(provider_map[int(task_id)] for task_id in task_order)


def hamming_distance(first: Sequence[NestItem], second: Sequence[NestItem]) -> int:
    first_map = nest_to_map(first)
    second_map = nest_to_map(second)
    return sum(
        1
        for task_id, provider_id in first_map.items()
        if second_map.get(task_id) != provider_id
    )


def population_diagnostics(population: Sequence[Nest], task_order: Sequence[int]) -> Dict[str, Any]:
    signatures = [nest_signature(nest, task_order) for nest in population]
    unique_count = len(set(signatures))

    distances: List[int] = []
    for first_index in range(len(population)):
        for second_index in range(first_index + 1, len(population)):
            distances.append(
                hamming_distance(
                    population[first_index],
                    population[second_index],
                )
            )

    mean_hamming = 0.0
    if distances:
        mean_hamming = sum(distances) / len(distances)

    return {
        "population_unique_count": int(unique_count),
        "population_mean_hamming": float(mean_hamming),
    }


def get_nest_quality(
    problem: GACDJayaProblem,
    nest: Sequence[NestItem],
    evaluation_cache: MutableMapping[Signature, float],
) -> float:
    signature = nest_signature(nest, problem.task_order)
    if signature not in evaluation_cache:
        evaluation_cache[signature] = problem.evaluate(nest)
    return float(evaluation_cache[signature])


def selection(population: Sequence[Nest], qualities: Sequence[float], rng: random.Random) -> Nest:
    if not population:
        raise ValueError("Population cannot be empty")
    if len(population) != len(qualities):
        raise ValueError("Population and qualities must have the same size")

    tournament_size = min(3, len(population))
    selected_indices = rng.sample(range(len(population)), tournament_size)
    best_index = max(selected_indices, key=lambda index: qualities[index])
    return list(population[best_index])


def crossover(
    parent1: Sequence[NestItem],
    parent2: Sequence[NestItem],
    problem: GACDJayaProblem,
    rng: random.Random,
) -> Nest:
    parent1_map = nest_to_map(parent1)
    parent2_map = nest_to_map(parent2)

    if set(parent1_map) != set(parent2_map):
        raise ValueError("Both parents must contain the same tasks")
    if len(problem.task_order) < 2:
        return list(parent1)

    child_map: Dict[int, int] = {}
    for task_id in problem.task_order:
        child_map[int(task_id)] = (
            parent1_map[int(task_id)]
            if rng.random() < 0.5
            else parent2_map[int(task_id)]
        )

    return problem.rebuild(child_map)


def mutation(
    nest: Sequence[NestItem],
    problem: GACDJayaProblem,
    rng: random.Random,
) -> Nest:
    if not problem.task_order:
        return list(nest)

    provider_map = nest_to_map(nest)
    movable_tasks: List[int] = []

    for task_id in problem.task_order:
        domain = problem.domain(int(task_id))
        if any(provider_id != provider_map[int(task_id)] for provider_id in domain):
            movable_tasks.append(int(task_id))

    if not movable_tasks:
        return list(nest)

    mutation_limit = max(
        1,
        int(math.ceil(math.log2(len(movable_tasks) + 1) / 2.0)),
    )
    mutation_count = min(
        len(movable_tasks),
        1 + int(rng.random() * mutation_limit),
    )

    for selected_task in rng.sample(movable_tasks, mutation_count):
        current_provider = provider_map[selected_task]
        alternatives = [
            provider_id
            for provider_id in problem.domain(selected_task)
            if provider_id != current_provider
        ]
        provider_map[selected_task] = int(rng.choice(alternatives))

    return problem.rebuild(provider_map)


def create_child(
    population: Sequence[Nest],
    qualities: Sequence[float],
    problem: GACDJayaProblem,
    rng: random.Random,
) -> Nest:
    parent1 = selection(population, qualities, rng)
    parent2 = selection(population, qualities, rng)

    attempts = 0
    while parent1 == parent2 and attempts < 5:
        parent2 = selection(population, qualities, rng)
        attempts += 1

    return mutation(
        crossover(parent1, parent2, problem, rng),
        problem,
        rng,
    )


def _sort_population(
    population: Sequence[Nest],
    qualities: Sequence[float],
    population_size: int,
) -> Tuple[List[Nest], List[float]]:
    rows = list(zip(population, qualities))
    rows.sort(key=lambda row: row[1], reverse=True)
    rows = rows[:population_size]
    return [list(row[0]) for row in rows], [float(row[1]) for row in rows]


def initial_population_counts(population_size: int) -> Dict[str, int]:
    """Allocate target 45% greedy, 45% genetic and 10% exploration."""
    weights = (("greedy", 45), ("genetic", 45), ("random", 10))
    counts = {
        name: (population_size * weight) // 100
        for name, weight in weights
    }
    remaining = population_size - sum(counts.values())
    remainders = sorted(
        (
            ((population_size * weight) % 100, -index, name)
            for index, (name, weight) in enumerate(weights)
        ),
        reverse=True,
    )
    for _remainder, _priority, name in remainders[:remaining]:
        counts[name] += 1
    return counts


def _unique_ranked_rows(
    population: Sequence[Nest],
    qualities: Sequence[float],
    task_order: Sequence[int],
    excluded_signatures: Sequence[Signature] | set[Signature] | None = None,
) -> List[Tuple[Nest, float]]:
    excluded = set(excluded_signatures or ())
    unique_rows: Dict[Signature, Tuple[Nest, float]] = {}
    for nest, quality in zip(population, qualities):
        signature = nest_signature(nest, task_order)
        if signature in excluded:
            continue
        previous = unique_rows.get(signature)
        if previous is None or float(quality) > previous[1]:
            unique_rows[signature] = (list(nest), float(quality))
    return sorted(unique_rows.values(), key=lambda row: row[1], reverse=True)


def select_quality_diverse_population(
    population: Sequence[Nest],
    qualities: Sequence[float],
    population_size: int,
    task_order: Sequence[int],
    *,
    reference_population: Sequence[Nest] = (),
    excluded_signatures: Sequence[Signature] | set[Signature] | None = None,
    shortlist_multiplier: int = 2,
) -> Tuple[List[Nest], List[float]]:
    if population_size <= 0:
        return [], []

    rows = _unique_ranked_rows(
        population,
        qualities,
        task_order,
        excluded_signatures=excluded_signatures,
    )
    if not rows:
        return [], []

    shortlist_size = min(
        len(rows),
        max(population_size, shortlist_multiplier * population_size),
    )
    shortlist = list(rows[:shortlist_size])
    selected: List[Tuple[Nest, float]] = [shortlist.pop(0)]
    reference = [list(nest) for nest in reference_population]

    while shortlist and len(selected) < population_size:
        comparison_nests = reference + [row[0] for row in selected]
        best_index = max(
            range(len(shortlist)),
            key=lambda index: (
                min(
                    hamming_distance(shortlist[index][0], chosen)
                    for chosen in comparison_nests
                ),
                shortlist[index][1],
            ),
        )
        selected.append(shortlist.pop(best_index))

    if len(selected) < population_size:
        selected_signatures = {
            nest_signature(row[0], task_order)
            for row in selected
        }
        for row in rows[shortlist_size:]:
            signature = nest_signature(row[0], task_order)
            if signature in selected_signatures:
                continue
            selected.append(row)
            selected_signatures.add(signature)
            if len(selected) >= population_size:
                break

    selected.sort(key=lambda row: row[1], reverse=True)
    return [row[0] for row in selected], [row[1] for row in selected]


def randomized_exploration_candidate(
    base_population: Sequence[Nest],
    problem: GACDJayaProblem,
    rng: random.Random,
) -> Nest:
    if not base_population:
        raise ValueError("Exploration requires at least one base solution")

    base_nest = list(rng.choice(base_population))
    provider_map = nest_to_map(base_nest)
    movable_tasks: List[int] = []

    for task_id in problem.task_order:
        domain = problem.domain(int(task_id))
        if any(provider_id != provider_map[int(task_id)] for provider_id in domain):
            movable_tasks.append(int(task_id))

    if not movable_tasks:
        return base_nest

    upper = max(1, int(math.ceil(math.log2(len(movable_tasks) + 1))))
    lower = max(1, int(math.ceil(upper / 2.0)))
    mutation_count = min(len(movable_tasks), rng.randint(lower, upper))

    for task_id in rng.sample(movable_tasks, mutation_count):
        current_provider = provider_map[task_id]
        alternatives = [
            provider_id
            for provider_id in problem.domain(task_id)
            if provider_id != current_provider
        ]
        provider_map[task_id] = int(rng.choice(alternatives))

    return problem.rebuild(provider_map)


def _evaluate_candidates(
    candidates: Sequence[Nest],
    problem: GACDJayaProblem,
    evaluation_cache: MutableMapping[Signature, float],
) -> List[float]:
    return [get_nest_quality(problem, nest, evaluation_cache) for nest in candidates]


def create_initial_population(
    problem: GACDJayaProblem,
    population_size: int,
    tmax: int,
    rng: random.Random,
    evaluation_cache: MutableMapping[Signature, float],
) -> Tuple[List[Nest], Dict[str, Any]]:
    """Build the canonical target-45/45/10 initialization.

    This intentionally preserves the proven benchmark behavior.  GA remains
    an initialization assistant and is stopped before the Jaya iterations.
    """
    counts = initial_population_counts(population_size)
    greedy_count = counts["greedy"]
    genetic_count = counts["genetic"]
    random_count = counts["random"]

    full_greedy_population = problem.greedy_population(population_size, rng)
    full_greedy_qualities = _evaluate_candidates(
        full_greedy_population,
        problem,
        evaluation_cache,
    )
    greedy_population, greedy_qualities = select_quality_diverse_population(
        full_greedy_population,
        full_greedy_qualities,
        greedy_count,
        problem.task_order,
        shortlist_multiplier=1,
    )

    selected_population = list(greedy_population)
    selected_qualities = list(greedy_qualities)
    selected_signatures = {
        nest_signature(nest, problem.task_order)
        for nest in selected_population
    }

    ga_generations = (
        max(2, min(5, int(math.ceil(float(tmax) / 4.0))))
        if genetic_count > 0
        else 0
    )
    genetic_candidate_target = 3 * genetic_count
    genetic_candidates: List[Nest] = []
    genetic_candidate_qualities: List[float] = []

    breeding_population = list(greedy_population)
    breeding_qualities = list(greedy_qualities)
    if len(breeding_population) < 2:
        breeding_population = list(problem.greedy_population(max(2, population_size), rng))
        breeding_qualities = _evaluate_candidates(
            breeding_population,
            problem,
            evaluation_cache,
        )

    generated_genetic = 0
    for generation_index in range(ga_generations):
        problem.check()
        remaining_candidates = genetic_candidate_target - generated_genetic
        remaining_generations = ga_generations - generation_index
        batch_count = int(math.ceil(remaining_candidates / remaining_generations))
        batch = [
            create_child(
                breeding_population,
                breeding_qualities,
                problem,
                rng,
            )
            for _ in range(batch_count)
        ]
        batch_qualities = _evaluate_candidates(batch, problem, evaluation_cache)
        genetic_candidates.extend(batch)
        genetic_candidate_qualities.extend(batch_qualities)
        generated_genetic += batch_count

        merged_population = breeding_population + batch
        merged_qualities = breeding_qualities + batch_qualities
        breeding_population, breeding_qualities = select_quality_diverse_population(
            merged_population,
            merged_qualities,
            max(2, min(population_size, len(merged_population))),
            problem.task_order,
            shortlist_multiplier=2,
        )

    selected_genetic, selected_genetic_qualities = select_quality_diverse_population(
        genetic_candidates,
        genetic_candidate_qualities,
        genetic_count,
        problem.task_order,
        reference_population=selected_population,
        excluded_signatures=selected_signatures,
        shortlist_multiplier=2,
    )
    selected_population.extend(selected_genetic)
    selected_qualities.extend(selected_genetic_qualities)
    selected_signatures.update(
        nest_signature(nest, problem.task_order)
        for nest in selected_genetic
    )

    random_candidate_target = 5 * random_count
    random_candidates: List[Nest] = []
    exploration_bases = selected_population or greedy_population
    for _ in range(random_candidate_target):
        random_candidates.append(
            randomized_exploration_candidate(exploration_bases, problem, rng)
        )
    random_candidate_qualities = _evaluate_candidates(
        random_candidates,
        problem,
        evaluation_cache,
    )
    selected_random, selected_random_qualities = select_quality_diverse_population(
        random_candidates,
        random_candidate_qualities,
        random_count,
        problem.task_order,
        reference_population=selected_population,
        excluded_signatures=selected_signatures,
        shortlist_multiplier=2,
    )
    selected_population.extend(selected_random)
    selected_qualities.extend(selected_random_qualities)
    selected_signatures.update(
        nest_signature(nest, problem.task_order)
        for nest in selected_random
    )

    if len(selected_population) < population_size:
        all_candidates = (
            list(full_greedy_population)
            + genetic_candidates
            + random_candidates
        )
        all_qualities = (
            list(full_greedy_qualities)
            + genetic_candidate_qualities
            + random_candidate_qualities
        )
        fill_population, fill_qualities = select_quality_diverse_population(
            all_candidates,
            all_qualities,
            population_size - len(selected_population),
            problem.task_order,
            reference_population=selected_population,
            excluded_signatures=selected_signatures,
            shortlist_multiplier=2,
        )
        selected_population.extend(fill_population)
        selected_qualities.extend(fill_qualities)

    # A population-based optimizer remains well-defined when the feasible
    # space contains fewer unique vectors than S.  Preserve every unique
    # vector first, then fill only the unavoidable remainder with copies of
    # the strongest feasible vectors.  Normal benchmark scenarios never enter
    # this branch, so their population and RNG sequence remain unchanged.
    duplicate_fill_count = 0
    if len(selected_population) < population_size:
        if not selected_population:
            raise RuntimeError("GAC-DJaya could not construct a feasible initial solution")
        sources = list(selected_population)
        source_qualities = list(selected_qualities)
        source_index = 0
        while len(selected_population) < population_size:
            selected_population.append(list(sources[source_index % len(sources)]))
            selected_qualities.append(float(source_qualities[source_index % len(sources)]))
            source_index += 1
            duplicate_fill_count += 1

    selected_population, selected_qualities = _sort_population(
        selected_population,
        selected_qualities,
        population_size,
    )
    diagnostics = {
        "initial_greedy_target": int(greedy_count),
        "initial_genetic_target": int(genetic_count),
        "initial_random_target": int(random_count),
        "initial_greedy_selected": int(len(greedy_population)),
        "initial_genetic_selected": int(len(selected_genetic)),
        "initial_random_selected": int(len(selected_random)),
        "initial_duplicate_fill": int(duplicate_fill_count),
        "ga_generations": int(ga_generations),
        "genetic_candidate_pool_size": int(len(genetic_candidates)),
        "random_candidate_pool_size": int(len(random_candidates)),
    }
    return selected_population, diagnostics


def jaya_move_limit(difference_count: int) -> int:
    if difference_count <= 0:
        return 0
    return max(1, int(math.ceil(math.log2(difference_count + 1))))


def guided_jaya_trial(
    current_nest: Sequence[NestItem],
    best_nest: Sequence[NestItem],
    worst_nest: Sequence[NestItem],
    problem: GACDJayaProblem,
    rng: random.Random,
) -> Nest:
    current_map = nest_to_map(current_nest)
    best_map = nest_to_map(best_nest)
    worst_map = nest_to_map(worst_nest)
    new_map = dict(current_map)

    different_tasks = [
        task_id
        for task_id in problem.task_order
        if current_map[int(task_id)] != best_map[int(task_id)]
    ]
    if not different_tasks:
        return list(current_nest)

    worst_matched = [
        task_id
        for task_id in different_tasks
        if current_map[int(task_id)] == worst_map[int(task_id)]
        and best_map[int(task_id)] != worst_map[int(task_id)]
    ]
    worst_set = set(worst_matched)
    remaining = [task_id for task_id in different_tasks if task_id not in worst_set]
    rng.shuffle(worst_matched)
    rng.shuffle(remaining)

    move_limit = jaya_move_limit(len(different_tasks))
    move_count = 1 + int(rng.random() * move_limit)
    for task_id in (worst_matched + remaining)[:move_count]:
        new_map[int(task_id)] = best_map[int(task_id)]

    return problem.rebuild(new_map)


def _task_type_counts(problem: GACDJayaProblem) -> Counter:
    return Counter(
        problem.task_type_ids.get(int(task_id))
        for task_id in problem.task_order
        if problem.task_type_ids.get(int(task_id)) is not None
    )


def choose_exploration_task(
    base_map: Mapping[int, int],
    best_map: Mapping[int, int],
    worst_map: Mapping[int, int],
    elite_maps: Sequence[Mapping[int, int]],
    problem: GACDJayaProblem,
    rng: random.Random,
    type_counts: Counter,
) -> int | None:
    options: List[int] = []

    for task_id in problem.task_order:
        domain = problem.domain(int(task_id))
        if any(provider_id != base_map[int(task_id)] for provider_id in domain):
            options.append(int(task_id))

    if not options:
        return None

    worst_options = [
        task_id
        for task_id in options
        if base_map[task_id] == worst_map[task_id]
        and best_map[task_id] != worst_map[task_id]
    ]
    if worst_options:
        options = worst_options

    repeated_service_options = [
        task_id
        for task_id in options
        if type_counts.get(problem.task_type_ids.get(task_id), 0) > 1
    ]
    if repeated_service_options:
        options = repeated_service_options

    disagreement = {
        task_id: len({elite_map[task_id] for elite_map in elite_maps})
        for task_id in options
    }
    max_disagreement = max(disagreement.values())
    options = [
        task_id
        for task_id in options
        if disagreement[task_id] == max_disagreement
    ]

    max_domain_size = max(len(problem.domain(task_id)) for task_id in options)
    options = [
        task_id
        for task_id in options
        if len(problem.domain(task_id)) == max_domain_size
    ]

    return int(rng.choice(options))


def cache_aware_trial(
    base_nest: Sequence[NestItem],
    best_nest: Sequence[NestItem],
    worst_nest: Sequence[NestItem],
    elite_population: Sequence[Nest],
    problem: GACDJayaProblem,
    rng: random.Random,
    type_counts: Counter,
) -> Nest:
    base_map = nest_to_map(base_nest)
    best_map = nest_to_map(best_nest)
    worst_map = nest_to_map(worst_nest)
    elite_maps = [nest_to_map(nest) for nest in elite_population]

    selected_task = choose_exploration_task(
        base_map,
        best_map,
        worst_map,
        elite_maps,
        problem,
        rng,
        type_counts,
    )
    if selected_task is None:
        return list(base_nest)

    current_provider = base_map[selected_task]
    alternatives = [
        provider_id
        for provider_id in problem.domain(selected_task)
        if provider_id != current_provider
    ]
    non_worst = [
        provider_id
        for provider_id in alternatives
        if provider_id != worst_map[selected_task]
    ]
    if non_worst:
        alternatives = non_worst

    task_type = problem.task_type_ids.get(selected_task)
    selected_index = problem.task_order.index(selected_task)
    earlier_same_type_providers: set[int] = set()

    if task_type is not None:
        for previous_task in problem.task_order[:selected_index]:
            if problem.task_type_ids.get(previous_task) == task_type:
                earlier_same_type_providers.add(base_map[previous_task])

    elite_provider_count = Counter(
        elite_map[selected_task]
        for elite_map in elite_maps
    )
    provider_load = Counter(base_map.values())

    ranked_alternatives: List[Tuple[Tuple[int, int, int, int], int]] = []
    for provider_id in alternatives:
        has_service_affinity = int(
            provider_id in earlier_same_type_providers
            or task_type in problem.initial_cache.get(provider_id, set())
        )
        score = (
            has_service_affinity,
            elite_provider_count.get(provider_id, 0),
            int(provider_id == best_map[selected_task]),
            -provider_load.get(provider_id, 0),
        )
        ranked_alternatives.append((score, provider_id))

    best_score = max(score for score, _provider_id in ranked_alternatives)
    best_alternatives = [
        provider_id
        for score, provider_id in ranked_alternatives
        if score == best_score
    ]

    target_provider = int(rng.choice(best_alternatives))
    new_map = dict(base_map)

    block_tasks = [selected_task]
    if task_type is not None:
        compatible_same_type = [
            task_id
            for task_id in problem.task_order
            if task_id != selected_task
            and problem.task_type_ids.get(task_id) == task_type
            and base_map[task_id] != target_provider
            and target_provider in problem.domain(task_id)
        ]
        rng.shuffle(compatible_same_type)
        block_limit = jaya_move_limit(len(compatible_same_type) + 1)
        additional_count = min(
            len(compatible_same_type),
            int(rng.random() * block_limit),
        )
        block_tasks.extend(compatible_same_type[:additional_count])

    for task_id in block_tasks:
        new_map[int(task_id)] = target_provider

    return problem.rebuild(new_map)


def ring_neighborhood(ring_order: Sequence[int], position: int) -> List[int]:
    size = len(ring_order)
    if size <= 0:
        return []
    return list(
        {
            int(ring_order[(position - 1) % size]),
            int(ring_order[position]),
            int(ring_order[(position + 1) % size]),
        }
    )


def _history_row(
    iteration: int,
    qualities: Sequence[float],
    function_evaluations: int,
    population: Sequence[Nest],
    problem: GACDJayaProblem,
    diagnostics: Mapping[str, Any],
) -> Dict[str, Any]:
    values = [float(value) for value in qualities]
    row: Dict[str, Any] = {
        "iteration": float(iteration),
        "best_total_efficiency": float(max(values)),
        "population_total_efficiencies": values,
        "function_evaluations": int(function_evaluations),
    }
    row.update(population_diagnostics(population, problem.task_order))
    row.update(dict(diagnostics))
    return row


def run_gac_djaya_core(
    problem: GACDJayaProblem,
    *,
    seed: int,
    tmax: int,
    population_size: int,
) -> GACDJayaCoreResult:
    if population_size < 2:
        raise ValueError("population_size must be at least 2")
    if not problem.task_order:
        raise ValueError("GAC-DJaya requires at least one non-entry task")

    tmax = max(1, int(tmax))
    rng = random.Random(int(seed))
    evaluation_cache: Dict[Signature, float] = {}
    type_counts = _task_type_counts(problem)

    population, initial_population_diagnostics = create_initial_population(
        problem,
        int(population_size),
        tmax,
        rng,
        evaluation_cache,
    )
    qualities = [
        get_nest_quality(problem, nest, evaluation_cache)
        for nest in population
    ]
    population, qualities = _sort_population(
        population,
        qualities,
        int(population_size),
    )

    history = [
        _history_row(
            0,
            qualities,
            len(evaluation_cache),
            population,
            problem,
            {
                "accepted_candidates": 0,
                "accepted_guided_trials": 0,
                "accepted_cache_trials": 0,
                "generated_trials": 0,
                "unique_trial_count": 0,
                "duplicate_trial_count": 0,
                "mean_trial_hamming": 0.0,
                "best_improved": False,
                "stagnation_generations": 0,
                **initial_population_diagnostics,
            },
        )
    ]

    stagnation_generations = 0
    iteration = 1

    while iteration < tmax:
        problem.check()
        generation_start_best = max(qualities)
        ring_order = list(range(population_size))
        rng.shuffle(ring_order)

        elite_count = max(2, math.ceil(population_size / 2))
        elite_population = list(population[:elite_count])
        global_best_index = max(
            range(population_size),
            key=lambda index: qualities[index],
        )

        accepted_candidates = 0
        accepted_guided_trials = 0
        accepted_cache_trials = 0
        generated_trials = 0
        duplicate_trial_count = 0
        trial_signatures: set[Signature] = set()
        trial_distances: List[int] = []

        for position, population_index in enumerate(ring_order):
            problem.check()
            neighbor_indices = ring_neighborhood(ring_order, position)
            local_best_index = max(
                neighbor_indices,
                key=lambda index: qualities[index],
            )
            local_worst_index = min(
                neighbor_indices,
                key=lambda index: qualities[index],
            )

            current_nest = population[population_index]
            current_quality = qualities[population_index]
            local_best = population[local_best_index]
            local_worst = population[local_worst_index]

            guided_trial = guided_jaya_trial(
                current_nest,
                local_best,
                local_worst,
                problem,
                rng,
            )
            trials: List[Tuple[str, Nest]] = [("guided", guided_trial)]

            cache_probe_count = 1
            if population_index == global_best_index:
                cache_probe_count += min(
                    stagnation_generations,
                    max(1, math.ceil(math.log2(population_size))),
                )

            for _ in range(cache_probe_count):
                trials.append(
                    (
                        "cache",
                        cache_aware_trial(
                            guided_trial,
                            local_best,
                            local_worst,
                            elite_population,
                            problem,
                            rng,
                            type_counts,
                        ),
                    )
                )

            best_trial = current_nest
            best_trial_quality = current_quality
            best_trial_type: str | None = None

            for trial_type, trial in trials:
                if trial == current_nest:
                    continue

                generated_trials += 1
                trial_signature = nest_signature(trial, problem.task_order)
                if trial_signature in evaluation_cache:
                    duplicate_trial_count += 1
                trial_signatures.add(trial_signature)
                trial_distances.append(hamming_distance(current_nest, trial))

                trial_quality = get_nest_quality(problem, trial, evaluation_cache)
                if trial_quality > best_trial_quality:
                    best_trial = trial
                    best_trial_quality = trial_quality
                    best_trial_type = trial_type

            if best_trial_quality > current_quality:
                population[population_index] = best_trial
                qualities[population_index] = best_trial_quality
                accepted_candidates += 1
                if best_trial_type == "guided":
                    accepted_guided_trials += 1
                elif best_trial_type == "cache":
                    accepted_cache_trials += 1

        population, qualities = _sort_population(
            population,
            qualities,
            population_size,
        )

        generation_end_best = qualities[0]
        best_improved = generation_end_best > generation_start_best
        if best_improved:
            stagnation_generations = 0
        else:
            stagnation_generations += 1

        mean_trial_hamming = 0.0
        if trial_distances:
            mean_trial_hamming = sum(trial_distances) / len(trial_distances)

        history.append(
            _history_row(
                iteration,
                qualities,
                len(evaluation_cache),
                population,
                problem,
                {
                    "accepted_candidates": int(accepted_candidates),
                    "accepted_guided_trials": int(accepted_guided_trials),
                    "accepted_cache_trials": int(accepted_cache_trials),
                    "generated_trials": int(generated_trials),
                    "unique_trial_count": int(len(trial_signatures)),
                    "duplicate_trial_count": int(duplicate_trial_count),
                    "mean_trial_hamming": float(mean_trial_hamming),
                    "best_improved": bool(best_improved),
                    "stagnation_generations": int(stagnation_generations),
                },
            )
        )
        iteration += 1

    return GACDJayaCoreResult(
        best_nest=list(population[0]),
        history=history,
        evaluation_cache=dict(evaluation_cache),
    )
