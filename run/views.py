from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema
from .serializers import RunSimulationInputSerializer
from .simulation.scenario import Scenario
from .simulation.core import simulate
from .simulation.metrics import summarize_metrics
from .simulation.policies.simple import PreferRSUPolicy, PreferV2VPolicy

def _build_policy(policy_mode: str):
    if policy_mode == "prefer_v2v":
        return PreferV2VPolicy()
    return PreferRSUPolicy()

class AppRunSimulationAPIView(APIView):
    @extend_schema(request=RunSimulationInputSerializer, responses=None)
    def post(self, request):
        serializer = RunSimulationInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        d = serializer.validated_data
        scenario = Scenario(
            time_simulate=int(d["time_simulate"]),
            time_task=int(d["time_task"]),
            time_step=int(d["time_step"]),
            vehicle_ids=d["vehicle_ids"],
            rsu_radius=float(d["rsu_radius"]),
            v2v_radius=float(d["v2v_radius"]),
            seed=d.get("seed"),
        )
        policy = _build_policy(d["policy_mode"])
        result = simulate(scenario, policy, output_mode=d["output_mode"])
        mode = d.get("output_mode", "timeline")
        if mode == "status":
            last_frame = result["timeline"][-1] if result["timeline"] else None
            return Response(
                {
                    "message": "Simulation status snapshot.",
                    "input": {**d, "policy_mode": policy.name},
                    "db_check": result["db_check"],
                    "rsu_info": result["rsu_info"],
                    "v2v_info": result["v2v_info"],
                    "status": last_frame,
                },
                status=status.HTTP_200_OK
            )
        if d["output_mode"] == "snapshot":
            return Response(
                {
                    "message": "Simulation completed (snapshot).",
                    "input": {**d, "policy_mode": policy.name},
                    "db_check": result["db_check"],
                    "rsu_info": result["rsu_info"],
                    "v2v_info": result["v2v_info"],
                    "state": result["state"],  # فقط وضعیت نهایی
                },
                status=status.HTTP_200_OK
            )
        metrics = summarize_metrics(result["timeline"])
        return Response(
            {
                "message": "Simulation completed (timeline).",
                "input": {**d, "policy_mode": policy.name},
                **result,
                "metrics": metrics,
            },
            status=status.HTTP_200_OK
        )
