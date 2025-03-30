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