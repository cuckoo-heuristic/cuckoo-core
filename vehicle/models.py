from django.db import models
from monarch_pylib.models import transmission


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
        return float(transmission.speed_vehicle(length, simulate_time))

    def refresh_motion(self) -> None:
        self.length = self.compute_length()
        simulate_time = self._get_simulate_time_from_params()
        self.speed = self.compute_speed(simulate_time)
    def save(self, *args, **kwargs):
        self.refresh_motion()
        super().save(*args, **kwargs)
