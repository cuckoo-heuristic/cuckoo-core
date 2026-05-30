from __future__ import annotations

import threading

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from run.simulation import (
    run_simulation,
    stop_simulation as stop_simulation_fn,
    simulation_status as status_fn,
)
from run.simulation.service import reset_simulation as reset_fn

from .serializer import StartSimulationSerializer


@extend_schema(
    request=StartSimulationSerializer,
    responses=inline_serializer(
        name="StartSimulationResponse",
        fields={
            "status": serializers.CharField(),
            "running": serializers.BooleanField(required=False),
        },
    ),
)
@api_view(["POST"])
def start_simulation(request):
    if status_fn().get("running"):
        return Response(
            {"status": "already running", **status_fn()},
            status=status.HTTP_200_OK,
        )

    ser = StartSimulationSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    a1 = ser.validated_data.get("a1", 1)
    a2 = ser.validated_data.get("a2", 1)
    a3 = ser.validated_data.get("a3", 1)

    t = threading.Thread(
        target=run_simulation,
        args=(a1, a2, a3),
        daemon=True,
    )
    t.start()

    return Response(
        {"status": "started", **status_fn()},
        status=status.HTTP_200_OK,
    )


@extend_schema(
    responses=inline_serializer(
        name="StopSimulationResponse",
        fields={
            "status": serializers.CharField(),
            "running": serializers.BooleanField(required=False),
        },
    )
)
@api_view(["POST"])
def stop_simulation(request):
    stop_simulation_fn()
    return Response(
        {"status": "stopped", **status_fn()},
        status=status.HTTP_200_OK,
    )


@extend_schema(
    responses=inline_serializer(
        name="SimulationStatusResponse",
        fields={
            "running": serializers.BooleanField(),
        },
    )
)
@api_view(["GET"])
def simulation_status(request):
    return Response(status_fn(), status=status.HTTP_200_OK)


@extend_schema(
    responses=inline_serializer(
        name="ResetSimulationResponse",
        fields={"status": serializers.CharField()},
    )
)
@api_view(["POST"])
def reset_simulation(request):
    stop_simulation_fn()
    reset_fn()
    return Response({"status": "reset"}, status=status.HTTP_200_OK)
