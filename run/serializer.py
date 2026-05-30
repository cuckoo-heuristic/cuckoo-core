from rest_framework import serializers


class StartSimulationSerializer(serializers.Serializer):
    a1 = serializers.IntegerField(default=1)
    a2 = serializers.IntegerField(default=1)
    a3 = serializers.IntegerField(default=1)


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
