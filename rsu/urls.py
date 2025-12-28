from django.urls import path
from .views import (
    RSUListAPI, RSUDetailAPI, RSUResetAPI,
    RSUVehicleListAPI, RSUVehicleDetailAPI, RSUVehicleResetAPI,
    ServiceProviderListAPI, ServiceProviderDetailAPI, ServiceProviderResetAPI,
    ResourceListAPI, ResourceDetailAPI, ResourceResetAPI,
    CacheListAPI, CacheDetailAPI, CacheResetAPI,
    RSUActiveAPI, RSUVIsCurrentAPI,
)

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

    path("resource/", ResourceListAPI.as_view()),
    path("resource/<int:pk>/", ResourceDetailAPI.as_view()),
    path("resource/<int:pk>/reset/", ResourceResetAPI.as_view()),

    path("cache/", CacheListAPI.as_view()),
    path("cache/<int:pk>/", CacheDetailAPI.as_view()),
    path("cache/<int:pk>/reset/", CacheResetAPI.as_view()),
]
