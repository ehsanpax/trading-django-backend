from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

class Migration(migrations.Migration):

    dependencies = [
        ('bots', '0012_rename_bots_backtest_bar_idx_bots_backte_backtes_14b9b1_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='backtestconfig',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='backtest_configs', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='backtestconfig',
            name='bot_version',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='backtest_configs', to='bots.botversion'),
        ),
    ]
