from rest_framework import serializers
from .models import Vehicle
from task.models import TaskExecution, State

class VehicleSer(serializers.ModelSerializer):
    def validate_path(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Path must be a list.")

        for point in value:
            if (not isinstance(point, list) or len(point) != 2 or not isinstance(point[0], (float, int)) or
                not isinstance(point[1], (float, int))):
                raise serializers.ValidationError(
                    "Each path point must be like: [lon, lat]"
                )

        return value
    class Meta:
        model = Vehicle
        fields = '__all__'
        read_only_fields = ["is_mission"]
    def to_representation(self, instance):
            data = super().to_representation(instance)
            mission_running = State.objects.filter(
                from_vehicle_id=instance.id,
            ).filter(
                task_execution_id__in=TaskExecution.objects.filter(end_time__isnull=True).values("id")
            ).exists()
            data["is_mission"] = mission_running
            return data