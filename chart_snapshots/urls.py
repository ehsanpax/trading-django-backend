from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChartSnapshotConfigViewSet, ChartSnapshotViewSet, AdhocChartSnapshotCreateView

router = DefaultRouter()
router.register(r'configs', ChartSnapshotConfigViewSet, basename='chartsnapshotconfig')
router.register(r'snapshots', ChartSnapshotViewSet, basename='chartsnapshot') # For listing/retrieving

urlpatterns = [
    path('', include(router.urls)),
    path('snapshots/create-adhoc/', AdhocChartSnapshotCreateView.as_view(), name='adhoc-snapshot-create'),
]
