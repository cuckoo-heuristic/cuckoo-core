from django.urls import path
from .views import RSUListAPIView,RSUDetailAPIView

urlpatterns = [
    path('', RSUListAPIView.as_view(), name='rsu'),
    path('<int:pk>/', RSUDetailAPIView.as_view(), name='rsu-detail'),
]
