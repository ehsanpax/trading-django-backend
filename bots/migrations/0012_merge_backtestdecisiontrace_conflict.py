# Merge migration to resolve conflicting leaf nodes for BacktestDecisionTrace
from django.db import migrations


class Migration(migrations.Migration):
    # Depend on the concrete 0012 migration to linearize the graph: 0011 -> 0012_rename... -> 0012_merge
    dependencies = [
        ('bots', '0012_rename_bots_backtest_bar_idx_bots_backte_backtes_14b9b1_idx_and_more'),
    ]

    operations = []
