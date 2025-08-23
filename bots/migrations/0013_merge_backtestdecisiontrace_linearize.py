# Merge migration to linearize bots migration graph after conflicting 0012 branches
from django.db import migrations


class Migration(migrations.Migration):
    # Depend on both 0012 branches so there is a single leaf at 0013
    dependencies = [
        ('bots', '0012_merge_backtestdecisiontrace_conflict'),
        ('bots', '0012_rename_bots_backtest_bar_idx_bots_backte_backtes_14b9b1_idx_and_more'),
    ]

    operations = []
