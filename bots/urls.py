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
    path('strategies/metadata/', views.StrategyMetadataAPIView.as_view(), name='strategy-metadata'),
    path('indicators/metadata/', views.IndicatorMetadataAPIView.as_view(), name='indicator-metadata'),
    path('nodes/metadata/', views.NodeMetadataAPIView.as_view(), name='node-metadata'),
    path('nodes/schema/', views.NodeSchemaAPIView.as_view(), name='node-schema'),
    path('backtests/launch/', views.LaunchBacktestAPIView.as_view(), name='launch-backtest'),
    path('backtest-runs/<uuid:backtest_run_id>/chart-data/', views.BacktestChartDataAPIView.as_view(), name='backtest-chart-data'),
    path('live-runs/start/', views.StartLiveRunAPIView.as_view(), name='start-liverun'),
    path('live-runs/<uuid:live_run_id>/stop/', views.StopLiveRunAPIView.as_view(), name='stop-liverun'),
    path('strategy-config/generate', views.StrategyConfigGenerateAPIView.as_view(), name='strategy-config-generate'),
    path('', include(router.urls)),
]
