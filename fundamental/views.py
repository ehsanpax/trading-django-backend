from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime
from .models import EconomicCalendar, Currency
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListAPIView
from .serializers import EconomicCalendarSerializer


class EconomicCalendarAPIView(APIView):
    authentication_classes = [TokenAuthentication]
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

                # Update or create the event
                EconomicCalendar.objects.update_or_create(
                    event=event,
                    event_time=event_time,
                    defaults={
                        "impact": item.get("impact"),
                        "actual": item.get("actual"),
                        "previous": item.get("previous"),
                        "forecast": item.get("forecast"),
                        "currency": currency_obj,
                    },
                )
            except KeyError as e:
                return Response(
                    {"detail": f"Missing field: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except ValueError as e:
                return Response(
                    {"detail": f"Date parsing error: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            {"message": "Data processed successfully."}, status=status.HTTP_200_OK
        )


class EconomicCalendarEventListAPIView(ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = EconomicCalendar.objects.all().order_by('-event_time')
    serializer_class = EconomicCalendarSerializer