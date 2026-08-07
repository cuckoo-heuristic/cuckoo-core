from __future__ import annotations

import copy
import random
from typing import Any, List, Tuple

from parameter.services import load_params_for_lib, load_params_obj
from monarch_pylib.model import communication, offloading_efficiency, policy, scheduling, transmission
from monarch_pylib.model.transmission import v2i_uplink_rate

from .low_complexity import run as optimize_tx_power, channel_gain

params = load_params_obj()
params_lib = load_params_for_lib()


def _weights(ctx):
    alpha_n = float(ctx.get("alpha_n", params.alpha_n))
    beta_n = float(ctx.get("beta_n", 1.0 - alpha_n))
    return alpha_n, beta_n


def _all_providers(ctx) -> List[int]:
    if isinstance(ctx.get("providers"), dict):
        providers = list(ctx["providers"].keys())
    else:
        providers = list(ctx.get("sp_cpu_freq", {}).keys())

    return [int(sp) for sp in providers]


def _providers(ctx) -> List[int]:
    providers = _all_providers(ctx)

    if ctx.get("v2i_only", False):
        return [int(sp) for sp in providers if ctx.get("sp_types", {}).get(sp) == "rsu"]

    return providers


def _tasks(ctx) -> List[int]:
    return list(ctx["cpu_cycles"].keys())


def _local_sp_id(ctx):
    return ctx.get("local_sp_id")


def _mode(ctx, sp_id: int) -> str:
    return ctx.get("sp_modes", {}).get(sp_id, "v2i" if ctx["sp_types"].get(sp_id) == "rsu" else "v2v")


def _task_types(ctx) -> List[int]:
    return sorted(set(ctx["task_type_ids"].values()) - {None})


def _vectors(ctx, sp_id: int, task_id: int):
    k_type = ctx["task_type_ids"].get(task_id)
    types = _task_types(ctx)

    if ctx.get("use_caching", True):
        cached = ctx.get("cache", {}).get(sp_id, set())
    else:
        cached = set()

    v_k = [1.0 if t == k_type else 0.0 for t in types]
    u_k = [1.0 if t in cached else 0.0 for t in types]
    w_k = [float(ctx.get("compile_workloads", {}).get(t, 0.0)) for t in types]

    return v_k, u_k, w_k


def _cpu_frequency(ctx, sp_id: int) -> float:
    sp_id = int(sp_id)
    allocated = ctx.get("sp_cpu_allocated_hz", {})
    if sp_id in allocated:
        value = float(allocated[sp_id])
    else:
        value = float(ctx.get("sp_cpu_freq", {}).get(sp_id, 0.0))
    if value <= 0.0:
        raise ValueError(f"Provider {sp_id} has no positive CPU frequency")
    return value


def t_loc_s(ctx) -> float:
    cached = ctx.get("_t_loc_s_cache")
    if cached is not None:
        return float(cached)
    value = offloading_efficiency.all_local_execution_time(
        cpu_cycles_list=list(ctx["cpu_cycles"].values()),
        f_max_local_hz=float(ctx.get("local_cpu_freq_hz", params_lib.fmax_vehicle_hz)),
    )
    ctx["_t_loc_s_cache"] = float(value)
    return float(value)


def e_loc_j(ctx) -> float:
    cached = ctx.get("_e_loc_j_cache")
    if cached is not None:
        return float(cached)
    value = offloading_efficiency.all_local_execution_energy(
        kappa=float(params.k),
        cpu_cycles_list=list(ctx["cpu_cycles"].values()),
        f_max_local_hz=float(ctx.get("local_cpu_freq_hz", params_lib.fmax_vehicle_hz)),
    )
    ctx["_e_loc_j_cache"] = float(value)
    return float(value)


def t_ref_s(ctx) -> float:
    cached = ctx.get("_t_ref_s_cache")
    if cached is not None:
        return float(cached)
    value = offloading_efficiency.reference_time(t_loc_s=t_loc_s(ctx), t_ddl_s=float(ctx["t_ddl_s"]))
    ctx["_t_ref_s_cache"] = float(value)
    return float(value)


def t_comp(ctx, sp_id: int, task_id: int) -> float:
    c = float(ctx["cpu_cycles"][task_id])
    f = _cpu_frequency(ctx, sp_id)
    mode = _mode(ctx, sp_id)

    if mode == "local":
        return communication.local_task_compute_time(cpu_cycles=c, local_cpu_freq_hz=f)

    v_k, u_k, w_k = _vectors(ctx, sp_id, task_id)

    if mode == "v2i":
        return communication.mec_task_compute_time(v_k=v_k, u_k_mec=u_k, w_k_cycles=w_k, mec_cpu_freq_hz=f, cpu_cycles=c)

    compile_time = communication.v2v_service_compile_time(v_k=v_k, u_k_peer=u_k, w_k_cycles=w_k, peer_cpu_freq_hz=f)
    process_time = communication.v2v_task_processing_time(cpu_cycles=c, peer_cpu_freq_hz=f)

    return communication.v2v_task_total_compute_time(compile_time_s=compile_time, processing_time_s=process_time)


def e_comp(ctx, sp_id: int, task_id: int) -> float:
    c = float(ctx["cpu_cycles"][task_id])
    f = _cpu_frequency(ctx, sp_id)
    mode = _mode(ctx, sp_id)

    if mode == "local":
        return communication.local_task_compute_energy(kappa=float(params.k), local_cpu_freq_hz=f, cpu_cycles=c)

    if mode == "v2i":
        return 0.0

    v_k, u_k, w_k = _vectors(ctx, sp_id, task_id)

    return communication.v2v_task_compute_energy(
        kappa=float(params.k),
        v_k=v_k,
        u_k_peer=u_k,
        w_k_cycles=w_k,
        peer_cpu_freq_hz=f,
        cpu_cycles=c,
    )


def _link_bandwidth_divisor(ctx, src_sp_id: int, dst_sp_id: int) -> float:
    src_type = ctx.get("sp_types", {}).get(src_sp_id)
    dst_type = ctx.get("sp_types", {}).get(dst_sp_id)

    if dst_type == "rsu":
        return float(max(float(ctx.get("connected_vehicles_count", {}).get(dst_sp_id, 1.0)), 1.0))

    if src_type == "rsu":
        return float(max(float(ctx.get("connected_vehicles_count", {}).get(src_sp_id, 1.0)), 1.0))

    if src_type == "vehicle" and dst_type == "vehicle":
        return float(max(float(ctx.get("connected_vehicles_count", {}).get(src_sp_id, 1.0)), 1.0))

    return 1.0


def link_rate(ctx, src_sp_id: int, dst_sp_id: int) -> float:
    src_sp_id = int(src_sp_id)
    dst_sp_id = int(dst_sp_id)

    if src_sp_id == dst_sp_id:
        return 0.0

    src_type = ctx.get("sp_types", {}).get(src_sp_id)
    dst_type = ctx.get("sp_types", {}).get(dst_sp_id)

    if src_type == "rsu" and dst_type == "rsu":
        return 0.0

    rate_cache = ctx.setdefault("_link_rate_cache", {})
    cache_key = (src_sp_id, dst_sp_id)
    if cache_key in rate_cache:
        return float(rate_cache[cache_key])

    p_opt = optimize_tx_power(ctx, sp_id=src_sp_id, dst_sp_id=dst_sp_id)
    gain = channel_gain(ctx, src_sp_id, dst_sp_id)

    value = float(
        v2i_uplink_rate(
            B_hz=float(params_lib.B_hz),
            V_m=_link_bandwidth_divisor(
                ctx,
                src_sp_id,
                dst_sp_id,
            ),
            tx_power_pn=p_opt,
            channel_gain_gnm=gain,
            noise_power_delta2=float(params_lib.delta2_w),
        )
    )
    rate_cache[cache_key] = value
    return value


def rate(ctx, sp_id: int) -> float:
    local_sp_id = _local_sp_id(ctx)

    if local_sp_id is None:
        raise ValueError("Local service provider is not available")

    return link_rate(ctx, int(local_sp_id), int(sp_id))


def _tx_time_energy(ctx, src_sp_id: int, dst_sp_id: int, data_bits: float) -> Tuple[float, float]:
    src_sp_id = int(src_sp_id)
    dst_sp_id = int(dst_sp_id)
    data_bits = float(data_bits)

    if src_sp_id == dst_sp_id or data_bits <= 0.0:
        return 0.0, 0.0

    if ctx.get("sp_types", {}).get(src_sp_id) == "rsu" and ctx.get("sp_types", {}).get(dst_sp_id) == "rsu":
        return 0.0, 0.0

    tx_cache = ctx.setdefault("_tx_time_energy_cache", {})
    cache_key = (src_sp_id, dst_sp_id, data_bits)
    if cache_key in tx_cache:
        item = tx_cache[cache_key]
        return float(item[0]), float(item[1])

    r = link_rate(ctx, src_sp_id, dst_sp_id)

    if r <= 0.0:
        raise ValueError(f"Link {src_sp_id}->{dst_sp_id} has no positive transmission rate")

    tx_time = transmission.intermediate_data_tx_time(data_bits=data_bits, link_rate_bps=r)
    p_opt = optimize_tx_power(ctx, sp_id=src_sp_id, dst_sp_id=dst_sp_id)
    if ctx.get("sp_types", {}).get(src_sp_id) == "vehicle":
        tx_energy = transmission.intermediate_data_tx_energy(tx_power_w=p_opt, tx_time_s=tx_time)
    else:
        tx_energy = 0.0

    value = (float(tx_time), float(tx_energy))
    tx_cache[cache_key] = value
    return value


def _service_program_energy(ctx, sp_id: int, task_id: int) -> float:
    mode = _mode(ctx, sp_id)

    if mode == "local":
        return 0.0

    task_type = ctx["task_type_ids"].get(task_id)

    if task_type is None:
        return 0.0

    if ctx.get("use_caching", True) and task_type in ctx.get("cache", {}).get(sp_id, set()):
        return 0.0

    # Source-program size is derived once by the context builder and shared by
    # runtime and benchmark.  Do not fall back to L_k here: doing so would make
    # cache-miss transfer energy depend on which execution path built the ctx.
    source_program_sizes = ctx.get("source_program_size_bits")
    if source_program_sizes is None:
        raise ValueError(
            "Context is missing source_program_size_bits; rebuild it with "
            "MiniSystemContextBuilder"
        )

    if task_type not in source_program_sizes:
        raise ValueError(
            f"No source-program size is defined for task type {task_type}"
        )

    size_bits = float(source_program_sizes[task_type])
    if size_bits <= 0.0:
        raise ValueError(
            f"Source-program size must be positive for task type {task_type}"
        )

    service_energy_cache = ctx.setdefault("_service_program_energy_cache", {})
    cache_key = (int(sp_id), int(task_type), size_bits)
    if cache_key in service_energy_cache:
        return float(service_energy_cache[cache_key])

    vehicle_sources = [
        int(source_id)
        for source_id in _all_providers(ctx)
        if int(source_id) != int(sp_id)
        and ctx.get("sp_types", {}).get(int(source_id)) == "vehicle"
    ]

    if not vehicle_sources:
        raise ValueError(f"No vehicle source is available for service type {task_type}")

    energies = []
    for source_id in vehicle_sources:
        _, energy = _tx_time_energy(ctx, source_id, int(sp_id), size_bits)
        energies.append(float(energy))

    value = min(energies)
    service_energy_cache[cache_key] = float(value)
    return float(value)


def _candidate_dependency_ready_and_energy(ctx, state, sp_id: int, task_id: int):
    preds = ctx["dependencies"].get(task_id, [])

    if not preds:
        return 0.0, 0.0, dict(state.get("link_finish", {})), []

    recv_times = []
    tx_energy_total = 0.0
    edge_data_bits = ctx.get("edge_data_bits", {})
    fallback_output = ctx.get("task_output_size_bits", ctx.get("output_size", {}))
    link_finish = dict(state.get("link_finish", {}))
    transfers = []

    ordered_preds = sorted((int(pred) for pred in preds), key=lambda pred: float(state["task_finish"].get(pred, 0.0)))

    for pred in ordered_preds:
        src_sp = state["task_provider"].get(pred)

        if src_sp is None:
            raise ValueError(f"Predecessor task {pred} must be scheduled before task {task_id}")

        src_sp = int(src_sp)
        finish_src = float(state["task_finish"][pred])

        if src_sp == int(sp_id):
            recv_times.append(finish_src)
            continue

        data_bits = edge_data_bits.get(pred, {}).get(task_id)

        if data_bits is None:
            data_bits = fallback_output.get(pred, 0.0)

        tx_time, tx_energy = _tx_time_energy(ctx, src_sp, int(sp_id), float(data_bits))
        link_key = (src_sp, int(sp_id))
        idle_time = float(link_finish.get(link_key, ctx.get("idle_time", 0.0)))
        transfer_start = max(finish_src, idle_time)
        arrival_time = transfer_start + tx_time
        link_finish[link_key] = arrival_time

        recv_times.append(arrival_time)
        tx_energy_total += tx_energy
        transfers.append(
            {
                "predecessor_task_id": pred,
                "source_provider_id": src_sp,
                "destination_provider_id": int(sp_id),
                "data_bits": float(data_bits),
                "transfer_start_s": float(transfer_start),
                "transfer_time_s": float(tx_time),
                "arrival_time_s": float(arrival_time),
                "transfer_energy_j": float(tx_energy),
            }
        )

    return (scheduling.all_dependencies_receive_time(recv_times), tx_energy_total, link_finish, transfers)


def _candidate_eval(ctx, state, sp_id: int, task_id: int):
    deps_ready, dep_energy, link_finish, transfers = _candidate_dependency_ready_and_energy(ctx, state, sp_id, task_id)

    start = scheduling.task_start_timestamp(
        deps_ready_time_s=deps_ready,
        prev_rank_finish_time_s=float(
            state["provider_finish"].get(sp_id, 0.0)
        ),
    )

    finish = scheduling.task_finish_timestamp(start_time_s=start, compute_time_s=t_comp(ctx, sp_id, task_id))

    energy = e_comp(ctx, sp_id, task_id) + dep_energy + _service_program_energy(ctx, sp_id, task_id)

    alpha_n, beta_n = _weights(ctx)

    q = policy.single_task_efficiency(
        alpha_n=alpha_n,
        beta_n=beta_n,
        t_ref_s=t_ref_s(ctx),
        task_finish_time_s=finish,
        e_loc_j=e_loc_j(ctx),
        e_task_off_j=energy,
    )

    return q, start, finish, energy, link_finish, transfers


def compute_Q(ctx, sp_id: int, i: int):
    state = ctx.get("_schedule_state")

    if state is None:
        state = _empty_state(ctx)

    q, _, _, _, _, _ = _candidate_eval(ctx, state, sp_id, i)

    return q


def _empty_state(ctx):
    initial_provider_finish = ctx.get("provider_initial_finish", {})

    return {
        "provider_finish": {
            sp: max(0.0, float(initial_provider_finish.get(sp, 0.0)))
            for sp in _all_providers(ctx)
        },
        "link_finish": {},
        "task_start": {},
        "task_finish": {},
        "task_provider": {},
        "task_energy": {},
        "task_transfers": {},
    }


def _apply_assignment(ctx, state, task_id: int, sp_id: int, rank: int):
    _, start, finish, energy, link_finish, transfers = _candidate_eval(ctx, state, sp_id, task_id)

    state["provider_finish"][sp_id] = finish
    shared_link_finish = state.setdefault("link_finish", {})
    shared_link_finish.clear()
    shared_link_finish.update(link_finish)
    state.setdefault("task_start", {})[task_id] = start
    state["task_finish"][task_id] = finish
    state["task_provider"][task_id] = sp_id
    state["task_energy"][task_id] = energy
    state.setdefault("task_transfers", {})[task_id] = transfers

    _update_z(ctx, task_id, sp_id, rank)


def _entry_task_id(ctx) -> int:
    entry_task_id = ctx.get("entry_task_id")

    if entry_task_id is None:
        ready = [int(task_id) for task_id in ctx.get("tasks", {}).get("ready", [])]

        if len(ready) != 1:
            raise ValueError("Exactly one entry task is required")

        entry_task_id = ready[0]

    entry_task_id = int(entry_task_id)

    if entry_task_id not in ctx.get("cpu_cycles", {}):
        raise ValueError(f"Entry task {entry_task_id} is not present in the context")

    return entry_task_id


def _apply_entry_task(ctx, state, rank_counter):
    entry_task_id = _entry_task_id(ctx)
    local_sp_id = ctx.get("local_sp_id")

    if local_sp_id is None:
        raise ValueError("Local service provider is required for the entry task")

    local_sp_id = int(local_sp_id)

    if local_sp_id not in rank_counter:
        raise ValueError(f"Local service provider {local_sp_id} is not available")

    assigned_provider = state.get("task_provider", {}).get(entry_task_id)

    if assigned_provider is not None:
        if int(assigned_provider) != local_sp_id:
            raise ValueError("Entry task must be assigned to the local service provider")

        return entry_task_id, local_sp_id

    rank_counter[local_sp_id] += 1

    _apply_assignment(ctx, state, entry_task_id, local_sp_id, rank_counter[local_sp_id])

    return entry_task_id, local_sp_id


def t_finish(ctx, sp_id: int, task_id: int):
    state = ctx.get("_schedule_state")

    if state and state["task_provider"].get(task_id) == sp_id:
        return float(state["task_finish"].get(task_id, 0.0))

    _, _, finish, _, _, _ = _candidate_eval(ctx, state or _empty_state(ctx), sp_id, task_id)

    return finish


def t_start(ctx, sp_id: int, task_id: int):
    state = ctx.get("_schedule_state")

    if state and state["task_provider"].get(task_id) == sp_id:
        return float(state["task_start"].get(task_id, 0.0))

    _, start, _, _, _, _ = _candidate_eval(ctx, state or _empty_state(ctx), sp_id, task_id)

    return start


def t_off(ctx):
    state = ctx.get("_schedule_state")
    if state and state["task_finish"]:
        return max(state["task_finish"].values())
    return 0.0


def e_off(ctx):
    state = ctx.get("_schedule_state")

    if state and state["task_energy"]:
        return sum(state["task_energy"].values())

    return 0.0


def compute_Q1(ctx, sp_id: int | None = None):
    alpha_n, beta_n = _weights(ctx)

    return offloading_efficiency.application_offloading_efficiency(
        alpha_n=alpha_n,
        beta_n=beta_n,
        t_ref_s=t_ref_s(ctx),
        t_off_s=t_off(ctx),
        e_loc_j=e_loc_j(ctx),
        e_off_j=e_off(ctx),
    )


def _update_z(ctx, task_id, provider_id, rank):
    z_binary = ctx["z"]["binary"]
    z_compact = ctx["z"]["compact"]

    for p in list(z_binary.keys()):
        for rk in list(z_binary[p].keys()):
            if task_id in z_binary[p][rk]:
                del z_binary[p][rk][task_id]
            if not z_binary[p][rk]:
                del z_binary[p][rk]
        if not z_binary[p]:
            del z_binary[p]

    z_compact[task_id]["provider"] = provider_id
    z_compact[task_id]["rank"] = rank

    z_binary.setdefault(provider_id, {})
    z_binary[provider_id].setdefault(rank, {})
    z_binary[provider_id][rank][task_id] = 1


def _reset_assignment(ctx):
    ctx["z"] = {"binary": {}, "compact": {tid: {"provider": None, "rank": None} for tid in ctx["task_ids"]}}


def procedure1_greedy_initialization(S: int, task_order: List[int], ctx):
    from algorithm.update_service_cache import update_cache

    sp_list = _providers(ctx)
    I = len(task_order)

    solutions = []

    for s in range(1, S + 1):
        work_ctx = copy.deepcopy(ctx)
        _reset_assignment(work_ctx)
        work_ctx["_schedule_state"] = _empty_state(work_ctx)

        mutaInd = random.randint(0, I - 1) if I > 0 else 0
        nest = []
        r = {sp: 0 for sp in sp_list}
        local_sp_id = _local_sp_id(work_ctx)
        if local_sp_id is not None:
            r.setdefault(int(local_sp_id), 0)

        _apply_entry_task(work_ctx, work_ctx["_schedule_state"], r)

        for idx, task_id in enumerate(task_order):
            q_map = {sp: compute_Q(work_ctx, sp, task_id) for sp in sp_list}

            if s == 1:
                x_star = max(q_map, key=q_map.get)
            elif idx == mutaInd and len(q_map) > 1:
                best = max(q_map, key=q_map.get)
                alternatives = [sp for sp in q_map if sp != best]
                x_star = max(alternatives, key=q_map.get)
            else:
                x_star = max(q_map, key=q_map.get)

            r[x_star] += 1

            _apply_assignment(work_ctx, work_ctx["_schedule_state"], task_id, x_star, r[x_star])

            if work_ctx.get("use_caching", True):
                update_cache(work_ctx, x_star, task_id, remaining_task_ids=task_order[idx + 1:])

            nest.append((task_id, x_star, r[x_star]))

        quality = compute_Q1(work_ctx)
        solutions.append((nest, quality))

    solutions.sort(key=lambda item: item[1], reverse=True)

    return [nest for nest, _ in solutions]