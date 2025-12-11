from django.db import models

class Vehicle(models.Model):
    plate = models.CharField(max_length=100,unique=True)
    path = models.JSONField(default=list)
    x_coord = models.FloatField()
    y_coord = models.FloatField()
    height = models.FloatField()
    speed = models.FloatField()
    cpu_capacity = models.BigIntegerField()
    cache_capacity = models.BigIntegerField()
    is_mission = models.BooleanField(default=False)
   