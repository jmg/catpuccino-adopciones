# Generated by Django 2.0.13 on 2022-08-16 18:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0017_auto_20220812_0001'),
    ]

    operations = [
        migrations.AddField(
            model_name='animalimage',
            name='posicion',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
