from django.urls import path
from .views import start_simulation

urlpatterns = [
    path("start-simulation/", start_simulation, name="start_simulation"),
]
