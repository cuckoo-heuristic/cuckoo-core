from django.db import models
from object.models import ServiceProvider
from dag.models import TaskType

class cache(models.Model):
    sp_id = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE, null=True, blank=True)
    task_type_id = models.ForeignKey(TaskType, on_delete=models.CASCADE)
    initial_snapshot = models.JSONField(null=True, blank=True)
