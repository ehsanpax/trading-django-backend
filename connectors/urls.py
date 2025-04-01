from django.urls import path
from .views import account_balance

urlpatterns = [
    path('balance/', account_balance, name='account_balance'),
]