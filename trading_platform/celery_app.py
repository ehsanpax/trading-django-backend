import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trading_platform.settings")

app = Celery("trading_platform")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


# Define the beat schedule
app.conf.beat_schedule = {
    "process-one-time-schedules": {
        "task": "AI.tasks.process_one_time_schedules",
        "schedule": crontab(minute="*/1"),
    },
    "scan-profit-targets": {
        "task": "trades.tasks.scan_profit_targets",
        "schedule": crontab(minute="*/1"),  # Run every 1 minute
    },
    "reconcile-open-positions": {
        "task": "trades.tasks.reconcile_open_positions",
        "schedule": crontab(
            minute=0, hour="*/1"
        ),  # Run every hour at the beginning of the hour
    },
    "reconcile-live-runs": {
        "task": "bots.reconciler.reconcile_live_runs",
        "schedule": 30.0,  # every 30 seconds
    },
}


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")