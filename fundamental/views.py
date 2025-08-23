
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime
from .models import EconomicCalendar, Currency, News
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.generics import ListAPIView
from .serializers import EconomicCalendarSerializer, NewsSerializer
from django.utils.dateparse import parse_date, parse_datetime
import logging

logger = logging.getLogger(__name__)


class EconomicCalendarAPIView(APIView):
    authentication_classes = [JWTAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        calendar_data = request.data.get("economic_calendar", [])
        if not isinstance(calendar_data, list):
            return Response(
                {"detail": "Invalid data format."}, status=status.HTTP_400_BAD_REQUEST
            )

        for item in calendar_data:
            try:
                event = item["event"]
                event_time_str = item["event_time"]  # e.g., "2025-01-16 00:00:00"
                if not event_time_str:
                    continue
                event_time_naive = datetime.strptime(
                    event_time_str, "%Y-%m-%d %H:%M:%S"
                )
                event_time = timezone.make_aware(
                    event_time_naive, timezone.get_current_timezone()
                )

                currency_code = item["currency"]
                currency_obj, _ = Currency.objects.get_or_create(currency=currency_code)

                EconomicCalendar.objects.update_or_create(
                    event=event,
                    event_time=event_time,
                    currency=currency_obj,
                    defaults={
                        "impact": item.get("impact"),
                        "actual": item.get("actual"),
                        "previous": item.get("previous"),
                        "forecast": item.get("forecast"),
                    },
                )
            except Exception as e:
                logger.error(f"Missing key in item: {e}")
                continue

        return Response(
            {"message": "Data processed successfully."}, status=status.HTTP_200_OK
        )


class EconomicCalendarEventListAPIView(APIView):
    authentication_classes = [JWTAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = EconomicCalendarSerializer

    def get_queryset(self):
        queryset = EconomicCalendar.objects.all().order_by("-event_time")

        # query parameters
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        currency = self.request.query_params.get("currency")
        impact = self.request.query_params.get("impact")
        event = self.request.query_params.get("event")

        if date_from and date_to:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d %H:%M:%S")
                date_from = timezone.make_aware(
                    date_from, timezone.get_current_timezone()
                )
                date_to = datetime.strptime(date_to, "%Y-%m-%d %H:%M:%S")
                date_to = timezone.make_aware(date_to, timezone.get_current_timezone())
                queryset = queryset.filter(
                    event_time__gte=date_from, event_time__lte=date_to
                )
            except ValueError:
                pass

        if currency:
            currencies = currency.split(",")
            queryset = queryset.filter(currency__currency__in=currencies)

        if impact:
            impacts = impact.split(",")
            queryset = queryset.filter(impact__in=impacts)

        if event:
            queryset = queryset.filter(event__icontains=event)

        return queryset

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.serializer_class(queryset, many=True)
        return Response(serializer.data)


class NewsAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        news_data = request.data.get("news", [])
        if not isinstance(news_data, list):
            return Response(
                {"detail": "Invalid data format. Expected a list of news."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for item in news_data:
            try:
                # parse time string to aware datetime
                time_str = item.get("Time")
                if not time_str:
                    continue

                try:

                    time_naive = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    event_time = timezone.make_aware(
                        time_naive, timezone.get_current_timezone()
                    )
                except ValueError:

                    event_time = None

                defaults = {
                    "headline": item.get("Headline"),
                    "time": event_time,
                    "source": item.get("Source"),
                    "content": item.get("Content"),
                }
                url = item.get("URL")
                if not url:
                    continue

                News.objects.update_or_create(url=url, defaults=defaults)

            except Exception as e:
                return Response(
                    {"detail": f"Error processing item: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            {"message": "News data processed successfully."}, status=status.HTTP_200_OK
        )


class NewsListAPIView(ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = NewsSerializer

    def get_queryset(self):
        queryset = News.objects.all().order_by("-time")

        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        source = self.request.query_params.get("source")

        if date_from and date_to:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d %H:%M:%S")
                date_from = timezone.make_aware(
                    date_from, timezone.get_current_timezone()
                )
                date_to = datetime.strptime(date_to, "%Y-%m-%d %H:%M:%S")
                date_to = timezone.make_aware(date_to, timezone.get_current_timezone())
                queryset = queryset.filter(time__gte=date_from, time__lte=date_to)
            except ValueError:
                pass

        if source:
            queryset = queryset.filter(source__iexact=source)

        return queryset
