# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from .serializers import AITradeRequestSerializer
from .services import select_next_account
from trades.views import ExecuteTradeView
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated

class ExecuteAITradeView(APIView):
    """Accepts AI trade payload, injects an account, forwards to ExecuteTradeView."""
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = AITradeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        account = select_next_account()
        if not account:
            return Response({'detail': 'No eligible automation accounts available.'}, status=status.HTTP_400_BAD_REQUEST)

        forward_data = {
            **payload,
            'account_id': str(account.id)
        }

        factory = APIRequestFactory()
        forward_request = factory.post('/trades/execute/', forward_data, format='json')
        # carry over authentication
        force_authenticate(forward_request, user=request.user)

        execution_view = ExecuteTradeView.as_view()
        return execution_view(forward_request, *args, **kwargs)