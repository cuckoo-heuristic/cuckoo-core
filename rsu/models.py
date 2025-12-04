from django.db import models
from vehicle.models import Vehicle
from django.utils import timezone

class RSU(models.Model):
    name = models.CharField(max_length=100)
    lat = models.FloatField()
    lon = models.FloatField()
    range = models.FloatField()
    height = models.FloatField()
    cpu_capacity = models.IntegerField()
    cache_capacity = models.IntegerField()
    is_active = models.BooleanField(default=True)

class RSUVehicle(models.Model):
    rsu = models.ForeignKey(RSU, on_delete=models.CASCADE, null=True, blank=True) 
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True) 
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    connect_time = models.FloatField()
    is_current = models.BooleanField(default=True)

class ServiceProvider(models.Model):
    TYPE_CHOICES = (
        ("rsu", "RSU"),
        ("vehicle", "Vehicle"),
    )
    rsu = models.ForeignKey(RSU, on_delete=models.CASCADE, null=True, blank=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True) 
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
