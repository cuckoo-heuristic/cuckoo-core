from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Parameter
from .serializer import (
    ParameterReadSerializer,
    ParameterPatchSerializer,
)


class ParameterListAPI(generics.ListAPIView):
    serializer_class = ParameterReadSerializer

    def get_queryset(self):
        return Parameter.objects.all().order_by("key")


class ParameterDetailAPI(generics.RetrieveUpdateAPIView):
    lookup_field = "key"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return Parameter.objects.all()

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return ParameterPatchSerializer
        return ParameterReadSerializer


class ParameterResetAPI(APIView):
    http_method_names = ["post", "head", "options"]

    def post(self, request):
        return Response(
            {
                "detail": (
                    "Parameter defaults are managed by database migrations. "
                    "Reset is disabled."
                )
            },
            status=status.HTTP_409_CONFLICT,
        )