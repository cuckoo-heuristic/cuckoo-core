from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import (Task, TaskType, Application, ApplicationType, TaskExecution, TaskDependency, cache)
from .serializer import (TaskSer, TaskTypeSer, ApplicationSer,ApplicationTypeSer, TaskExecutionSer,TaskDependencySer,CacheSer)
from drf_spectacular.utils import extend_schema
# /////////////////////////
class BaseListAPI(APIView):
    model = None
    serializer = None
    def get(self, request):
        items = self.model.objects.all()
        ser = self.serializer(items, many=True)
        return Response(ser.data)

    def post(self, request):
        ser = self.serializer(data=request.data)
        if ser.is_valid():
            ser.save()
            return Response(ser.data, status=status.HTTP_201_CREATED)
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

class BaseDetailAPI(APIView):
    model = None
    serializer = None

    def get_object(self, pk):
        try:
            return self.model.objects.get(pk=pk)
        except self.model.DoesNotExist:
            return None

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
# //////////////////////
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
# //////////////////////
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
# //////////////////////
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
# //////////////////////
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
# //////////////////////
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
# //////////////////////
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
# //////////////////////
class CacheListAPI(BaseListAPI):
    model = cache
    serializer = CacheSer

    @extend_schema(request=CacheSer, responses=CacheSer)
    def post(self, request):
        return super().post(request)

class CacheDetailAPI(BaseDetailAPI):
    model = cache
    serializer = CacheSer

    @extend_schema(request=TaskDependencySer, responses=TaskDependencySer)
    def patch(self, request, pk):
        return super().patch(request, pk)
