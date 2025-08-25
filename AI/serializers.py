from rest_framework import serializers
from .models import (
    Prompt,
    Execution,
    ChatSession,
    SessionExecution,
    SessionSchedule,
)
from trade_journal.models import TradeJournal
from django.db import models
from trades.serializers import TradeSerializer, OrderSerializer
from .choices import (
    WeekDayChoices,
    ChatSessionTypeChoices,
    ScheduleTypeChoices,
)
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule
from typing import Any, Mapping, cast
from datetime import timezone as dt_timezone


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
    session_type = serializers.ChoiceField(
        choices=ChatSessionTypeChoices.choices,
        default=ChatSessionTypeChoices.CHAT.value,
    )

    def create(self, validated_data):
        # Not used; save() implements the creation path.
        return validated_data

    def update(self, instance, validated_data):
        # Not used for this serializer; return instance unchanged.
        return instance

    def save(self, **kwargs):
        user = self.context["request"].user
        v = cast(Mapping[str, Any], self.validated_data)

        # Create or update the ChatSession
        # type: ignore[attr-defined]  # pylint: disable=no-member
        chat_session, _ = ChatSession.objects.update_or_create(
            external_session_id=v.get("external_session_id"),
            user=user,
            session_type=v.get("session_type"),
            defaults={
                "user_first_message": v.get("user_first_message"),
                "session_data": v.get("session_data"),
            },
        )

        # Create or update the Execution
        # type: ignore[attr-defined]  # pylint: disable=no-member
        execution, _ = Execution.objects.update_or_create(
            external_execution_id=v.get("external_execution_id"),
            user=user,
            defaults={
                "total_cost": v.get("total_cost"),
                "metadata": v.get("metadata"),
            },
        )

        # Link ChatSession and Execution
        # type: ignore[attr-defined]  # pylint: disable=no-member
        session_execution, _ = SessionExecution.objects.get_or_create(
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
            "is_archived",
        ]
        read_only_fields = [
            "user"
        ]  # User is set by the view, not directly by the client

    def get_total_cost(self, obj):
        """Sum total cost of all executions for this chat session."""
        agg = obj.executions.aggregate(total_cost=models.Sum("execution__total_cost"))
        return agg["total_cost"]


class TradeJournalSerializer(serializers.ModelSerializer):
    trade = TradeSerializer(allow_null=True, required=False, read_only=True)
    order = OrderSerializer(allow_null=True, required=False, read_only=True)

    class Meta:
        model = TradeJournal
        fields = "__all__"


class SessionScheduleSerializer(serializers.ModelSerializer):
    session_id = serializers.CharField()
    session = serializers.PrimaryKeyRelatedField(
        queryset=ChatSession.objects.all(),  # type: ignore[attr-defined]
        allow_null=True,
        required=False,
    )
    external_session_id = serializers.CharField(
        source="session.external_session_id", read_only=True
    )
    excluded_days = serializers.CharField(
        allow_blank=True, allow_null=True, required=False
    )
    interval_every = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    interval_period = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=IntervalSchedule.PERIOD_CHOICES,  # type: ignore[attr-defined]
    )

    class Meta:
        model = SessionSchedule
        fields = "__all__"
        read_only_fields = ["created_at"]

    def validate_excluded_days(self, value):
        new_value = []
        if value:
            if isinstance(value, list):
                days = value
            else:
                days = str(value).split(",")
            for day in days:
                day = str(day).strip()
                if day and day not in WeekDayChoices.values:
                    allowed = ", ".join(WeekDayChoices.values)
                    raise serializers.ValidationError(
                        f"Invalid day: {day}. Must be one of {allowed}."
                    )
                if day and day not in new_value:
                    new_value.append(day)
        return new_value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        sch_type = attrs.get("type")
        ie = attrs.get("interval_every")
        ip = attrs.get("interval_period")
        start_at = attrs.get("start_at")

        if sch_type == ScheduleTypeChoices.RECURRING.value:
            has_interval = ie is not None and ip is not None
            has_crontab = start_at is not None
            if not has_interval and not has_crontab:
                raise serializers.ValidationError(
                    "For RECURRING schedules, provide either interval_every "
                    "+ interval_period or a start_at time."
                )
        elif sch_type == ScheduleTypeChoices.ONE_TIME.value:
            # For one-time schedules, interval fields should not be set
            if ie is not None or ip is not None:
                raise serializers.ValidationError(
                    "interval_* fields are not allowed for ONE_TIME schedules."
                )
        return attrs

    def create(self, validated_data):
        session_id = validated_data.pop("session_id")
        name = validated_data.pop("name")
        # type: ignore[attr-defined]  # pylint: disable=no-member
        session = ChatSession.objects.filter(external_session_id=session_id).first()
        if not session:
            # type: ignore[attr-defined]  # pylint: disable=no-member
            session = ChatSession.objects.create(
                external_session_id=session_id,
                user=self.context["request"].user,
                session_type=ChatSessionTypeChoices.CHAT.value,
                user_first_message=f"Schedule {name}",
                session_data={},
            )

        if validated_data.get("start_at"):
            dt = validated_data["start_at"]
            if timezone.is_naive(dt):
                validated_data["start_at"] = timezone.make_aware(dt, dt_timezone.utc)
            else:
                validated_data["start_at"] = dt.astimezone(dt_timezone.utc)
        if validated_data.get("end_at"):
            dt = validated_data["end_at"]
            if timezone.is_naive(dt):
                validated_data["end_at"] = timezone.make_aware(dt, dt_timezone.utc)
            else:
                validated_data["end_at"] = dt.astimezone(dt_timezone.utc)

        # Avoid passing session inside defaults to prevent duplication
        validated_data.pop("session", None)

        # type: ignore[attr-defined]  # pylint: disable=no-member
        schedule, _ = SessionSchedule.objects.update_or_create(
            session=session,
            name=name,
            defaults=validated_data,
        )
        return schedule
