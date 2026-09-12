from django.urls import path
from .views import (
    ResourceListAPI, ResourceDetailAPI, ResourceResetAPI,

)

urlpatterns = [

    path("resource/", ResourceListAPI.as_view()),
    path("resource/<int:pk>/", ResourceDetailAPI.as_view()),
    path("resource/<int:pk>/reset/", ResourceResetAPI.as_view()),

]
