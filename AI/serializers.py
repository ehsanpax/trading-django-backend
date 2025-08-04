from rest_framework import serializers
from .models import Prompt, Execution, ChatSession, SessionExecution, SessionSchedule
from trade_journal.models import TradeJournal
from django.db import models
from trading.models import Trade, Order
from trades.serializers import TradeSerializer, OrderSerializer
from .choices import WeekDayChoices
import datetime


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
    session_id = serializers.CharField()
    session = serializers.PrimaryKeyRelatedField(
        queryset=ChatSession.objects.all(),
        allow_null=True,
        required=False,
    )
    external_session_id = serializers.CharField(
        source="session.external_session_id", read_only=True
    )
    excluded_days = serializers.CharField(allow_blank=True, allow_null=True, required=False)

    class Meta:
        model = SessionSchedule
        fields = "__all__"
        read_only_fields = ["created_at"]

    def validate_excluded_days(self, value):
        new_value = []
        if value:
            days = value.split(",")
            for day in days:
                day = day.strip()
                if day not in WeekDayChoices.values:
                    raise serializers.ValidationError(
                        f"Invalid day: {day}. Must be one of {', '.join(WeekDayChoices.values)}."
                    )
                if day not in new_value:
                    new_value.append(day)
        return new_value

    def create(self, validated_data):
        session_id = validated_data.pop("session_id")
        name = validated_data.pop("name")
        session = ChatSession.objects.filter(external_session_id=session_id).first()
        if validated_data["start_at"]:
            validated_data["start_at"] = validated_data["start_at"].replace(
                tzinfo=datetime.timezone.utc
            )
        if validated_data["end_at"]:
            validated_data["end_at"] = validated_data["end_at"].replace(
                tzinfo=datetime.timezone.utc
            )

        schedule, created = SessionSchedule.objects.update_or_create(
            session=session,
            name=name,
            defaults=validated_data,
        )
        return schedule
