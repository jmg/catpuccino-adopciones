from django.db import migrations, models


class Migration(migrations.Migration):
    """PasoFormulario: el embudo del formulario de pre-adopción, contadores por día, especie y
    paso (services/embudo.py). Una tabla nueva, sin tocar las demás."""

    dependencies = [
        ("catus", "0042_avisos_de_estado"),
    ]

    operations = [
        migrations.CreateModel(
            name="PasoFormulario",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha", models.DateField()),
                ("especie", models.CharField(choices=[("G", "Gatos"), ("P", "Perros")], max_length=1)),
                ("paso", models.CharField(choices=[
                    ("abrio", "Abrió el formulario"),
                    ("requisitos", "Aceptó los requisitos"),
                    ("empezo", "Empezó a contestar"),
                    ("faltantes", "Quiso enviar con respuestas sin contestar"),
                    ("intento", "Lo envió desde el navegador"),
                    ("enviado", "Llegó y se guardó"),
                    ("frenado", "Lo frenó BuenAdoptante"),
                    ("rechazado", "El servidor lo rechazó"),
                ], max_length=12)),
                ("n", models.PositiveIntegerField(default=0)),
            ],
            options={
                "unique_together": {("fecha", "especie", "paso")},
            },
        ),
    ]
