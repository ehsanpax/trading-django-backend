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
        session_endpoint_url = "https://endlessly-central-gelding.ngrok-free.app/webhook/08dbc21f-2055-47ea-8aaf-c1dfe2dbc69f"
<<<<<<< Updated upstream

        schedule_message = f"Running schedule {schedule.name}.\n"
        context = schedule_message + str(schedule.context)

        data = {
            "context": context,
=======
        data = {
            "context": schedule.context,
>>>>>>> Stashed changes
            "session_id": str(schedule.session.external_session_id),
            "system_session_id": str(schedule.session.id),
            "trading_account_api_key": str(schedule.session.user_token),
            "backend_url": settings.BACKEND_URL,
        }
        request = requests.post(
            session_endpoint_url,
            json=data,
            timeout=None,
        )
<<<<<<< Updated upstream
        task_record.status = SessionScheduleTaskStatusChoices.SUCCESS.value
        task_record.result = request.content
        task_record.save()
=======

>>>>>>> Stashed changes
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
