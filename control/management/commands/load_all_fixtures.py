from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Loads all fixtures"

    def handle(self, *args, **options):
        fixtures = []

        for fixture in fixtures:
            self.stdout.write(f"Loading fixture: {fixture}")
            call_command("loaddata", fixture)
            self.stdout.write(f"Loaded fixture: {fixture}")

        self.stdout.write(self.style.SUCCESS("All fixtures are loaded."))
