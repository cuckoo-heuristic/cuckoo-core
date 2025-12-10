from rest_framework import serializers

class RouteInputSerializer(serializers.Serializer):
    origin_lat = serializers.FloatField()
    origin_lon = serializers.FloatField()
    dest_lat = serializers.FloatField()
    dest_lon = serializers.FloatField()