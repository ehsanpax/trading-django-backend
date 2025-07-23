from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .services import IndicatorService

class AvailableIndicatorsView(APIView):
    """
    An endpoint to retrieve a list of available technical indicators and their parameters.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """
        Returns a list of all available indicators that can be used on the platform.
        """
        indicator_service = IndicatorService()
        indicators = indicator_service.get_available_indicators()
        return Response(indicators)
