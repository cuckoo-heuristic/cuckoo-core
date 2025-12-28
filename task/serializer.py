from rest_framework import serializers
from .models import Task, TaskType, Application, ApplicationType, TaskExecution, TaskDependency, State


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


class ApplicationSer(serializers.ModelSerializer):
    deadline = serializers.IntegerField(read_only=True)  # ✅ نوع مشخص شد
    is_progress = serializers.BooleanField(read_only=True)

    class Meta:
        model = Application
        exclude = ["initial_snapshot"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["is_progress"] = instance.end_at is None
        return data


class TaskExecutionSer(serializers.ModelSerializer):
    class Meta:
        model = TaskExecution
        exclude = ["initial_snapshot"]


class TaskDependencySer(serializers.ModelSerializer):
    class Meta:
        model = TaskDependency
        exclude = ["initial_snapshot"]


class StateSer(serializers.ModelSerializer):
    class Meta:
        model = State
        exclude = ["initial_snapshot"]
