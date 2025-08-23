from django.db import models
from django.contrib.auth.models import User
from uuid import uuid4
from django.contrib.postgres.fields import ArrayField
import json
from django_celery_beat.models import PeriodicTask, CrontabSchedule
from .choices import (
    ScheduleTypeChoices,
    WeekDayChoices,
    SessionScheduleTaskStatusChoices,
    ChatSessionTypeChoices,
)
from rest_framework.authtoken.models import Token


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
    session_type = models.CharField(
        max_length=50,
        choices=ChatSessionTypeChoices.choices,
        default=ChatSessionTypeChoices.CHAT.value,
    )
    external_session_id = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    session_data = models.JSONField(default=dict, blank=True)
    user_first_message = models.TextField(blank=True)

    class Meta:
        unique_together = ("external_session_id", "user")

    @property
    def user_token(self):
        token = Token.objects.filter(user=self.user).first()
        if token:
            return token.key


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
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    excluded_days = ArrayField(
        models.CharField(max_length=255, choices=WeekDayChoices.choices),
        blank=True,
        null=True,
        default=list,
    )
    excluded_time_ranges = models.JSONField(default=list, blank=True)
    context = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    task = models.OneToOneField(
        PeriodicTask, on_delete=models.SET_NULL, null=True, blank=True
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if self.type == ScheduleTypeChoices.RECURRING.value:
            if self.start_at:
                schedule, _ = CrontabSchedule.objects.get_or_create(
                    minute=str(self.start_at.minute),
                    hour=str(self.start_at.hour),
                    day_of_week=(
                        ",".join(map(str, self.excluded_days))
                        if self.excluded_days
                        else "*"
                    ),
                )

                task_name = f"session-schedule-{self.pk}"
                task_data = {
                    "crontab": schedule,
                    "name": task_name,
                    "task": "AI.tasks.execute_session_schedule",
                    "args": json.dumps([self.pk]),
                    "start_time": self.start_at,
                    "expires": self.end_at,
                    "enabled": True,
                }

                periodic_task, _ = PeriodicTask.objects.update_or_create(
                    name=task_name, defaults=task_data
                )

                if self.task != periodic_task:
                    SessionSchedule.objects.filter(pk=self.pk).update(
                        task=periodic_task
                    )
            elif self.task:
                self.task.enabled = False
                self.task.save()
        elif self.type == ScheduleTypeChoices.ONE_TIME.value:
            if self.task:
                self.task.delete()
                self.task = None
            # One-time tasks are handled by the `process_one_time_schedules` Celery task
            pass

    def delete(self, *args, **kwargs):
        if self.task:
            self.task.delete()  # pylint: disable=no-member
        return super().delete(*args, **kwargs)


class SessionScheduleTask(models.Model):
    schedule = models.ForeignKey(
        SessionSchedule, on_delete=models.CASCADE, related_name="tasks"
    )
    task_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=50,
        choices=SessionScheduleTaskStatusChoices.choices,
        default=SessionScheduleTaskStatusChoices.PENDING,
    )
    result = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
