from django.urls import path
from .views import VehicleListAPIView,VehicleDetailAPIView

urlpatterns = [
    path('', VehicleListAPIView.as_view(), name='vehicle'),
    path('<int:pk>/', VehicleDetailAPIView.as_view(), name='vehicle-detail'),
]
