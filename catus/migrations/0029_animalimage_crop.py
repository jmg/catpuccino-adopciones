from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0028_catususer_animales_comentario'),
    ]

    operations = [
        migrations.AddField(
            model_name='animalimage',
            name='crop_x',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='animalimage',
            name='crop_y',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='animalimage',
            name='crop_w',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='animalimage',
            name='crop_h',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
