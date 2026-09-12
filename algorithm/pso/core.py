from __future__ import annotations

import copy
import math
import random
from typing import Dict, Iterable, List, Sequence, Tuple

from .initial_population import create_initial_population
from .memory import repair_solution


# Classical PSO defaults (kept explicit so later variants/innovations can be
# added without changing the base implementation).
DEFAULT_INERTIA_WEIGHT = 0.7298
DEFAULT_COGNITIVE_COEFFICIENT = 1.49618
DEFAULT_SOCIAL_COEFFICIENT = 1.49618
DEFAULT_VELOCITY_LIMIT = 4.0
DEFAULT_INERTIA_MAX = 0.90
DEFAULT_INERTIA_MIN = 0.40
DEFAULT_COGNITIVE_START = 2.50
DEFAULT_COGNITIVE_END = 0.50
DEFAULT_SOCIAL_START = 0.50
DEFAULT_SOCIAL_END = 2.50
DEFAULT_TEMPERATURE_START = 1.20
DEFAULT_TEMPERATURE_END = 0.25
STAGNATION_RESTART_AFTER = 5
RESTART_FRACTION = 0.15
LOCAL_REFINEMENT_FRACTION = 0.15


class _EvaluationBudgetReached(RuntimeError):
    """Internal control-flow signal used for an exact NFE stopping budget."""

Gene = Tuple[int, int, int]
Velocity = Dict[int, Dict[int, float]]


def _context_value(context, key, default=None):
    if isinstance(context, dict) and key in context:
        return context.get(key, default)
    return getattr(context, key, default)


def _solution_key(solution: Sequence) -> tuple[tuple[int, int], ...]:
    return tuple(
        (int(gene[0]), int(gene[1]))
        for gene in solution
        if isinstance(gene, (tuple, list)) and len(gene) >= 2
    )


def _provider_map(solution: Sequence) -> dict[int, int]:
    return {
        int(gene[0]): int(gene[1])
        for gene in solution
        if isinstance(gene, (tuple, list)) and len(gene) >= 2
    }


def _task_order(context, solution=None) -> list[int]:
    order = _context_value(context, "task_order", None)
    if order:
        return [int(x) for x in order]
    return [
        int(gene[0])
        for gene in (solution or [])
        if isinstance(gene, (tuple, list)) and len(gene) >= 2
    ]


def _task_priority_weights(context, tasks: Sequence[int]) -> dict[int, float]:
    """Rank/DAG guided importance weights for discrete PSO task updates.

    Higher priority tasks receive larger update probability. The method is
    intentionally guidance-only: fitness/evaluation remains unchanged.
    """
    tasks = [int(t) for t in tasks]
    if not tasks:
        return {}

    rank_data = _context_value(context, "task_rank", None)
    if not rank_data:
        rank_data = _context_value(context, "global_ranks", {})

    raw = {}
    for task in tasks:
        value = 0.0
        if isinstance(rank_data, dict):
            value = float(rank_data.get(task, rank_data.get(str(task), 0.0)) or 0.0)
        elif isinstance(rank_data, (list, tuple)) and task < len(rank_data):
            value = float(rank_data[task])
        raw[task] = value

    maximum = max(raw.values()) if raw else 0.0
    minimum = min(raw.values()) if raw else 0.0
    span = max(1e-12, maximum - minimum)

    # Normalize so the lowest rank still has a non-zero chance.
    return {task: 0.5 + 0.5 * ((value - minimum) / span)
            for task, value in raw.items()}


def _valid_providers(context, task: int) -> list[int]:
    validator = getattr(context, "valid_provider", None)
    if callable(validator):
        return list(dict.fromkeys(int(p) for p in (validator(int(task)) or [])))

    if isinstance(context, dict):
        domains = context.get("task_domains", context.get("providers", {}))
        if isinstance(domains, dict):
            values = domains.get(int(task), [])
            if isinstance(values, dict):
                values = values.keys()
            return list(dict.fromkeys(int(p) for p in (values or [])))
    return []


def _repair(context, solution):
    repair = getattr(context, "repair_solution", None)
    if callable(repair):
        return repair(solution)
    return repair_solution(solution, context)


def _evaluate(context, solution) -> float:
    """Use the project's authoritative evaluator; PSO never defines a new Q."""
    evaluator = getattr(context, "evaluate", None)
    if callable(evaluator):
        return float(evaluator(solution))

    if isinstance(context, dict):
        from algorithm.main_dcsga import evaluate_solution_quality

        result = evaluate_solution_quality(
            context,
            solution,
            _task_order(context, solution),
        )
        return float(result[0] if isinstance(result, tuple) else result)

    raise TypeError("PSO context must expose evaluate(solution)")


def _sort_unique(rows):
    result = []
    seen = set()
    for solution, score in sorted(rows, key=lambda row: float(row[1]), reverse=True):
        key = _solution_key(solution)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append((solution, float(score)))
    return result


def _mean_pairwise_hamming(rows) -> float:
    if len(rows) < 2:
        return 0.0

    dimension = max(1, len(rows[0][0]))
    total = 0.0
    pairs = 0
    for i in range(len(rows)):
        left = _provider_map(rows[i][0])
        for j in range(i + 1, len(rows)):
            right = _provider_map(rows[j][0])
            tasks = set(left) | set(right)
            distance = sum(left.get(task) != right.get(task) for task in tasks)
            total += float(distance) / float(dimension)
            pairs += 1
    return total / float(max(1, pairs))


def _initial_velocity(context, solution: Sequence, rng: random.Random) -> Velocity:
    """Create a small categorical velocity for every feasible task-provider bit.

    A particle position is represented by one provider per task.  Internally the
    base PSO uses a one-hot categorical view: every feasible (task, provider)
    pair owns one scalar velocity.  This preserves the standard cognitive/social
    PSO update while keeping the published task-provider encoding unchanged.
    """
    velocity: Velocity = {}
    for task in _task_order(context, solution):
        providers = _valid_providers(context, int(task))
        if not providers:
            continue
        velocity[int(task)] = {
            int(provider): rng.uniform(-0.10, 0.10)
            for provider in providers
        }
    return velocity


def _project_provider(
    current_provider: int,
    provider_velocities: Dict[int, float],
    rng: random.Random,
    *,
    temperature: float = 1.0,
    exploration_probability: float = 0.0,
    candidate_providers: Sequence[int] | None = None,
    change_probability: float = 1.0,
) -> int:
    """Project one-hot PSO velocity back to one categorical provider.

    A temperature-controlled softmax is used instead of a hard argmax.  Hard
    projection made all particles copy the same provider as soon as a leader
    coordinate became positive, which caused premature categorical collapse.
    """
    if not provider_velocities:
        return int(current_provider)

    if rng.random() > max(0.0, min(1.0, float(change_probability))):
        return int(current_provider)

    all_providers = list(provider_velocities)
    if rng.random() < max(0.0, min(1.0, float(exploration_probability))):
        return int(rng.choice(all_providers))

    allowed = {
        int(provider)
        for provider in (candidate_providers or all_providers)
        if int(provider) in provider_velocities
    }
    allowed.add(int(current_provider))
    providers = [provider for provider in all_providers if provider in allowed]

    temperature = max(1e-6, float(temperature))
    maximum = max(float(provider_velocities[provider]) for provider in providers)
    weights = {
        int(provider): math.exp(
            max(
                -60.0,
                min(
                    60.0,
                    (float(provider_velocities[provider]) - maximum) / temperature,
                ),
            )
        )
        for provider in providers
    }
    # A small categorical inertia term avoids gratuitous provider churn while
    # preserving a non-zero probability for every feasible assignment.
    if int(current_provider) in weights:
        weights[int(current_provider)] *= 1.10
    threshold = rng.random() * sum(weights.values())
    cumulative = 0.0
    for provider, weight in weights.items():
        cumulative += float(weight)
        if threshold <= cumulative:
            return int(provider)
    return int(providers[-1])


def _update_particle(
    particle: Sequence,
    velocity: Velocity,
    personal_best: Sequence,
    global_best: Sequence,
    context,
    *,
    inertia_weight: float,
    cognitive_coefficient: float,
    social_coefficient: float,
    velocity_limit: float,
    rng: random.Random,
    task_priority_weights: dict[int, float] | None = None,
    temperature: float = 1.0,
    exploration_probability: float = 0.0,
) -> tuple[list[Gene], Velocity]:
    """One discrete categorical PSO position/velocity update.

    For each task we use the standard PSO equation on its one-hot feasible
    provider coordinates:

        v = w*v + c1*r1*(pbest - x) + c2*r2*(gbest - x)

    The resulting categorical velocity is then projected to exactly one valid
    provider for that task.  The external schedule representation remains
    ``(task_id, provider_id, rank)``.
    """
    current_map = _provider_map(particle)
    pbest_map = _provider_map(personal_best)
    gbest_map = _provider_map(global_best)

    new_velocity: Velocity = {}
    updated: list[Gene] = []
    task_order = _task_order(context, particle)

    vmax = max(1e-12, float(velocity_limit))
    w = float(inertia_weight)
    c1 = float(cognitive_coefficient)
    c2 = float(social_coefficient)

    # Updating every coordinate of a long categorical schedule in one PSO
    # step destroys useful building blocks.  Keep the classical velocity
    # update on every coordinate, but project only a dimension-normalised
    # trust region back into the discrete position.
    evidence = []
    for task in task_order:
        task = int(task)
        current_provider = int(current_map.get(task, 0))
        pbest_provider = int(pbest_map.get(task, current_provider))
        gbest_provider = int(gbest_map.get(task, current_provider))
        priority = float((task_priority_weights or {}).get(task, 1.0))
        disagreement = (
            int(pbest_provider != current_provider)
            + 2 * int(gbest_provider != current_provider)
        )
        evidence.append((task, max(1e-9, priority * (1.0 + disagreement))))

    projection_limit = min(
        len(evidence),
        max(
            1,
            int(
                math.ceil(
                    math.sqrt(max(1, len(evidence)))
                    * (0.25 + 2.0 * float(exploration_probability))
                )
            ),
        ),
    )
    movable_tasks: set[int] = set()
    remaining = list(evidence)
    for _ in range(projection_limit):
        if not remaining:
            break
        total = sum(weight for _task, weight in remaining)
        threshold = rng.random() * total
        cumulative = 0.0
        selected_index = len(remaining) - 1
        for item_index, (_task, weight) in enumerate(remaining):
            cumulative += weight
            if threshold <= cumulative:
                selected_index = item_index
                break
        selected_task, _weight = remaining.pop(selected_index)
        movable_tasks.add(int(selected_task))

    for position, task in enumerate(task_order):
        task = int(task)
        providers = _valid_providers(context, task)
        if not providers:
            continue

        current_provider = int(current_map.get(task, providers[0]))
        pbest_provider = int(pbest_map.get(task, current_provider))
        gbest_provider = int(gbest_map.get(task, current_provider))
        previous = velocity.get(task, {})
        task_velocity: Dict[int, float] = {}

        # r1/r2 are sampled once per task, matching the vector interpretation
        # of the classical PSO equation.
        priority = float((task_priority_weights or {}).get(task, 1.0))
        r1 = rng.random() * priority
        r2 = rng.random() * priority

        for provider in providers:
            provider = int(provider)
            x = 1.0 if provider == current_provider else 0.0
            p = 1.0 if provider == pbest_provider else 0.0
            g = 1.0 if provider == gbest_provider else 0.0

            value = (
                w * float(previous.get(provider, 0.0))
                + c1 * r1 * (p - x)
                + c2 * r2 * (g - x)
            )
            task_velocity[provider] = max(-vmax, min(vmax, float(value)))

        selected_provider = _project_provider(
            current_provider,
            task_velocity,
            rng,
            temperature=float(temperature),
            exploration_probability=float(exploration_probability),
            candidate_providers=(
                int(current_provider),
                int(pbest_provider),
                int(gbest_provider),
            ),
            change_probability=(0.85 if task in movable_tasks else 0.0),
        )
        new_velocity[task] = task_velocity
        updated.append((task, int(selected_provider), int(position)))

    return _repair(context, updated), new_velocity


def adaptive_inertia_weight(
    iteration: int,
    iterations: int,
    w_max: float = DEFAULT_INERTIA_MAX,
    w_min: float = DEFAULT_INERTIA_MIN,
) -> float:
    """Linearly decrease inertia to balance exploration and exploitation.

    Early iterations keep larger momentum for exploration; later iterations
    reduce momentum so particles converge toward personal/global experience.
    """
    if int(iterations) <= 0:
        return float(w_min)
    progress = max(0.0, min(1.0, float(iteration) / float(iterations)))
    return float(w_max - (w_max - w_min) * progress)


def time_varying_acceleration(iteration: int, iterations: int) -> tuple[float, float]:
    """Decrease self-attraction and increase social attraction over time."""
    progress = max(
        0.0,
        min(1.0, float(iteration) / float(max(1, int(iterations)))),
    )
    cognitive = DEFAULT_COGNITIVE_START + (
        DEFAULT_COGNITIVE_END - DEFAULT_COGNITIVE_START
    ) * progress
    social = DEFAULT_SOCIAL_START + (
        DEFAULT_SOCIAL_END - DEFAULT_SOCIAL_START
    ) * progress
    return float(cognitive), float(social)


def _ring_best(personal_best, personal_best_scores, index: int, radius: int = 1):
    size = len(personal_best)
    neighbors = [
        (index + offset) % size
        for offset in range(-max(1, int(radius)), max(1, int(radius)) + 1)
    ]
    best_index = max(neighbors, key=lambda item: float(personal_best_scores[item]))
    return personal_best[best_index]


def _mutate_particle(solution, context, rng, probability, priority_weights):
    result = [tuple(int(value) for value in gene[:3]) for gene in solution]
    if not result or rng.random() >= max(0.0, min(1.0, float(probability))):
        return result

    choices = []
    for index, (task, provider, _position) in enumerate(result):
        alternatives = [
            int(value)
            for value in _valid_providers(context, int(task))
            if int(value) != int(provider)
        ]
        if alternatives:
            importance = float((priority_weights or {}).get(int(task), 0.5))
            choices.append((index, alternatives, 1.25 - 0.75 * importance))
    if not choices:
        return result

    threshold = rng.random() * sum(item[2] for item in choices)
    cumulative = 0.0
    selected = choices[-1]
    for item in choices:
        cumulative += item[2]
        if threshold <= cumulative:
            selected = item
            break
    index, alternatives, _weight = selected
    task, _provider, position = result[index]
    result[index] = (int(task), int(rng.choice(alternatives)), int(position))
    return _repair(context, result)


def _restart_particle(best, context, rng, strength=0.20):
    result = [tuple(int(value) for value in gene[:3]) for gene in best]
    mutable = []
    for index, (task, provider, _position) in enumerate(result):
        alternatives = [
            int(value)
            for value in _valid_providers(context, int(task))
            if int(value) != int(provider)
        ]
        if alternatives:
            mutable.append((index, alternatives))
    if not mutable:
        return result
    count = max(
        1,
        min(
            len(mutable),
            int(
                math.ceil(
                    math.sqrt(max(1, len(result)))
                    * (0.50 + 2.0 * float(strength))
                )
            ),
        ),
    )
    for index, alternatives in rng.sample(mutable, min(count, len(mutable))):
        task, _provider, position = result[index]
        result[index] = (int(task), int(rng.choice(alternatives)), int(position))
    return _repair(context, result)


def _swarm_guided_best_neighbor(best, personal_best, context, rng, priority_weights):
    """One-coordinate best neighbor learned from PSO personal bests."""
    result = [tuple(int(value) for value in gene[:3]) for gene in best]
    best_map = _provider_map(best)
    pbest_maps = [_provider_map(solution) for solution in personal_best]
    task_types = _context_value(context, "task_type_ids", {}) or {}
    service_frequency = {}
    for solution in personal_best:
        for task, provider, *_ in solution:
            task_type = task_types.get(int(task), task_types.get(str(int(task))))
            if task_type is not None:
                key = (int(task_type), int(provider))
                service_frequency[key] = service_frequency.get(key, 0) + 1
    choices = []
    for index, (task, provider, _position) in enumerate(result):
        alternatives = [int(p) for p in _valid_providers(context, task) if int(p) != provider]
        if not alternatives:
            continue
        task_type = task_types.get(int(task), task_types.get(str(int(task))))
        provider_scores = {}
        for candidate in alternatives:
            direct = sum(int(m.get(task) == candidate) for m in pbest_maps)
            shared = service_frequency.get((int(task_type), candidate), 0) if task_type is not None else 0
            provider_scores[candidate] = 0.20 + float(direct) + 0.35 * float(shared)
        disagreement = sum(int(m.get(task) != best_map.get(task)) for m in pbest_maps) / float(max(1, len(pbest_maps)))
        importance = float((priority_weights or {}).get(task, 0.5))
        choices.append((index, provider_scores, 0.25 + disagreement + 0.35 * (1.0 - importance)))
    if not choices:
        return result
    threshold, cumulative = rng.random() * sum(x[2] for x in choices), 0.0
    index, provider_scores, _ = choices[-1]
    for item in choices:
        cumulative += item[2]
        if threshold <= cumulative:
            index, provider_scores, _ = item
            break
    providers = list(provider_scores)
    if rng.random() < 0.20:
        selected_provider = rng.choice(providers)
    else:
        threshold, cumulative, selected_provider = rng.random() * sum(provider_scores.values()), 0.0, providers[-1]
        for provider, weight in provider_scores.items():
            cumulative += weight
            if threshold <= cumulative:
                selected_provider = provider
                break
    task, _provider, position = result[index]
    result[index] = (int(task), int(selected_provider), int(position))
    return _repair(context, result)


def run_pso(
    context,
    population_size: int = 20,
    iterations: int = 50,
    initial_population=None,
    initial_discard_probability: float = 0.0,
    *,
    inertia_weight: float = DEFAULT_INERTIA_WEIGHT,
    cognitive_coefficient: float = DEFAULT_COGNITIVE_COEFFICIENT,
    social_coefficient: float = DEFAULT_SOCIAL_COEFFICIENT,
    velocity_limit: float = DEFAULT_VELOCITY_LIMIT,
    stagnation_restart_after: int = STAGNATION_RESTART_AFTER,
    restart_fraction: float = RESTART_FRACTION,
    local_refinement_fraction: float = LOCAL_REFINEMENT_FRACTION,
    max_function_evaluations: int | None = None,
):
    """Run the base discrete PSO on the project's task-provider search space.

    This first implementation intentionally contains only the PSO essentials:
      * the same feasible initial-population mechanism as the current GWO;
      * particle positions using the existing task-provider schedule encoding;
      * one categorical velocity vector per task;
      * personal-best and global-best memory;
      * the unchanged project evaluator as the sole fitness source.

    The first adaptive extension is enabled through a linearly decreasing
    inertia controller. Other PSO enhancements remain intentionally disabled.
    """
    del initial_discard_probability  # retained only for future adapter parity

    context = copy.deepcopy(context)
    seed = _context_value(context, "seed", None)
    rng = random.Random(seed)

    size = max(3, int(population_size))
    iterations = max(0, int(iterations))
    evaluation_budget = (
        None
        if max_function_evaluations is None
        else max(1, int(max_function_evaluations))
    )
    if evaluation_budget is not None and evaluation_budget < size:
        raise ValueError(
            "max_function_evaluations must be at least population_size so the "
            "initial population can be evaluated"
        )

    population = initial_population or create_initial_population(
        context,
        size,
        rng=rng,
    )
    population = [_repair(context, solution) for solution in population]
    population = [solution for solution in population if solution][:size]
    if len(population) < size:
        raise RuntimeError(
            f"Initial population is {len(population)}, expected {size}"
        )

    initial_memo = _context_value(context, "initial_evaluation_memo", {}) or {}
    evaluation_cache = {
        key: float(score)
        for key, score in initial_memo.items()
    }
    function_evaluations_total = max(
        len(evaluation_cache),
        int(_context_value(context, "initial_function_evaluations", 0) or 0),
    )

    def evaluate_one(raw):
        nonlocal function_evaluations_total
        solution = _repair(context, raw)
        if not solution:
            raise ValueError("Cannot evaluate an empty PSO particle")
        key = _solution_key(solution)
        if key not in evaluation_cache:
            if (
                evaluation_budget is not None
                and function_evaluations_total >= evaluation_budget
            ):
                raise _EvaluationBudgetReached
            evaluation_cache[key] = float(_evaluate(context, solution))
            function_evaluations_total += 1
        return solution, float(evaluation_cache[key])

    evaluated = _sort_unique([evaluate_one(solution) for solution in population])
    if len(evaluated) < size:
        raise RuntimeError(
            f"Initial population has only {len(evaluated)} unique evaluated particles; expected {size}"
        )
    evaluated = evaluated[:size]

    # Keep particle identity stable across iterations.  Unlike GWO survivor
    # selection, PSO updates each particle's own pbest history.
    particles = [copy.deepcopy(solution) for solution, _ in evaluated]
    scores = [float(score) for _, score in evaluated]
    velocities = [_initial_velocity(context, particle, rng) for particle in particles]

    personal_best = [copy.deepcopy(particle) for particle in particles]
    personal_best_scores = list(scores)

    best_index = max(range(size), key=lambda idx: personal_best_scores[idx])
    global_best = copy.deepcopy(personal_best[best_index])
    global_best_score = float(personal_best_scores[best_index])

    history = []
    stagnation_count = 0
    total_accepted_moves = 0
    total_local_refinement_trials = 0
    total_local_refinement_accepts = 0
    last_parameters = {
        "inertia_weight": float(DEFAULT_INERTIA_MAX),
        "cognitive_coefficient": float(DEFAULT_COGNITIVE_START),
        "social_coefficient": float(DEFAULT_SOCIAL_START),
        "temperature": float(DEFAULT_TEMPERATURE_START),
        "mutation_probability": 0.08,
    }

    def record(iteration: int):
        rows = list(zip(particles, scores))
        history.append(
            {
                "iteration": int(iteration),
                "best_total_efficiency": float(global_best_score),
                "population_total_efficiencies": [float(score) for score in scores],
                "population_mean_efficiency": float(
                    sum(float(score) for score in scores) / float(max(1, len(scores)))
                ),
                "population_diversity_mean": float(_mean_pairwise_hamming(rows)),
                "function_evaluations": int(function_evaluations_total),
                "stagnation_count": int(stagnation_count),
                "accepted_moves": int(total_accepted_moves),
                "local_refinement_trials": int(total_local_refinement_trials),
                "local_refinement_accepts": int(total_local_refinement_accepts),
                **last_parameters,
            }
        )

    record(0)

    task_priority_weights = _task_priority_weights(
        context,
        _task_order(context, particles[0] if particles else None),
    )

    for iteration in range(1, iterations + 1):
        accepted_this_iteration = 0
        adaptive_w = adaptive_inertia_weight(iteration, iterations)
        adaptive_c1, adaptive_c2 = time_varying_acceleration(iteration, iterations)
        progress = float(iteration) / float(max(1, iterations))
        temperature = DEFAULT_TEMPERATURE_START + (
            DEFAULT_TEMPERATURE_END - DEFAULT_TEMPERATURE_START
        ) * progress
        exploration_probability = 0.10 * (1.0 - progress) + 0.01
        mutation_probability = min(
            0.25,
            0.06 * (1.0 - progress) + 0.015 + 0.02 * stagnation_count,
        )
        last_parameters = {
            "inertia_weight": float(
                adaptive_w if inertia_weight == DEFAULT_INERTIA_WEIGHT else inertia_weight
            ),
            "cognitive_coefficient": float(
                adaptive_c1
                if cognitive_coefficient == DEFAULT_COGNITIVE_COEFFICIENT
                else cognitive_coefficient
            ),
            "social_coefficient": float(
                adaptive_c2
                if social_coefficient == DEFAULT_SOCIAL_COEFFICIENT
                else social_coefficient
            ),
            "temperature": float(temperature),
            "mutation_probability": float(mutation_probability),
        }
        next_particles = []
        next_scores = []
        next_velocities = []
        budget_exhausted = False

        for index in range(size):
            if budget_exhausted:
                next_particles.append(copy.deepcopy(particles[index]))
                next_scores.append(float(scores[index]))
                next_velocities.append(copy.deepcopy(velocities[index]))
                continue
            neighborhood_best = _ring_best(
                personal_best,
                personal_best_scores,
                index,
            )
            social_best = (
                global_best
                if rng.random() < 0.20 + 0.80 * progress
                else neighborhood_best
            )
            candidate, candidate_velocity = _update_particle(
                particles[index],
                velocities[index],
                personal_best[index],
                social_best,
                context,
                inertia_weight=float(adaptive_w if inertia_weight == DEFAULT_INERTIA_WEIGHT else inertia_weight),
                cognitive_coefficient=last_parameters["cognitive_coefficient"],
                social_coefficient=last_parameters["social_coefficient"],
                velocity_limit=float(velocity_limit),
                rng=rng,
                task_priority_weights=task_priority_weights,
                temperature=float(temperature),
                exploration_probability=float(exploration_probability),
            )
            candidate = _mutate_particle(
                candidate,
                context,
                rng,
                mutation_probability,
                task_priority_weights,
            )
            try:
                candidate, candidate_score = evaluate_one(candidate)
            except _EvaluationBudgetReached:
                budget_exhausted = True
                next_particles.append(copy.deepcopy(particles[index]))
                next_scores.append(float(scores[index]))
                next_velocities.append(copy.deepcopy(velocities[index]))
                continue

            if float(candidate_score) >= float(scores[index]):
                selected_particle = candidate
                selected_score = float(candidate_score)
                selected_velocity = candidate_velocity
                accepted_this_iteration += 1
            else:
                # Elitist particle survival prevents a costly categorical move
                # from erasing a useful building block. Exploration is retained
                # by DLHS, softmax projection, mutation and bounded restarts.
                selected_particle = copy.deepcopy(particles[index])
                selected_score = float(scores[index])
                selected_velocity = copy.deepcopy(velocities[index])

            next_particles.append(selected_particle)
            next_scores.append(selected_score)
            next_velocities.append(selected_velocity)

            if float(selected_score) > float(personal_best_scores[index]):
                personal_best[index] = copy.deepcopy(selected_particle)
                personal_best_scores[index] = float(selected_score)

        particles = next_particles
        scores = next_scores
        velocities = next_velocities
        total_accepted_moves += int(accepted_this_iteration)

        previous_global_score = float(global_best_score)
        best_index = max(range(size), key=lambda idx: personal_best_scores[idx])
        if float(personal_best_scores[best_index]) > float(global_best_score):
            global_best = copy.deepcopy(personal_best[best_index])
            global_best_score = float(personal_best_scores[best_index])

        if float(global_best_score) > previous_global_score + 1e-12:
            stagnation_count = 0
        else:
            stagnation_count += 1

        local_trials = max(1, int(round(
            size * max(0.0, min(0.35, float(local_refinement_fraction)))
            * (1.0 + min(1.0, stagnation_count / 5.0))
        )))
        for _ in range(local_trials):
            if budget_exhausted:
                break
            neighbor = _swarm_guided_best_neighbor(global_best, personal_best, context, rng, task_priority_weights)
            try:
                neighbor, neighbor_score = evaluate_one(neighbor)
            except _EvaluationBudgetReached:
                budget_exhausted = True
                break
            total_local_refinement_trials += 1
            if neighbor_score <= global_best_score:
                continue
            total_local_refinement_accepts += 1
            global_best, global_best_score, stagnation_count = copy.deepcopy(neighbor), float(neighbor_score), 0
            worst_index = min(range(size), key=lambda idx: float(scores[idx]))
            particles[worst_index], scores[worst_index] = copy.deepcopy(neighbor), float(neighbor_score)
            velocities[worst_index] = _initial_velocity(context, neighbor, rng)
            personal_best[worst_index], personal_best_scores[worst_index] = copy.deepcopy(neighbor), float(neighbor_score)

        if (
            not budget_exhausted
            and stagnation_count >= max(1, int(stagnation_restart_after))
        ):
            restart_count = max(
                1,
                int(round(size * max(0.0, min(0.50, float(restart_fraction))))),
            )
            worst = sorted(range(size), key=lambda idx: float(scores[idx]))[:restart_count]
            for index in worst:
                restarted = _restart_particle(
                    global_best,
                    context,
                    rng,
                    strength=min(0.50, 0.20 + 0.03 * stagnation_count),
                )
                try:
                    restarted, restarted_score = evaluate_one(restarted)
                except _EvaluationBudgetReached:
                    budget_exhausted = True
                    break
                if float(restarted_score) < float(scores[index]):
                    continue
                particles[index] = restarted
                scores[index] = float(restarted_score)
                velocities[index] = _initial_velocity(context, restarted, rng)
                if float(restarted_score) > float(personal_best_scores[index]):
                    personal_best[index] = copy.deepcopy(restarted)
                    personal_best_scores[index] = float(restarted_score)
                if float(restarted_score) > float(global_best_score):
                    global_best = copy.deepcopy(restarted)
                    global_best_score = float(restarted_score)
                    stagnation_count = 0

        record(iteration)
        if budget_exhausted:
            break

    return _repair(context, global_best), float(global_best_score), history
