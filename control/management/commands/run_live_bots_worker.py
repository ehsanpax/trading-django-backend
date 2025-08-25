import os
import uuid
import subprocess
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Starts the dedicated Celery worker for live bot runs (queue: live_bots)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hostname",
            type=str,
            required=False,
            default=None,
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            required=False,
            default=1,
        )
        parser.add_argument(
            "--pool",
            type=str,
            required=False,
            default="solo",  # safest for event loop isolation
            choices=["solo", "threads", "gevent", "prefork"],
        )

    def handle(self, *args, **options):
        hostname = options["hostname"] or f"live-bots-{uuid.uuid4().hex[:8]}@%h"
        concurrency = options["concurrency"]
        pool = options["pool"]

        celery_command = [
            "celery",
            "-A",
            "trading_platform.celery_app",
            "worker",
            "-Q",
            "live_bots",
            "--loglevel=info",
            f"--concurrency={concurrency}",
            "-P",
            pool,
            f"--hostname={hostname}",
            "--logfile=logs/celery_live_bots.log",
        ]

        self.stdout.write(
            f"Starting live-bots worker with command: {' '.join(celery_command)}"
        )

        # Ensure log dir exists
        os.makedirs("logs", exist_ok=True)

        subprocess.Popen(celery_command)
