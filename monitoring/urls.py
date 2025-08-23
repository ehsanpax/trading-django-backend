from django.urls import path
from .views import ConnectionStatusView

urlpatterns = [
    path('connections/', ConnectionStatusView.as_view(), name='connection-status'),
]
