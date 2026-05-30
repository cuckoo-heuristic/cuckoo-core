import random
from typing import List, Tuple
from parameter.services import load_params_for_lib, load_params_obj
from .greedy_nests import procedure1_greedy_initialization, compute_Q1
from .procedure3_generate_new_solution import procedure3_generate_new_solution
from .update_service_cache import update_cache
from .low_complexity import run as optimize_tx_power
from monarch_pylib.model import task_ranking
from monarch_pylib.model import offloading_efficiency, transmission, communication, scheduling
from monarch_pylib.model.transmission import channel_gain_v2i, v2i_uplink_rate

params = load_params_obj()
params_lib = load_params_for_lib()

# ////////
def ch_gain(ctx, sp_id: int) -> float:
    distance = float(ctx["distance"][sp_id])
    tau_nm = float(getattr(params, "sigma_v2i", 8.0))
    g_rsu_db = float(getattr(params, "G_rsu", 8.0))
    g_vehicle_db = float(getattr(params, "G_vehicle", 3.0))
    g_rsu = 10 ** (g_rsu_db / 10.0)
    g_vehicle = 10 ** (g_vehicle_db / 10.0)

    rho = g_rsu * g_vehicle
    varpi_nm = float(getattr(params, "h_rsu", 5.0)) * float(getattr(params, "h_vehicle", 1.5))
    gamma = float(getattr(params, "Y_v2i", 3.76))

    return float(
        channel_gain_v2i(
            tau_nm=tau_nm,
            rho=rho,
            varpi_nm=varpi_nm,
            distance_nm=distance,
            pathloss_exponent_gamma=gamma
        )
    )

# //////////
def rate(ctx, sp_id: int) -> float:
    vn_m = float(ctx["connected_vehicles_count"].get(sp_id, 1.0)) if "connected_vehicles_count" in ctx else 1.0
    b_hz = float(getattr(params_lib, "B_hz", 20.0 * 1e6))
    delta2_w = float(getattr(params_lib, "delta2_w", 1e-13))
    h = ch_gain(ctx, sp_id)

    sp_type = ctx.get("sp_types", {}).get(sp_id, None)
    if sp_type == "rsu":
        pmax = float(getattr(params_lib, "pmax_rsu_w", 0.0))
    else:
        pmax = float(getattr(params_lib, "pmax_vehicle_w", 0.0))

    p_opt = optimize_tx_power(ctx, pmax=pmax)
    return float(
        v2i_uplink_rate(
            B_hz=b_hz,
            V_m=vn_m,
            tx_power_pn=p_opt,
            channel_gain_gnm=h,
            noise_power_delta2=delta2_w
        )
    )

def compute_local_ranks(ctx):
    children = ctx["children"]
    cpu_cycles = ctx["cpu_cycles"]
    sizes_bits = ctx["task_type_size_bits"]
    rates = ctx["rates"]
    all_tasks = ctx["tasks"]["all"]
    ranks = {}
    r = max(rates.values()) if rates else 1e-6

    for tid in reversed(all_tasks):
        exec_time = communication.local_task_compute_time(
            cpu_cycles=cpu_cycles[tid],
            local_cpu_freq_hz=ctx["local_cpu_freq_hz"]
        )

        succs = children[tid]

        if not succs:
            ranks[tid] = exec_time
            continue

        comm_times = []
        succ_ranks = []

        for s in succs:
            size = sizes_bits[tid]

            comm_times.append(
                transmission.intermediate_data_tx_time(
                    data_bits=size,
                    link_rate_bps=r
                )
            )

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


def evaluate_solution_quality(ctx, nest, task_order):
    ctx["cache"] = {}
    total_q = 0
    task_map = {task: sp for (task, sp, _) in nest}

    for task_id in task_order:
        sp_id = task_map[task_id]
        update_cache(ctx, sp_id, task_id)
        total_q += compute_Q1(ctx, sp_id)

    return total_q


def dcsga_compute_ranks_and_order(ctx):
    local_ranks = compute_local_ranks(ctx)
    global_ranks = compute_global_ranks(ctx, local_ranks)
    task_order = get_task_order(global_ranks)
    return task_order


def dcsga_run(ctx):
    params = load_params_obj()
    tmax = int(params.simulate_time)
    S = int(params.S)
    Pa0 = float(params.p_discard_init)

    ctx["rates"] = {}
    for sp_id in ctx["distance"]:
        ctx["rates"][sp_id] = rate(ctx, sp_id)

    task_order = dcsga_compute_ranks_and_order(ctx)

    population = procedure1_greedy_initialization(S=S, task_order=task_order, ctx=ctx)
    quality = [evaluate_solution_quality(ctx, nest, task_order) for nest in population]

    t = 1
    X_best = population[0]

    while t < tmax:
        new_population = [X_best]

        for s in range(1, S):
            Xs = population[s]
            X_new = procedure3_generate_new_solution(Xs, X_best, ctx)
            new_population.append(X_new)

        random_walk = []
        for s in range(S):
            X_rand = procedure3_generate_new_solution(new_population[s], None, ctx)
            random_walk.append(X_rand)

        combined = new_population + random_walk
        combined_q = [evaluate_solution_quality(ctx, nest, task_order) for nest in combined]

        zipped = sorted(zip(combined, combined_q), key=lambda x: x[1], reverse=True)
        combined, combined_q = zip(*zipped)
        combined = list(combined)
        combined_q = list(combined_q)

        Pa = 2 * Pa0 / t

        if random.random() <= Pa:
            worst = combined[-1]
            worst_walk = []

            for _ in range(S):
                X_new = procedure3_generate_new_solution(worst, None, ctx)
                worst_walk.append(X_new)

            combined += worst_walk
            combined_q = [evaluate_solution_quality(ctx, nest, task_order) for nest in combined]

            zipped = sorted(zip(combined, combined_q), key=lambda x: x[1], reverse=True)
            combined, combined_q = zip(*zipped)
            combined = list(combined)
            combined_q = list(combined_q)

        population = combined[:S]
        quality = combined_q[:S]

        X_best = population[0]
        t += 1

    return population[0], quality[0], ctx["cache"]
