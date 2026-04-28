import random
from typing import List, Tuple
from parameter.services import load_params_for_lib, load_params_obj
from greedy_nests import procedure1_greedy_initialization , compute_Q1
from procedure3_generate_new_solution import procedure3_generate_new_solution
from update_service_cache import update_cache
from low_complexity import run as optimize_tx_power
from monarch_pylib.model import task_ranking
from monarch_pylib.model import offloading_efficiency, transmission, communication, scheduling
from system.build_context import MiniSystemContextBuilder
builder = MiniSystemContextBuilder(application_id=1)
ctx = builder.build_context()
params = load_params_obj()
params_lib = load_params_for_lib()

cpu_cycles = ctx["cpu_cycles"]
t_ddl_s = ctx["t_ddl_s"]
z_binary = ctx["z"]["binary"]
z_compact = ctx["z"]["compact"]

def compute_local_ranks(ctx):
    children = ctx["children"]
    cpu_cycles = ctx["cpu_cycles"]
    sizes_bits = ctx["task_type_size_bits"]
    rates = ctx["rates"]
    all_tasks = ctx["tasks"]["all"]

    ranks = {}

    for tid in reversed(all_tasks):
        exec_time = cpu_cycles[tid] / 1e9
        succs = children[tid]

        if not succs:
            ranks[tid] = exec_time
            continue

        comm_times = []
        succ_ranks = []

        for s in succs:
            size = sizes_bits[tid]
            r = rates[tid] if rates[tid] > 0 else 1e-6
            comm_times.append(size / r)
            succ_ranks.append(ranks[s])

        ranks[tid] = task_ranking.heft_task_local_rank(
            task_time_s=exec_time,
            succ_comm_times_s=comm_times,
            succ_ranks_s=succ_ranks,
        )

    return ranks


def compute_global_ranks(ctx, local_ranks):
    max_deadline = ctx["deadline_max_s"]
    app_deadline = ctx["deadline_s"]

    global_ranks = {}

    for tid, r in local_ranks.items():
        global_ranks[tid] = task_ranking.heft_task_global_rank(
            local_rank_s=r,
            max_deadline_s=max_deadline,
            app_deadline_s=app_deadline,
        )

    return global_ranks


def get_task_order(global_ranks):
    return [
        tid for tid, _ in sorted(global_ranks.items(), key=lambda x: x[1], reverse=True)
    ]

def evaluate_solution_quality(ctx, nest):
    # Qs = sum of Q1(sp) for all providers chosen in the nest
    return sum(compute_Q1(sp) for (_, sp, _) in nest)


def dcsga_compute_ranks_and_order(ctx):
    local_ranks = compute_local_ranks(ctx)
    global_ranks = compute_global_ranks(ctx, local_ranks)
    task_order = get_task_order(global_ranks)
    return  task_order


def dcsga_run(ctx):

    params = load_params_obj()
    tmax = int(params.simulate_time)
    S = int(params.S)
    Pa0 = float(params.p_discard_init)
    task_order = dcsga_compute_ranks_and_order(ctx)

    population = procedure1_greedy_initialization(S=S, task_order=task_order, ctx=ctx)
    quality = [evaluate_solution_quality(ctx, nest) for nest in population]

    t = 1
    X_best = population[0]

    while t < tmax:

        new_population = [X_best]

        for s in range(1, S):
            Xs = population[s]
            X_new = procedure3_generate_new_solution(Xs, X_best)
            for (_, sp_id, _) in X_new:
                update_cache(ctx, sp_id, 0, t)
            new_population.append(X_new)

        random_walk = []
        for s in range(S):
            X_rand = procedure3_generate_new_solution(new_population[s], None)
            for (_, sp_id, _) in X_rand:
                update_cache(ctx, sp_id, 0, t)
            random_walk.append(X_rand)

        combined = new_population + random_walk
        combined_q = [evaluate_solution_quality(ctx, nest) for nest in combined]

        zipped = sorted(zip(combined, combined_q), key=lambda x: x[1], reverse=True)
        combined, combined_q = zip(*zipped)
        combined = list(combined)
        combined_q = list(combined_q)

        Pa = 2 * Pa0 / t

        if random.random() <= Pa:
            worst = combined[-1]
            worst_walk = []
            for _ in range(S):
                X_new = procedure3_generate_new_solution(worst, None)
                for (_, sp_id, _) in X_new:
                    update_cache(ctx, sp_id, 0, t)
                worst_walk.append(X_new)

            combined += worst_walk
            combined_q = [evaluate_solution_quality(ctx, nest) for nest in combined]

            zipped = sorted(zip(combined, combined_q), key=lambda x: x[1], reverse=True)
            combined, combined_q = zip(*zipped)
            combined = list(combined)
            combined_q = list(combined_q)

        population = combined[:S]
        quality = combined_q[:S]

        X_best = population[0]
        t += 1


    return population[0], quality[0], ctx["cache"]
