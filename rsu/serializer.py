from rest_framework import serializers
from .models import RSU

class RSUSerializer(serializers.ModelSerializer):
    class Meta:
        model = RSU
        fields = '__all__'