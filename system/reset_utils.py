from __future__ import annotations

from typing import Any, Mapping

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.dateparse import parse_datetime


def _snapshot_values(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    model_values = snapshot.get("model_values")
    if isinstance(model_values, Mapping):
        return model_values
    return snapshot


def restore_initial_snapshot(obj, snapshot: Mapping[str, Any]) -> list[str]:
    """Restore concrete model fields while preserving metadata-only keys."""
    if not isinstance(snapshot, Mapping):
        raise ValueError("initial_snapshot must be a JSON object")

    ignored: list[str] = []
    for field_name, value in _snapshot_values(snapshot).items():
        try:
            model_field = obj._meta.get_field(field_name)
        except FieldDoesNotExist:
            ignored.append(str(field_name))
            continue

        if (
            model_field.primary_key
            or not getattr(model_field, "concrete", False)
            or getattr(model_field, "many_to_many", False)
        ):
            ignored.append(str(field_name))
            continue

        if isinstance(model_field, models.ForeignKey):
            setattr(obj, model_field.attname, value)
            continue

        if isinstance(model_field, models.DateTimeField) and isinstance(value, str):
            parsed = parse_datetime(value)
            if parsed is None:
                raise ValueError(
                    f"Invalid datetime in initial_snapshot for {field_name}: {value!r}"
                )
            setattr(obj, field_name, parsed)
            continue

        setattr(obj, field_name, value)

    obj.save()
    return ignored
