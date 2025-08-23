from django.db import migrations

def backfill_scopes(apps, schema_editor):
    BacktestConfig = apps.get_model('bots', 'BacktestConfig')
    for cfg in BacktestConfig.objects.all().iterator():
        changed = False
        if cfg.bot_version and not cfg.bot_id:
            cfg.bot_id = cfg.bot_version.bot_id
            changed = True
        if not getattr(cfg, 'owner_id', None) and cfg.bot_version_id:
            # pick owner from bot
            try:
                cfg.owner_id = cfg.bot_version.bot.created_by_id
                changed = True
            except Exception:
                pass
        if changed:
            cfg.save(update_fields=['bot', 'owner'])


def backfill_runs(apps, schema_editor):
    BacktestRun = apps.get_model('bots', 'BacktestRun')
    for run in BacktestRun.objects.filter(bot_version__isnull=True).select_related('config__bot_version').iterator():
        if run.config and run.config.bot_version_id:
            run.bot_version_id = run.config.bot_version_id
            run.save(update_fields=['bot_version'])

class Migration(migrations.Migration):

    dependencies = [
        ('bots', '0014_backtestrun_bot_version'),
    ]

    operations = [
        migrations.RunPython(backfill_scopes, migrations.RunPython.noop),
        migrations.RunPython(backfill_runs, migrations.RunPython.noop),
    ]
