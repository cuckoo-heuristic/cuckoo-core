from django.urls import path
from .views import (TaskListAPI, TaskDetailAPI, TaskTypeListAPI, TaskTypeDetailAPI, ApplicationListAPI, ApplicationDetailAPI,
    ApplicationTypeListAPI, ApplicationTypeDetailAPI, TaskExeListAPI, TaskExeDetailAPI,TaskDepListAPI, TaskDepDetailAPI,)

urlpatterns = [
    path('task/', TaskListAPI.as_view(), name='task'),
    path('task/<int:pk>/', TaskDetailAPI.as_view(), name='task-detail'),

    path('task-types/', TaskTypeListAPI.as_view(), name='task-type'),
    path('task-types/<int:pk>/', TaskTypeDetailAPI.as_view(), name='task-type-detail'),

    path('application/', ApplicationListAPI.as_view(), name='application'),
    path('application/<int:pk>/', ApplicationDetailAPI.as_view(), name='application-detail'),

    path('application-type/', ApplicationTypeListAPI.as_view(), name='application-type'),
    path('application-type/<int:pk>/', ApplicationTypeDetailAPI.as_view(), name='application-type-detail'),

    path('task-execution/', TaskExeListAPI.as_view(), name='task-executions'),
    path('task-execution/<int:pk>/', TaskExeDetailAPI.as_view(), name='task-executions-detail'),

    path('task-dependency/', TaskDepListAPI.as_view(), name='task-dependency'),
    path('task-dependency/<int:pk>/', TaskDepDetailAPI.as_view(), name='task-dependency-detail'),

]
