from django.db import migrations, models


class Migration(migrations.Migration):
    """Animal.revision_ia_intentos y Animal.espera_a_una_persona, para que ningún animal quede
    sin veredicto de la revisión con IA (services/revision_pendiente.py). Las dos con db_default:
    se deployan antes que el código que las usa, y el código anterior inserta animales sin
    nombrarlas."""

    dependencies = [
        ("catus", "0047_avisar_candidatos"),
    ]

    operations = [
        migrations.AddField(
            model_name="animal",
            name="revision_ia_intentos",
            field=models.PositiveSmallIntegerField(db_default=0, default=0),
        ),
        migrations.AddField(
            model_name="animal",
            name="espera_a_una_persona",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
