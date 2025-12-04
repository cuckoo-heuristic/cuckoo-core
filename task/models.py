from django.db import models
from vehicle.models import Vehicle
from django.utils import timezone
from rsu.models import ServiceProvider

class TaskType(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    size = models.IntegerField()

class ApplicationType(models.Model):
    name = models.CharField(max_length=100)
    deadline = models.FloatField()
    description = models.TextField()

class Application(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True)
    app_type = models.ForeignKey(ApplicationType , on_delete=models.CASCADE, null=True, blank=True)
    deadline = models.FloatField()
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    is_progress = models.BooleanField(default=True)

class Task(models.Model):
    index = models.IntegerField()
    application = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True)
    task_type = models.ForeignKey(TaskType, on_delete=models.CASCADE, null=True, blank=True)
    workload_cycles = models.IntegerField()

class TaskExecution(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True)
    sp = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE, null=True, blank=True)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    exec_time = models.FloatField(default=0)
    energy = models.FloatField(default=0)

class TaskDependency(models.Model):
    parent_task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="parents", null=True, blank=True)
    child_task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="children", null=True, blank=True)

class cache(models.Model):
    sp = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE, null=True, blank=True)
    task_type = models.ForeignKey(TaskType, on_delete=models.CASCADE, null=True, blank=True)

