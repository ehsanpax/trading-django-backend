from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RequiredWinRateSerializer
from .services    import calc_required_hit_rate

class RequiredWinRateView(APIView):
    

    def post(self, request):
        s = RequiredWinRateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        p_min = calc_required_hit_rate(**s.validated_data)
        return Response({'required_hit_rate': round(p_min, 4)})
