from django.urls import path
from .views import vehicleListAPIView

urlpatterns = [
    path('vehicle/', vehicleListAPIView.as_view(), name='vehicle'),
]
