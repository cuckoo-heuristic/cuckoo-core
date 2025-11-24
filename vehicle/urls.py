from django.urls import path
from .views import vehicleListAPIView,vehicleDetailAPIView

urlpatterns = [
    path('', vehicleListAPIView.as_view(), name='vehicle'),
    path('<int:pk>/', vehicleDetailAPIView.as_view(), name='vehicle-detail'),
]
