from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catus", "0039_buenadoptante"),
    ]

    operations = [
        migrations.AddField(
            model_name="animal",
            name="expiro_el",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
