from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Scenario:
    time_simulate: int
    time_task: int
    time_step: int
    vehicle_ids: List[int]
    rsu_radius: float
    v2v_radius: float
    seed: Optional[int] = None
