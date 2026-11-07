# Default en la base, además del de Python, para las tres columnas NOT NULL que suman
# 0030, 0032 y 0034. Con el default solo en Python, MySQL las deja sin DEFAULT, y el
# release de antes de estas migraciones (un rollback del deploy) no sabe de ellas: cada
# alta de un animal daba IntegrityError 1364 "Field 'revision_ia_estado' doesn't have a
# default value". Con esto el código viejo sigue andando sobre la base migrada.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0035_merge_django52'),
    ]

    operations = [
        migrations.AlterField(
            model_name='animal',
            name='aprobado_por_persona',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AlterField(
            model_name='animal',
            name='instagram_intentos',
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
        migrations.AlterField(
            model_name='animal',
            name='revision_ia_estado',
            field=models.CharField(choices=[('P', 'Sin revisar'), ('OK', 'Parece correcta'), ('R', 'Revisar a mano'), ('E', 'No se pudo revisar')], db_default='P', default='P', max_length=2),
        ),
    ]
