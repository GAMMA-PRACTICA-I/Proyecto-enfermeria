from django.db import migrations, models
import django.utils.timezone
import django.contrib.auth.models

class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designa que este usuario tiene todos los permisos.', verbose_name='superuser status')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('is_staff', models.BooleanField(default=False, verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('email', models.EmailField(unique=True, db_index=True, max_length=254)),
                ('rol', models.CharField(max_length=10, db_index=True, choices=[('STUDENT', 'Estudiante'), ('REVIEWER', 'Revisor'), ('ADMIN', 'Admin')], default='STUDENT')),
                ('rut', models.CharField(blank=True, null=True, max_length=20)),
                ('groups', models.ManyToManyField(blank=True, related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'abstract': False,
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
    ]
