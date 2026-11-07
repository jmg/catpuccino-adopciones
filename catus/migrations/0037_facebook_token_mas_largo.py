# El token de la página mide ~210 caracteres hoy; si Facebook los alarga, con 255
# volver a conectar Instagram fallaría al guardar. Agrandar el campo no le cambia nada
# al código que ya corre, así que se puede migrar antes o después del deploy.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catus", "0036_db_default_para_el_rollback"),
    ]

    operations = [
        migrations.AlterField(
            model_name="facebookaccount",
            name="facebook_token",
            field=models.CharField(blank=True, max_length=1000, null=True),
        ),
    ]
