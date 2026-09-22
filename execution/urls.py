from django.urls import path
from .views import (
    TaskExeListAPI, TaskExeDetailAPI, TaskExeResetAPI,
)

urlpatterns = [
    path('task-execution/', TaskExeListAPI.as_view(), name='task-executions'),
    path('task-execution/<int:pk>/', TaskExeDetailAPI.as_view(), name='task-executions-detail'),
    path('task-execution/<int:pk>/reset/', TaskExeResetAPI.as_view(), name='task-executions-reset'),
]
