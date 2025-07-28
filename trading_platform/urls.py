"""
URL configuration for trading_platform project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    # ✅ JWT endpoints:
    path(
        "api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"
    ),  # login
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/accounts/", include("accounts.urls")),  # refresh token
    path("api/trades/", include("trades.urls")),
    path("api/ctrader/", include("ctrader_auth.urls")),
    path("api/risk/", include("risk.urls")),
    path("api/trade_journal/", include("trade_journal.urls")),
    path("api/connectors/", include("connectors.urls")),
    path("api/automations/", include("automations.urls")),
    path("api/calculators/", include("calculators.urls")),
    path("api/history/", include("trade_history.urls")),
    path("api/chart-snapshots/", include("chart_snapshots.urls")),
    path("api/analysis/", include("analysis.urls")),  # Added analysis app urls
    path("api/bots/", include("bots.urls")),  # Added bots app urls
    path("api/ta/", include("ta.urls")),
    path("api/ai/", include("AI.urls")),  # Added AI app urls
    path("api/user/", include("user.urls")),
    path("api/price/", include("price.urls")),
    path("api/charts/", include("charts.urls")),
    path("api/indicators/", include("indicators.urls")),
    path("api/", include("trading.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
