from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView
)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/docs/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    path('run/', include('run.urls')),
    path("parameter/", include("parameter.urls")),
    path("application/", include("application.urls")),
    path("cache/", include("cache.urls")),
    path("dag/", include("dag.urls")),
    path("execution/", include("execution.urls")),
    path("object/", include("object.urls")),
    path("resource/", include("resource.urls")),
    path("state/", include("state.urls")),
]
