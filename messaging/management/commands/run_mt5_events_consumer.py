from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Entrypoint to run the MT5 events consumer"

    def handle(self, *args, **options):
        # Lazy import to avoid requiring pika unless this command is executed
        from messaging.consumer import Command as ConsumerCommand
        ConsumerCommand().handle(*args, **options)
