from django.urls import path
from .views import RequiredWinRateView

urlpatterns = [
    path('required-win-rate/', RequiredWinRateView.as_view(), name='required-win-rate'),
]
