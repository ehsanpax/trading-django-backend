""" This is views for the accounts app. it provides the account query entry point for multiple platforms - ctrader, mt5. the frontend - as well as other functions in the backend - will call these APIs, and they will handle the request
and call relevant parts to process and return the requested data """


import uuid
from uuid import UUID
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.conf import settings
from django.shortcuts import get_object_or_404
import json
from .serializers import AccountCreateSerializer
from .models import Account, MT5Account, CTraderAccount
from django.contrib.auth import get_user_model
from rest_framework import status, permissions
from .serializers import AccountSerializer
import os, logging
from asgiref.sync import async_to_sync
from twisted.internet import defer
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import traceback
from accounts.services import get_account_details
from trading_platform.mt5_api_client import MT5APIClient
from django.http import Http404

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTRADER_TOKEN_STORAGE = os.path.join(BASE_DIR, "ctrader_tokens.json")

logger = logging.getLogger(__name__)
User = get_user_model()

class CreateAccountView(APIView):
    """
    POST /accounts/create/
    Creates a new trading account and links it to a platform-specific record (MT5 or cTrader).
    """
    permission_classes = [IsAuthenticated]
    def post(self, request, format=None):
        serializer = AccountCreateSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            user = request.user  # Using Django's authentication system

            # Create the main Account record
            new_account = Account.objects.create(
                id=uuid.uuid4(),
                user=user,
                name=data["name"],
                platform=data["platform"],
                balance=0.00,
                equity=0.00,
            )

            # Create platform-specific record
            if data["platform"] == "MT5":
                MT5Account.objects.create(
                    account=new_account,  # Assuming a ForeignKey relationship in your model
                    user=user,
                    account_number=data["account_number"],
                    broker_server=data["broker_server"],
                    encrypted_password=data["password"],  # You can add proper encryption here if needed
                )
            elif data["platform"] == "cTrader":
                CTraderAccount.objects.create(
                    account=new_account,
                    user=user,
                    # Add other required cTrader-specific fields here, for example:
                    # account_number=data.get("account_number"),
                    # access_token=data.get("access_token"),
                    # refresh_token=data.get("refresh_token"),
                )

            return Response(
                {"message": "Account created successfully", "account_id": str(new_account.id)},
                status=status.HTTP_201_CREATED
            )
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class ListAccountsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication, JWTAuthentication]

    def get(self, request, format=None):
        user = request.user
        accounts = Account.objects.filter(user=user)
        serializer = AccountSerializer(accounts, many=True)
        print(f"Returning {len(serializer.data)} accounts for user {user.id}")
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class UpdateAccountView(APIView):
    """
    PUT /accounts/update/<uuid:account_id>/
    Updates the name of an existing account if the user owns it.
    """
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, account_id):
        # 1️⃣ Fetch the account and ensure it belongs to the current user
        account = get_object_or_404(Account, id=account_id, user=request.user)

        # 2️⃣ Parse the new name from request.data
        new_name = request.data.get("name")
        if not new_name:
            return Response({"detail": "New name is required."}, status=status.HTTP_400_BAD_REQUEST)

        # 3️⃣ Update and save
        account.name = new_name
        account.save()

        return Response({
            "message": "Account updated successfully",
            "account_id": str(account.id)
        }, status=status.HTTP_200_OK)
    
class DeleteAccountView(APIView):
    """
    DELETE /accounts/delete/<uuid:account_id>/
    Deletes an account (and optionally linked MT5/cTrader records) if the user owns it.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, account_id):
        # 1️⃣ Fetch the account and ensure it belongs to the current user
        account = get_object_or_404(Account, id=account_id, user=request.user)
        logger.info(f"Deleting accountttttt {account_id} for user {request.user.id}")
        # 2️⃣ If it's an MT5 account, delete the instance from the MT5 API server
        if account.platform == "MT5" and hasattr(account, "mt5_account"):
            mt5_account = account.mt5_account
            client = MT5APIClient(
                base_url=settings.MT5_API_BASE_URL,
                account_id=mt5_account.account_number,
                password=mt5_account.encrypted_password,  # Assuming this is the password
                broker_server=mt5_account.broker_server,
                internal_account_id=str(account.id)
            )
            response = client.delete_instance()
            if "error" in response:
                logger.error(f"Failed to delete MT5 instance for account {account.id}: {response['error']}")
                # Decide if you want to stop the deletion process here or just log the error
                # For now, we'll log and continue
            else:
                logger.info(f"Successfully deleted MT5 instance for account {account.id}")

            mt5_account.delete()

        # 3️⃣ If you want to also delete linked cTrader account
        #    (assuming OneToOne or reverse relation named `ctrader_account`)
        if hasattr(account, "ctrader_account"):
            account.ctrader_account.delete()

        # 4️⃣ Finally, delete the main account
        account.delete()

        return Response({"message": "Account and linked records deleted successfully"}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class FetchAccountDetailsView(APIView):
    """
    GET /accounts/details/<uuid:account_id>/
    Retrieves real-time account details based on the account's platform.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, account_id):
        account_details = get_account_details(account_id, request.user)
        if "error" in account_details:
            return Response({"detail": account_details["error"]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(account_details, status=status.HTTP_200_OK)

from rest_framework import generics
from .serializers import UserRegistrationSerializer


class UserRegistrationView(generics.CreateAPIView):
    """
    POST /accounts/register/
    Creates a new user account. The account will be inactive until approved by an admin.
    """
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]  # Allow anyone to register

from rest_framework import viewsets
from accounts.models import ProfitTakingProfile
from .serializers import ProfitTakingProfileSerializer, UserSerializer # Added UserSerializer
from rest_framework.exceptions import PermissionDenied

class MeView(APIView):
    """
    API endpoint to retrieve details of the currently authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

class ProfitTakingProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ProfitTakingProfileSerializer

    def get_queryset(self):
        # only show profiles for the logged-in user
        return ProfitTakingProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        # HiddenField already ensures `user=request.user`, so just save
        serializer.save()

# --- Internal endpoints for cTrader token management ---
class InternalCTraderTokensView(APIView):
    """
    Internal API used by the cTrader microservice to fetch and update tokens
    for a specific CTraderAccount (broker_connection_id).

    Auth: requires header 'X-Internal-Secret' matching settings.INTERNAL_SHARED_SECRET
    """
    permission_classes = [permissions.AllowAny]

    def _check_secret(self, request):
        shared_secret = getattr(settings, "INTERNAL_SHARED_SECRET", None) or getattr(settings, "APP_INTERNAL_SHARED_SECRET", None)
        provided = request.headers.get("X-Internal-Secret") or request.META.get("HTTP_X_INTERNAL_SECRET")
        if not shared_secret or not provided or provided != shared_secret:
            raise PermissionDenied("Forbidden")

    def _resolve_broker_id(self, ctrader_account_id: str):
        """Accept either numeric CTraderAccount.id or UUID Account.id. Return CTraderAccount instance."""
        from .models import CTraderAccount, Account
        # Try numeric CTraderAccount.id first
        try:
            int_id = int(ctrader_account_id)
            return CTraderAccount.objects.get(id=int_id)
        except (ValueError, CTraderAccount.DoesNotExist):
            pass
        # Try UUID Account.id
        try:
            from uuid import UUID
            uuid_obj = UUID(str(ctrader_account_id))
            return CTraderAccount.objects.get(account__id=uuid_obj)
        except Exception:
            raise Http404("CTrader account not found")

    def get(self, request, ctrader_account_id: str):
        self._check_secret(request)
        acct = self._resolve_broker_id(ctrader_account_id)
        payload = {
            "broker_connection_id": acct.id,
            "access_token": acct.access_token or "",
            "refresh_token": acct.refresh_token or "",
            "ctid_trader_account_id": acct.ctid_trader_account_id,
            "ctid_user_id": acct.ctid_user_id,
            "token_expires_at": int(acct.token_expires_at.timestamp()) if acct.token_expires_at else None,
            "environment": ("LIVE" if acct.live else "DEMO") if acct.live is not None else None,
            "user_id": acct.user_id,
            "account_uuid": str(acct.account_id),
        }
        return Response(payload, status=status.HTTP_200_OK)

    def put(self, request, ctrader_account_id: str):
        self._check_secret(request)
        acct = self._resolve_broker_id(ctrader_account_id)
        data = request.data or {}

        changed = False
        if "access_token" in data:
            acct.access_token = data.get("access_token")
            changed = True
        if "refresh_token" in data:
            acct.refresh_token = data.get("refresh_token")
            changed = True
        ctid_val = data.get("ctid_trader_account_id", data.get("ctrader_account_id"))
        if ctid_val is not None:
            try:
                acct.ctid_trader_account_id = int(ctid_val)
            except (TypeError, ValueError):
                return Response({"detail": "ctid_trader_account_id must be int"}, status=status.HTTP_400_BAD_REQUEST)
            changed = True
        if "ctid_user_id" in data and data.get("ctid_user_id") is not None:
            try:
                acct.ctid_user_id = int(data.get("ctid_user_id"))
            except (TypeError, ValueError):
                return Response({"detail": "ctid_user_id must be int"}, status=status.HTTP_400_BAD_REQUEST)
            changed = True
        if "token_expires_at" in data and data.get("token_expires_at") is not None:
            from datetime import datetime, timezone
            try:
                epoch = int(data.get("token_expires_at"))
                acct.token_expires_at = datetime.fromtimestamp(epoch, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return Response({"detail": "token_expires_at must be epoch seconds"}, status=status.HTTP_400_BAD_REQUEST)
            changed = True
        if "environment" in data:
            env = str(data.get("environment", "")).upper()
            if env in ("LIVE", "DEMO"):
                acct.live = True if env == "LIVE" else False
                changed = True
            else:
                return Response({"detail": "environment must be LIVE or DEMO"}, status=status.HTTP_400_BAD_REQUEST)
        if "account_number" in data:
            acct.account_number = data.get("account_number") or None
            changed = True

        if changed:
            acct.save()

        return Response({
            "message": "Updated",
            "broker_connection_id": acct.id,
            "stored_fields": {
                "access_token": bool(acct.access_token),
                "refresh_token": bool(acct.refresh_token),
                "ctid_trader_account_id": acct.ctid_trader_account_id,
                "ctid_user_id": acct.ctid_user_id,
                "token_expires_at": int(acct.token_expires_at.timestamp()) if acct.token_expires_at else None,
                "environment": "LIVE" if acct.live else "DEMO" if acct.live is not None else None,
                "account_number": acct.account_number,
            }
        }, status=status.HTTP_200_OK)
