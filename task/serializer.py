from rest_framework import serializers
from .models import Task, TaskType, Application, ApplicationType, TaskExecution, TaskDependency, cache

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
    class Meta:
        model = Application
        fields = '__all__'   

class TaskExecutionSer(serializers.ModelSerializer):
    class Meta:
        model = TaskExecution
        fields = '__all__'

class TaskDependencySer(serializers.ModelSerializer):
    class Meta:
        model = TaskDependency
        fields = '__all__'

class CacheSer(serializers.ModelSerializer):
    class Meta:
        model = cache
        fields = '__all__'