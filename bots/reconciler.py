import logging
from datetime import timedelta
from django.utils import timezone
from celery import shared_task
from bots.models import LiveRun

logger = logging.getLogger(__name__)

HEARTBEAT_STALE_SECONDS = 30

@shared_task(bind=True)
def reconcile_live_runs(self):
    now = timezone.now()
    stale_after = timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    running = LiveRun.objects.filter(status='RUNNING')
    for lr in running:
        if not lr.last_heartbeat or (now - lr.last_heartbeat) > stale_after:
            logger.warning(f"LiveRun {lr.id} heartbeat stale. Marking ERROR.")
            LiveRun.objects.filter(id=lr.id).update(status='ERROR', last_error='Heartbeat stale or worker restart detected')

    stopping = LiveRun.objects.filter(status='STOPPING')
    for lr in stopping:
        # If no recent heartbeat and no task id, assume it's not running and mark STOPPED
        if not lr.last_heartbeat or (now - lr.last_heartbeat) > stale_after:
            logger.info(f"LiveRun {lr.id} in STOPPING with no heartbeat. Marking STOPPED.")
            LiveRun.objects.filter(id=lr.id).update(status='STOPPED', stopped_at=now)

    return {
        'running_checked': running.count(),
        'stopping_checked': stopping.count(),
    }
