from django.urls import path
from .views import VehicleListAPIView,VehicleDetailAPIView,VehicleMissionAPI

urlpatterns = [
    path('', VehicleListAPIView.as_view(), name='vehicle'),
    path('<int:pk>/', VehicleDetailAPIView.as_view(), name='vehicle-detail'),

    path('mission/<int:pk>/', VehicleMissionAPI.as_view(), name='vehicle-detail'),
]
