from django.db import models


class Parameter(models.Model):
    class ValueType(models.TextChoices):
        INT = "int"
        FLOAT = "float"
        BOOL = "bool"
        STR = "str"
        JSON = "json"
    key = models.CharField(max_length=64, unique=True)
    value = models.JSONField()
    unit = models.CharField(max_length=16, blank=True, default="")
    value_type = models.CharField(max_length=16, choices=ValueType.choices, default=ValueType.JSON)
