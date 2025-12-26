import threading
from dataclasses import dataclass
from django.db import transaction
from vehicle.models import Vehicle
from rsu.models import RSU
from monarch_pylib.models import transmission

@dataclass(frozen=True)
class SimulationConfig:
    total_time: int
    tick_seconds: int = 1

def position_at(sim_total_time: int, t: int, path: list) -> tuple[float, float]:
    pos = transmission.current_position(sim_total_time, t, path)
    return float(pos[0]), float(pos[1])

class VehicleWorker(threading.Thread):
    def __init__(self, vehicle_id: int, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.vehicle_id = vehicle_id
        self.cfg = cfg
        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):
        vehicle = Vehicle.objects.get(id=self.vehicle_id)
        with transaction.atomic():
            vehicle.save(update_fields=["length", "speed"])
        t = 0
        while (t <= self.cfg.total_time) and (not self._stop_flag.is_set()):
            vehicle = Vehicle.objects.get(id=self.vehicle_id)

            if vehicle.path and len(vehicle.path) >= 2:
                x, y = position_at(self.cfg.total_time, t, vehicle.path)
                with transaction.atomic():
                    vehicle.x_coord = x
                    vehicle.y_coord = y
                    vehicle.save(update_fields=["x_coord", "y_coord"])

            # بهتر از sleep: اگر stop بخورد سریع قطع می‌شود
            if self._stop_flag.wait(self.cfg.tick_seconds):
                break

            t += self.cfg.tick_seconds


class RSUWorker(threading.Thread):
    def __init__(self, rsu_id: int, cfg: SimulationConfig):
        super().__init__(daemon=True)
        self.rsu_id = rsu_id
        self.cfg = cfg
        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):
        t = 0
        while (t <= self.cfg.total_time) and (not self._stop_flag.is_set()):
            _ = RSU.objects.get(id=self.rsu_id)

            if self._stop_flag.wait(self.cfg.tick_seconds):
                break

            t += self.cfg.tick_seconds
