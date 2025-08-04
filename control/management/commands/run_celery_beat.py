import os
import subprocess
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Starts the Celery beat scheduler."

    def handle(self, *args, **options):
        # Ensure the log directory exists
        os.makedirs("logs", exist_ok=True)

        celery_command = [
            "celery",
            "-A",
            "trading_platform",
            "beat",
            "--loglevel=info",
            "--scheduler",
            "django_celery_beat.schedulers:DatabaseScheduler",
            "--logfile=logs/celery_beat.log",
        ]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Celery beat with command: {' '.join(celery_command)}"
            )
        )

        # Use subprocess.Popen to run celery beat in a separate process.
        subprocess.Popen(celery_command)
