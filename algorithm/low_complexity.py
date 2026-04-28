from __future__ import annotations
from typing import Any
from parameter.services import load_params_for_lib, load_params_obj
from monarch_pylib.model import block_coordinate_descent, offloading_efficiency
from system.build_context import MiniSystemContextBuilder

params = load_params_obj()
params_lib = load_params_for_lib()

builder = MiniSystemContextBuilder(application_id=1)
ctx = builder.build_context()

cpu_cycles = ctx["cpu_cycles"]
t_ddl_s = ctx["t_ddl_s"]
z_binary = ctx["z"]["binary"]
hh = ctx["hh"]

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except:
        return float(default)

def compute_local_time() -> float:
    fmax_vehicle_hz = _safe_float(getattr(params_lib, "fmax_vehicle_hz", 0.0), 0.0)
    return offloading_efficiency.all_local_execution_time(
        cpu_cycles_list=cpu_cycles,
        f_max_local_hz=float(fmax_vehicle_hz),
    )

def compute_local_energy() -> float:
    kappa = _safe_float(getattr(params, "k", 1e-25), 1e-25)
    fmax_vehicle_hz = _safe_float(getattr(params_lib, "fmax_vehicle_hz", 0.0), 0.0)
    return offloading_efficiency.all_local_execution_energy(
        kappa=float(kappa),
        cpu_cycles_list=cpu_cycles,
        f_max_local_hz=float(fmax_vehicle_hz),
    )

def compute_reference_time() -> float:
    t_loc = compute_local_time()
    return offloading_efficiency.reference_time(
        t_loc_s=float(t_loc),
        t_ddl_s=float(t_ddl_s),
    )

def _get_z_selected() -> float:
    for sp in z_binary:
        for r in z_binary[sp]:
            for _, v in z_binary[sp][r].items():
                if v == 1:
                    return 1.0
    return 0.0

def y_function(p: float) -> float:
    alpha_n = _safe_float(getattr(params, "alpha_n", 0.5), 0.5)
    beta_n = _safe_float(getattr(params, "beta_n", 1.0 - alpha_n), 1.0 - alpha_n)
    d2 = _safe_float(getattr(params_lib, "delta2_w", 0.0), 0.0)
    e_loc_j = compute_local_energy()
    t_ref_s = compute_reference_time()
    z_selected = _get_z_selected()
    h_selected = float(list(hh.values())[0])
    return block_coordinate_descent.tx_power_aux_function(
        z_selected=float(z_selected),
        alpha_n=float(alpha_n),
        beta_n=float(beta_n),
        t_ref_s=float(t_ref_s),
        e_loc_j=float(e_loc_j),
        p_w=float(p),
        h=float(h_selected),
        noise_delta2=float(d2),
    )

def run(pmax: float | None = None) -> float:
    params_lib = load_params_for_lib()
    if pmax is None:
        pmax = _safe_float(getattr(params_lib, "pmax_vehicle_w", 0.0), 0.0)

    eps = 1e-6
    p_l = 0.0
    p_u = float(pmax)

    y_pmax = y_function(p_u)
    if y_pmax <= 0:
        return float(p_u)

    while abs(p_u - p_l) > eps:
        p_mid = 0.5 * (p_l + p_u)
        y_mid = y_function(p_mid)
        if y_mid <= 0:
            p_l = p_mid
        else:
            p_u = p_mid

    return 0.5 * (p_l + p_u)
