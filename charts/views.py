from rest_framework import viewsets
from .models import ChartProfile
from .serializers import ChartProfileSerializer
from rest_framework.permissions import IsAuthenticated

class ChartProfileViewSet(viewsets.ModelViewSet):
    queryset = ChartProfile.objects.all()
    serializer_class = ChartProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
