from rest_framework import serializers
from .models import RSU, Vehicle, Task


class RSUSerializer(serializers.ModelSerializer):
    class Meta:
        model = RSU
        fields = '__all__'


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = '__all__'


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = '__all__'
