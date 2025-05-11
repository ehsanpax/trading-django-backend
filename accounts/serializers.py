from rest_framework import serializers
from .models import Account


class AccountCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(choices=[("MT5", "MT5"), ("cTrader", "cTrader")])
    account_number = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    broker_server = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data.get("platform") == "MT5":
            missing_fields = []
            for field in ["account_number", "password", "broker_server"]:
                if not data.get(field):
                    missing_fields.append(field)
            if missing_fields:
                raise serializers.ValidationError(
                    {field: "This field is required for MT5 accounts." for field in missing_fields}
                )
        return data
class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = '__all__'  # or explicitly list: ['id', 'name', 'platform', ...]


from accounts.models import ProfitTakingProfile

class ProfitTakingProfileSerializer(serializers.ModelSerializer):
    # HiddenField will automatically set `user = request.user`
    user = serializers.HiddenField(
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        model = ProfitTakingProfile
        fields = [
            'id', 'user', 'name',
            'partial_targets', 'is_default',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_partial_targets(self, value):
        total = sum(item.get('size_pct', 0) for item in value)
        if round(total, 2) != 100:
            raise serializers.ValidationError('Sum of size_pct must be 100.')
        return value

    def validate(self, data):
        # Enforce only one default per user
        if data.get('is_default', False):
            user = self.context['request'].user
            qs = ProfitTakingProfile.objects.filter(user=user, is_default=True)
            # Exclude self when doing an update
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    'Only one default profile allowed per user.'
                )
        return data

