from django.db import models
from object.models import ServiceProvider

class Resource(models.Model):
    sp_id = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE)
    cpu_used = models.BigIntegerField()
    cache_used = models.BigIntegerField()
    initial_snapshot = models.JSONField(null=True, blank=True)

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