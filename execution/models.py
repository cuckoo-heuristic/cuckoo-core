from django.db import models
from django.utils import timezone

from application.models import Application
from dag.models import Task
from object.models import ServiceProvider


class TaskExecution(models.Model):
    application_id = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    sp_id = models.ForeignKey(
        ServiceProvider,
        on_delete=models.CASCADE,
    )
    task_id = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    exec_time = models.FloatField(null=True, blank=True)
    energy = models.FloatField(default=0)
    initial_snapshot = models.JSONField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.start_time is not None and self.end_time is not None:
            exec_time = float(
                (self.end_time - self.start_time).total_seconds()
            )
            self.exec_time = max(0.0, exec_time)

        super().save(*args, **kwargs)