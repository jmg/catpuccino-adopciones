from django.db import migrations, models


class Migration(migrations.Migration):
    """Animal.avisar_candidatos: lo que eligió el rescatista, al marcarlo adoptado, sobre avisarles
    a los demás que se postularon (services/aviso_candidatos.py). Nullable: el código anterior
    no la conoce y sigue andando con la columna puesta."""

    dependencies = [
        ("catus", "0046_edad_en_meses"),
    ]

    operations = [
        migrations.AddField(
            model_name="animal",
            name="avisar_candidatos",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
