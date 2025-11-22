from django.urls import path
from .views import RSUListAPIView

urlpatterns = [
    path('rsu/', RSUListAPIView.as_view(), name='rsu'),
]
