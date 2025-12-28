from django.urls import path
from .views import (
    TaskListAPI, TaskDetailAPI, TaskResetAPI,
    TaskTypeListAPI, TaskTypeDetailAPI, TaskTypeResetAPI,
    ApplicationListAPI, ApplicationDetailAPI, ApplicationResetAPI,
    ApplicationTypeListAPI, ApplicationTypeDetailAPI, ApplicationTypeResetAPI,
    TaskExeListAPI, TaskExeDetailAPI, TaskExeResetAPI,
    TaskDepListAPI, TaskDepDetailAPI, TaskDepResetAPI,
    StateListAPI, StateDetailAPI, StateResetAPI,
    AppProgressAPI,
)

urlpatterns = [
    path('task/', TaskListAPI.as_view(), name='task'),
    path('task/<int:pk>/', TaskDetailAPI.as_view(), name='task-detail'),
    path('task/<int:pk>/reset/', TaskResetAPI.as_view(), name='task-reset'),  # ✅

    path('task-types/', TaskTypeListAPI.as_view(), name='task-type'),
    path('task-types/<int:pk>/', TaskTypeDetailAPI.as_view(), name='task-type-detail'),
    path('task-types/<int:pk>/reset/', TaskTypeResetAPI.as_view(), name='task-type-reset'),  # ✅

    path('application/', ApplicationListAPI.as_view(), name='application'),
    path('application/<int:pk>/', ApplicationDetailAPI.as_view(), name='application-detail'),
    path('application/<int:pk>/reset/', ApplicationResetAPI.as_view(), name='application-reset'),  # ✅
    path('application/progress/<int:pk>/', AppProgressAPI.as_view(), name='application_progress'),

    path('application-type/', ApplicationTypeListAPI.as_view(), name='application-type'),
    path('application-type/<int:pk>/', ApplicationTypeDetailAPI.as_view(), name='application-type-detail'),
    path('application-type/<int:pk>/reset/', ApplicationTypeResetAPI.as_view(), name='application-type-reset'),  # ✅

    path('task-execution/', TaskExeListAPI.as_view(), name='task-executions'),
    path('task-execution/<int:pk>/', TaskExeDetailAPI.as_view(), name='task-executions-detail'),
    path('task-execution/<int:pk>/reset/', TaskExeResetAPI.as_view(), name='task-executions-reset'),  # ✅

    path('task-dependency/', TaskDepListAPI.as_view(), name='task-dependency'),
    path('task-dependency/<int:pk>/', TaskDepDetailAPI.as_view(), name='task-dependency-detail'),
    path('task-dependency/<int:pk>/reset/', TaskDepResetAPI.as_view(), name='task-dependency-reset'),  # ✅

    path('state/', StateListAPI.as_view(), name='state'),
    path('state/<int:pk>/', StateDetailAPI.as_view(), name='state-detail'),
    path('state/<int:pk>/reset/', StateResetAPI.as_view(), name='state-reset'),  # ✅
]
