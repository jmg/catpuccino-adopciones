# Generated by Django 2.0.13 on 2023-03-07 23:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0021_animal_instagram_post_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='animal',
            name='instagram_media_url',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
