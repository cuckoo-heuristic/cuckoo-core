from rest_framework import serializers
from run.simulation.runtime_status import application_is_active
from .models import  Application

class ApplicationSer(serializers.ModelSerializer):
    deadline = serializers.IntegerField(source='application_type_id.deadline', read_only=True)
    is_progress = serializers.BooleanField(read_only=True)

    class Meta:
        model = Application
        exclude = ["initial_snapshot"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["is_progress"] = application_is_active(instance)
        return data
