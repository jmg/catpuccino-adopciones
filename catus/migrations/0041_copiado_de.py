import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """EstadoFormulario.copiado_de: de qué formulario salió uno que la persona mandó con
    "postularme a otro animal con las mismas respuestas" (services/postulacion.py)."""

    dependencies = [
        ("catus", "0040_expiro_el"),
    ]

    operations = [
        migrations.AddField(
            model_name="estadoformulario",
            name="copiado_de",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="copias", to="catus.estadoformulario"),
        ),
    ]
