from django.db import models
from vehicle.models import Vehicle
from django.utils import timezone

class TaskType(models.Model):
    name = models.TextField(max_length=20,unique=True)
    description = models.TextField(max_length=200,blank=True,null=True)
    size = models.BigIntegerField()

class ApplicationType(models.Model):
    name = models.TextField(max_length=100)
    deadline = models.IntegerField()
    description = models.TextField(max_length=200)

class Application(models.Model):
    vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True)
    application_type_id = models.ForeignKey(ApplicationType , on_delete=models.CASCADE, null=True, blank=True)
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(null=True, blank=True)
    is_progress = models.BooleanField(default=True)
    @property
    def deadline(self):
        if self.application_type_id:
            return self.application_type_id.deadline

class Task(models.Model):
    index = models.TextField(max_length=200)
    application_id = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True)
    task_type_id = models.ForeignKey(TaskType, on_delete=models.CASCADE, null=True, blank=True)
    workload_cycles = models.BigIntegerField()

class TaskExecution(models.Model):
    application_id = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True)
    provider = models.ForeignKey("rsu.ServiceProvider", on_delete=models.CASCADE)
    task_id = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    exec_time = models.IntegerField(null=True, blank=True)
    energy = models.FloatField(default=0)

class TaskDependency(models.Model):
    parent_task_id = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="parents", null=True, blank=True)
    child_task_id = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="children", null=True, blank=True)


