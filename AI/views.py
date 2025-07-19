from rest_framework import viewsets, permissions
from .models import Prompt
from .serializers import PromptSerializer

class PromptViewSet(viewsets.ModelViewSet):
    queryset = Prompt.objects.all()
    serializer_class = PromptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        This view should return a list of all prompts
        for the currently authenticated user, or globally shared prompts.
        """
        user = self.request.user
        if user.is_authenticated:
            return Prompt.objects.filter(user=user) | Prompt.objects.filter(is_globally_shared=True)
        return Prompt.objects.filter(is_globally_shared=True)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
