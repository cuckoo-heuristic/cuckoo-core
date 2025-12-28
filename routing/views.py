from drf_spectacular.utils import extend_schema
import requests
from rest_framework.views import APIView
from rest_framework.response import Response
import polyline
from .serializer import RouteInputSerializer


class RouteAPIView(APIView):

    @extend_schema(
        request=RouteInputSerializer,
        responses=None
    )
    def post(self, request):

        origin_lat = request.data.get("origin_lat")
        origin_lon = request.data.get("origin_lon")
        dest_lat = request.data.get("dest_lat")
        dest_lon = request.data.get("dest_lon")

        if not all([origin_lat, origin_lon, dest_lat, dest_lon]):
            return Response({"error": "enter lat and lon"}, status=400)

        url = "https://api.neshan.org/v4/direction"
        headers = {
            "Api-Key": "service.214f45d3ef634f048a4dc1ebe413fb2d"
        }
        params = {
            "origin": f"{origin_lat},{origin_lon}",
            "destination": f"{dest_lat},{dest_lon}",
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if "routes" not in data:
            return Response({"error": "route not found"}, status=400)

        encoded_polyline = data["routes"][0]["overview_polyline"]["points"]
        decoded_path = polyline.decode(encoded_polyline)
        vehicle_path = [[lon, lat] for lat, lon in decoded_path]

        return Response({
            "path": vehicle_path,
            "distance": data["routes"][0]["legs"][0]["distance"]["text"],
            "duration": data["routes"][0]["legs"][0]["duration"]["text"]
        })

