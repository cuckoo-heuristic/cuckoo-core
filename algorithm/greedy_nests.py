from __future__ import annotations
import random
from typing import List
from parameter.services import load_params_for_lib, load_params_obj
from monarch_pylib.model import offloading_efficiency, transmission, communication, scheduling

params = load_params_obj()
params_lib = load_params_for_lib()


def _safe_float(x, default=0.0):
    try:
        return float(x)
    except:
        return float(default)


def _cpu_cycles_list(ctx):
    return list(ctx["cpu_cycles"].values())


def _providers(ctx):
    return list(ctx["sp_cpu_freq"].keys())


def _tasks(ctx):
    return list(ctx["cpu_cycles"].keys())


def _z_task_provider(ctx):
    providers = _providers(ctx)
    tasks = _tasks(ctx)
    z_binary = ctx["z"]["binary"]

    mat = [[0.0 for _ in providers] for _ in tasks]

    for p_i, p in enumerate(providers):
        for ranks in z_binary.get(p, {}).values():
            for t_i, t in enumerate(tasks):
                if ranks.get(t, 0) == 1:
                    mat[t_i][p_i] = 1.0

    return mat


def _z_rank_for_provider(ctx, sp_id):
    tasks = _tasks(ctx)
    z_binary = ctx["z"]["binary"]

    row = [0.0 for _ in tasks]

    for ranks in z_binary.get(sp_id, {}).values():
        for i, t in enumerate(tasks):
            if ranks.get(t, 0) == 1:
                row[i] = 1.0

    return row


def t_loc_s(ctx):
    fmax = _safe_float(params_lib.fmax_vehicle_hz)

    return offloading_efficiency.all_local_execution_time(
        cpu_cycles_list=_cpu_cycles_list(ctx),
        f_max_local_hz=fmax
    )


def t_ref_s(ctx):
    return offloading_efficiency.reference_time(
        t_loc_s=t_loc_s(ctx),
        t_ddl_s=float(ctx["t_ddl_s"])
    )


def t_comp(ctx, sp_id: int, task_id: int):
    C = float(ctx["cpu_cycles"][task_id])
    k_type = ctx["task_type_ids"][task_id]
    f_sp = float(ctx["sp_cpu_freq"][sp_id])

    task_types_sorted = sorted(ctx["compile_workloads"].keys())

    v_k = [1.0 if k_type == t else 0.0 for t in task_types_sorted]
    w_k = [float(ctx["compile_workloads"][t]) for t in task_types_sorted]

    cached = ctx["cache"].get(sp_id, set())
    u_k = [1.0 if t in cached else 0.0 for t in task_types_sorted]

    sp_type = ctx["sp_types"][sp_id]

    local_vehicle_ids = [sid for sid, t in ctx["sp_types"].items() if t == "vehicle"]
    local_vehicle_id = min(local_vehicle_ids) if local_vehicle_ids else None

    if sp_id == local_vehicle_id:
        return communication.local_task_compute_time(
            cpu_cycles=C,
            local_cpu_freq_hz=f_sp
        )

    if sp_type == "rsu":
        return communication.mec_task_compute_time(
            v_k=v_k,
            u_k_mec=u_k,
            w_k_cycles=w_k,
            mec_cpu_freq_hz=f_sp,
            cpu_cycles=C
        )

    compile_time = communication.v2v_service_compile_time(
        v_k=v_k,
        u_k_peer=u_k,
        w_k_cycles=w_k,
        peer_cpu_freq_hz=f_sp
    )

    process_time = communication.v2v_task_processing_time(
        cpu_cycles=C,
        peer_cpu_freq_hz=f_sp
    )

    return communication.v2v_task_total_compute_time(
        compile_time_s=compile_time,
        processing_time_s=process_time
    )


def t_finish(ctx, sp_id: int, task_id: int):
    return float(t_start(ctx, sp_id, task_id)) + float(t_comp(ctx, sp_id, task_id))


def t_off(ctx):
    providers = _providers(ctx)
    tasks = _tasks(ctx)

    finish_matrix = [[t_finish(ctx, sp, t) for sp in providers] for t in tasks]

    return offloading_efficiency.offloaded_completion_time(
        task_finish_times_by_provider_s=finish_matrix,
        z_task_provider=_z_task_provider(ctx)
    )


def e_loc_j(ctx):
    kappa = _safe_float(params.k)
    fmax = _safe_float(params_lib.fmax_vehicle_hz)

    return offloading_efficiency.all_local_execution_energy(
        kappa=kappa,
        cpu_cycles_list=_cpu_cycles_list(ctx),
        f_max_local_hz=fmax
    )


def e_com(ctx, sp_id: int, task_id: int):
    cyc = float(ctx["cpu_cycles"][task_id])
    ttype = ctx["task_type_ids"][task_id]

    k = _safe_float(params.k)
    f = float(ctx["sp_cpu_freq"].get(sp_id))

    local_vehicle_ids = [sid for sid, t in ctx["sp_types"].items() if t == "vehicle"]
    local_vehicle_id = min(local_vehicle_ids) if local_vehicle_ids else None

    if sp_id == local_vehicle_id:
        return k * (f ** 2) * cyc

    wk = float(ctx["compile_workloads"].get(ttype, 0.0))
    cached = 1 if ttype in ctx["cache"].get(sp_id, set()) else 0

    e_compile = (1 - cached) * k * (f ** 2) * wk
    e_process = k * (f ** 2) * cyc

    return e_compile + e_process


def e_off(ctx):
    providers = _providers(ctx)
    tasks = _tasks(ctx)

    energy_matrix = [[e_com(ctx, sp, t) for sp in providers] for t in tasks]

    return offloading_efficiency.offloaded_total_energy(
        compute_energy_by_provider_j=energy_matrix,
        z_task_provider=_z_task_provider(ctx)
    )


def t_rec_i_prim(ctx, src_sp: int, dst_sp: int, src_task: int, dst_task: int):
    ft_src = t_finish(ctx, src_sp, src_task)
    ft_dst = t_finish(ctx, dst_sp, dst_task)

    same = src_sp == dst_sp
    idle = float(ctx["idle_time"])

    if same:
        tr = 0.0
    else:
        tr = transmission.task_output_transmission_time(
            data_size_bits=float(ctx["output_size"][src_task]),
            src_sp_id=src_sp,
            dst_sp_id=dst_sp
        )

    return scheduling.dependency_output_receive_time(
        finish_time_src_s=ft_src,
        finish_time_same_provider_s=ft_dst,
        idle_time_s=idle,
        transfer_time_s=tr,
        same_provider=same
    )


def t_rec(ctx, sp_id: int, task_id: int):
    preds = ctx["dependencies"].get(task_id, [])

    if not preds:
        return 0.0

    dep_times = [t_rec_i_prim(ctx, sp_id, sp_id, p, task_id) for p in preds]

    return scheduling.all_dependencies_receive_time(
        dep_receive_times_s=dep_times
    )


def t_finish_rank(ctx, sp_id: int):
    tasks = _tasks(ctx)

    finish_list = [t_finish(ctx, sp_id, t) for t in tasks]

    return scheduling.provider_rank_finish_time(
        task_finish_times_s=finish_list,
        z_task_to_rank=_z_rank_for_provider(ctx, sp_id)
    )


def t_start(ctx, sp_id: int, task_id: int):
    return scheduling.task_start_timestamp(
        deps_ready_time_s=t_rec(ctx, sp_id, task_id),
        prev_rank_finish_time_s=t_finish_rank(ctx, sp_id)
    )


def compute_Q(ctx, sp_id: int, i: int):
    a = _safe_float(params.alpha_n)
    b = _safe_float(params.beta_n)

    return offloading_efficiency.application_offloading_efficiency(
        alpha_n=a,
        beta_n=b,
        t_ref_s=t_ref_s(ctx),
        t_off_s=t_finish(ctx, sp_id, i),
        e_loc_j=e_com(ctx, sp_id, i),
        e_task_off_j=e_com(ctx, sp_id, i)
    )


def compute_Q1(ctx, sp_id: int):
    a = _safe_float(params.alpha_n)
    b = _safe_float(params.beta_n)

    return offloading_efficiency.application_offloading_efficiency(
        alpha_n=a,
        beta_n=b,
        t_ref_s=t_ref_s(ctx),
        t_off_s=t_off(ctx),
        e_loc_j=e_loc_j(ctx),
        e_task_off_j=e_off(ctx)
    )


def _update_z(ctx, task_id, provider_id, rank):
    z_binary = ctx["z"]["binary"]
    z_compact = ctx["z"]["compact"]

    z_compact[task_id]["provider"] = provider_id
    z_compact[task_id]["rank"] = rank

    if provider_id not in z_binary:
        z_binary[provider_id] = {}

    if rank not in z_binary[provider_id]:
        z_binary[provider_id][rank] = {}

    z_binary[provider_id][rank][task_id] = 1


def procedure1_greedy_initialization(S: int, task_order: List[int], ctx):
    from algorithm.update_service_cache import update_cache

    sp_list = list(ctx["providers"].keys())
    I = len(task_order)

    solutions = []

    for s in range(1, S + 1):
        mutaInd = random.randint(0, I - 1)

        nest = []
        r = {sp: 0 for sp in sp_list}

        for idx, task_id in enumerate(task_order):

            qm = {sp: compute_Q(ctx, sp, task_id) for sp in sp_list}

            if s == 1:
                x_star = max(qm, key=qm.get)

            elif idx == mutaInd:
                xb = max(qm, key=qm.get)
                xw = min(qm, key=qm.get)
                qm[xb] = qm[xw]
                x_star = max(qm, key=qm.get)

            else:
                x_star = max(qm, key=qm.get)

            r[x_star] += 1

            _update_z(ctx, task_id, x_star, r[x_star])
            update_cache(ctx, x_star, task_id)

            nest.append((task_id, x_star, r[x_star]))

        solutions.append(nest)

    return sorted(
        solutions,
        key=lambda s: sum(compute_Q1(ctx, sp) for (_, sp, _) in s),
        reverse=True
    )
