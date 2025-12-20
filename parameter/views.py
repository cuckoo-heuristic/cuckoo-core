from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction

from .models import Parameter
from .serializer import (
    ParameterReadSerializer,
    ParameterPatchSerializer,
)


DEFAULTS = [
        ("B", 20, "float", "MHz"),
        ("delta2", -114, "float", "dBm"),
        ("Y_v2i", 3.76, "float", ""),
        ("Y_v2v", 1.8, "float", ""),
        ("sigma_v2i", 8, "float", "dB"),
        ("sigma_v2v", 3, "float", "dB"),
        ("h_rsu", 5, "float", "m"),
        ("h_vehicle", 1.5, "float", "m"),
        ("G_rsu", 8, "float", "dBi"),
        ("G_vehicle", 3, "float", "dBi"),
        ("levy_lambda", 1.5, "float", "-"),
        ("p_discard_init", 0.2, "float", "-"),
        ("S", 50, "float", "-"),
        ("k", 1e-25, "float", "-"),
        ("alpha_n", 0.5, "float", "-"),
        ("cell_radius_rsu", 250, "float", "m"),
        ("rec_noi_rsu", 5, "float", "dB"),
        ("rec_noi_vehicle", 9, "float", "dB"),
        ("pmax_vehicle", 23, "float", "dBm"),
        ("pmax_rsu", 30, "float", "dBm"),
        ("fmax_vehicle", 3, "float", "GHz"),
        ("fmax_rsu", 50, "float", "GHz"),
        ("simulate_time", 120, "int", "s"),
        ("taking_task_time", 30, "int", "s"),
]


class ParameterListAPI(generics.ListAPIView):
    queryset = Parameter.objects.all().order_by("key")
    serializer_class = ParameterReadSerializer


class ParameterDetailAPI(generics.RetrieveUpdateAPIView):
    queryset = Parameter.objects.all()
    lookup_field = "key"
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return ParameterPatchSerializer
        return ParameterReadSerializer


class ParameterResetAPI(APIView):

    http_method_names = ["post", "head", "options"]

    def post(self, request):
        wanted_keys = {key for key, _, _, _ in DEFAULTS}

        with transaction.atomic():
            Parameter.objects.exclude(key__in=wanted_keys).delete()
            for key, value, value_type, unit in DEFAULTS:
                Parameter.objects.update_or_create(
                    key=key,
                    defaults={"value": value, "unit": unit, "value_type": value_type},
                )

        return Response({"detail": "Parameters reset to default values."})

