from rest_framework import serializers
from .models import RSU, RSUVehicle, ServiceProvider,Resource, cache

class RSUSer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)
    class Meta:
        model = RSU
        fields = "__all__"
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
        fields = '__all__'
        read_only_fields = ["connect_time"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["is_current"] = instance.end_time is None
        return data
        

class ServiceProviderSer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProvider
        fields = '__all__'

class ResourceSer(serializers.ModelSerializer):
    cpu_capacity = serializers.ReadOnlyField()
    cache_capacity = serializers.ReadOnlyField()

    class Meta:
        model = Resource
        fields =  '__all__'
    
    def validate(self, attrs):
        sp = attrs["sp_id"]
        cpu_capacity = sp.rsu_id.cpu_capacity if sp.rsu_id else sp.vehicle_id.cpu_capacity
        cache_capacity = sp.rsu_id.cache_capacity if sp.rsu_id else sp.vehicle_id.cache_capacity
        cpu_used = attrs.get("cpu_used")
        cache_used = attrs.get("cache_used")
        if cpu_used > cpu_capacity:
            raise serializers.ValidationError({
                "cpu_used": f"CPU used ({cpu_used}) cannot exceed capacity ({cpu_capacity})."
            })

        if cache_used > cache_capacity:
            raise serializers.ValidationError({
                "cache_used": f"Cache used ({cache_used}) cannot exceed capacity ({cache_capacity})."
            })

        return attrs

class CacheSer(serializers.ModelSerializer):
    class Meta:
        model = cache
        fields = '__all__'