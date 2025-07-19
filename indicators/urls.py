from django.urls import path
from .views import AvailableIndicatorsView

urlpatterns = [
    path('available/', AvailableIndicatorsView.as_view(), name='available-indicators'),
]
