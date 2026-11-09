# Field.slug como está la columna en la base de producción: varchar(200) NULL. Las
# migraciones decían 100 y NOT NULL, así que una base nueva (el staging, los tests) no podía
# cargar los slugs largos que ya existen (hasta 195 caracteres). En producción el ALTER no
# cambia nada.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('forms', '0003_sizes_from_settings'),
    ]

    operations = [
        migrations.AlterField(
            model_name='field',
            name='slug',
            field=models.SlugField(blank=True, default='', max_length=200, null=True, verbose_name='Slug'),
        ),
    ]
