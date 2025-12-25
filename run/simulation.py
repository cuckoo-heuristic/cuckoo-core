from vehicle.models import Vehicle
from rsu.models import RSU
from .worker import VehicleWorker, RSUWorker, SimulationConfig
from parameter.services import load_params_obj

def run_simulation():
    params = load_params_obj()
    total_time = params.simulate_time

    cfg = SimulationConfig(total_time=total_time, tick_seconds=1)

    vehicle_workers = [VehicleWorker(v.id, cfg) for v in Vehicle.objects.all()]
    rsu_workers = [RSUWorker(r.id, cfg) for r in RSU.objects.all()]

    for w in vehicle_workers + rsu_workers:
        w.start()

    for w in vehicle_workers + rsu_workers:
        w.join()

    return {"vehicles": len(vehicle_workers), "rsus": len(rsu_workers), "time": total_time}
