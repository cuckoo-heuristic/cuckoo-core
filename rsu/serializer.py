from rest_framework import serializers
from .models import RSU, RSUVehicle, ServiceProvider,Resource

class RSUSer(serializers.ModelSerializer):
    class Meta:
        model = RSU
        fields = '__all__'

class RSUVehicleSer(serializers.ModelSerializer):
    class Meta:
        model = RSUVehicle
        fields = '__all__'

class ServiceProviderSer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProvider
        fields = '__all__'

class ResourceSer(serializers.ModelSerializer):
    cpu_capacity = serializers.ReadOnlyField()
    cache_capacity = serializers.ReadOnlyField()

    class Meta:
        model = Resource
        fields = ['id', 'sp_id', 'cpu_used', 'cache_used', 'cpu_capacity', 'cache_capacity']

