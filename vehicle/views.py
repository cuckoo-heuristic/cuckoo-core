from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Vehicle
from .serializer import VehicleSerializer

class vehicleListAPIView(APIView):

    def get(self, request):
        vehicles = Vehicle.objects.all()
        serializer = VehicleSerializer(vehicles, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = VehicleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class vehicleDetailAPIView(APIView):

    def get(self, request, pk):
        try:
            Vehicle = Vehicle.objects.get(pk=pk)
        except Vehicle.DoesNotExist:
            return Response({"error": "Vehicle not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = VehicleSerializer(Vehicle)
        return Response(serializer.data)