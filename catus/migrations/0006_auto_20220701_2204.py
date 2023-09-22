# Generated by Django 2.0.13 on 2022-07-02 01:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0005_auto_20220617_2021'),
    ]

    operations = [
        migrations.AddField(
            model_name='catususer',
            name='banner_img',
            field=models.ImageField(blank=True, default='static/defaults/banner_bg.png', null=True, upload_to='gallery'),
        ),
        migrations.AddField(
            model_name='catususer',
            name='description',
            field=models.TextField(blank=True, default='Descripción del Perfil', null=True),
        ),
        migrations.AddField(
            model_name='catususer',
            name='facebook',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='catususer',
            name='logo_img',
            field=models.ImageField(blank=True, default='static/defaults/logo.png', null=True, upload_to='gallery'),
        ),
        migrations.AddField(
            model_name='catususer',
            name='title',
            field=models.CharField(blank=True, default='Título del Perfil', max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='catususer',
            name='twitter',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
