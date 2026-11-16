from django.db import migrations, models


class Migration(migrations.Migration):
    """Los avisos por mail de los cambios de estado:

    - Animal.expiro_avisado_el: cuándo se le mandó al rescatista el mail "¿Siguen en
      adopción?" de esa expiración (services/expiracion.py).
    - EstadoFormulario.aviso_cierre_el: cuándo se resolvió el aviso "ya tiene familia" a
      quien mandó ese formulario (services/aviso_candidatos.py).

    Las dos aceptan NULL, así que el código anterior (un rollback) sigue dando de alta.
    """

    dependencies = [
        ("catus", "0041_copiado_de"),
    ]

    operations = [
        migrations.AddField(
            model_name="animal",
            name="expiro_avisado_el",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="estadoformulario",
            name="aviso_cierre_el",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
