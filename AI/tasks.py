from celery import shared_task
from django.utils import timezone
from .models import SessionSchedule, SessionScheduleTask
from .choices import SessionScheduleTaskStatusChoices, ScheduleTypeChoices
from django.conf import settings
import requests
from django_celery_beat.models import PeriodicTask
from django.db.models import Q


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
