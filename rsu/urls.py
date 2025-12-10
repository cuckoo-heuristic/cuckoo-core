from django.urls import path
from .views import RSUListAPI,RSUDetailAPI,SPListAPI,SPDetailAPI,RVListAPI,RVDetailAPI,ResourceListAPI,ResourceDetailAPI,CacheListAPI,CacheDetailAPI,RSUActiveAPI,RSUVIsCurrentAPI
urlpatterns = [
    path('rsu/', RSUListAPI.as_view(), name='rsu'),
    path('rsu/<int:pk>/', RSUDetailAPI.as_view(), name='rsu-detail'),

    path('rsu/active/<int:pk>/', RSUActiveAPI.as_view(), name='rsu'),

    path('servicepro/', SPListAPI.as_view(), name='service_provider'),
    path('servicepro/<int:pk>/', SPDetailAPI.as_view(), name='service_provider-detail'),
    
    path('rsuvehicle/', RVListAPI.as_view(), name='rsu_vehicle'),
    path('rsuvehicle/<int:pk>/', RVDetailAPI.as_view(), name='rsu_vehicle-detail'),

    path('rsuvehicle/current/<int:pk>/', RSUVIsCurrentAPI.as_view(), name='rsu_vehicle'),

    path('resource/', ResourceListAPI.as_view(), name='resource'),
    path('resource/<int:pk>/', ResourceDetailAPI.as_view(), name='resource-detail'),
    
    path('cache/', CacheListAPI.as_view(), name='cache'),
    path('cache/<int:pk>/', CacheDetailAPI.as_view(), name='cache-detail'),

]
