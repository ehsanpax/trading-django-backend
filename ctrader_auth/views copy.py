import os
import json
import urllib.parse
import requests

from django.shortcuts import redirect
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from utils.utils import token_required

# cTrader OAuth Configuration (adjust these values as needed)
CLIENT_ID = "13641_QqAQIxv5R7wUGHoSjbKTalzNMPbyDEt6b9I8VxgwUO3rs3qN0P"
CLIENT_SECRET = "tFzXEFQi2fYtaIWm7xdz54n6jhnT5dQHGT82Jf5Z3J6DSUwV1i"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
REDIRECT_URI = f"{API_BASE_URL}/ctrader/callback"
AUTH_URL = "https://connect.spotware.com/oauth/v2/auth"
TOKEN_URL = "https://connect.spotware.com/oauth/v2/token"
TOKEN_STORAGE = os.path.join(os.getcwd(), "ctrader_tokens.json")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CTRADER_ACCOUNTS_URL = "https://api.spotware.com/connect/tradingaccounts"

class CTRaderLoginView(View):
    """
    Initiates the cTrader OAuth flow.
    """
    def get(self, request):
        auth_redirect_url = (
            f"{AUTH_URL}?client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=trading"
        )
        return JsonResponse({"redirect_url": auth_redirect_url})


@method_decorator(token_required, name='get')
class CTRaderRedirectView(View):
    """
    Stores the pending account ID in session and redirects to cTrader.
    """
    def get(self, request):
        print(2222, request.user)
        account_id = request.GET.get("account_id")
        if not account_id:
            return HttpResponseBadRequest("Missing account_id parameter.")
        request.session["pending_account_id"] = account_id
        auth_url = (
            f"https://connect.spotware.com/apps/auth?"
            f"client_id={CLIENT_ID}"
            f"&response_type=code"
            f"&redirect_uri={REDIRECT_URI}"
            f"&scope=trading"
        )
        # Return JSON if the request expects JSON; otherwise, perform a redirect.
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"redirect_url": auth_url})
        print(11111, auth_url)
        return redirect(auth_url)


class CTRaderCallbackView(View):
    """
    Handles the callback from cTrader OAuth.
    Exchanges the code for tokens, fetches account data, and redirects to frontend.
    """
    def get(self, request):
        code = request.GET.get("code")
        pending_account_id = request.session.get("pending_account_id")
        if not code or not pending_account_id:
            return HttpResponseBadRequest("Missing code or pending account id.")

        # Exchange authorization code for tokens
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
            return JsonResponse({"error": "Failed to get access token."}, status=400)
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not access_token:
            return JsonResponse({"error": "Invalid access token received."}, status=400)

        # Fetch available cTrader trading accounts using the access token
        accounts_url = f"{CTRADER_ACCOUNTS_URL}?access_token={access_token}"
        accounts_response = requests.get(accounts_url)
        if accounts_response.status_code != 200:
            return JsonResponse({"error": "Failed to retrieve trading accounts."}, status=400)
        try:
            accounts_data = accounts_response.json()
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid response format from cTrader."}, status=400)
        if "data" not in accounts_data or not accounts_data["data"]:
            return JsonResponse({"error": "No linked trading accounts found."}, status=400)
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

        # Save tokens to TOKEN_STORAGE for later use
        try:
            with open(TOKEN_STORAGE, "w") as file:
                json.dump({"access_token": access_token, "refresh_token": refresh_token}, file)
        except Exception as e:
            return JsonResponse({"error": "Failed to store tokens."}, status=500)

        # Redirect user to frontend to select a specific cTrader account
        encoded_accounts = urllib.parse.quote(json.dumps(formatted_accounts))
        frontend_redirect = f"{FRONTEND_URL}/select-ctrader-account?accounts={encoded_accounts}"
        return redirect(frontend_redirect)


@method_decorator(csrf_exempt, name='dispatch')
class CTRaderSelectAccountView(View):
    """
    Finalizes linking the selected cTrader account to the internal account.
    """
@method_decorator(csrf_exempt, name='dispatch')
class CTRaderSelectAccountView(View):
    """
    Finalizes linking the selected cTrader account to the internal account.
    """
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON."}, status=400)
        
        selected_account_id = data.get("accountId")
        if not selected_account_id:
            return JsonResponse({"error": "No account selected."}, status=400)
        
        pending_account_id = request.session.get("pending_account_id")
        if not pending_account_id:
            return JsonResponse({"error": "Session lost! Internal account ID missing."}, status=400)
        
        # Retrieve the stored accounts list from session
        stored_accounts = request.session.get("ctrader_accounts", [])
        # Find the selected account in the stored list
        selected_account = next(
            (acc for acc in stored_accounts if str(acc["accountId"]) == str(selected_account_id)), 
            None
        )
        if not selected_account:
            return JsonResponse({"error": "Selected account not found in session."}, status=400)
        
        try:
            with open(TOKEN_STORAGE, "r") as file:
                tokens = json.load(file)
        except Exception as e:
            return JsonResponse({"error": "Missing cTrader tokens."}, status=400)
        
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            return JsonResponse({"error": "Missing access or refresh token."}, status=400)
        
        # Update the CTraderAccount in the database
        from accounts.models import CTraderAccount  # Assuming your CTraderAccount is in accounts.models
        try:
            ctrader_account = CTraderAccount.objects.get(account__id=pending_account_id)
        except CTraderAccount.DoesNotExist:
            return JsonResponse({"error": "Internal account not found! Cannot link cTrader account."}, status=400)
        
        # Update all desired fields from the selected account data
        ctrader_account.account_number = selected_account.get("accountNumber")
        ctrader_account.ctid_trader_account_id = selected_account.get("accountId")
        ctrader_account.currency = selected_account.get("depositCurrency")
        ctrader_account.broker = selected_account.get("brokerTitle")
        ctrader_account.live = selected_account.get("live")
        ctrader_account.leverage = selected_account.get("leverage")
        ctrader_account.access_token = access_token
        ctrader_account.refresh_token = refresh_token
        
        ctrader_account.save()
        return JsonResponse({"message": "Account successfully linked to cTrader!"})

