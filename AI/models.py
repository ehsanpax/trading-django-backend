from django.db import models
from django.contrib.auth.models import User
from uuid import uuid4
from .choices import ScheduleTypeChoices, ScheduleRecurrenceChoices, WeekDayChoices
from django.contrib.postgres.fields import ArrayField


class Prompt(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    user_prompt = models.TextField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    config = models.JSONField(default=dict)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_prompts")
    is_globally_shared = models.BooleanField(default=False)

    class Meta:
        unique_together = ("name", "user")


class Execution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_executions"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    external_execution_id = models.CharField(max_length=255, blank=True, db_index=True)
    total_cost = models.FloatField(null=True, blank=True)
    result = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("external_execution_id", "user")


class ChatSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_chat_sessions"
    )
    external_session_id = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    session_data = models.JSONField(default=dict, blank=True)
    user_first_message = models.TextField(blank=True)

    class Meta:
        unique_together = ("external_session_id", "user")


class SessionExecution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="executions"
    )
    execution = models.ForeignKey(
        Execution, on_delete=models.CASCADE, related_name="session_executions"
    )

    class Meta:
        unique_together = ("session", "execution")


class SessionSchedule(models.Model):
    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="schedules"
    )
    name = models.CharField(max_length=255)
    type = models.CharField(
        max_length=50,
        choices=ScheduleTypeChoices.choices,
        default=ScheduleTypeChoices.ONE_TIME.value,
    )
    recurrence = models.CharField(
        max_length=50,
        choices=ScheduleRecurrenceChoices.choices,
        default=ScheduleRecurrenceChoices.MINUTELY.value,
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)
    excluded_days = ArrayField(
        models.CharField(max_length=255, choices=WeekDayChoices.choices),
        blank=True,
        default=list,
    )
    excluded_time_ranges = models.JSONField(default=list, blank=True)
    context = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
