# Generated by Django 2.0.13 on 2022-06-14 19:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0003_animal_zona'),
    ]

    operations = [
        migrations.AddField(
            model_name='animal',
            name='edad_en_meses',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]