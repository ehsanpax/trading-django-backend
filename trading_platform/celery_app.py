import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_platform.settings')

app = Celery('trading_platform')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Define the beat schedule
app.conf.beat_schedule = {
    'monitor-mt5-stop-losses': {
        'task': 'mt5.tasks.monitor_mt5_stop_losses', # Path to the new task
        'schedule': crontab(minute='*/1'),  # Run every 1 minute
    },
    # Example of an existing task (if any, adjust as needed or remove if not present)
    # 'run-daily-at-midnight': {
    #     'task': 'indicators.tasks.run_daily_at_midnight',
    #     'schedule': crontab(hour=0, minute=0),
    # },
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
