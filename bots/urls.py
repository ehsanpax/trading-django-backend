# Bots URL Configuration
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'bots'

router = DefaultRouter()
router.register(r'bots', views.BotViewSet, basename='bot')
router.register(r'versions', views.BotVersionViewSet, basename='botversion')
router.register(r'backtest-configs', views.BacktestConfigViewSet, basename='backtestconfig')
router.register(r'backtest-runs', views.BacktestRunViewSet, basename='backtestrun')
router.register(r'live-runs', views.LiveRunViewSet, basename='liverun')

urlpatterns = [
    path('', include(router.urls)),
    path('strategy-templates/', views.ListStrategyTemplatesAPIView.as_view(), name='list-strategy-templates'),
    path('backtests/launch/', views.LaunchBacktestAPIView.as_view(), name='launch-backtest'),
    path('live-runs/start/', views.StartLiveRunAPIView.as_view(), name='start-liverun'),
    path('live-runs/<uuid:live_run_id>/stop/', views.StopLiveRunAPIView.as_view(), name='stop-liverun'),
]
