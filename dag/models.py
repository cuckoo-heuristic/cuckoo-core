from django.db import models

class TaskType(models.Model):
    name = models.TextField(max_length=20, unique=True)
    description = models.TextField(max_length=200, blank=True, null=True)
    size = models.BigIntegerField()
    initial_snapshot = models.JSONField(null=True, blank=True)


class ApplicationType(models.Model):
    name = models.TextField(max_length=100)
    deadline = models.IntegerField()
    description = models.TextField(max_length=200)
    initial_snapshot = models.JSONField(null=True, blank=True)


class Task(models.Model):
    index = models.TextField(max_length=200)
    application_type_id = models.ForeignKey(ApplicationType, on_delete=models.CASCADE, null=True, blank=True)
    task_type_id = models.ForeignKey(TaskType, on_delete=models.CASCADE, null=True, blank=True)
    workload_cycles = models.BigIntegerField()
    initial_snapshot = models.JSONField(null=True, blank=True)

class TaskDependency(models.Model):
    parent_task_id = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="parents", null=True, blank=True)
    child_task_id = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="children", null=True, blank=True)
    initial_snapshot = models.JSONField(null=True, blank=True) 
