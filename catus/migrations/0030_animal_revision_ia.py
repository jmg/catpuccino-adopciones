from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0029_animalimage_crop'),
    ]

    operations = [
        migrations.AddField(
            model_name='animal',
            name='revision_ia_estado',
            field=models.CharField(
                choices=[('P', 'Sin revisar'), ('OK', 'Parece correcta'),
                         ('R', 'Revisar a mano'), ('E', 'No se pudo revisar')],
                default='P', max_length=2,
            ),
        ),
        migrations.AddField(
            model_name='animal',
            name='revision_ia_motivo',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='animal',
            name='revision_ia_fecha',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
