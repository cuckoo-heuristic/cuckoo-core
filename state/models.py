from django.db import models
from object.models import Vehicle
from execution.models import TaskExecution
from object.models import RSU

class State(models.Model):
    time_step = models.BigIntegerField()
    task_execution_id = models.ForeignKey(TaskExecution, on_delete=models.CASCADE, null=True, blank=True)
    from_vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="From", null=True, blank=True)
    to_vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="to", null=True, blank=True)
    to_rsu_id = models.ForeignKey(RSU, on_delete=models.CASCADE, null=True, blank=True)
    gain = models.FloatField()
    distance = models.FloatField()
    rate = models.FloatField()
    initial_snapshot = models.JSONField(null=True, blank=True)
