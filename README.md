# trading-django-backend
USE THIS ONE- Django Backend

LiveRun health
- LiveRun has task_id, last_heartbeat, last_action_at.
- live_loop updates last_heartbeat every 5s and sets last_action_at when actions execute.
- Reconciler task bots.reconciler.reconcile_live_runs can be scheduled via Celery Beat to mark stale RUNNING as ERROR and finalize STOPPING to STOPPED when heartbeats are stale.

Test