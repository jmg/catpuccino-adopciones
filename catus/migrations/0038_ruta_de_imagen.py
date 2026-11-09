# Las imágenes subidas se guardan como gallery/<uuid><extensión> (catus.models.ruta_de_imagen):
# solo cambia el estado de Django, la base queda igual.
import catus.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0037_facebook_token_mas_largo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='animalimage',
            name='image',
            field=models.ImageField(upload_to=catus.models.ruta_de_imagen),
        ),
        migrations.AlterField(
            model_name='animalimage',
            name='image_for_instagram',
            field=models.ImageField(blank=True, null=True, upload_to=catus.models.ruta_de_imagen),
        ),
        migrations.AlterField(
            model_name='catususer',
            name='banner_img',
            field=models.ImageField(blank=True, default='static/defaults/banner_bg.png', null=True, upload_to=catus.models.ruta_de_imagen),
        ),
        migrations.AlterField(
            model_name='catususer',
            name='logo_img',
            field=models.ImageField(blank=True, default='static/defaults/logo.png', null=True, upload_to=catus.models.ruta_de_imagen),
        ),
    ]
