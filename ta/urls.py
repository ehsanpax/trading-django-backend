# File: ta/urls.py
# ────────────────────────────────
from rest_framework import routers
from .views import TAAnalysisViewSet

router = routers.DefaultRouter()
router.register(r"analyses", TAAnalysisViewSet, basename="ta-analysis")

urlpatterns = router.urls