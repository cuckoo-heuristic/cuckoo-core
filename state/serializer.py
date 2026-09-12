from rest_framework import serializers
from .models import State

class StateSer(serializers.ModelSerializer):
    class Meta:
        model = State
        exclude = ["initial_snapshot"]
