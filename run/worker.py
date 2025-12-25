import threading
import time as pytime
from dataclasses import dataclass

from django.db import transaction

from vehicle.models import Vehicle
from rsu.models import RSU

from monarch_pylib.models import transmission


@dataclass(frozen=True)
class SimulationConfig:
    total_time: int          # زمان کل شبیه‌سازی (ثانیه)
    tick_seconds: int = 1    # هر چند ثانیه آپدیت کنیم (فعلاً 1)


def compute_length_and_speed(vehicle: Vehicle, total_time: int) -> tuple[float, float]:
    path = vehicle.path or []
    length = float(transmission.path_length_2d(path)) if len(path) >= 2 else 0.0
    speed = float(transmission.speed_vehicle(length, total_time)) if total_time > 0 else 0.0
    return length, speed


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
        length, speed = compute_length_and_speed(vehicle, self.cfg.total_time)

        with transaction.atomic():
            vehicle.length = length
            vehicle.speed = speed
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
            pytime.sleep(self.cfg.tick_seconds)
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
            rsu = RSU.objects.get(id=self.rsu_id)
            pytime.sleep(self.cfg.tick_seconds)
            t += self.cfg.tick_seconds
