from django.urls import re_path
from .consumers import VehicleStatusConsumer

websocket_urlpatterns = [
    re_path(r"ws/vehicle-status/(?P<vehicle_id>\d+)/$", VehicleStatusConsumer.as_asgi()),
]