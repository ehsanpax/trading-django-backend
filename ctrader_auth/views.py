import os
import json
import urllib.parse
import requests

from django.shortcuts import redirect
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated

# cTrader OAuth Configuration
CLIENT_ID = "13641_QqAQIxv5R7wUGHoSjbKTalzNMPbyDEt6b9I8VxgwUO3rs3qN0P"
CLIENT_SECRET = "tFzXEFQi2fYtaIWm7xdz54n6jhnT5dQHGT82Jf5Z3J6DSUwV1i"
API_BASE_URL = os.getenv("API_BASE_URL", "https://paksistrading.com/api")
REDIRECT_URI = f"{API_BASE_URL}/ctrader/callback"
AUTH_URL = "https://connect.spotware.com/oauth/v2/auth"
TOKEN_URL = "https://connect.spotware.com/oauth/v2/token"
TOKEN_STORAGE = os.path.join(os.getcwd(), "ctrader_tokens.json")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://paksistrading.com/")
CTRADER_ACCOUNTS_URL = "https://api.spotware.com/connect/tradingaccounts"


class CTRaderLoginAPIView(APIView):
    """
    Initiates the cTrader OAuth flow.
    """
    def get(self, request, format=None):
        auth_redirect_url = (
            f"{AUTH_URL}?client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=trading"
        )
        return Response({"redirect_url": auth_redirect_url})


class CTRaderRedirectAPIView(APIView):
    """
    Stores the pending account ID in session and redirects to cTrader.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        account_id = request.GET.get("account_id")
        if not account_id:
            return Response({"error": "Missing account_id parameter."}, status=status.HTTP_400_BAD_REQUEST)
        request.session["pending_account_id"] = account_id
        auth_url = (
            f"https://connect.spotware.com/apps/auth?"
            f"client_id={CLIENT_ID}"
            f"&response_type=code"
            f"&redirect_uri={REDIRECT_URI}"
            f"&scope=trading"
        )
        if "application/json" in request.headers.get("Accept", ""):
            return Response({"redirect_url": auth_url})
        return redirect(auth_url)


class CTRaderCallbackAPIView(APIView):
    permission_classes = []
    """
    Handles the callback from cTrader OAuth.
    Exchanges code for tokens, fetches account data, and redirects to frontend.
    """
    def get(self, request, format=None):
        code = request.GET.get("code")
        pending_account_id = request.session.get("pending_account_id")
        if not code or not pending_account_id:
            return Response({"error": "Missing code or pending account id."}, status=status.HTTP_400_BAD_REQUEST)

        token_response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
        if token_response.status_code != 200:
            return Response({"error": "Failed to get access token."}, status=status.HTTP_400_BAD_REQUEST)
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not access_token:
            return Response({"error": "Invalid access token received."}, status=status.HTTP_400_BAD_REQUEST)

        accounts_url = f"{CTRADER_ACCOUNTS_URL}?access_token={access_token}"
        accounts_response = requests.get(accounts_url)
        if accounts_response.status_code != 200:
            return Response({"error": "Failed to retrieve trading accounts."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            accounts_data = accounts_response.json()
        except json.JSONDecodeError:
            return Response({"error": "Invalid response format from cTrader."}, status=status.HTTP_400_BAD_REQUEST)
        if "data" not in accounts_data or not accounts_data["data"]:
            return Response({"error": "No linked trading accounts found."}, status=status.HTTP_400_BAD_REQUEST)
        request.session["ctrader_accounts"] = accounts_data["data"]
        formatted_accounts = [
            {
                "accountId": acc["accountId"],
                "accountNumber": acc["accountNumber"],
                "broker": acc["brokerTitle"],
                "currency": acc["depositCurrency"],
                "leverage": acc["leverage"],
                "balance": acc["balance"],
                "live": acc["live"],
            }
            for acc in accounts_data["data"]
        ]

        try:
            with open(TOKEN_STORAGE, "w") as file:
                json.dump({"access_token": access_token, "refresh_token": refresh_token}, file)
        except Exception:
            return Response({"error": "Failed to store tokens."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        encoded_accounts = urllib.parse.quote(json.dumps(formatted_accounts))
        frontend_redirect = f"{FRONTEND_URL}/select-ctrader-account?accounts={encoded_accounts}"
        return redirect(frontend_redirect)


class CTRaderSelectAccountAPIView(APIView):
    """
    Finalizes linking the selected cTrader account to the internal account.
    """
    def post(self, request, format=None):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)

        selected_account_id = data.get("accountId")
        if not selected_account_id:
            return Response({"error": "No account selected."}, status=status.HTTP_400_BAD_REQUEST)

        pending_account_id = request.session.get("pending_account_id")
        if not pending_account_id:
            return Response({"error": "Session lost! Internal account ID missing."}, status=status.HTTP_400_BAD_REQUEST)

        stored_accounts = request.session.get("ctrader_accounts", [])
        selected_account = next(
            (acc for acc in stored_accounts if str(acc["accountId"]) == str(selected_account_id)),
            None,
        )
        if not selected_account:
            return Response({"error": "Selected account not found in session."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with open(TOKEN_STORAGE, "r") as file:
                tokens = json.load(file)
        except Exception:
            return Response({"error": "Missing cTrader tokens."}, status=status.HTTP_400_BAD_REQUEST)

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            return Response({"error": "Missing access or refresh token."}, status=status.HTTP_400_BAD_REQUEST)

        # Update the CTraderAccount in the database
        from accounts.models import CTraderAccount  # Adjust import as needed
        try:
            ctrader_account = CTraderAccount.objects.get(account__id=pending_account_id)
        except CTraderAccount.DoesNotExist:
            return Response({"error": "Internal account not found! Cannot link cTrader account."}, status=status.HTTP_400_BAD_REQUEST)

        ctrader_account.account_number = selected_account.get("accountNumber")
        ctrader_account.ctid_trader_account_id = selected_account.get("accountId")
        ctrader_account.currency = selected_account.get("depositCurrency")
        ctrader_account.broker = selected_account.get("brokerTitle")
        ctrader_account.live = selected_account.get("live")
        ctrader_account.leverage = selected_account.get("leverage")
        ctrader_account.access_token = access_token
        ctrader_account.refresh_token = refresh_token

        ctrader_account.save()
        return Response({"message": "Account successfully linked to cTrader!"})


class CTraderOnboardProxyAPIView(APIView):
    """Proxy: POST -> FastAPI /ctrader/onboard to initiate OAuth."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            payload = request.data if hasattr(request, "data") else json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)

        url = f"{settings.CTRADER_API_BASE_URL.rstrip('/')}/ctrader/onboard"
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Secret": settings.INTERNAL_SHARED_SECRET or "",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
        except requests.RequestException as e:
            return Response({"error": f"Upstream error: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(resp.json() if resp.content else {}, status=resp.status_code)


class CTraderOAuthCallbackProxyView(APIView):
    """Proxy: Redirect GET to FastAPI /ctrader/oauth/callback with same query params."""
    permission_classes = []

    def get(self, request, *args, **kwargs):
        base = f"{settings.CTRADER_API_BASE_URL.rstrip('/')}/ctrader/oauth/callback"
        query = request.META.get("QUERY_STRING", "")
        target = f"{base}?{query}" if query else base
        return redirect(target)


class CTraderAccountsProxyAPIView(APIView):
    """Proxy: GET -> FastAPI /ctrader/accounts (lists accounts after OAuth)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        url = f"{settings.CTRADER_API_BASE_URL.rstrip('/')}/ctrader/accounts"
        headers = {
            "X-Internal-Secret": settings.INTERNAL_SHARED_SECRET or "",
            "Accept": "application/json",
        }
        try:
            resp = requests.get(url, params=request.GET, headers=headers, timeout=25)
        except requests.RequestException as e:
            return Response({"error": f"Upstream error: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        # Try to return JSON; if it fails, return a safe text payload for debugging
        try:
            data = resp.json()
            return Response(data, status=resp.status_code)
        except ValueError:
            content_type = resp.headers.get("Content-Type", "")
            text = resp.text or ""
            payload = {
                "error": "Upstream returned non-JSON response",
                "status": resp.status_code,
                "content_type": content_type,
                "body": text[:1000],  # truncate to avoid huge responses
            }
            return Response(payload, status=resp.status_code)


class CTraderOnboardCompleteProxyAPIView(APIView):
    """Proxy: POST -> FastAPI /ctrader/onboard/{account_id}/complete to finalize selection."""
    permission_classes = [IsAuthenticated]

    def post(self, request, account_id: str, *args, **kwargs):
        try:
            payload = request.data if hasattr(request, "data") else json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)

        url = f"{settings.CTRADER_API_BASE_URL.rstrip('/')}/ctrader/onboard/{account_id}/complete"
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Secret": settings.INTERNAL_SHARED_SECRET or "",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=25)
        except requests.RequestException as e:
            return Response({"error": f"Upstream error: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(resp.json() if resp.content else {}, status=resp.status_code)


# New proxies: connect/close and instance delete
class CTraderConnectProxyAPIView(APIView):
    """Proxy: POST -> FastAPI /ctrader/connect to ensure session for account_id."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            payload = request.data if hasattr(request, "data") else json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)

        url = f"{settings.CTRADER_API_BASE_URL.rstrip('/')}/ctrader/connect"
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Secret": settings.INTERNAL_SHARED_SECRET or "",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=25)
        except requests.RequestException as e:
            return Response({"error": f"Upstream error: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(resp.json() if resp.content else {}, status=resp.status_code)


class CTraderCloseProxyAPIView(APIView):
    """Proxy: POST -> FastAPI /ctrader/close to stop session."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            payload = request.data if hasattr(request, "data") else json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)

        url = f"{settings.CTRADER_API_BASE_URL.rstrip('/')}/ctrader/close"
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Secret": settings.INTERNAL_SHARED_SECRET or "",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=25)
        except requests.RequestException as e:
            return Response({"error": f"Upstream error: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(resp.json() if resp.content else {}, status=resp.status_code)


class CTraderInstanceDeleteProxyAPIView(APIView):
    """Proxy: DELETE -> FastAPI /ctrader/instance/{account_id} to delete runtime and mappings."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, account_id: str, *args, **kwargs):
        url = f"{settings.CTRADER_API_BASE_URL.rstrip('/')}/ctrader/instance/{account_id}"
        headers = {
            "X-Internal-Secret": settings.INTERNAL_SHARED_SECRET or "",
            "Accept": "application/json",
        }
        try:
            resp = requests.delete(url, headers=headers, timeout=25)
        except requests.RequestException as e:
            return Response({"error": f"Upstream error: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
        try:
            data = resp.json()
            return Response(data, status=resp.status_code)
        except ValueError:
            return Response({}, status=resp.status_code)
