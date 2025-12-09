from rest_framework import serializers
from .models import Vehicle

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