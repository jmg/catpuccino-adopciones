# Generated by Django 2.0.13 on 2022-06-14 19:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0002_animal_aprobado'),
    ]

    operations = [
        migrations.AddField(
            model_name='animal',
            name='zona',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]