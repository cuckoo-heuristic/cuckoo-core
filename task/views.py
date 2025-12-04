from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import (Task, TaskType, Application, ApplicationType, TaskExecution, TaskDependency, cache)
from .serializer import (TaskSer, TaskTypeSer, ApplicationSer,ApplicationTypeSer, TaskExecutionSer,TaskDependencySer,CacheSer)
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

class TaskDetailAPI(BaseDetailAPI):
    model = Task
    serializer = TaskSer
# //////////////////////
class TaskTypeListAPI(BaseListAPI):
    model = TaskType
    serializer = TaskTypeSer

class TaskTypeDetailAPI(BaseDetailAPI):
    model = TaskType
    serializer = TaskTypeSer
# //////////////////////
class ApplicationListAPI(BaseListAPI):
    model = Application
    serializer = ApplicationSer

class ApplicationDetailAPI(BaseDetailAPI):
    model = Application
    serializer = ApplicationSer
# //////////////////////
class ApplicationTypeListAPI(BaseListAPI):
    model = ApplicationType
    serializer = ApplicationTypeSer

class ApplicationTypeDetailAPI(BaseDetailAPI):
    model = ApplicationType
    serializer = ApplicationTypeSer
# //////////////////////
class TaskExeListAPI(BaseListAPI):
    model = TaskExecution
    serializer = TaskExecutionSer

class TaskExeDetailAPI(BaseDetailAPI):
    model = TaskExecution
    serializer = TaskExecutionSer
# //////////////////////
class TaskDepListAPI(BaseListAPI):
    model = TaskDependency
    serializer = TaskDependencySer

class TaskDepDetailAPI(BaseDetailAPI):
    model = TaskDependency
    serializer = TaskDependencySer
# //////////////////////
class CacheListAPI(BaseListAPI):
    model = cache
    serializer = CacheSer

class CacheDetailAPI(BaseDetailAPI):
    model = cache
    serializer = CacheSer
