from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ApplicationResult:
    application_id: int
    vehicle_id: int | None
    delay_s: float
    energy_j: float
    efficiency: float
    deadline_s: float
    completed: bool
    task_count: int
    scheduled_task_count: int
    providers_used: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AlgorithmResult:
    algorithm: str
    seed: int
    applications: List[ApplicationResult]
    metrics: Dict[str, float]
    iteration_history: List[Dict[str, float]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "seed": self.seed,
            "applications": [item.to_dict() for item in self.applications],
            "metrics": dict(self.metrics),
            "iteration_history": list(self.iteration_history),
        }


@dataclass(frozen=True)
class JointApplicationResult:
    application_id: int
    vehicle_id: int | None
    deadline_s: float
    alpha_n: float
    beta_n: float
    delay_s: float
    energy_j: float
    efficiency: float
    completed: bool
    task_count: int
    optimized_task_count: int
    scheduled_task_count: int
    entry_task_id: int
    entry_provider_id: int
    providers_used: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JointAlgorithmResult:
    algorithm: str
    seed: int
    population_size: int
    tmax: int
    total_efficiency: float
    applications: List[JointApplicationResult]
    metrics: Dict[str, float]
    iteration_history: List[Dict[str, float]] = field(default_factory=list)
    scientific_status: str = "article-aligned-runtime-final-with-declared-limitations"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "seed": self.seed,
            "population_size": self.population_size,
            "tmax": self.tmax,
            "total_efficiency": self.total_efficiency,
            "applications": [item.to_dict() for item in self.applications],
            "metrics": dict(self.metrics),
            "iteration_history": list(self.iteration_history),
            "scientific_status": self.scientific_status,
        }