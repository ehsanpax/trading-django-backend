# fundumental/urls.py
from django.urls import path
from fundamental.views import EconomicCalendarAPIView, EconomicCalendarEventListAPIView

urlpatterns = [
    path(
        "economic-calendar/",
        EconomicCalendarAPIView.as_view(),
        name="economic_calendar",
    ),
    path('economic-calendar-list/', EconomicCalendarEventListAPIView.as_view(), name='economic-calendar-list'),
]

