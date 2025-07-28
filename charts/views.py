from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
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
        user = self.request.user
        # Check if this is the first profile for the user
        if not ChartProfile.objects.filter(user=user).exists():
            serializer.validated_data['is_default'] = True
        elif serializer.validated_data.get('is_default'):
            # If a new profile is explicitly set as default, unset others
            ChartProfile.objects.filter(user=user, is_default=True).update(is_default=False)
        serializer.save(user=user)

    def perform_update(self, serializer):
        if serializer.validated_data.get('is_default'):
            ChartProfile.objects.filter(user=self.request.user, is_default=True).exclude(pk=self.get_object().pk).update(is_default=False)
        serializer.save()

    @action(detail=False, methods=['get'])
    def default(self, request):
        try:
            default_profile = ChartProfile.objects.get(user=request.user, is_default=True)
            serializer = self.get_serializer(default_profile)
            return Response(serializer.data)
        except ChartProfile.DoesNotExist:
            return Response({"detail": "No default chart profile found."}, status=status.HTTP_404_NOT_FOUND)
