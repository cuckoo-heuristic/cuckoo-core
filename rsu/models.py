from django.db import models
from vehicle.models import Vehicle
from django.utils import timezone


class RSU(models.Model):
    name = models.CharField(max_length=100, unique=True)
    x_coord = models.FloatField()
    y_coord = models.FloatField()
    height = models.FloatField()
    cpu_capacity = models.BigIntegerField()
    cache_capacity = models.BigIntegerField()
    is_active = models.BooleanField(default=False)

class RSUVehicle(models.Model):
    rsu_id = models.ForeignKey(RSU, on_delete=models.CASCADE, null=True, blank=True) 
    vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True) 
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    connect_time = models.FloatField(null=True, blank=True)
    is_current = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
         if self.start_time and self.end_time:
             delta = self.end_time - self.start_time
             self.connect_time = delta.total_seconds()

         super().save(*args, **kwargs)

class ServiceProvider(models.Model):
    TYPE_CHOICES = (
        ("rsu", "RSU"),
        ("vehicle", "Vehicle"),
    )
    rsu_id = models.ForeignKey(RSU, on_delete=models.CASCADE, null=True, blank=True)
    vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True) 
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)

class Resource(models.Model):
    sp_id = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE)
    # cpu_capacity = models.BigIntegerField()
    # cache_capacity = models.IntegerField(default=0)
    cpu_used = models.BigIntegerField()
    cache_used = models.BigIntegerField()
    @property
    def cpu_capacity(self):
        if self.sp_id.rsu_id:
            return self.sp_id.rsu_id.cpu_capacity
        return self.sp_id.vehicle_id.cpu_capacity

    @property
    def cache_capacity(self):
        if self.sp_id.rsu_id:
            return self.sp_id.rsu_id.cache_capacity
        return self.sp_id.vehicle_id.cache_capacity
    
class cache(models.Model):
    sp_id = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE, null=True, blank=True)
    task_type_id = models.ForeignKey("task.TaskType", on_delete=models.CASCADE)
