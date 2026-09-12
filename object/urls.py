from django.urls import path
from .views import ( VehicleListAPIView, VehicleDetailAPIView, VehicleMissionAPI, VehicleResetAPI,RSUListAPI, RSUDetailAPI, RSUResetAPI,
    RSUVehicleListAPI, RSUVehicleDetailAPI, RSUVehicleResetAPI,
    ServiceProviderListAPI, ServiceProviderDetailAPI, ServiceProviderResetAPI,
    RSUActiveAPI, RSUVIsCurrentAPI,)

urlpatterns = [
    path("rsu/", RSUListAPI.as_view()),
    path("rsu/<int:pk>/", RSUDetailAPI.as_view()),
    path("rsu/<int:pk>/reset/", RSUResetAPI.as_view()),
    path("rsu/<int:pk>/active/", RSUActiveAPI.as_view()),

    path("rsu-vehicle/", RSUVehicleListAPI.as_view()),
    path("rsu-vehicle/<int:pk>/", RSUVehicleDetailAPI.as_view()),
    path("rsu-vehicle/<int:pk>/reset/", RSUVehicleResetAPI.as_view()),
    path("rsu-vehicle/<int:pk>/is-current/", RSUVIsCurrentAPI.as_view()),

    path("service-provider/", ServiceProviderListAPI.as_view()),
    path("service-provider/<int:pk>/", ServiceProviderDetailAPI.as_view()),
    path("service-provider/<int:pk>/reset/", ServiceProviderResetAPI.as_view()),

    path('vehicle/', VehicleListAPIView.as_view(), name='vehicle'),
    path('vehicle/mission/<int:pk>/', VehicleMissionAPI.as_view(), name='vehicle-mission'),

    path('vehicle/<int:pk>/', VehicleDetailAPIView.as_view(), name='vehicle-detail'),
    path('vehicle/<int:pk>/reset/', VehicleResetAPI.as_view(), name='vehicle-reset'),
]