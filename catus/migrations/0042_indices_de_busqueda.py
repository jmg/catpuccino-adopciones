from django.db import migrations, models


class Migration(migrations.Migration):
    """Índices para lo que se busca en cada pedido: /formularios/<hash>/
    (EstadoFormulario.hash), /contrato/<hash>/ (Contrato.hash) y /<handle>/
    (CatusUser.handle). Sin ellos cada una de esas páginas recorría la tabla entera.

    Son índices comunes y no unique a propósito: no está verificado que no haya repetidos
    en producción, y un unique que choca con un repetido hace fallar la migración a mitad
    del deploy. handle se sabe que sí los tiene (get_user_por_handle). Para ver si se
    puede pasar a unique más adelante, en la base de producción:

        SELECT hash, COUNT(*) FROM catus_estadoformulario GROUP BY hash HAVING COUNT(*) > 1;
        SELECT hash, COUNT(*) FROM catus_contrato GROUP BY hash HAVING COUNT(*) > 1;
        SELECT handle, COUNT(*) FROM catus_catususer WHERE handle IS NOT NULL
            GROUP BY handle HAVING COUNT(*) > 1;

    En MySQL cada índice es un ALTER TABLE ... ADD INDEX, que InnoDB arma sin bloquear las
    escrituras (ALGORITHM=INPLACE); con las tablas de hoy tarda menos de un segundo.
    """

    dependencies = [
        ("catus", "0041_copiado_de"),
    ]

    operations = [
        migrations.AlterField(
            model_name="estadoformulario",
            name="hash",
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="contrato",
            name="hash",
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="catususer",
            name="handle",
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
    ]
