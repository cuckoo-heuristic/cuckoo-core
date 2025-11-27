import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from vehicle.models import Vehicle

class RouteAPIView(APIView):
    def post(self, request):

        vehicle_id = request.data.get("vehicle_id")

        if not vehicle_id:
            return Response({"error": "id?"}, status=400)

        try:
            vehicle = Vehicle.objects.get(id=vehicle_id)
        except Vehicle.DoesNotExist:
            return Response({"error": "The vehicle was not found!"}, status=404)

        origin_lat = vehicle.origin_lat
        origin_lon = vehicle.origin_lon
        dest_lat = vehicle.destination_lat
        dest_lon = vehicle.destination_lon

        url = 'https://api.neshan.org/v4/direction'
        headers = {
            "Api-Key": "service.214f45d3ef634f048a4dc1ebe413fb2d"
        }
        params = {
            "origin": f"{origin_lat},{origin_lon}",
            "destination": f"{dest_lat},{dest_lon}"
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if "routes" not in data:
            return Response({"error": "مسیر پیدا نشد"}, status=400)

        formatted_routes = []

        for route in data["routes"]:
            formatted_routes.append({
                "summary": route["legs"][0].get("summary", ""),
                "distance": route["legs"][0]["distance"]["text"],
                "duration": route["legs"][0]["duration"]["text"],
                "polyline": route["overview_polyline"]["points"]
            })

        return Response({"routes": formatted_routes})
