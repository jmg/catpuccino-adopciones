# Generated by Django 2.0.13 on 2023-07-14 18:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0027_auto_20230713_2046'),
    ]

    operations = [
        migrations.AddField(
            model_name='catususer',
            name='animales_comentario',
            field=models.TextField(blank=True, null=True),
        ),
    ]
