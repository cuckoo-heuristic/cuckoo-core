from rest_framework import serializers
from .models import Resource

class ResourceSer(serializers.ModelSerializer):
    cpu_capacity = serializers.IntegerField(read_only=True)
    cache_capacity = serializers.IntegerField(read_only=True)
    cpu_used = serializers.IntegerField(
        min_value=0,
        help_text="Cumulative executed CPU cycles (not CPU frequency/utilization).",
    )

    class Meta:
        model = Resource
        exclude = ["initial_snapshot"]

    def validate(self, attrs):
        sp = attrs.get("sp_id") or getattr(self.instance, "sp_id", None)
        if sp is None:
            raise serializers.ValidationError({"sp_id": "This field is required."})

        cache_capacity = sp.rsu_id.cache_capacity if sp.rsu_id else sp.vehicle_id.cache_capacity

        cache_used = attrs.get("cache_used", getattr(self.instance, "cache_used", None))

        if cache_used is not None and cache_used > cache_capacity:
            raise serializers.ValidationError({"cache_used": "cache_used cannot exceed cache_capacity."})

        return attrs


