from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentGeneralPhotoBlob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mime', models.CharField(default='image/png', max_length=100)),
                ('data', models.BinaryField()),
                ('size_bytes', models.BigIntegerField(default=0)),
                ('sha256', models.CharField(db_index=True, max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('general', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='photo_blob', to='accounts.studentgeneral')),
            ],
            options={
                'db_table': 'student_general_photo_blob',
                'indexes': [
                    models.Index(fields=['sha256'], name='idx_genphotoblob_sha256'),
                ],
            },
        ),
    ]