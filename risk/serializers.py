# risk/serializers.py
from rest_framework import serializers
from .models import RiskManagement
from accounts.serializers import ProfitTakingProfileSerializer
from accounts.models import ProfitTakingProfile

class LotSizeRequestSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    equity = serializers.FloatField()
    risk_percent = serializers.FloatField()
    stop_loss_distance = serializers.FloatField()
    symbol = serializers.CharField(default="EURUSD")
    trade_direction = serializers.ChoiceField(
        choices=[("BUY", "BUY"), ("SELL", "SELL")],
        default="BUY"
    )

class RiskManagementSerializer(serializers.ModelSerializer):
    # Nested read-only default TP profile
    default_tp_profile = ProfitTakingProfileSerializer(read_only=True)
    # Write-only field for setting default TP profile by ID
    default_tp_profile_id = serializers.PrimaryKeyRelatedField(
        source='default_tp_profile',
        queryset=ProfitTakingProfile.objects.all(),
        write_only=True,
        allow_null=True,
        required=False,
        help_text='ID of the profit-taking profile to set as default'
    )

    class Meta:
        model = RiskManagement
        fields = [
            'id',
            'max_daily_loss',        # percentage of equity
            'max_trade_risk',
            'max_open_positions',
            'enforce_cooldowns',
            'consecutive_loss_limit',
            'cooldown_period',
            'max_lot_size',
            'max_open_trades_same_symbol',
            'risk_percent',          # default risk % for trades
            'last_updated',
            'default_tp_profile',    # nested data
            'default_tp_profile_id', # input field
            'created_at',
        ]
        read_only_fields = ['id', 'last_updated', 'created_at']
        extra_kwargs = {
            'max_daily_loss': {
                'help_text': 'Maximum daily loss as a percentage of equity (e.g., 5 for 5%)'
            }
        }

    def update(self, instance, validated_data):
        # source mapping will handle default_tp_profile update
        return super().update(instance, validated_data)
