from rest_framework import serializers


class StartSimulationSerializer(serializers.Serializer):
    tmax = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        default=10,
    )


class SimulationConfigSerializer(serializers.Serializer):
    total_time = serializers.IntegerField()
    tick_seconds = serializers.IntegerField()
    cell_radius_rsu = serializers.FloatField()


class SimulationWorkersSerializer(serializers.Serializer):
    vehicle = serializers.IntegerField()
    rsu = serializers.IntegerField()
    task_generator = serializers.BooleanField()
    context = serializers.BooleanField()
    status = serializers.BooleanField()


class SimulationCountsSerializer(serializers.Serializer):
    vehicles = serializers.IntegerField()
    rsus = serializers.IntegerField()
    rsu_vehicle_total = serializers.IntegerField()
    rsu_vehicle_open = serializers.IntegerField()
    applications = serializers.IntegerField()
    applications_in_progress = serializers.IntegerField()
    tasks = serializers.IntegerField()
    taskexecutions = serializers.IntegerField()
    cache_items = serializers.IntegerField()


class SimulationContextSerializer(serializers.Serializer):
    ok = serializers.IntegerField()
    fail = serializers.IntegerField()
    sample = serializers.DictField(required=False, allow_null=True)
    vehicles = serializers.ListField(child=serializers.DictField(), required=False)
    sim_time_s = serializers.FloatField(required=False, allow_null=True)
    base_time = serializers.DateTimeField(required=False, allow_null=True)
    base_time_type = serializers.CharField(required=False, allow_null=True)
    last_error = serializers.CharField(required=False, allow_null=True)


class SimulationStatusSerializer(serializers.Serializer):
    running = serializers.BooleanField()
    workers = SimulationWorkersSerializer()
    counts = SimulationCountsSerializer()
    context = SimulationContextSerializer()
    cfg = SimulationConfigSerializer(required=False, allow_null=True)
    snapshot_ts = serializers.CharField(required=False, allow_null=True)
class BenchmarkRequestSerializer(serializers.Serializer):
    application_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )

    algorithms = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[
                "dcsga",
                "dtosc",
                "to_v2i",
                "to_wo_c",
                "to_wo_r",
            ]
        ),
        required=False,
        allow_empty=False,
    )

    seeds = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=False,
        default=[1],
    )

    tmax = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        default=10,
    )

class PaperExperimentRequestSerializer(serializers.Serializer):
    figure = serializers.ChoiceField(
        choices=[
            "figure_6",
            "figure_7",
            "figure_8",
            "figure_9",
            "figure_10",
            "all",
            "*",
        ]
    )
    repetitions = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
    )
    seed_start = serializers.IntegerField(
        required=False,
        default=1,
    )
    tmax = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        default=15,
    )
    population_size = serializers.IntegerField(
        required=False,
        min_value=2,
        max_value=500,
        allow_null=True,
    )