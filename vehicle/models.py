from django.db import models
from rsu.models import RSU

class Vehicle(models.Model):
    name = models.CharField(max_length=100)
    lat = models.FloatField()
    lon = models.FloatField()
    path = models.JSONField(default=list)
    height = models.FloatField()
    speed = models.FloatField()
    cpu_capacity = models.IntegerField()
    cache_capacity = models.IntegerField()
    is_mission = models.BooleanField(default=True)
   