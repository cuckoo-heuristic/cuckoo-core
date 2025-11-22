from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import RSU
from .serializer import RSUSerializer

class RSUListAPIView(APIView):

    def get(self, request):
        RSUs = RSU.objects.all()
        serializer = RSUSerializer(RSUs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RSUSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
