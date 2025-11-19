# accounts/migrations/0011_comentariodocumento_order_studentdocuments_order_and_more.py

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_comentariodocumento_order_studentdocuments_order_and_more"),
    ]

    # Esta migración NO hace cambios reales en la base de datos.
    # Las columnas "order" ya existen y el modelo SupportTicket debe mantenerse.
    operations = []
