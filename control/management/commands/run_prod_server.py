import os
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Starts production server"

    def add_arguments(self, parser):
        parser.add_argument(
            "--concurrency",
            type=int,
            required=False,
            default=10,
        )

    def handle(self, *args, **options):
        concurrency = options["concurrency"]

        # Build the uvicorn command list
        uvicorn_command = [
            "uvicorn",
            "trading_platform.asgi:application",  # Adjust module path if needed
            "--host",
            "0.0.0.0",
            "--port",
            "80",
            "--workers",
            str(concurrency),
        ]

        self.stdout.write(
            f"Starting uvicorn server with command: {' '.join(uvicorn_command)}"
        )

        # Replace the current process with uvicorn
        os.execvp(uvicorn_command[0], uvicorn_command)
