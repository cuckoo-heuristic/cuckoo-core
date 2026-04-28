from django.urls import path
from .views import CacheListAPI, CacheDetailAPI, CacheResetAPI

urlpatterns = [
    path("cache/", CacheListAPI.as_view()),
    path("cache/<int:pk>/", CacheDetailAPI.as_view()),
    path("cache/<int:pk>/reset/", CacheResetAPI.as_view()),
]
