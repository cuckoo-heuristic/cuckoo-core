from django.db import models
from rsu.models import RSU

class Vehicle(models.Model):
    name = models.CharField(max_length=100)

    origin_lat = models.FloatField()
    origin_lon = models.FloatField()

    destination_lat = models.FloatField()
    destination_lon = models.FloatField()

    range = models.FloatField()

    rsu = models.ForeignKey(
        RSU,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
