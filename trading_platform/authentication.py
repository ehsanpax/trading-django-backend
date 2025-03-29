from rest_framework_simplejwt.authentication import JWTAuthentication
from asgiref.sync import async_to_sync, sync_to_async

class AsyncJWTAuthentication(JWTAuthentication):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default values if they are not already set.
        if not hasattr(self, 'user_id_claim'):
            self.user_id_claim = 'user_id'
        if not hasattr(self, 'user_id_field'):
            self.user_id_field = 'id'

    def authenticate(self, request):
        # Call our async authenticate method and wait for its result.
        return async_to_sync(self.authenticate_async)(request)

    async def authenticate_async(self, request):
        # Wrap the synchronous parent's authenticate method.
        result = await sync_to_async(super().authenticate)(request)
        return result

    def get_user(self, validated_token):
        # Wrap get_user to return a concrete user.
        return async_to_sync(self.get_user_async)(validated_token)

    async def get_user_async(self, validated_token):
        user_id_claim = self.user_id_claim  # Should be 'user_id'
        user_id_field = self.user_id_field  # Should be 'id'
        user_id = validated_token.get(user_id_claim)
        if user_id is None:
            raise Exception("User ID claim missing")
        user = await sync_to_async(self.user_model.objects.get)(**{user_id_field: user_id})
        return user
