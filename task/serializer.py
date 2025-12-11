from rest_framework import serializers
from .models import Task, TaskType, Application, ApplicationType, TaskExecution, TaskDependency,State

class TaskSer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = '__all__'

class TaskTypeSer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = '__all__'

class ApplicationTypeSer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationType
        fields = '__all__'

class ApplicationSer(serializers.ModelSerializer):
    deadline = serializers.ReadOnlyField() 
    is_progress = serializers.BooleanField(read_only=True)
    class Meta:
        model = Application
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["is_progress"] = instance.end_at is None
        return data


class TaskExecutionSer(serializers.ModelSerializer):
    class Meta:
        model = TaskExecution
        fields = '__all__'

class TaskDependencySer(serializers.ModelSerializer):
    class Meta:
        model = TaskDependency
        fields = '__all__'

class StateSer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = '__all__'