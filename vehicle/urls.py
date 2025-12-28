from django.urls import path
from .views import VehicleListAPIView, VehicleDetailAPIView, VehicleMissionAPI, VehicleResetAPI

urlpatterns = [
    path('', VehicleListAPIView.as_view(), name='vehicle'),
    path('mission/<int:pk>/', VehicleMissionAPI.as_view(), name='vehicle-mission'),

    path('<int:pk>/', VehicleDetailAPIView.as_view(), name='vehicle-detail'),
    path('<int:pk>/reset/', VehicleResetAPI.as_view(), name='vehicle-reset'),  # ✅
]
