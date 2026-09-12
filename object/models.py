from django.db import models
from cuckoo_library.model import transmission
from django.utils import timezone

class RSU(models.Model):
    name = models.CharField(max_length=100, unique=True)
    x_coord = models.FloatField()
    y_coord = models.FloatField()
    cpu_capacity = models.BigIntegerField()
    cache_capacity = models.BigIntegerField()
    is_active = models.BooleanField(default=False)
    initial_snapshot = models.JSONField(null=True, blank=True)

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
    def compute_length(self) -> float:
        path = self.path or []
        return float(transmission.path_length_2d(path)) if len(path) >= 2 else 0.0

    def _get_simulate_time_from_params(self) -> int:
        try:
            from parameter.models import Parameter
            p = Parameter.objects.filter(key="simulate_time").first()
            if not p:
                return 0
            return int(float(p.value))
        except Exception:
            return 0

    def compute_speed(self, simulate_time: int) -> float:
        if simulate_time <= 0:
            return 0.0
        length = self.length if self.length is not None else self.compute_length()
        return float((transmission.speed_vehicle(length, simulate_time))*3.6)

    def refresh_motion(self) -> None:
        self.length = self.compute_length()
        simulate_time = self._get_simulate_time_from_params()
        self.speed = self.compute_speed(simulate_time)
    def save(self, *args, **kwargs):
        self.refresh_motion()
        super().save(*args, **kwargs)


class RSUVehicle(models.Model):
    rsu_id = models.ForeignKey(RSU, on_delete=models.CASCADE, null=True, blank=True)
    vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    connect_time = models.FloatField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    initial_snapshot = models.JSONField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.connect_time = delta.total_seconds()
        else:
            self.connect_time = None
        super().save(*args, **kwargs)


class ServiceProvider(models.Model):
    TYPE_CHOICES = (
        ("rsu", "RSU"),
        ("vehicle", "Vehicle"),
    )
    rsu_id = models.ForeignKey(RSU, on_delete=models.CASCADE, null=True, blank=True)
    vehicle_id = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    initial_snapshot = models.JSONField(null=True, blank=True)

