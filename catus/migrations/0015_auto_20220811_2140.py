# Generated by Django 2.0.13 on 2022-08-12 00:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0014_facebookaccount'),
    ]

    operations = [
        migrations.AlterField(
            model_name='facebookaccount',
            name='profile_picture',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
    ]