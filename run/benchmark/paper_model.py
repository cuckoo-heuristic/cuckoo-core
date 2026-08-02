"""Pure mathematical helpers for the paper's VEFC model.

This module is intentionally isolated from Django, workers, and the current
benchmark runner.  It implements only equations that are explicitly stated in
Shen et al., *Cuckoo Search-Enabled Task Scheduling and Cache Updating in
Vehicular Edge-Fog Computing*.

Implemented:
- Table III application weights: alpha_n = 0.01 / T_ddl + 0.6, beta_n = 1-alpha_n
- Equations (22)-(25): reference local time/energy and offloading efficiency
- Equation (30): CPU-frequency allocation for vehicle SPs; MEC uses f_max
- Equations (32)-(34) and Algorithm 1: transmission-power bisection
- Table III V2I pathloss expression and sender-side power limits

Not implemented here:
- WINNER+B1 V2V pathloss details (the article refers to an external source)
- stochastic shadowing/Rayleigh samples
- scheduling, cache updates, or any database mutation
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite, log, log10, log2
from typing import Iterable


class PaperModelError(ValueError):
    """Raised when inputs violate the mathematical domain of the paper model."""


class ProviderKind(str, Enum):
    VEHICLE = "vehicle"
    RSU = "rsu"


@dataclass(frozen=True)
class ApplicationWeights:
    alpha: float
    beta: float


@dataclass(frozen=True)
class LocalReference:
    t_local_s: float
    t_ref_s: float
    e_local_j: float


@dataclass(frozen=True)
class PowerSearchResult:
    power_w: float
    iterations: int
    used_upper_bound: bool


def _positive_finite(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0.0:
        raise PaperModelError(f"{name} must be a finite value greater than zero")
    return value


def dbm_to_watts(dbm: float) -> float:
    dbm = float(dbm)
    if not isfinite(dbm):
        raise PaperModelError("dbm must be finite")
    return 10.0 ** ((dbm - 30.0) / 10.0)


def watts_to_dbm(watts: float) -> float:
    watts = _positive_finite(watts, "watts")
    return 10.0 * log10(watts) + 30.0


def article_weights(deadline_s: float) -> ApplicationWeights:
    deadline_s = _positive_finite(deadline_s, "deadline_s")

    deadline_ms = deadline_s * 1000.0

    alpha = 0.01 / deadline_ms + 0.6
    beta = 1.0 - alpha
    if not (0.0 <= alpha <= 1.0 and 0.0 <= beta <= 1.0):
        raise PaperModelError("The article weights must be between zero and one")

    return ApplicationWeights(
        alpha=float(alpha),
        beta=float(beta),
    )
def local_reference(
    cpu_cycles: Iterable[float],
    *,
    vehicle_fmax_hz: float,
    deadline_s: float,
    kappa: float,
) -> LocalReference:
    """Compute equations (23)-(25) for the all-local reference execution."""
    cycles = [float(value) for value in cpu_cycles]
    if not cycles:
        raise PaperModelError("cpu_cycles must contain at least one task")
    if any((not isfinite(value) or value < 0.0) for value in cycles):
        raise PaperModelError("cpu_cycles values must be finite and non-negative")

    fmax = _positive_finite(vehicle_fmax_hz, "vehicle_fmax_hz")
    deadline = _positive_finite(deadline_s, "deadline_s")
    kappa = _positive_finite(kappa, "kappa")

    total_cycles = sum(cycles)
    t_local = total_cycles / fmax
    t_ref = min(t_local, deadline)
    e_local = sum(kappa * (fmax**2) * value for value in cycles)

    if t_ref <= 0.0 or e_local <= 0.0:
        raise PaperModelError(
            "The reference time and energy must be positive; verify task workloads"
        )

    return LocalReference(
        t_local_s=float(t_local),
        t_ref_s=float(t_ref),
        e_local_j=float(e_local),
    )


def offloading_efficiency(
    *,
    t_off_s: float,
    e_off_j: float,
    reference: LocalReference,
    weights: ApplicationWeights,
) -> float:
    """Compute equation (22) without clipping the objective value."""
    t_off = float(t_off_s)
    e_off = float(e_off_j)
    if not isfinite(t_off) or t_off < 0.0:
        raise PaperModelError("t_off_s must be finite and non-negative")
    if not isfinite(e_off) or e_off < 0.0:
        raise PaperModelError("e_off_j must be finite and non-negative")

    return float(
        weights.alpha * (reference.t_ref_s - t_off) / reference.t_ref_s
        + weights.beta * (reference.e_local_j - e_off) / reference.e_local_j
    )


def allocated_cpu_frequency_hz(
    *,
    provider_kind: ProviderKind | str,
    provider_fmax_hz: float,
    reference: LocalReference,
    weights: ApplicationWeights,
    kappa: float,
) -> float:
    """Compute equation (30); MEC servers use their maximum CPU frequency."""
    try:
        kind = ProviderKind(provider_kind)
    except ValueError as exc:
        raise PaperModelError(f"Unknown provider kind: {provider_kind!r}") from exc

    fmax = _positive_finite(provider_fmax_hz, "provider_fmax_hz")
    kappa = _positive_finite(kappa, "kappa")

    if kind is ProviderKind.RSU:
        return float(fmax)

    if weights.beta <= 0.0:
        return float(fmax)

    numerator = weights.alpha * reference.e_local_j
    denominator = 2.0 * weights.beta * kappa * reference.t_ref_s
    f_star = (numerator / denominator) ** (1.0 / 3.0)
    return float(min(f_star, fmax))


def sender_power_limit_w(provider_kind: ProviderKind | str) -> float:
    """Return Table III's sender-side maximum power: vehicle 23 dBm, RSU 30 dBm."""
    try:
        kind = ProviderKind(provider_kind)
    except ValueError as exc:
        raise PaperModelError(f"Unknown provider kind: {provider_kind!r}") from exc
    return dbm_to_watts(23.0 if kind is ProviderKind.VEHICLE else 30.0)


def v2i_pathloss_db(distance_m: float) -> float:
    """Table III V2I pathloss: 128.1 + 37.6 log10(d), d in kilometres."""
    distance_m = _positive_finite(distance_m, "distance_m")
    distance_km = distance_m / 1000.0
    return float(128.1 + 37.6 * log10(distance_km))


def power_stationarity_y(
    power_w: float,
    *,
    channel_gain: float,
    noise_power_w: float,
    reference: LocalReference,
    weights: ApplicationWeights,
    scheduled: float = 1.0,
) -> float:
    """Evaluate equation (32), whose zero is searched by Algorithm 1."""
    p = float(power_w)
    if not isfinite(p) or p < 0.0:
        raise PaperModelError("power_w must be finite and non-negative")
    h = _positive_finite(channel_gain, "channel_gain")
    noise = _positive_finite(noise_power_w, "noise_power_w")
    z = float(scheduled)
    if not isfinite(z) or z < 0.0:
        raise PaperModelError("scheduled must be finite and non-negative")

    snr_term = 1.0 + p * h / noise
    first = z * weights.beta / reference.e_local_j * log2(snr_term)
    second = (
        z
        * (
            weights.alpha / reference.t_ref_s
            + weights.beta * p / reference.e_local_j
        )
        * h
        / (log(2.0) * (noise + p * h))
    )
    return float(first - second)


def optimal_transmit_power_w(
    *,
    channel_gain: float,
    noise_power_w: float,
    pmax_w: float,
    reference: LocalReference,
    weights: ApplicationWeights,
    tolerance_w: float = 1e-9,
    max_iterations: int = 256,
) -> PowerSearchResult:
    """Implement Algorithm 1's low-complexity bisection in watt units."""
    pmax = _positive_finite(pmax_w, "pmax_w")
    tolerance = _positive_finite(tolerance_w, "tolerance_w")
    if max_iterations <= 0:
        raise PaperModelError("max_iterations must be greater than zero")

    if power_stationarity_y(
        pmax,
        channel_gain=channel_gain,
        noise_power_w=noise_power_w,
        reference=reference,
        weights=weights,
    ) <= 0.0:
        return PowerSearchResult(
            power_w=float(pmax),
            iterations=0,
            used_upper_bound=True,
        )

    lower = 0.0
    upper = pmax
    iterations = 0

    while upper - lower > tolerance and iterations < max_iterations:
        midpoint = (lower + upper) / 2.0
        y_mid = power_stationarity_y(
            midpoint,
            channel_gain=channel_gain,
            noise_power_w=noise_power_w,
            reference=reference,
            weights=weights,
        )
        if y_mid <= 0.0:
            lower = midpoint
        else:
            upper = midpoint
        iterations += 1

    return PowerSearchResult(
        power_w=float((lower + upper) / 2.0),
        iterations=iterations,
        used_upper_bound=False,
    )