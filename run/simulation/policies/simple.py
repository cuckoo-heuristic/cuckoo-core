from typing import List
from .base import PolicyBase, Task, VehicleState, RSUState, Decision


class PreferRSUPolicy(PolicyBase):
    name = "prefer_rsu"

    def decide(self, task: Task, vehicle: VehicleState, rsus: List[RSUState], neighbors: List[VehicleState], now: float) -> Decision:
        # ترتیب فقط "انتخاب مقصد" است. Core بعداً زمان‌بندی/صف را اعمال می‌کند.

        # 1) local همیشه اولین انتخاب است
        if vehicle.cpu_capacity >= task.required_cpu:
            return Decision(type="local", target_id=vehicle.id)

        # 2) rsu بعدی
        if vehicle.rsu_id is not None:
            for r in rsus:
                if r.id == vehicle.rsu_id and r.cpu_capacity >= task.required_cpu:
                    return Decision(type="rsu", target_id=r.id)

        # 3) v2v بعدی
        for n in neighbors:
            if n.cpu_capacity >= task.required_cpu:
                return Decision(type="v2v", target_id=n.id)

        return Decision(type="dropped", target_id=None)


class PreferV2VPolicy(PolicyBase):
    name = "prefer_v2v"

    def decide(self, task: Task, vehicle: VehicleState, rsus: List[RSUState], neighbors: List[VehicleState], now: float) -> Decision:
        # 1) local
        if vehicle.cpu_capacity >= task.required_cpu:
            return Decision(type="local", target_id=vehicle.id)

        # 2) v2v قبل از rsu
        for n in neighbors:
            if n.cpu_capacity >= task.required_cpu:
                return Decision(type="v2v", target_id=n.id)

        # 3) rsu آخر
        if vehicle.rsu_id is not None:
            for r in rsus:
                if r.id == vehicle.rsu_id and r.cpu_capacity >= task.required_cpu:
                    return Decision(type="rsu", target_id=r.id)

        return Decision(type="dropped", target_id=None)
