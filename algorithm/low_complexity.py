from __future__ import annotations

from math import log10
from random import Random
from typing import Any

from parameter.services import load_params_for_lib, load_params_obj
from monarch_pylib.model import block_coordinate_descent, offloading_efficiency
from monarch_pylib.model.transmission import distance_3d

params = load_params_obj()
params_lib = load_params_for_lib()


def _weights(ctx):
    alpha_n = float(ctx.get("alpha_n", params.alpha_n))
    beta_n = float(ctx.get("beta_n", 1.0 - alpha_n))
    return alpha_n, beta_n


def db_to_linear(db: float) -> float:
    return 10.0 ** (float(db) / 10.0)


def _provider_height(ctx, sp_id: int) -> float:
    return float(params.h_rsu if ctx.get("sp_types", {}).get(sp_id) == "rsu" else params.h_vehicle)


def link_distance(ctx, src_sp_id: int, dst_sp_id: int) -> float:
    src_sp_id = int(src_sp_id)
    dst_sp_id = int(dst_sp_id)

    if src_sp_id == dst_sp_id:
        return 0.0

    src_position = ctx.get("sp_position", {}).get(src_sp_id)
    dst_position = ctx.get("sp_position", {}).get(dst_sp_id)

    if src_position is None or dst_position is None:
        raise ValueError(f"Missing position for link {src_sp_id}->{dst_sp_id}")

    return float(
        distance_3d(
            float(src_position[0]),
            float(src_position[1]),
            _provider_height(ctx, src_sp_id),
            float(dst_position[0]),
            float(dst_position[1]),
            _provider_height(ctx, dst_sp_id),
        )
    )


def _stable_seed(ctx, src_sp_id: int, dst_sp_id: int) -> int:
    base_seed = int(ctx.get("seed", 0) or 0)
    application_id = int(ctx.get("application_id", 0) or 0)

    return (
        base_seed * 1_000_003
        + application_id * 97_409
        + int(src_sp_id) * 9_973
        + int(dst_sp_id) * 37
    ) & 0xFFFFFFFF


def _fading_factors(ctx, src_sp_id: int, dst_sp_id: int, sigma_db: float):
    cache = ctx.setdefault("_link_fading", {})
    key = (int(src_sp_id), int(dst_sp_id))

    if key not in cache:
        rng = Random(_stable_seed(ctx, *key))
        shadowing_db = rng.gauss(0.0, float(sigma_db))
        shadowing_linear = 10.0 ** (-shadowing_db / 10.0)
        rayleigh_power = max(rng.expovariate(1.0), 1e-12)
        cache[key] = {
            "shadowing_db": float(shadowing_db),
            "shadowing_linear": float(shadowing_linear),
            "rayleigh_power": float(rayleigh_power),
        }

    item = cache[key]
    return float(item["shadowing_linear"]), float(item["rayleigh_power"])


def _v2i_pathloss_db(distance_m: float) -> float:
    distance_km = max(float(distance_m), 1.0) / 1000.0
    return float(128.1 + 37.6 * log10(distance_km))


def _winner_b1_los_pathloss_db(distance_m: float) -> float:
    distance_m = max(float(distance_m), 10.0)
    carrier_ghz = 2.0
    return float(22.7 * log10(distance_m) + 41.0 + 20.0 * log10(carrier_ghz / 5.0))


def channel_gain(ctx, sp_id: int, dst_sp_id: int | None = None) -> float:
    if dst_sp_id is None:
        src_sp_id = ctx.get("local_sp_id")
        dst_sp_id = sp_id
    else:
        src_sp_id = sp_id

    if src_sp_id is None:
        raise ValueError("Local service provider is not available")

    src_sp_id = int(src_sp_id)
    dst_sp_id = int(dst_sp_id)

    if src_sp_id == dst_sp_id:
        return 0.0

    src_type = ctx.get("sp_types", {}).get(src_sp_id)
    dst_type = ctx.get("sp_types", {}).get(dst_sp_id)

    if src_type == "rsu" and dst_type == "rsu":
        return 0.0

    gain_cache = ctx.setdefault("_channel_gain_cache", {})
    cache_key = (src_sp_id, dst_sp_id)

    if cache_key in gain_cache:
        return float(gain_cache[cache_key])

    is_v2i = src_type == "rsu" or dst_type == "rsu"
    sigma_db = float(params.sigma_v2i if is_v2i else params.sigma_v2v)
    distance_m = link_distance(ctx, src_sp_id, dst_sp_id)
    pathloss_db = _v2i_pathloss_db(distance_m) if is_v2i else _winner_b1_los_pathloss_db(distance_m)

    src_gain_db = float(params.G_rsu if src_type == "rsu" else params.G_vehicle)
    dst_gain_db = float(params.G_rsu if dst_type == "rsu" else params.G_vehicle)
    shadowing_linear, rayleigh_power = _fading_factors(ctx, src_sp_id, dst_sp_id, sigma_db)
    mean_path_gain = 10.0 ** ((src_gain_db + dst_gain_db - pathloss_db) / 10.0)

    value = float(max(mean_path_gain * shadowing_linear * rayleigh_power, 1e-30))
    gain_cache[cache_key] = value
    return value


def compute_local_time(ctx) -> float:
    return offloading_efficiency.all_local_execution_time(
        cpu_cycles_list=list(ctx["cpu_cycles"].values()),
        f_max_local_hz=float(ctx.get("local_cpu_freq_hz", params_lib.fmax_vehicle_hz)),
    )


def compute_local_energy(ctx) -> float:
    return offloading_efficiency.all_local_execution_energy(
        kappa=float(params.k),
        cpu_cycles_list=list(ctx["cpu_cycles"].values()),
        f_max_local_hz=float(ctx.get("local_cpu_freq_hz", params_lib.fmax_vehicle_hz)),
    )


def compute_reference_time(ctx) -> float:
    return offloading_efficiency.reference_time(
        t_loc_s=compute_local_time(ctx),
        t_ddl_s=float(ctx["t_ddl_s"]),
    )


def y_function(ctx, sp_id: int, p: float, z_selected: float = 1.0, dst_sp_id: int | None = None) -> float:
    if dst_sp_id is None:
        src_sp_id = ctx.get("local_sp_id")
        dst_sp_id = sp_id
    else:
        src_sp_id = sp_id

    if src_sp_id is None:
        raise ValueError("Local service provider is not available")

    src_sp_id = int(src_sp_id)
    dst_sp_id = int(dst_sp_id)

    if src_sp_id == dst_sp_id:
        return 0.0

    if ctx.get("sp_types", {}).get(src_sp_id) == "rsu" and ctx.get("sp_types", {}).get(dst_sp_id) == "rsu":
        return 0.0

    alpha_n, beta_n = _weights(ctx)

    return block_coordinate_descent.tx_power_aux_function(
        z_selected=float(z_selected),
        alpha_n=alpha_n,
        beta_n=beta_n,
        t_ref_s=compute_reference_time(ctx),
        e_loc_j=compute_local_energy(ctx),
        p_w=float(p),
        h=channel_gain(ctx, src_sp_id, dst_sp_id),
        noise_delta2=float(params_lib.delta2_w),
    )


def run(ctx, sp_id: int, pmax: float | None = None, z_selected: float = 1.0, dst_sp_id: int | None = None) -> float:
    if dst_sp_id is None:
        src_sp_id = ctx.get("local_sp_id")
        dst_sp_id = sp_id
    else:
        src_sp_id = sp_id

    if src_sp_id is None:
        raise ValueError("Local service provider is not available")

    src_sp_id = int(src_sp_id)
    dst_sp_id = int(dst_sp_id)

    if src_sp_id == dst_sp_id:
        return 0.0

    if ctx.get("sp_types", {}).get(src_sp_id) == "rsu" and ctx.get("sp_types", {}).get(dst_sp_id) == "rsu":
        return 0.0

    power_cache = ctx.setdefault("_tx_power_cache", {})
    cache_key = (src_sp_id, dst_sp_id, float(z_selected), None if pmax is None else float(pmax))

    if cache_key in power_cache:
        return float(power_cache[cache_key])

    if pmax is None:
        src_type = ctx.get("sp_types", {}).get(src_sp_id)
        pmax = float(params_lib.pmax_rsu_w if src_type == "rsu" else params_lib.pmax_vehicle_w)

    p_l = 0.0
    p_u = float(pmax)
    eps = 1e-6

    if p_u <= 0.0:
        return 0.0

    if y_function(ctx, src_sp_id, p_u, z_selected=z_selected, dst_sp_id=dst_sp_id) <= 0.0:
        power_cache[cache_key] = float(p_u)
        return float(p_u)

    while p_u - p_l > eps:
        p_mid = 0.5 * (p_l + p_u)

        if y_function(ctx, src_sp_id, p_mid, z_selected=z_selected, dst_sp_id=dst_sp_id) <= 0.0:
            p_l = p_mid
        else:
            p_u = p_mid

    value = 0.5 * (p_l + p_u)
    power_cache[cache_key] = float(value)
    return float(value)