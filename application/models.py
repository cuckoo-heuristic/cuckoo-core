from django.db import models
from django.utils import timezone
from object.models import Vehicle
from dag.models import ApplicationType

class Application(models.Model):
    vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True)
    application_type_id = models.ForeignKey(ApplicationType, on_delete=models.CASCADE, null=True, blank=True)
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(null=True, blank=True)
    is_progress = models.BooleanField(default=False)
    initial_snapshot = models.JSONField(null=True, blank=True)