from django.urls import path
from .views import EquityCurveView

urlpatterns = [
    path('equity-curve/<uuid:account_id>/', EquityCurveView.as_view(), name='equity-curve'),
]
