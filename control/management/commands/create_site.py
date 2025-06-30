from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from django.conf import settings


class Command(BaseCommand):
    help = "Create or Update Site Record"

    def handle(self, *args, **options):
        Site.objects.filter(domain="example.com").delete()
        site, created = Site.objects.update_or_create(
            domain=settings.SITE_URL, defaults=dict(name=settings.SITE_NAME)
        )

        if created:
            self.stdout.write(self.style.SUCCESS("Successfully created site."))
        else:
            self.stdout.write(self.style.SUCCESS("Site already exists."))
