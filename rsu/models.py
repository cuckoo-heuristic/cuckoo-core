from django.db import models

class RSU(models.Model):
    name = models.CharField(max_length=100)
    lat = models.FloatField()
    lon = models.FloatField()
    range = models.FloatField()
    