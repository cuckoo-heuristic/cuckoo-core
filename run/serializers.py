from rest_framework import serializers


class RunSimulationInputSerializer(serializers.Serializer):
    time_simulate = serializers.IntegerField(min_value=1, default=120)
    time_task = serializers.IntegerField(min_value=1, default=30)
    time_step = serializers.IntegerField(min_value=1, default=1)
    vehicle_ids = serializers.ListField(child=serializers.IntegerField(min_value=1),allow_empty=False,)
    policy_mode = serializers.ChoiceField(
        choices=["prefer_rsu", "prefer_v2v"],
        default="prefer_rsu",
        help_text="After local: prefer_rsu => local->rsu->v2v, prefer_v2v => local->v2v->rsu"
    )
    rsu_radius = serializers.FloatField(min_value=0, default=500.0)
    v2v_radius = serializers.FloatField(min_value=0, default=200.0)
    seed = serializers.IntegerField(required=False, allow_null=True)
    output_mode = serializers.ChoiceField(
        choices=["timeline", "status"],
        default="timeline",
        required=False,
        help_text="timeline=full frames, status=only last frame snapshot"
)