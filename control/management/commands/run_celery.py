import os
import uuid
from django.core.management.base import BaseCommand



class Command(BaseCommand):
    help = "Starts the Celery worker"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hostname",
            type=str,
            required=False,
            default=None,  # No default value, it will be generated if not provided
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            required=False,
            default=10,
        )

    def handle(self, *args, **options):
        # Generate a unique hostname if not provided
        hostname = options["hostname"] or f"worker-{uuid.uuid4().hex}@%h"
        concurrency = options["concurrency"]

        # Construct the arguments for the celery command.
        # Note: We use a list of arguments directly.
        celery_command = [
            "celery",
            "-A",
            "trading_platform",  # Adjust your app name if necessary
            "worker",
            "-Q",
            "backtests,default",
            "--loglevel=info",
            f"--concurrency={concurrency}",
            "-P",
            "threads",
            f"--hostname={hostname}",
        ]

        # Log the command for debugging purposes (optional)
        self.stdout.write(
            f"Starting celery worker with command: {' '.join(celery_command)}"
        )

        # Use os.execvp to replace the current process with the celery process.
        # This way celery becomes the main process and will directly receive signals.
        os.execvp(celery_command[0], celery_command)

