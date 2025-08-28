from celery import shared_task
from django.utils import timezone
from .models import SessionSchedule, SessionScheduleTask
from .choices import SessionScheduleTaskStatusChoices, ScheduleTypeChoices
from django.conf import settings
import requests
from django_celery_beat.models import PeriodicTask
from django.db.models import Q
from datetime import time as dtime


@shared_task
def process_one_time_schedules():
    """
    Ensure ONE_TIME schedules are executed once.
    If a schedule has a linked PeriodicTask (clocked), skip.
    Otherwise, if due now, dispatch immediately.
    """
    now = timezone.now()
    schedules = (
        SessionSchedule.objects.filter(
            type=ScheduleTypeChoices.ONE_TIME.value,
            start_at__lte=now,
        )
        .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
        .exclude(tasks__isnull=False)  # skip ones already executed
    )
    for schedule in schedules:
        # If a clocked/periodic task exists and is enabled, handle it
        sid = str(schedule.pk)
        has_task = bool(schedule.task and isinstance(schedule.task, PeriodicTask))
        if has_task and schedule.task:  # type: ignore[truthy-function]
            clocked = getattr(schedule.task, "clocked", None)
            clocked_time = getattr(clocked, "clocked_time", None)
            is_due = bool(clocked_time and clocked_time <= now)
            if schedule.task.enabled and is_due:
                # Disable the clocked task to avoid double-send, then fire now
                schedule.task.enabled = False
                schedule.task.save(update_fields=["enabled"])
                execute_session_schedule.apply_async(
                    args=(sid,),
                    queue=getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", "default"),
                )  # type: ignore[misc]
                continue
            # If it's not due yet, skip; beat will handle it
            continue
        # No PeriodicTask wired; dispatch now
        execute_session_schedule.apply_async(
            args=(sid,),
            queue=getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", "default"),
        )  # type: ignore[misc]


@shared_task(bind=True)
def execute_session_schedule(self, schedule_id):
    task_record = None
    try:
        schedule = SessionSchedule.objects.get(id=schedule_id)
        # Blackout handling for excluded days and time ranges
        now_local = timezone.localtime(timezone.now())
        current_day = now_local.strftime("%A").upper()

        # If today is excluded, skip execution
        excluded_days = list(schedule.excluded_days or [])
        if excluded_days and current_day in excluded_days:
            msg = f"Skipped schedule {schedule.name}: excluded day " f"{current_day}."
            SessionScheduleTask.objects.create(
                schedule=schedule,
                task_id=self.request.id,
                status=SessionScheduleTaskStatusChoices.SUCCESS.value,
                result=msg,
            )
            return msg

        # Excluded time ranges structure:
        # [ {"start": "HH:MM"[, "end": "HH:MM"][, "days": ["MONDAY", ...]] },
        #   ... ]
        def _parse_time(val):
            if not val:
                return None
            try:
                parts = [int(p) for p in str(val).split(":")]
                while len(parts) < 3:
                    parts.append(0)
                return dtime(parts[0], parts[1], parts[2])
            except Exception:
                return None

        def _in_range(now_t, start_t, end_t):
            # Handles overnight windows when start > end
            if not start_t or not end_t:
                return False
            if start_t <= end_t:
                return start_t <= now_t < end_t
            return now_t >= start_t or now_t < end_t

        now_t = now_local.time()
        ranges = schedule.excluded_time_ranges or []
        for rng in ranges:
            try:
                days = rng.get("days") or rng.get("weekdays")
                if days:
                    days = [str(d).upper() for d in days]
                    if current_day not in days:
                        continue
                start_t = _parse_time(
                    rng.get("start") or rng.get("from") or rng.get("start_time")
                )
                end_t = _parse_time(
                    rng.get("end") or rng.get("to") or rng.get("end_time")
                )
                if _in_range(now_t, start_t, end_t):
                    msg = (
                        f"Skipped schedule {schedule.name}: excluded time "
                        f"range {start_t}-{end_t} on {current_day}."
                    )
                    SessionScheduleTask.objects.create(
                        schedule=schedule,
                        task_id=self.request.id,
                        status=SessionScheduleTaskStatusChoices.SUCCESS.value,
                        result=msg,
                    )
                    return msg
            except Exception:
                # Ignore malformed range entries
                continue
        # Here you would add the logic that needs to be executed.
        # For now, we'll just simulate a successful execution.
        result_message = f"Successfully executed schedule {schedule.name}"

        task_record = SessionScheduleTask.objects.create(
            schedule=schedule,
            task_id=self.request.id,
            status=SessionScheduleTaskStatusChoices.STARTED.value,
            result=result_message,
        )
        session_endpoint_url = (
            "https://endlessly-central-gelding.ngrok-free.app/webhook/"
            "08dbc21f-2055-47ea-8aaf-c1dfe2dbc69f"
        )

        schedule_message = f"Running schedule {schedule.name}.\n"
        context = schedule_message + str(schedule.context)

        data = {
            "context": context,
            "session_id": str(schedule.session.external_session_id),
            "system_session_id": str(schedule.session.id),
            "trading_account_api_key": str(schedule.session.user_token),
            "backend_url": settings.BACKEND_URL,
        }
        resp = requests.post(
            session_endpoint_url,
            json=data,
            timeout=None,
        )
        task_record.status = SessionScheduleTaskStatusChoices.SUCCESS.value
        task_record.result = resp.text
        task_record.save()
        return result_message
    except SessionSchedule.DoesNotExist:
        # Handle the case where the schedule is not found
        return f"Schedule with id {schedule_id} not found."
    except Exception as e:
        # Handle other potential errors
        if task_record:
            task_record.status = SessionScheduleTaskStatusChoices.FAILURE.value
            task_record.result = str(e)
            task_record.save()

        return f"Failed to execute schedule {schedule_id}: {e}"
