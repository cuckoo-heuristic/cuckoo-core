from __future__ import annotations

from django.db.models import Q


def _logical_now():
    from run.simulation.service import get_logical_now

    return get_logical_now()


def application_is_active(application) -> bool:
    now = _logical_now()
    if now is None:
        return bool(application.is_progress)

    if application.start_at is not None and now < application.start_at:
        return False

    if application.end_at is not None:
        return bool(now < application.end_at)

    return bool(application.is_progress)


def vehicle_is_mission(vehicle_id: int) -> bool:
    from application.models import Application

    now = _logical_now()
    queryset = Application.objects.filter(vehicle_id_id=int(vehicle_id))

    if now is None:
        return queryset.filter(is_progress=True).exists()

    return (
        queryset.filter(start_at__lte=now)
        .filter(Q(end_at__gt=now) | Q(end_at__isnull=True, is_progress=True))
        .exists()
    )
