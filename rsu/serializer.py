from rest_framework import serializers
from .models import RSU, RSUVehicle, ServiceProvider

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



