from django.urls import path
from .views import (
    CTRaderLoginAPIView,
    CTRaderRedirectAPIView,
    CTRaderCallbackAPIView,
    CTRaderSelectAccountAPIView,
    CTraderOnboardProxyAPIView,
    CTraderOAuthCallbackProxyView,
    CTraderAccountsProxyAPIView,
    CTraderOnboardCompleteProxyAPIView,
    # new proxies
    CTraderConnectProxyAPIView,
    CTraderCloseProxyAPIView,
    CTraderInstanceDeleteProxyAPIView,
)

urlpatterns = [
    path("login/", CTRaderLoginAPIView.as_view(), name="ctrader-login"),
    path("redirect/", CTRaderRedirectAPIView.as_view(), name="ctrader-redirect"),
    path("callback/", CTRaderCallbackAPIView.as_view(), name="ctrader-callback"),
    path("select-account/", CTRaderSelectAccountAPIView.as_view(), name="ctrader-select-account"),
    # Proxy microservice endpoints
    path("onboard/", CTraderOnboardProxyAPIView.as_view(), name="ctrader-onboard-proxy"),
    path("oauth/callback", CTraderOAuthCallbackProxyView.as_view(), name="ctrader-oauth-callback-proxy"),
    path("accounts/", CTraderAccountsProxyAPIView.as_view(), name="ctrader-accounts-proxy"),
    # Accept string (UUID or int) for account_id
    path("onboard/<str:account_id>/complete", CTraderOnboardCompleteProxyAPIView.as_view(), name="ctrader-onboard-complete-proxy"),
    # Session management proxies
    path("connect/", CTraderConnectProxyAPIView.as_view(), name="ctrader-connect-proxy"),
    path("close/", CTraderCloseProxyAPIView.as_view(), name="ctrader-close-proxy"),
    path("instance/<str:account_id>", CTraderInstanceDeleteProxyAPIView.as_view(), name="ctrader-instance-delete-proxy"),
]
