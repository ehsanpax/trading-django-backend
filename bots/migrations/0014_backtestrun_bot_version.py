from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('bots', '0013_backtestconfig_owner_and_optional_version'),
    ]

    operations = [
        migrations.AddField(
            model_name='backtestrun',
            name='bot_version',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='backtest_runs', to='bots.botversion'),
        ),
    ]
