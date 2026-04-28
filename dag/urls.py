from django.urls import path
from .views import (
    TaskListAPI, TaskDetailAPI, TaskResetAPI,
    TaskTypeListAPI, TaskTypeDetailAPI, TaskTypeResetAPI,
    ApplicationTypeListAPI, ApplicationTypeDetailAPI, ApplicationTypeResetAPI,
    TaskDepListAPI, TaskDepDetailAPI, TaskDepResetAPI,
)

urlpatterns = [
    path('task/', TaskListAPI.as_view(), name='task'),
    path('task/<int:pk>/', TaskDetailAPI.as_view(), name='task-detail'),
    path('task/<int:pk>/reset/', TaskResetAPI.as_view(), name='task-reset'),

    path('task-types/', TaskTypeListAPI.as_view(), name='task-type'),
    path('task-types/<int:pk>/', TaskTypeDetailAPI.as_view(), name='task-type-detail'),
    path('task-types/<int:pk>/reset/', TaskTypeResetAPI.as_view(), name='task-type-reset'),

    path('application-type/', ApplicationTypeListAPI.as_view(), name='application-type'),
    path('application-type/<int:pk>/', ApplicationTypeDetailAPI.as_view(), name='application-type-detail'),
    path('application-type/<int:pk>/reset/', ApplicationTypeResetAPI.as_view(), name='application-type-reset'),

    path('task-dependency/', TaskDepListAPI.as_view(), name='task-dependency'),
    path('task-dependency/<int:pk>/', TaskDepDetailAPI.as_view(), name='task-dependency-detail'),
    path('task-dependency/<int:pk>/reset/', TaskDepResetAPI.as_view(), name='task-dependency-reset'),

]
