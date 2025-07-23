from rest_framework import viewsets, permissions
from .models import Prompt
from .serializers import PromptSerializer, SessionExecutionSerializer
from rest_framework.views import APIView
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework import status


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
            return Prompt.objects.filter(user=user) | Prompt.objects.filter(
                is_globally_shared=True
            )
        return Prompt.objects.filter(is_globally_shared=True)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StoreSessionExecutionViewset(APIView):
    serializer_class = SessionExecutionSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        session_execution = serializer.save()
        return Response(
            {
                "message": "Session execution stored successfully",
                "id": str(session_execution.id),
            },
            status=status.HTTP_201_CREATED,
        )
