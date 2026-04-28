from rest_framework import serializers
from .models import  Application

class ApplicationSer(serializers.ModelSerializer):
    deadline = serializers.IntegerField(source='application_type.deadline', read_only=True)
    is_progress = serializers.BooleanField(read_only=True)

    class Meta:
        model = Application
        exclude = ["initial_snapshot"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["is_progress"] = instance.end_at is None
        return data
