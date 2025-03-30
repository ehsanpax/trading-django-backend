from django.urls import path
from .views import (
    CTRaderLoginAPIView,
    CTRaderRedirectAPIView,
    CTRaderCallbackAPIView,
    CTRaderSelectAccountAPIView
)

urlpatterns = [
    path("api/ctrader/login/", CTRaderLoginAPIView.as_view(), name="ctrader-login"),
    path("api/ctrader/redirect/", CTRaderRedirectAPIView.as_view(), name="ctrader-redirect"),
    path("callback/", CTRaderCallbackAPIView.as_view(), name="ctrader-callback"),
    path("api/ctrader/select-account/", CTRaderSelectAccountAPIView.as_view(), name="ctrader-select-account"),
]
