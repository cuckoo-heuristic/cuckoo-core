import requests
from rest_framework.views import APIView
from rest_framework.response import Response

class RouteAPIView(APIView):
    def post(self, request):

        origin_lat = request.data.get("origin_lat")
        origin_lon = request.data.get("origin_lon")
        dest_lat = request.data.get("dest_lat")
        dest_lon = request.data.get("dest_lon")

        if not all([origin_lat, origin_lon, dest_lat, dest_lon]):
            return Response({"error": "enter lat and lon"}, status=400)

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
            return Response({"error": "not found"}, status=400)

        formatted_routes = []

        for route in data["routes"]:
            formatted_routes.append({
                "summary": route["legs"][0].get("summary", ""),
                "distance": route["legs"][0]["distance"]["text"],
                "duration": route["legs"][0]["duration"]["text"],
                "polyline": route["overview_polyline"]["points"]
            })

        return Response({"routes": formatted_routes})
