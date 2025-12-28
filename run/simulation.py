import threading
from vehicle.models import Vehicle
from rsu.models import RSU
from parameter.services import load_params_obj

from .worker import VehicleWorker, RSUWorker, SimulationConfig


_registry_lock = threading.Lock()
_vehicle_workers = []
_rsu_workers = []
_running = False


def run_simulation():
    global _running, _vehicle_workers, _rsu_workers

    params = load_params_obj()
    total_time = int(params.simulate_time)

    cfg = SimulationConfig(total_time=total_time, tick_seconds=1)

    with _registry_lock:
        _running = True
        _vehicle_workers = [VehicleWorker(v.id, cfg) for v in Vehicle.objects.all()]
        _rsu_workers = [RSUWorker(r.id, cfg) for r in RSU.objects.all()]

    workers = _vehicle_workers + _rsu_workers
    for w in workers:
        w.start()

    for w in workers:
        w.join()

    with _registry_lock:
        _running = False


def stop_simulation():
    global _running

    with _registry_lock:
        workers = list(_vehicle_workers + _rsu_workers)

    for w in workers:
        w.stop()

    for w in workers:
        w.join()

    with _registry_lock:
        _running = False


def simulation_status():
    with _registry_lock:
        return {"running": _running, "vehicles": len(_vehicle_workers), "rsus": len(_rsu_workers)}
