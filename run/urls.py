from django.urls import path
from .views import AppRunSimulationAPIView

urlpatterns = [
    path('app-run/', AppRunSimulationAPIView.as_view(), name='app-run'),
]