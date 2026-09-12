from django.urls import path
from .views import (
    StateListAPI, StateDetailAPI, StateResetAPI,

)

urlpatterns = [

    path('state/', StateListAPI.as_view(), name='state'),
    path('state/<int:pk>/', StateDetailAPI.as_view(), name='state-detail'),
    path('state/<int:pk>/reset/', StateResetAPI.as_view(), name='state-reset'),
]
