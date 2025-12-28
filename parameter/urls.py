from django.urls import path
from .views import ParameterListAPI, ParameterDetailAPI,ParameterResetAPI

urlpatterns = [
    path("", ParameterListAPI.as_view(), name="param-list"),
    path("reset/", ParameterResetAPI.as_view(), name="params-reset"),
    path("<str:key>/", ParameterDetailAPI.as_view(), name="params-detail"),
]
