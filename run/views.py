from rest_framework.decorators import api_view
from rest_framework.response import Response
from run.simulation import run_simulation
import threading

@api_view(["POST"])
def start_simulation(request):
    total_time = int(request.data.get("time", 30))
    t = threading.Thread(target=run_simulation, args=(total_time,), daemon=True)
    t.start()
    return Response({"status": "started", "time": total_time})
