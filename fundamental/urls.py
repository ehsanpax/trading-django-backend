# fundumental/urls.py
from django.urls import path
from fundamental.views import EconomicCalendarAPIView, EconomicCalendarEventListAPIView, NewsAPIView, NewsListAPIView

urlpatterns = [
    path(
        "economic-calendar/",
        EconomicCalendarAPIView.as_view(),
        name="economic_calendar",
    ),
    path('economic-calendar-list/', EconomicCalendarEventListAPIView.as_view(), name='economic-calendar-list'),
    path(
        "news-api/",
        NewsAPIView.as_view(),
        name="news_api",
    ),
    path('news-list/', NewsListAPIView.as_view(), name='news-list'),

]

