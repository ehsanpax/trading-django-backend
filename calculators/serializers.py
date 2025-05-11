from rest_framework import serializers

class RequiredWinRateSerializer(serializers.Serializer):
    growth_pct    = serializers.FloatField(min_value=0)
    risk_pct      = serializers.FloatField(min_value=0)
    num_trades    = serializers.IntegerField(min_value=1)
    avg_winner_R  = serializers.FloatField(min_value=0)
