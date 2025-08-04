from celery import shared_task
from django.utils import timezone
from .models import SessionSchedule, SessionScheduleTask
from .choices import SessionScheduleTaskStatusChoices, ScheduleTypeChoices
from django.conf import settings
import requests


@shared_task
def process_one_time_schedules():
    """
    Processes one-time schedules that are due and have not yet been executed.
    A schedule is considered "not yet executed" if it has no related
    SessionScheduleTask objects.
    """
    now = timezone.now()
    schedules = SessionSchedule.objects.filter(
        type=ScheduleTypeChoices.ONE_TIME.value,
        start_at__lte=now,
        tasks__isnull=True,  # Check if any tasks have been created for this schedule
    )
    for schedule in schedules:
        # Dispatch the task for execution
        execute_session_schedule.delay(schedule.id)


@shared_task(bind=True)
def execute_session_schedule(self, schedule_id):
    try:
        schedule = SessionSchedule.objects.get(id=schedule_id)
        # Here you would add the logic that needs to be executed.
        # For now, we'll just simulate a successful execution.
        result_message = f"Successfully executed schedule {schedule.name}"

        SessionScheduleTask.objects.create(
            schedule=schedule,
            task_id=self.request.id,
            status=SessionScheduleTaskStatusChoices.STARTED.value,
            result=result_message,
        )
        session_endpoint_url = "https://endlessly-central-gelding.ngrok-free.app/webhook/08dbc21f-2055-47ea-8aaf-c1dfe2dbc69f"
        data = {
            "context": schedule.context,
            "session_id": schedule.session.external_session_id,
            "system_session_id": schedule.session.id,
            "trading_account_api_key": schedule.session.user_token,
            "backend_url": settings.BACKEND_URL,
        }
        request = requests.post(
            session_endpoint_url,
            json=data,
            timeout=None,
        )

        return result_message
    except SessionSchedule.DoesNotExist:
        # Handle the case where the schedule is not found
        return f"Schedule with id {schedule_id} not found."
    except Exception as e:
        # Handle other potential errors
        SessionScheduleTask.objects.create(
            schedule_id=schedule_id,
            task_id=self.request.id,
            status=SessionScheduleTaskStatusChoices.FAILURE.value,
            result=str(e),
        )
        return f"Failed to execute schedule {schedule_id}: {e}"
