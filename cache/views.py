from django.forms.models import model_to_dict
from django.utils.timezone import is_aware
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from django.db import models
from .models import  cache
from .serializer import CacheSer
from system.reset_utils import restore_initial_snapshot

class ResetResponseSer(serializers.Serializer):
    detail = serializers.CharField()

def _json_safe(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def make_snapshot(obj):
    data = model_to_dict(obj)
    data.pop("id", None)
    data.pop("initial_snapshot", None)
    for k, v in list(data.items()):
        if isinstance(v, list):
            data[k] = [_json_safe(x) for x in v]
        else:
            data[k] = _json_safe(v)

    return data


class BaseListAPI(APIView):
    model = None
    serializer = None 

    def get(self, request):
        items = self.model.objects.all()
        ser = self.serializer(items, many=True)
        return Response(ser.data)

    def post(self, request):
        ser = self.serializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        obj = ser.save()

        if hasattr(obj, "initial_snapshot") and not obj.initial_snapshot:
            obj.initial_snapshot = make_snapshot(obj)
            obj.save(update_fields=["initial_snapshot"])

        return Response(self.serializer(obj).data, status=status.HTTP_201_CREATED)


class BaseDetailAPI(APIView):
    model = None
    serializer = None

    def get_object(self, pk):
        return self.model.objects.filter(pk=pk).first()

    def get(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({"error": "Not Found"}, status=404)
        ser = self.serializer(obj)
        return Response(ser.data)

    def patch(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({"error": "Not Found"}, status=404)

        ser = self.serializer(obj, data=request.data, partial=True)
        if ser.is_valid():
            ser.save()
            return Response(ser.data)
        return Response(ser.errors, status=400)

    def delete(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({"error": "Not Found"}, status=404)

        obj.delete()
        return Response({"message": "Deleted"}, status=204)


class BaseResetOneAPI(APIView):
    model = None
    http_method_names = ["post", "head", "options"]

    @extend_schema(request=None, responses=ResetResponseSer)
    def post(self, request, pk):
        obj = self.model.objects.filter(pk=pk).first()
        if not obj:
            return Response({"error": "Not Found"}, status=404)

        snap = getattr(obj, "initial_snapshot", None)
        if not snap:
            return Response({"error": "No initial snapshot saved for this object."}, status=400)

        restore_initial_snapshot(obj, snap)
        return Response({"detail": "Reset to initial POST snapshot done."}, status=200)

class CacheListAPI(BaseListAPI):
    model = cache
    serializer = CacheSer

    @extend_schema(responses=CacheSer)
    def get(self, request):
        return super().get(request)

    @extend_schema(request=CacheSer, responses=CacheSer)
    def post(self, request):
        return super().post(request)


class CacheDetailAPI(BaseDetailAPI):
    model = cache
    serializer = CacheSer

    @extend_schema(responses=CacheSer)
    def get(self, request, pk):
        return super().get(request, pk)

    @extend_schema(request=CacheSer, responses=CacheSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class CacheResetAPI(BaseResetOneAPI):
    model = cache


