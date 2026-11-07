# Junta las dos ramas de migraciones: la de deploycloud (0029, first_name a 150 por
# Django 3.1) y la de master (0029 a 0034: recorte de Instagram, revisión con IA y
# posteo automático). No cambia nada de la primera.
#
# Además pasa el índice del cupo diario de la revisión con IA de index_together, que
# Django 5.1 sacó, a Meta.indexes. RenameIndex con old_fields es la conversión que
# documenta Django: renombra el índice que creó 0033, sin borrarlo ni volver a armarlo.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0029_alter_catususer_first_name'),
        ('catus', '0034_animal_aprobado_por_persona'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='revisioniallamada',
            new_name='catus_revia_pedido_fecha_idx',
            old_fields=('pedido_por', 'created_at'),
        ),
    ]
