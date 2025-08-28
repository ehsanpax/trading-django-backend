from django.contrib.auth import get_user_model # To get the active User model
from rest_framework import serializers
from .models import Account, Profile
import pytz


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

User = get_user_model()

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('username', 'password', 'email', 'first_name', 'last_name')

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            is_active=False  # Deactivate account until approved
        )
        return user

class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the User model, to be used for the 'me' endpoint.
    """
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active', 'date_joined')
        read_only_fields = fields # Make all fields read-only for this specific use case


class ProfileSerializer(serializers.ModelSerializer):
    """Serializer to view/update the current user's profile.
    Name/Surname are sourced from User.first_name/last_name; email from User.email.
    They are exposed as write-through fields for convenience.
    """
    # Expose basic user fields
    email = serializers.EmailField(source='user.email', required=False)
    name = serializers.CharField(source='user.first_name', required=False, allow_blank=True)
    surname = serializers.CharField(source='user.last_name', required=False, allow_blank=True)

    default_account = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Profile
        fields = [
            'email', 'name', 'surname',
            'phone', 'trading_experience', 'country', 'state', 'address',
            'timezone', 'profile_currency', 'is_approved',
            'locale', 'city', 'postal_code', 'date_of_birth',
            'notification_prefs', 'default_account',
        ]
        read_only_fields = ['is_approved']

    def update(self, instance, validated_data):
        # Handle nested user updates
        user_data = validated_data.pop('user', {})
        user = instance.user
        if 'email' in user_data:
            user.email = user_data['email']
        if 'first_name' in user_data:
            user.first_name = user_data['first_name']
        if 'last_name' in user_data:
            user.last_name = user_data['last_name']
        user.save()

        return super().update(instance, validated_data)

    def validate_profile_currency(self, value: str):
        if not value:
            return value
        v = value.strip().upper()
        # Minimal ISO-4217 set; can be extended as needed without extra deps
        iso4217 = {
            'USD','EUR','GBP','JPY','CHF','CAD','AUD','NZD','CNY','HKD','SGD','SEK','NOK','DKK','ZAR','MXN','BRL','INR'
        }
        if len(v) != 3 or not v.isalpha() or v not in iso4217:
            raise serializers.ValidationError('Use a valid 3-letter ISO currency code, e.g., USD, EUR, GBP.')
        return v

    def validate_timezone(self, value: str):
        v = (value or '').strip() or 'UTC'
        if v not in pytz.all_timezones_set:
            raise serializers.ValidationError('Timezone must be a valid IANA timezone, e.g., UTC or Europe/London.')
        return v

    def validate_default_account(self, account):
        if account is None:
            return None
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError('Authentication required.')
        if account.user_id != request.user.id:
            raise serializers.ValidationError('Default account must belong to the current user.')
        return account
