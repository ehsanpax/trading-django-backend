import logging
from celery import current_task

class DatabaseLogHandler(logging.Handler):
    def emit(self, record):
        # Import model lazily to avoid AppRegistryNotReady error
        from .models import TaskLog

        if not current_task:
            return

        try:
            TaskLog.objects.create(
                task_id=current_task.request.id,
                log_level=record.levelname,
                message=self.format(record)
            )
        except Exception:
            # If logging to the DB fails, we can't do much without causing a loop.
            # You might want to log this to a file or stderr for debugging.
            pass
