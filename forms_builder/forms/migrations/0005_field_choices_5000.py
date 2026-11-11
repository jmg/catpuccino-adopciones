# Field.choices de 1000 a 5000 caracteres (FORMS_BUILDER_CHOICES_MAX_LENGTH). El desplegable "Gato a
# adoptar" lleva los ids de todos los gatos en adopción y el 2026-11-11 ocupaba 918 de 1000: pasados los
# 1000, MySQL estricto rechaza el UPDATE y el desplegable deja de sumar animales. Agrandar un varchar no
# toca los datos.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('forms', '0004_field_slug_como_en_produccion'),
    ]

    operations = [
        migrations.AlterField(
            model_name='field',
            name='choices',
            field=models.CharField(blank=True, help_text='Comma separated options where applicable. If an option itself contains commas, surround the option starting with the `character and ending with the ` character.', max_length=5000, verbose_name='Choices'),
        ),
    ]
