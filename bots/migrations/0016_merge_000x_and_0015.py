from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('bots', '000X_backtestdecisiontrace'),
        ('bots', '0015_backfill_scopes'),
    ]

    operations = [
        # Merge migration to linearize branches from 000X_backtestdecisiontrace and 0015_backfill_scopes
    ]
