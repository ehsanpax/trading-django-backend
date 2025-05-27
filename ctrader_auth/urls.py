from django.urls import path
from .views import (
    CTRaderLoginAPIView,
    CTRaderRedirectAPIView,
    CTRaderCallbackAPIView,
    CTRaderSelectAccountAPIView
)

urlpatterns = [
    path("login/", CTRaderLoginAPIView.as_view(), name="ctrader-login"),
    path("redirect/", CTRaderRedirectAPIView.as_view(), name="ctrader-redirect"),
    path("callback/", CTRaderCallbackAPIView.as_view(), name="ctrader-callback"),
    path("select-account/", CTRaderSelectAccountAPIView.as_view(), name="ctrader-select-account"),
]
