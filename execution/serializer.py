from rest_framework import serializers
from .models import TaskExecution

class TaskExecutionSer(serializers.ModelSerializer):
    class Meta:
        model = TaskExecution
        exclude = ["initial_snapshot"]


