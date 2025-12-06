from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import (RSU,RSUVehicle,ServiceProvider,Resource)
from .serializer import (RSUSer,RSUVehicleSer,ServiceProviderSer,ResourceSer)
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

class RSUListAPI(BaseListAPI):
    model = RSU
    serializer = RSUSer

    @extend_schema(request=RSUSer, responses=RSUSer)
    def post(self, request):
        return super().post(request)

class RSUDetailAPI(BaseDetailAPI):
    model = RSU
    serializer = RSUSer

    @extend_schema(request=RSUSer, responses=RSUSer)
    def patch(self, request, pk):
        return super().patch(request, pk)


# //////////////////////
class RVListAPI(BaseListAPI):
    model = RSUVehicle
    serializer = RSUVehicleSer

    @extend_schema(request=RSUVehicleSer, responses=RSUVehicleSer)
    def post(self, request):
        return super().post(request)

class RVDetailAPI(BaseDetailAPI):
    model = RSUVehicle
    serializer = RSUVehicleSer

    @extend_schema(request=RSUVehicleSer, responses=RSUVehicleSer)
    def patch(self, request, pk):
        return super().patch(request, pk)

# //////////////////////
class SPListAPI(BaseListAPI):
    model = ServiceProvider
    serializer = ServiceProviderSer

    @extend_schema(request=ServiceProviderSer, responses=ServiceProviderSer)
    def post(self, request):
        return super().post(request)

class SPDetailAPI(BaseDetailAPI):
    model = ServiceProvider
    serializer = ServiceProviderSer

    @extend_schema(request=ServiceProviderSer, responses=ServiceProviderSer)
    def patch(self, request, pk):
        return super().patch(request, pk)

# //////////////////////
class ResourceListAPI(BaseListAPI):
    model = Resource
    serializer = ResourceSer

    @extend_schema(request=ResourceSer, responses=ResourceSer)
    def post(self, request):
        return super().post(request)

class ResourceDetailAPI(BaseDetailAPI):
    model = Resource
    serializer = ResourceSer

    @extend_schema(request=ResourceSer, responses=ResourceSer)
    def patch(self, request, pk):
        return super().patch(request, pk)