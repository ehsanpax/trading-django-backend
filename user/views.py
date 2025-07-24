from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.authtoken.models import Token


class CreateUserToken(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        new_token, _ = Token.objects.get_or_create(
            user=request.user
        )  # Create new token
        return Response({"token": new_token.key}, status=status.HTTP_201_CREATED)
