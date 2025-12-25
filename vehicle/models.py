from django.db import models

class Vehicle(models.Model):
    plate = models.CharField(max_length=100, unique=True)
    path = models.JSONField(default=list)
    x_coord = models.FloatField(default=0)
    y_coord = models.FloatField(default=0)
    speed = models.FloatField(default=0)
    length = models.FloatField(default=0)
    cpu_capacity = models.BigIntegerField()
    cache_capacity = models.BigIntegerField()
    is_mission = models.BooleanField(default=False)
    initial_snapshot = models.JSONField(null=True, blank=True)
