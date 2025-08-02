# fundumental/urls.py
from django.urls import path
from fundamental.views import EconomicCalendarAPIView

urlpatterns = [
    path(
        "economic-calendar/",
        EconomicCalendarAPIView.as_view(),
        name="economic_calendar",
    ),
]
