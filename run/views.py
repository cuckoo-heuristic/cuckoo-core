from rest_framework.decorators import api_view
from rest_framework.response import Response
import threading
from parameter.services import load_params_obj
from vehicle.models import Vehicle
from run.simulation import run_simulation, stop_simulation as stop_simulation_fn, simulation_status as status_fn

@api_view(["POST"])
def start_simulation(request):
    params = load_params_obj()
    t = threading.Thread(target=run_simulation, daemon=True)
    t.start()
    return Response({"status": "started", "time": params.simulate_time, **status_fn()})


@api_view(["POST"])
def stop_simulation(request):
    stop_simulation_fn()
    return Response({"status": "stopped", **status_fn()})

@api_view(["GET"])
def simulation_status(request):
    return Response(status_fn())

