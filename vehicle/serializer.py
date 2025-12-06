from rest_framework import serializers
from .models import Vehicle

class VehicleSer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = '__all__'