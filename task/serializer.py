from rest_framework import serializers
from .models import Task, TaskType, Application, ApplicationType, TaskExecution, TaskDependency

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

    class Meta:
        model = Application
        fields = [
            'id',
            'vehicle_id',
            'application_type_id',
            'start_at',
            'end_at',
            'is_progress',
            'deadline',
        ]

class TaskExecutionSer(serializers.ModelSerializer):
    class Meta:
        model = TaskExecution
        fields = '__all__'

class TaskDependencySer(serializers.ModelSerializer):
    class Meta:
        model = TaskDependency
        fields = '__all__'

