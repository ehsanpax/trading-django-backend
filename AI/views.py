from rest_framework import viewsets, permissions
from .models import Prompt, ChatSession, SessionSchedule
from .serializers import (
    PromptSerializer,
    SessionExecutionSerializer,
    ChatSessionSerializer,
    TradeJournalSerializer,
    SessionScheduleSerializer,
)
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework import status
from trade_journal.models import TradeJournal
from django.db.models import Q


class PromptViewSet(viewsets.ModelViewSet):
    queryset = Prompt.objects.all()
    serializer_class = PromptSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]

    def get_queryset(self):
        """
        This view should return a list of all prompts
        for the currently authenticated user, or globally shared prompts.
        """
        user = self.request.user
        if user.is_authenticated:
            queryset = Prompt.objects.filter(
                Q(user=user) | Q(is_globally_shared=True)
            ).order_by("-created_at")
        else:
            queryset = Prompt.objects.filter(is_globally_shared=True)
        prompt_name = self.request.query_params.get("name", None)
        if prompt_name:
            queryset = queryset.filter(name=prompt_name)
        return queryset


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


class ChatSessionViewset(ModelViewSet):
    serializer_class = ChatSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = ChatSession.objects.all()

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(user=self.request.user)
            .order_by("-created_at")
        )


class TradeJournalViewset(ModelViewSet):
    serializer_class = TradeJournalSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    queryset = TradeJournal.objects.all()
    pagination_class = None  # Disable pagination for simplicity

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(trade__account__user=self.request.user)
            .order_by("-created_at")
        )
        account_id = self.request.query_params.get("account", None)
        if account_id:
            queryset = queryset.filter(
                Q(trade__account__id=account_id) | Q(trade__account__simple_id=True)
            )
        return queryset


class SessionScheduleViewset(ModelViewSet):
    serializer_class = SessionScheduleSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    queryset = SessionSchedule.objects.all()

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(session__user=self.request.user)
            .order_by("-created_at")
        )
        session_id = self.request.query_params.get("session_id", None)
        if session_id:
            queryset = queryset.filter(session__id=session_id)
        name = self.request.query_params.get("name", None)
        if name:
            queryset = queryset.filter(name__iexact=name)

        return queryset
