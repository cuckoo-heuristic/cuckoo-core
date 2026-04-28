from rest_framework import serializers
from .models import Vehicle, RSU, RSUVehicle, ServiceProvider
from state.models import State
from execution.models import TaskExecution
from rest_framework import serializers

class RSUSer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = RSU
        exclude = ["initial_snapshot"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        active_conn = RSUVehicle.objects.filter(
            rsu_id=instance.id,
            vehicle_id__isnull=False,
            end_time__isnull=True
        ).exists()
        data["is_active"] = active_conn
        return data


class RSUVehicleSer(serializers.ModelSerializer):
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = RSUVehicle
        exclude = ["initial_snapshot"]
        read_only_fields = ["connect_time"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["is_current"] = instance.end_time is None
        return data


class ServiceProviderSer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProvider
        exclude = ["initial_snapshot"]

class VehicleSer(serializers.ModelSerializer):
    is_mission = serializers.BooleanField(read_only=True)

    def validate_path(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Path must be a list.")

        for point in value:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or not isinstance(point[0], (float, int))
                or not isinstance(point[1], (float, int))
            ):
                raise serializers.ValidationError("Each path point must be like: [lon, lat]")
        return value

    class Meta:
        model = Vehicle
        exclude = ["initial_snapshot"]
        read_only_fields = ["is_mission", "length", "speed","x_coord","y_coord"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        mission_running = State.objects.filter(
            from_vehicle_id=instance.id,
            task_execution_id__in=TaskExecution.objects.filter(end_time__isnull=True).values("id"),
        ).exists()
        data["is_mission"] = mission_running
        return data
