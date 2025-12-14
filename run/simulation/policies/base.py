from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass(frozen=True)
class Task:
    task_id: str
    vehicle_id: int
    created_at: float
    required_cpu: int


@dataclass(frozen=True)
class VehicleState:
    id: int
    x: Optional[float]
    y: Optional[float]
    rsu_id: Optional[int]
    cpu_capacity: int


@dataclass(frozen=True)
class RSUState:
    id: int
    x: float
    y: float
    cpu_capacity: int


@dataclass(frozen=True)
class Decision:
    """
    خروجی الگوریتم:
      - local: روی خود vehicle
      - rsu: روی rsu_id مشخص
      - v2v: روی vehicle_id همسایه
      - dropped: هیچکدام
    """
    type: str  # "local" | "rsu" | "v2v" | "dropped"
    target_id: Optional[int] = None  # برای rsu/v2v لازم است


class PolicyBase:
    """
    این interface الگوریتم‌هاست.
    Core به هیچ الگوریتمی وابسته نیست؛ فقط این interface را صدا می‌زند.
    """

    name: str = "base"

    def decide(
        self,
        task: Task,
        vehicle: VehicleState,
        rsus: List[RSUState],
        neighbors: List[VehicleState],
        now: float,
    ) -> Decision:
        raise NotImplementedError
