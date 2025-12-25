from rest_framework.decorators import api_view
from rest_framework.response import Response
from run.simulation import run_simulation
from parameter.services import load_params_obj

import threading

@api_view(["POST"])
def start_simulation(request):
    params = load_params_obj()

    t = threading.Thread(target=run_simulation, daemon=True)
    t.start()

    return Response({"status": "started", "time": params.simulate_time})
