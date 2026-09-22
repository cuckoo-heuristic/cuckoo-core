from django.urls import path
from .views import ( ApplicationListAPI, ApplicationDetailAPI, ApplicationResetAPI, AppProgressAPI)

urlpatterns = [
    path('application/', ApplicationListAPI.as_view(), name='application'),
    path('application/<int:pk>/', ApplicationDetailAPI.as_view(), name='application-detail'),
    path('application/<int:pk>/reset/', ApplicationResetAPI.as_view(), name='application-reset'),
    path('application/progress/<int:pk>/', AppProgressAPI.as_view(), name='application_progress')

    ]