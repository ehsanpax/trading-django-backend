# Generated manually to remove unique constraint on ('bot', 'code_hash') before removing the code_hash field

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bots", "0001_initial"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="botversion",
            unique_together=set(),
        ),
    ]
