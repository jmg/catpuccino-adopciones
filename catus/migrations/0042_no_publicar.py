from django.db import migrations, models


class Migration(migrations.Migration):
    """Animal.no_publicar_el y no_publicar_motivo: el equipo decidió no publicarlo
    ("No publicar" en /tools/animalespendientes/ o el comando archivar_pendientes)."""

    dependencies = [
        ("catus", "0041_copiado_de"),
    ]

    operations = [
        migrations.AddField(
            model_name="animal",
            name="no_publicar_el",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="animal",
            name="no_publicar_motivo",
            field=models.TextField(blank=True, null=True),
        ),
    ]
