from django.urls import path
from . import views 

urlpatterns = [
    path('rsu/', views.test_view, name='rsu_test'),
]