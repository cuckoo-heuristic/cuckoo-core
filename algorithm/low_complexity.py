from __future__ import annotations
from typing import Any
from parameter.services import load_params_for_lib, load_params_obj
from monarch_pylib.model import block_coordinate_descent, offloading_efficiency
from monarch_pylib.model.transmission import channel_gain_v2i, v2i_uplink_rate

params = load_params_obj()
params_lib = load_params_for_lib()

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def db_to_linear(db: float) -> float:
    return 10 ** (float(db) / 10.0)

def hh(ctx, sp_id: int) -> float:
    distance = float(ctx["distance"][sp_id])
    tau_nm = float(getattr(params, "sigma_v2i", 8.0))
    g_rsu_db = float(getattr(params, "G_rsu", 8.0))
    g_vehicle_db = float(getattr(params, "G_vehicle", 3.0))
    rho = db_to_linear(g_rsu_db) * db_to_linear(g_vehicle_db)
    varpi_nm = float(getattr(params, "h_rsu", 5.0)) * float(getattr(params, "h_vehicle", 1.5))
    gamma = float(getattr(params, "Y_v2i", 3.76))

    return float(channel_gain_v2i(
        tau_nm=tau_nm,
        rho=rho,
        varpi_nm=varpi_nm,
        distance_nm=distance,
        pathloss_exponent_gamma=gamma
    ))

def compute_local_time(ctx) -> float:
    cpu_cycles_list = list(ctx["cpu_cycles"].values())
    fmax_vehicle_hz = _safe_float(getattr(params_lib, "fmax_vehicle_hz", 0.0), 0.0)
    return offloading_efficiency.all_local_execution_time(cpu_cycles_list=cpu_cycles_list, f_max_local_hz=fmax_vehicle_hz)

def compute_local_energy(ctx) -> float:
    cpu_cycles_list = list(ctx["cpu_cycles"].values())
    kappa = _safe_float(getattr(params, "k", 1e-25), 1e-25)
    fmax_vehicle_hz = _safe_float(getattr(params_lib, "fmax_vehicle_hz", 0.0), 0.0)
    return offloading_efficiency.all_local_execution_energy(kappa=kappa, cpu_cycles_list=cpu_cycles_list, f_max_local_hz=fmax_vehicle_hz)

def compute_reference_time(ctx) -> float:
    t_ddl_s = float(ctx["t_ddl_s"])
    t_loc = compute_local_time(ctx)
    return offloading_efficiency.reference_time(t_loc_s=t_loc, t_ddl_s=t_ddl_s)

def _get_z_selected_for_provider(ctx, sp_id) -> float:
    z_binary = ctx["z"]["binary"]
    for r in z_binary.get(sp_id, {}):
        for _, v in z_binary[sp_id][r].items():
            if v == 1:
                return 1.0
    return 0.0

def _get_selected_provider(ctx):
    for sp in ctx.get("providers", []):
        z_binary = ctx["z"]["binary"]
        for r in z_binary.get(sp, {}):
            for _, v in z_binary[sp][r].items():
                if v == 1:
                    return sp
    return None

def y_function(ctx, p: float) -> float:
    alpha_n = _safe_float(getattr(params, "alpha_n", 0.5), 0.5)
    beta_n = _safe_float(getattr(params, "beta_n", 1.0 - alpha_n), 1.0 - alpha_n)
    d2 = _safe_float(getattr(params_lib, "delta2_w", 0.0), 0.0)
    e_loc_j = compute_local_energy(ctx)
    t_ref_s = compute_reference_time(ctx)
    sp_id = _get_selected_provider(ctx)
    if sp_id is None:
        return 0.0
    z_selected = _get_z_selected_for_provider(ctx, sp_id)
    h_selected = hh(ctx, sp_id)
    return block_coordinate_descent.tx_power_aux_function(z_selected=z_selected, alpha_n=alpha_n, beta_n=beta_n, t_ref_s=t_ref_s, e_loc_j=e_loc_j, p_w=p, h=h_selected, noise_delta2=d2)

def run(ctx, pmax: float | None = None) -> float:
    params_lib = load_params_for_lib()
    if pmax is None:
        pmax = _safe_float(getattr(params_lib, "pmax_vehicle_w", 0.0), 0.0)
    eps = 1e-6
    p_l = 0.0
    p_u = float(pmax)
    y_pmax = y_function(ctx, p_u)
    if y_pmax <= 0:
        return p_u
    while abs(p_u - p_l) > eps:
        p_mid = 0.5 * (p_l + p_u)
        y_mid = y_function(ctx, p_mid)
        if y_mid <= 0:
            p_l = p_mid
        else:
            p_u = p_mid
    return 0.5 * (p_l + p_u)
