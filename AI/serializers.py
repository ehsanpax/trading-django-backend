from rest_framework import serializers
from .models import Prompt, Execution, ChatSession, SessionExecution, SessionSchedule
from trade_journal.models import TradeJournal
from django.db import models
from trading.models import Trade, Order
from trades.serializers import TradeSerializer, OrderSerializer


class PromptSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Prompt
        exclude = ["user", "active", "is_globally_shared"]

    def create(self, validated_data):
        user = self.context["request"].user
        name = validated_data.pop("name")
        prompt, _ = Prompt.objects.update_or_create(
            user=user, name=name, defaults=validated_data
        )
        return prompt


class SessionExecutionSerializer(serializers.Serializer):
    external_execution_id = serializers.CharField(
        max_length=255,
        required=False,
    )
    external_session_id = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    metadata = serializers.JSONField(default=dict, required=False)
    user_first_message = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )
    session_data = serializers.JSONField(default=dict, required=False)
    total_cost = serializers.FloatField(required=False, allow_null=True)

    def save(self, **kwargs):
        user = self.context["request"].user
        chat_session, updated = ChatSession.objects.update_or_create(
            external_session_id=self.validated_data.get("external_session_id"),
            user=user,
            defaults=dict(
                user_first_message=self.validated_data.get("user_first_message"),
                session_data=self.validated_data.get("session_data"),
            ),
        )
        execution, updated = Execution.objects.update_or_create(
            external_execution_id=self.validated_data.get("external_execution_id"),
            user=user,
            defaults={
                "total_cost": self.validated_data.get("total_cost"),
                "metadata": self.validated_data.get("metadata"),
            },
        )
        session_execution, created = SessionExecution.objects.get_or_create(
            session=chat_session,
            execution=execution,
        )
        return session_execution


class ChatSessionSerializer(serializers.ModelSerializer):
    total_cost = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            "id",
            "external_session_id",
            "user_first_message",
            "session_data",
            "user",
            "created_at",
            "total_cost",
        ]
        read_only_fields = [
            "user"
        ]  # User is set by the view, not directly by the client

    def get_total_cost(self, obj):
        """
        Calculate the total cost of all executions associated with this chat session.
        """
        return obj.executions.aggregate(total_cost=models.Sum("execution__total_cost"))[
            "total_cost"
        ]


class TradeJournalSerializer(serializers.ModelSerializer):
    trade = TradeSerializer(allow_null=True, required=False, read_only=True)
    order = OrderSerializer(allow_null=True, required=False, read_only=True)

    class Meta:
        model = TradeJournal
        fields = "__all__"


class SessionScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionSchedule
        fields = "__all__"
        read_only_fields = ["created_at"]
