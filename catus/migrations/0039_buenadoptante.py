# BuenAdoptante: lo que se le manda (ActividadBuenAdoptante), el estado "Bloqueado" de un
# formulario frenado y cuándo volver a preguntar si un animal se adoptó. Son una tabla
# nueva y una columna que acepta NULL: el código anterior sigue andando con ellas, así que
# volver a la release anterior no pide deshacer la migración.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0038_ruta_de_imagen'),
    ]

    operations = [
        migrations.AddField(
            model_name='animal',
            name='pregunta_adopcion_hasta',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='estadoformulario',
            name='estado',
            field=models.CharField(choices=[('N', 'No asignado'), ('P', 'En proceso de contacto con el candidato'), ('R', 'Reservado'), ('A', 'Adoptado'), ('D', 'Descartado'), ('U', 'Duplicado'), ('T', 'Transitado'), ('B', 'Bloqueado por BuenAdoptante')], default='N', max_length=1),
        ),
        migrations.CreateModel(
            name='ActividadBuenAdoptante',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(blank=True, null=True)),
                ('tipo', models.CharField(choices=[('adoption_request', 'Solicitud de adopción'), ('adoption', 'Adopción')], max_length=20)),
                ('external_id', models.CharField(max_length=100, unique=True)),
                ('estado', models.CharField(choices=[('P', 'Pendiente'), ('OK', 'Enviada'), ('E', 'Rechazada')], default='P', max_length=2)),
                ('intentos', models.PositiveIntegerField(default=0)),
                ('ultimo_intento', models.DateTimeField(blank=True, null=True)),
                ('error', models.CharField(blank=True, max_length=255, null=True)),
                ('match', models.CharField(blank=True, max_length=20, null=True)),
                ('nivel', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('marcas', models.TextField(blank=True, null=True)),
                ('alertas', models.TextField(blank=True, null=True)),
                ('perfil_url', models.CharField(blank=True, max_length=255, null=True)),
                ('activity_id', models.CharField(blank=True, max_length=64, null=True)),
                ('bloqueo', models.BooleanField(default=False)),
                ('avisado', models.BooleanField(default=False)),
                ('animal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='catus.animal')),
                ('estado_formulario', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='catus.estadoformulario')),
            ],
            options={
                'indexes': [models.Index(fields=['estado', 'ultimo_intento'], name='catus_ba_estado_intento_idx')],
            },
        ),
    ]
