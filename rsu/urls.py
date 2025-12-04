from django.urls import path
from .views import RSUListAPI,RSUDetailAPI,SPListAPI,SPDetailAPI,RVListAPI,RVDetailAPI

urlpatterns = [
    path('rsu', RSUListAPI.as_view(), name='rsu'),
    path('rsu/<int:pk>/', RSUDetailAPI.as_view(), name='rsu-detail'),

    path('rsuvehicle/', SPListAPI.as_view(), name='service_provider'),
    path('rsuvehicle/<int:pk>/', RSUDetailAPI.as_view(), name='service_provider-detail'),
    
    path('servicepro/', RVListAPI.as_view(), name='rsu_vehicle'),
    path('servicepro/<int:pk>/', RVDetailAPI.as_view(), name='rsu_vehicle-detail'),
]
