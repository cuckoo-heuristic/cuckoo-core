from rest_framework import serializers
from .models import cache

class CacheSer(serializers.ModelSerializer):
    class Meta:
        model = cache
        exclude = ["initial_snapshot"]
