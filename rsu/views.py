from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import RSU
from .serializer import RSUSerializer

class RSUListAPIView(APIView):

    def get(self, request):
        RSU = RSU.objects.all()
        serializer = RSUSerializer(RSU, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RSUSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
class RSUDetailAPIView(APIView):

    def get(self, request, pk):
        try:
            RSU = RSU.objects.get(pk=pk)
        except RSU.DoesNotExist:
            return Response({"error": "RSU not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = RSUSerializer(RSU)
        return Response(serializer.data)