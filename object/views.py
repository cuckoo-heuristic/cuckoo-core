from django.forms.models import model_to_dict
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from django.db import models
from django.utils.dateparse import parse_datetime
from .models import Vehicle, RSU, RSUVehicle, ServiceProvider
from .serializer import VehicleSer,RSUSer, RSUVehicleSer, ServiceProviderSer
from state.models import State

def make_snapshot(obj):
    data = model_to_dict(obj)
    data.pop("id", None)
    data.pop("initial_snapshot", None)
    return data


ResetResponseSerializer = inline_serializer(
    name="ResetResponse",
    fields={"detail": serializers.CharField()},
)


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

    def post(self, request, pk):
        obj = self.model.objects.filter(pk=pk).first()
        if not obj:
            return Response({"error": "Not Found"}, status=404)

        snap = getattr(obj, "initial_snapshot", None)
        if not snap:
            return Response(
                {"error": "No initial snapshot saved for this object."},
                status=400
            )

        for field, value in snap.items():
            model_field = obj._meta.get_field(field)
            if isinstance(model_field, models.ForeignKey):
                setattr(obj, model_field.attname, value)
                continue
            if isinstance(model_field, models.DateTimeField) and isinstance(value, str):
                setattr(obj, field, parse_datetime(value))
                continue

            setattr(obj, field, value)

        obj.save()
        return Response(
            {"detail": "Reset to initial POST snapshot done."},
            status=200
        )

def post(self, request, pk):
    obj = self.model.objects.filter(pk=pk).first()
    if not obj:
        return Response({"error": "Not Found"}, status=404)

    snap = getattr(obj, "initial_snapshot", None)
    if not snap:
        return Response({"error": "No initial snapshot saved for this object."}, status=400)

    for field, value in snap.items():
        model_field = obj._meta.get_field(field)
        if isinstance(model_field, models.ForeignKey):
            setattr(obj, model_field.attname, value)
            continue
        if isinstance(model_field, models.DateTimeField) and isinstance(value, str):
            setattr(obj, field, parse_datetime(value))
            continue

        setattr(obj, field, value)

    obj.save()
    return Response({"detail": "Reset to initial POST snapshot done."}, status=200)


class RSUListAPI(BaseListAPI):
    model = RSU
    serializer = RSUSer

    @extend_schema(responses=RSUSer)
    def get(self, request):
        return super().get(request)

    @extend_schema(request=RSUSer, responses=RSUSer)
    def post(self, request):
        return super().post(request)


class RSUDetailAPI(BaseDetailAPI):
    model = RSU
    serializer = RSUSer

    @extend_schema(responses=RSUSer)
    def get(self, request, pk):
        return super().get(request, pk)

    @extend_schema(request=RSUSer, responses=RSUSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class RSUResetAPI(BaseResetOneAPI):
    model = RSU


class RSUVehicleListAPI(BaseListAPI):
    model = RSUVehicle
    serializer = RSUVehicleSer

    @extend_schema(responses=RSUVehicleSer)
    def get(self, request):
        return super().get(request)

    @extend_schema(request=RSUVehicleSer, responses=RSUVehicleSer)
    def post(self, request):
        return super().post(request)


class RSUVehicleDetailAPI(BaseDetailAPI):
    model = RSUVehicle
    serializer = RSUVehicleSer

    @extend_schema(responses=RSUVehicleSer)
    def get(self, request, pk):
        return super().get(request, pk)

    @extend_schema(request=RSUVehicleSer, responses=RSUVehicleSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class RSUVehicleResetAPI(BaseResetOneAPI):
    model = RSUVehicle


class ServiceProviderListAPI(BaseListAPI):
    model = ServiceProvider
    serializer = ServiceProviderSer

    @extend_schema(responses=ServiceProviderSer)
    def get(self, request):
        return super().get(request)

    @extend_schema(request=ServiceProviderSer, responses=ServiceProviderSer)
    def post(self, request):
        return super().post(request)


class ServiceProviderDetailAPI(BaseDetailAPI):
    model = ServiceProvider
    serializer = ServiceProviderSer

    @extend_schema(responses=ServiceProviderSer)
    def get(self, request, pk):
        return super().get(request, pk)

    @extend_schema(request=ServiceProviderSer, responses=ServiceProviderSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class ServiceProviderResetAPI(BaseResetOneAPI):
    model = ServiceProvider

class VehicleListAPIView(BaseListAPI):
    model = Vehicle
    serializer = VehicleSer

    @extend_schema(responses=VehicleSer)
    def get(self, request):
        return super().get(request)

    @extend_schema(request=VehicleSer, responses=VehicleSer)
    def post(self, request):
        return super().post(request)


class VehicleDetailAPIView(BaseDetailAPI):
    model = Vehicle
    serializer = VehicleSer

    @extend_schema(responses=VehicleSer)
    def get(self, request, pk):
        return super().get(request, pk)

    @extend_schema(request=VehicleSer, responses=VehicleSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class VehicleResetAPI(BaseResetOneAPI):
    model = Vehicle

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


class VehicleMissionAPI(APIView):
    @extend_schema(
        responses=inline_serializer(
            name="VehicleMissionResponse",
            fields={
                "vehicle_id": serializers.IntegerField(),
                "is_mission": serializers.BooleanField(),
            },
        )
    )
    def get(self, request, pk):
        mission = State.objects.filter(
            from_vehicle_id=pk,
            task_execution_id__end_time__isnull=True
        ).exists()

        return Response({"vehicle_id": pk, "is_mission": mission})

class RSUActiveAPI(APIView):
    @extend_schema(
        responses=inline_serializer(
            name="RSUActiveResponse",
            fields={
                "rsu_id": serializers.IntegerField(),
                "is_active": serializers.BooleanField(),
            },
        )
    )
    def get(self, request, pk):
        active = RSUVehicle.objects.filter(
            rsu_id=pk,
            vehicle_id__isnull=False,
            end_time__isnull=True
        ).exists()
        return Response({"rsu_id": pk, "is_active": active})


class RSUVIsCurrentAPI(APIView):
    @extend_schema(
        responses=inline_serializer(
            name="RSUVIsCurrentResponse",
            fields={
                "id": serializers.IntegerField(),
                "is_current": serializers.BooleanField(),
            },
        )
    )
    def get(self, request, pk):
        r = RSUVehicle.objects.filter(id=pk).first()
        if not r:
            return Response({"error": "not found"}, status=404)
        return Response({"id": pk, "is_current": r.end_time is None})
