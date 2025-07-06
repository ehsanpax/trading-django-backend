import os
import sys
import subprocess
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Starts dev server"

    def add_arguments(self, parser):
        parser.add_argument(
            "--concurrency",
            type=int,
            required=False,
            default=1, # Default to 1 worker for better Windows compatibility
        )

    def handle(self, *args, **options):
        concurrency = options["concurrency"]

        # On Windows, multiprocessing with uvicorn can cause issues.
        # Force concurrency to 1 worker to avoid OSError: [WinError 10022]
        if sys.platform == "win32" and concurrency > 1:
            self.stdout.write(
                self.style.WARNING(
                    "Warning: Limiting concurrency to 1 worker on Windows due to multiprocessing limitations."
                )
            )
            concurrency = 1

        # Build the uvicorn command list
        uvicorn_command = [
            sys.executable,  # Use sys.executable to ensure the correct python interpreter is used
            "-m",
            "uvicorn",
            "trading_platform.asgi:application",  # Adjust module path if needed
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            str(concurrency),
        ]

        self.stdout.write(
            f"Starting uvicorn server with command: {' '.join(uvicorn_command)}"
        )

        # Run uvicorn as a subprocess instead of replacing the current process
        # This is more compatible with Windows multiprocessing behavior.
        try:
            subprocess.run(uvicorn_command, check=True)
        except subprocess.CalledProcessError as e:
            self.stderr.write(self.style.ERROR(f"Uvicorn server exited with error: {e}"))
            sys.exit(1)
