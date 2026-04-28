from rest_framework import serializers
from .models import Resource

class ResourceSer(serializers.ModelSerializer):
    cpu_capacity = serializers.IntegerField(read_only=True)
    cache_capacity = serializers.IntegerField(read_only=True)

    class Meta:
        model = Resource
        exclude = ["initial_snapshot"]

    def validate(self, attrs):
        sp = attrs.get("sp_id") or getattr(self.instance, "sp_id", None)
        if sp is None:
            raise serializers.ValidationError({"sp_id": "This field is required."})

        cpu_capacity = sp.rsu_id.cpu_capacity if sp.rsu_id else sp.vehicle_id.cpu_capacity
        cache_capacity = sp.rsu_id.cache_capacity if sp.rsu_id else sp.vehicle_id.cache_capacity

        cpu_used = attrs.get("cpu_used", getattr(self.instance, "cpu_used", None))
        cache_used = attrs.get("cache_used", getattr(self.instance, "cache_used", None))

        if cpu_used is not None and cpu_used > cpu_capacity:
            raise serializers.ValidationError({"cpu_used": "cpu_used cannot exceed cpu_capacity."})

        if cache_used is not None and cache_used > cache_capacity:
            raise serializers.ValidationError({"cache_used": "cache_used cannot exceed cache_capacity."})

        return attrs


