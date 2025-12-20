from django.db import models
from vehicle.models import Vehicle
from django.utils import timezone


class TaskType(models.Model):
    name = models.TextField(max_length=20, unique=True)
    description = models.TextField(max_length=200, blank=True, null=True)
    size = models.BigIntegerField()

    initial_snapshot = models.JSONField(null=True, blank=True)  # ✅


class ApplicationType(models.Model):
    name = models.TextField(max_length=100)
    deadline = models.IntegerField()
    description = models.TextField(max_length=200)

    initial_snapshot = models.JSONField(null=True, blank=True)  # ✅


class Application(models.Model):
    vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True)
    application_type_id = models.ForeignKey(ApplicationType, on_delete=models.CASCADE, null=True, blank=True)
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(null=True, blank=True)
    is_progress = models.BooleanField(default=False)

    initial_snapshot = models.JSONField(null=True, blank=True)  # ✅

    @property
    def deadline(self):
        if self.application_type_id:
            return self.application_type_id.deadline


class Task(models.Model):
    index = models.TextField(max_length=200)
    application_type_id = models.ForeignKey(ApplicationType, on_delete=models.CASCADE, null=True, blank=True)
    task_type_id = models.ForeignKey(TaskType, on_delete=models.CASCADE, null=True, blank=True)
    workload_cycles = models.BigIntegerField()

    initial_snapshot = models.JSONField(null=True, blank=True)  # ✅


class TaskExecution(models.Model):
    application_id = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True)
    sp_id = models.ForeignKey("rsu.ServiceProvider", on_delete=models.CASCADE)
    task_id = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    exec_time = models.IntegerField(null=True, blank=True)
    energy = models.FloatField(default=0)

    initial_snapshot = models.JSONField(null=True, blank=True)  # ✅

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.exec_time = delta.total_seconds()
        super().save(*args, **kwargs)


class TaskDependency(models.Model):
    parent_task_id = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="parents", null=True, blank=True)
    child_task_id = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="children", null=True, blank=True)

    initial_snapshot = models.JSONField(null=True, blank=True)  # ✅


class State(models.Model):
    time_step = models.BigIntegerField()
    task_execution_id = models.ForeignKey(TaskExecution, on_delete=models.CASCADE, null=True, blank=True)
    from_vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="From", null=True, blank=True)
    to_vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="to", null=True, blank=True)
    to_rsu_id = models.ForeignKey("rsu.RSU", on_delete=models.CASCADE, null=True, blank=True)
    gain = models.FloatField()
    distance = models.FloatField()
    rate = models.FloatField()

    initial_snapshot = models.JSONField(null=True, blank=True)  # ✅
