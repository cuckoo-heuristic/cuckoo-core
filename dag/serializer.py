from rest_framework import serializers
from .models import Task, TaskType, ApplicationType, TaskDependency

class TaskSer(serializers.ModelSerializer):
    class Meta:
        model = Task
        exclude = ["initial_snapshot"]


class TaskTypeSer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        exclude = ["initial_snapshot"]


class ApplicationTypeSer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationType
        exclude = ["initial_snapshot"]


class TaskDependencySer(serializers.ModelSerializer):
    class Meta:
        model = TaskDependency
        exclude = ["initial_snapshot"]
