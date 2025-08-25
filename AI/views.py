from rest_framework import viewsets, permissions
from .models import Prompt, ChatSession, SessionSchedule
from .serializers import (
    PromptSerializer,
    SessionExecutionSerializer,
    ChatSessionSerializer,
    TradeJournalSerializer,
    SessionScheduleSerializer,
)
from .choices import ChatSessionTypeChoices
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework import status
from trade_journal.models import TradeJournal
from django.db.models import Q
import uuid
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"  # /?page_size=50
    max_page_size = 200
    page_query_param = "page"


class PromptViewSet(viewsets.ModelViewSet):
    queryset = Prompt.objects.all()
    serializer_class = PromptSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication, JWTAuthentication]

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
    authentication_classes = [TokenAuthentication, JWTAuthentication]
    queryset = ChatSession.objects.filter(
        session_type=ChatSessionTypeChoices.CHAT.value
    )
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset().filter(user=self.request.user)

        archived = self.request.query_params.get("archived")
        include_archived = self.request.query_params.get("include_archived")

        if archived is not None:
            flag = str(archived).lower() in ("1", "true", "yes")
            qs = qs.filter(is_archived=flag)
        elif not (str(include_archived).lower() in ("1", "true", "yes")):
            qs = qs.filter(is_archived=False)

        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        session = self.get_object()
        # Idempotent
        if not session.is_archived:
            session.is_archived = True
            session.save(update_fields=["is_archived"])
        return Response({"status": "archived", "id": str(session.id)})

    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive(self, request, pk=None):
        session = ChatSession.objects.get(pk=pk, user=request.user)
        if session.is_archived:
            session.is_archived = False
            session.save(update_fields=["is_archived"])
        return Response({"status": "unarchived", "id": str(session.id)})


class TradeJournalViewset(ModelViewSet):
    serializer_class = TradeJournalSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication, JWTAuthentication]
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
            try:
                account_id = uuid.UUID(account_id, version=4)
                queryset = queryset.filter(
                    trade__account__id=account_id,
                    trade__account__user=self.request.user,
                )
            except Exception:
                queryset = queryset.filter(
                    trade__account__name__iexact=str(account_id),
                    trade__account__user=self.request.user,
                )

        return queryset


class SessionScheduleViewset(ModelViewSet):
    serializer_class = SessionScheduleSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication, JWTAuthentication]
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
            queryset = queryset.filter(
                Q(session__id=session_id) | Q(session__external_session_id=session_id)
            )
        name = self.request.query_params.get("name", None)
        if name:
            queryset = queryset.filter(name__iexact=name)

        return queryset
