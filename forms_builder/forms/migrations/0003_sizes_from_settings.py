# The sizes these fields have had in the sites' databases all along: label and
# help text as long as FORMS_BUILDER_LABEL_MAX_LENGTH and
# FORMS_BUILDER_HELPTEXT_MAX_LENGTH (1000 in adopciones and feliscatus), which
# 0001 did not take from settings. There the ALTERs change nothing; the sites
# change is Django state only.
from django.db import migrations, models

from forms_builder.forms import settings


class Migration(migrations.Migration):

    dependencies = [
        ('forms', '0002_auto_20160418_0120'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.AlterField(
            model_name='field',
            name='help_text',
            field=models.CharField(blank=True, max_length=settings.HELPTEXT_MAX_LENGTH, verbose_name='Help text'),
        ),
        migrations.AlterField(
            model_name='field',
            name='label',
            field=models.CharField(max_length=settings.LABEL_MAX_LENGTH, verbose_name='Label'),
        ),
        migrations.AlterField(
            model_name='form',
            name='sites',
            field=models.ManyToManyField(default=[settings.SITE_ID], related_name='%(app_label)s_%(class)s_forms', to='sites.site'),
        ),
    ]
