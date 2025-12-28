from dataclasses import dataclass
from typing import Any
from parameter.models import Parameter


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        raise ValueError(f"Cannot convert to float: {x}")

def _to_int(x: Any) -> int:
    try:
        return int(float(x))
    except Exception:
        raise ValueError(f"Cannot convert to int: {x}")


@dataclass(frozen=True)
class SimParams:
    B: float
    delta2: float
    Y_v2i: float
    Y_v2v: float
    sigma_v2i: float
    sigma_v2v: float
    h_rsu: float
    h_vehicle: float
    G_rsu: float
    G_vehicle: float
    levy_lambda: float
    p_discard_init: float
    S: float
    k: float
    alpha_n: float
    cell_radius_rsu: float
    rec_noi_rsu: float
    rec_noi_vehicle: float
    pmax_vehicle: float
    pmax_rsu: float
    fmax_vehicle: float
    fmax_rsu: float
    simulate_time: int
    taking_task_time: int
    @property
    def beta_n(self) -> float:
        return 1.0 - self.alpha_n


def load_params_obj() -> SimParams:
    raw = {p.key: p.value for p in Parameter.objects.all()}
    return SimParams(
        B=_to_float(raw["B"]),
        delta2=_to_float(raw["delta2"]),
        Y_v2i=_to_float(raw["Y_v2i"]),
        Y_v2v=_to_float(raw["Y_v2v"]),
        sigma_v2i=_to_float(raw["sigma_v2i"]),
        sigma_v2v=_to_float(raw["sigma_v2v"]),
        h_rsu=_to_float(raw["h_rsu"]),
        h_vehicle=_to_float(raw["h_vehicle"]),
        G_rsu=_to_float(raw["G_rsu"]),
        G_vehicle=_to_float(raw["G_vehicle"]),
        levy_lambda=_to_float(raw["levy_lambda"]),
        p_discard_init=_to_float(raw["p_discard_init"]),
        S=_to_float(raw["S"]),
        k=_to_float(raw["k"]),
        alpha_n=_to_float(raw["alpha_n"]),
        cell_radius_rsu=_to_float(raw["cell_radius_rsu"]),
        rec_noi_rsu=_to_float(raw["rec_noi_rsu"]),
        rec_noi_vehicle=_to_float(raw["rec_noi_vehicle"]),
        pmax_vehicle=_to_float(raw["pmax_vehicle"]),
        pmax_rsu=_to_float(raw["pmax_rsu"]),
        fmax_vehicle=_to_float(raw["fmax_vehicle"]),
        fmax_rsu=_to_float(raw["fmax_rsu"]),
        simulate_time=_to_int(raw["simulate_time"]),
        taking_task_time=_to_int(raw["taking_task_time"]),
    )
