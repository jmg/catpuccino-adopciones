# Django 3.1 lengthened AbstractUser.first_name from 30 to 150 characters. A
# wider column: the code before Django 5.2 runs on it as well.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catus', '0028_catususer_animales_comentario'),
    ]

    operations = [
        migrations.AlterField(
            model_name='catususer',
            name='first_name',
            field=models.CharField(blank=True, max_length=150, verbose_name='first name'),
        ),
    ]
