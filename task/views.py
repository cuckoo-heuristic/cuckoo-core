from django.forms.models import model_to_dict
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from django.db import models
from django.utils.dateparse import parse_datetime
from .models import Task, TaskType, Application, ApplicationType, TaskExecution, TaskDependency, State
from .serializer import (
    TaskSer, TaskTypeSer, ApplicationSer, ApplicationTypeSer,
    TaskExecutionSer, TaskDependencySer, StateSer
)


def make_snapshot(obj):
    data = model_to_dict(obj)
    data.pop("id", None)
    data.pop("initial_snapshot", None)

    # اگر فیلدهایی داری که نمی‌خوای reset بشن (runtime)، اینجا حذف کن:
    # data.pop("start_at", None)
    # data.pop("start_time", None)

    return data


ResetResponseSerializer = inline_serializer(
    name="ResetResponse",
    fields={"detail": serializers.CharField()}
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
            return Response({"error": "No initial snapshot saved for this object."}, status=400)

        for field, value in snap.items():
            model_field = obj._meta.get_field(field)

            # ✅ 1) ForeignKey ها: مقدار ID را روی *_id ست کن
            if isinstance(model_field, models.ForeignKey):
                setattr(obj, model_field.attname, value)  # مثل rsu_id_id
                continue

            # ✅ 2) DateTimeField ها: اگر رشته است برگردون به datetime
            if isinstance(model_field, models.DateTimeField) and isinstance(value, str):
                setattr(obj, field, parse_datetime(value))
                continue

            # ✅ 3) بقیه فیلدها
            setattr(obj, field, value)

        obj.save()
        return Response({"detail": "Reset to initial POST snapshot done."}, status=200)



# ---- Task ----
class TaskListAPI(BaseListAPI):
    model = Task
    serializer = TaskSer

    @extend_schema(request=TaskSer, responses=TaskSer)
    def post(self, request):
        return super().post(request)


class TaskDetailAPI(BaseDetailAPI):
    model = Task
    serializer = TaskSer

    @extend_schema(request=TaskSer, responses=TaskSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class TaskResetAPI(BaseResetOneAPI):
    model = Task

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


# ---- TaskType ----
class TaskTypeListAPI(BaseListAPI):
    model = TaskType
    serializer = TaskTypeSer

    @extend_schema(request=TaskTypeSer, responses=TaskTypeSer)
    def post(self, request):
        return super().post(request)


class TaskTypeDetailAPI(BaseDetailAPI):
    model = TaskType
    serializer = TaskTypeSer

    @extend_schema(request=TaskTypeSer, responses=TaskTypeSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class TaskTypeResetAPI(BaseResetOneAPI):
    model = TaskType

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


# ---- Application ----
class ApplicationListAPI(BaseListAPI):
    model = Application
    serializer = ApplicationSer

    @extend_schema(request=ApplicationSer, responses=ApplicationSer)
    def post(self, request):
        return super().post(request)


class ApplicationDetailAPI(BaseDetailAPI):
    model = Application
    serializer = ApplicationSer

    @extend_schema(request=ApplicationSer, responses=ApplicationSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class ApplicationResetAPI(BaseResetOneAPI):
    model = Application

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


# ---- ApplicationType ----
class ApplicationTypeListAPI(BaseListAPI):
    model = ApplicationType
    serializer = ApplicationTypeSer

    @extend_schema(request=ApplicationTypeSer, responses=ApplicationTypeSer)
    def post(self, request):
        return super().post(request)


class ApplicationTypeDetailAPI(BaseDetailAPI):
    model = ApplicationType
    serializer = ApplicationTypeSer

    @extend_schema(request=ApplicationTypeSer, responses=ApplicationTypeSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class ApplicationTypeResetAPI(BaseResetOneAPI):
    model = ApplicationType

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


# ---- TaskExecution ----
class TaskExeListAPI(BaseListAPI):
    model = TaskExecution
    serializer = TaskExecutionSer

    @extend_schema(request=TaskExecutionSer, responses=TaskExecutionSer)
    def post(self, request):
        return super().post(request)


class TaskExeDetailAPI(BaseDetailAPI):
    model = TaskExecution
    serializer = TaskExecutionSer

    @extend_schema(request=TaskExecutionSer, responses=TaskExecutionSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class TaskExeResetAPI(BaseResetOneAPI):
    model = TaskExecution

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


# ---- TaskDependency ----
class TaskDepListAPI(BaseListAPI):
    model = TaskDependency
    serializer = TaskDependencySer

    @extend_schema(request=TaskDependencySer, responses=TaskDependencySer)
    def post(self, request):
        return super().post(request)


class TaskDepDetailAPI(BaseDetailAPI):
    model = TaskDependency
    serializer = TaskDependencySer

    @extend_schema(request=TaskDependencySer, responses=TaskDependencySer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class TaskDepResetAPI(BaseResetOneAPI):
    model = TaskDependency

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


# ---- State ----
class StateListAPI(BaseListAPI):
    model = State
    serializer = StateSer

    @extend_schema(request=StateSer, responses=StateSer)
    def post(self, request):
        return super().post(request)


class StateDetailAPI(BaseDetailAPI):
    model = State
    serializer = StateSer

    @extend_schema(request=StateSer, responses=StateSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


class StateResetAPI(BaseResetOneAPI):
    model = State

    @extend_schema(request=None, responses=ResetResponseSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


# ---- Extra ----
class AppProgressAPI(APIView):
    @extend_schema(
        responses=inline_serializer(
            name="AppProgressResponse",
            fields={
                "id": serializers.IntegerField(),
                "is_progress": serializers.BooleanField(),
            },
        )
    )
    def get(self, request, pk):
        app = Application.objects.filter(id=pk).first()
        if not app:
            return Response({"error": "not found"}, 404)
        return Response({"id": pk, "is_progress": app.end_at is None})
