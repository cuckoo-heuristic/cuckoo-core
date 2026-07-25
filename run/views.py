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
from run.benchmark.experiments import run_paper_experiment
from run.benchmark.runner import run_joint_benchmark as run_benchmark_fn
from .serializer import (
    BenchmarkRequestSerializer,
    PaperExperimentRequestSerializer,
    StartSimulationSerializer,
)


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

    tmax = ser.validated_data.get("tmax", 10)

    t = threading.Thread(
        target=run_simulation,
        kwargs={"tmax": tmax},
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
@extend_schema(
    request=BenchmarkRequestSerializer,
    responses=inline_serializer(
        name="BenchmarkResponse",
        fields={
            "application_ids": serializers.ListField(
                child=serializers.IntegerField()
            ),
            "algorithms": serializers.ListField(
                child=serializers.CharField()
            ),
            "seeds": serializers.ListField(
                child=serializers.IntegerField()
            ),
            "tmax": serializers.IntegerField(),
            "runs": serializers.ListField(
                child=serializers.DictField()
            ),
            "summary": serializers.DictField(),
        },
    ),
)
@api_view(["POST"])
def benchmark(request):
    if status_fn().get("running"):
        return Response(
            {
                "detail": (
                    "Stop the simulation before "
                    "running the benchmark."
                )
            },
            status=status.HTTP_409_CONFLICT,
        )

    ser = BenchmarkRequestSerializer(
        data=request.data
    )
    ser.is_valid(raise_exception=True)

    try:
        result = run_benchmark_fn(
            application_ids=(
                ser.validated_data[
                    "application_ids"
                ]
            ),
            algorithms=(
                ser.validated_data.get(
                    "algorithms"
                )
            ),
            seeds=(
                ser.validated_data.get(
                    "seeds",
                    [1],
                )
            ),
            tmax=(
                ser.validated_data.get(
                    "tmax",
                    10,
                )
            ),
        )

    except ValueError as exc:
        return Response(
            {
                "detail": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        result,
        status=status.HTTP_200_OK,
    )

@extend_schema(
    request=PaperExperimentRequestSerializer,
    responses=serializers.DictField(),
)
@api_view(["POST"])
def paper_benchmark(request):
    if status_fn().get("running"):
        return Response(
            {
                "detail": (
                    "Stop the simulation before running the paper experiment."
                )
            },
            status=status.HTTP_409_CONFLICT,
        )
    ser = PaperExperimentRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    try:
        result = run_paper_experiment(
            figure=ser.validated_data["figure"],
            repetitions=ser.validated_data.get("repetitions"),
            seed_start=ser.validated_data.get("seed_start", 1),
            tmax=ser.validated_data.get("tmax", 15),
            population_size=ser.validated_data.get("population_size"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(result, status=status.HTTP_200_OK)