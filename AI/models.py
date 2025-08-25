from django.db import models
from django.contrib.auth.models import User
from uuid import uuid4
from django.contrib.postgres.fields import ArrayField
import json
from django_celery_beat.models import (
    PeriodicTask,
    CrontabSchedule,
    IntervalSchedule,
    ClockedSchedule,
)
from django.utils import timezone
from typing import cast
from datetime import datetime
from django.conf import settings
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
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ai_prompts",
    )
    is_globally_shared = models.BooleanField(default=False)

    class Meta:
        unique_together = ("name", "user")


class Execution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_executions"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    external_execution_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
    )
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
    external_session_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    session_data = models.JSONField(default=dict, blank=True)
    user_first_message = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = ("external_session_id", "user")

    @property
    def user_token(self):
        # pylint: disable=no-member
        qs = Token.objects.filter(user=self.user)  # type: ignore[attr-defined]
        # pylint: enable=no-member
        token = qs.first()
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
    # Optional interval-based recurrence (e.g. every N minutes/hours/days)
    interval_every = models.PositiveIntegerField(null=True, blank=True)
    interval_period = models.CharField(
        max_length=24,
        choices=IntervalSchedule.PERIOD_CHOICES,  # type: ignore[attr-defined]
        null=True,
        blank=True,
    )
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
            use_interval = bool(self.interval_every and self.interval_period)
            if use_interval:
                # Build an interval schedule (ignores excluded_days at the
                # scheduler level; enforce blackout ranges/days in the task if
                # needed)
                # type: ignore[attr-defined]  # pylint: disable=no-member
                interval, _ = IntervalSchedule.objects.get_or_create(
                    every=self.interval_every,
                    period=self.interval_period,
                )

                task_name = f"session-schedule-{self.pk}"
                task_data = {
                    "interval": interval,
                    "crontab": None,
                    "solar": None,
                    "clocked": None,
                    "name": task_name,
                    "task": "AI.tasks.execute_session_schedule",
                    "args": json.dumps([self.pk]),
                    "start_time": self.start_at,
                    "expires": self.end_at,
                    "enabled": True,
                    "one_off": False,
                    "queue": getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", "default"),
                }

                # type: ignore[attr-defined]  # pylint: disable=no-member
                periodic_task, _ = PeriodicTask.objects.update_or_create(
                    name=task_name,
                    defaults=task_data,
                )

                if self.task != periodic_task:
                    # type: ignore[attr-defined]  # pylint: disable=no-member
                    SessionSchedule.objects.filter(pk=self.pk).update(
                        task=periodic_task
                    )
            elif self.start_at:
                # Determine allowed days by inverting excluded_days
                choices = getattr(WeekDayChoices, "choices", None)
                if choices:
                    all_days = [c[0] for c in choices]
                else:
                    all_days = list(getattr(WeekDayChoices, "values", []))

                if not self.excluded_days:
                    day_of_week = "*"
                else:
                    excluded = list(self.excluded_days or [])
                    allowed_days = [d for d in all_days if d not in excluded]
                    if not allowed_days:
                        # All days are excluded; ensure any existing task is
                        # disabled and stop here
                        if self.task:
                            self.task.enabled = False
                            self.task.save()
                        return
                    day_of_week = ",".join(map(str, allowed_days))

                # Use project timezone so the crontab fires at the intended
                # local time
                tzname = timezone.get_current_timezone_name()

                dt = cast(datetime, self.start_at)
                # type: ignore[attr-defined]  # pylint: disable=no-member
                schedule, _ = CrontabSchedule.objects.get_or_create(
                    minute=str(dt.minute),  # type: ignore[union-attr]
                    hour=str(dt.hour),  # type: ignore[union-attr]
                    day_of_week=day_of_week,
                    day_of_month="*",
                    month_of_year="*",
                    timezone=tzname,
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
                    "one_off": False,
                    "queue": getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", "default"),
                }

                # type: ignore[attr-defined]  # pylint: disable=no-member
                periodic_task, _ = PeriodicTask.objects.update_or_create(
                    name=task_name,
                    defaults=task_data,
                )

                if self.task != periodic_task:
                    # type: ignore[attr-defined]  # pylint: disable=no-member
                    SessionSchedule.objects.filter(pk=self.pk).update(
                        task=periodic_task
                    )
            elif self.task:
                self.task.enabled = False
                self.task.save()
        elif self.type == ScheduleTypeChoices.ONE_TIME.value:
            # For one-time schedules, use a ClockedSchedule so Celery Beat
            # fires the task exactly once at start_at.
            if self.start_at:
                # type: ignore[attr-defined]  # pylint: disable=no-member
                clocked, _ = ClockedSchedule.objects.get_or_create(
                    clocked_time=self.start_at
                )

                task_name = f"session-schedule-once-{self.pk}"
                task_data = {
                    "clocked": clocked,
                    "interval": None,
                    "crontab": None,
                    "solar": None,
                    "name": task_name,
                    "task": "AI.tasks.execute_session_schedule",
                    "args": json.dumps([self.pk]),
                    "expires": self.end_at,
                    "enabled": True,
                    "one_off": True,
                    "queue": getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", "default"),
                }

                # type: ignore[attr-defined]  # pylint: disable=no-member
                periodic_task, _ = PeriodicTask.objects.update_or_create(
                    name=task_name,
                    defaults=task_data,
                )

                if self.task != periodic_task:
                    # type: ignore[attr-defined]  # pylint: disable=no-member
                    SessionSchedule.objects.filter(pk=self.pk).update(
                        task=periodic_task
                    )
            else:
                # No start time: ensure no periodic task remains
                if self.task:
                    self.task.delete()
                    self.task = None

    def delete(self, *args, **kwargs):
        # Delete linked PeriodicTask and prune orphaned schedule objects
        if self.task:  # type: ignore[attr-defined]
            pt = self.task
            # Capture schedule refs before deleting the task
            interval = getattr(pt, "interval", None)
            crontab = getattr(pt, "crontab", None)
            clocked = getattr(pt, "clocked", None)
            solar = getattr(pt, "solar", None)

            # Delete the periodic task itself
            pt.delete()

            # If no other PeriodicTask uses these schedule rows, delete them
            try:
                if (
                    interval
                    and not PeriodicTask.objects.filter(interval=interval).exists()
                ):
                    interval.delete()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            try:
                if (
                    crontab
                    and not PeriodicTask.objects.filter(crontab=crontab).exists()
                ):
                    crontab.delete()
            except Exception:  # pragma: no cover
                pass
            try:
                if (
                    clocked
                    and not PeriodicTask.objects.filter(clocked=clocked).exists()
                ):
                    clocked.delete()
            except Exception:  # pragma: no cover
                pass
            try:
                if solar and not PeriodicTask.objects.filter(solar=solar).exists():
                    solar.delete()
            except Exception:  # pragma: no cover
                pass

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
