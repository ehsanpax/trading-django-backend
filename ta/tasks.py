# File: ta/tasks.py
# ────────────────────────────────
from celery import shared_task
from .services.analyzer import analyze


@shared_task(bind=True, acks_late=True, max_retries=3)
def run_ta_analysis(self, symbol: str, timeframe: str):
    obj, created = analyze(symbol, timeframe)
    return {"id": obj.id, "created": created}