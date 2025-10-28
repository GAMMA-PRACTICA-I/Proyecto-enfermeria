from django.db import migrations, models
import accounts.models  # para usar _foto_ficha_path

class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="studentficha",
            name="foto",
            field=models.ImageField(
                upload_to=accounts.models._foto_ficha_path,
                blank=True,
                null=True,
            ),
        ),
    ]