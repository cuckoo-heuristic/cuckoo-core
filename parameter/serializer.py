from rest_framework import serializers
from .models import Parameter

class ParameterReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parameter
        fields = ["key", "value", "unit"]


class ParameterPatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parameter
        fields = ["value"]

    def validate_value(self, v):
        instance: Parameter = self.instance
        if not instance:
            return v

        t = instance.value_type
        if t == Parameter.ValueType.INT and not isinstance(v, int):
            raise serializers.ValidationError("value must be int")
        if t == Parameter.ValueType.FLOAT and not isinstance(v, (int, float)):
            raise serializers.ValidationError("value must be float")
        if t == Parameter.ValueType.BOOL and not isinstance(v, bool):
            raise serializers.ValidationError("value must be bool")
        if t == Parameter.ValueType.STR and not isinstance(v, str):
            raise serializers.ValidationError("value must be string")
        return v
