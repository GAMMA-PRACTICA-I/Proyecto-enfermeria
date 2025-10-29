#!/bin/sh
set -e
chown -R app:app /app
mkdir -p /app/media
chown -R app:app /app/media

tries=0
max=20
echo "Esperando conexión a la base de datos AWS..."

while ! mysql -h "${DB_HOST}" -P "${DB_PORT:-3306}" -u "${DB_USER}" -p${DB_PASS} \
  --ssl --ssl-ca="${DB_SSL_CA}" --ssl-verify-server-cert=OFF -e "SELECT 1;" >/dev/null 2> /tmp/db_err.log; do
  tries=$((tries+1))
  echo "Aguardando que la base de datos esté disponible... (intento $tries/$max)"
  if [ $tries -ge $max ]; then
    echo "❌ Error al conectar a la BD. Último error:"
    cat /tmp/db_err.log
    exit 1
  fi
  sleep 3
done

echo "✅ Conexión exitosa a la base de datos AWS."

echo "✅ Conexión exitosa a la base de datos AWS."
mysql -h "${DB_HOST}" -P "${DB_PORT:-3306}" -u "${DB_USER}" -p${DB_PASS} \
  --ssl --ssl-ca="${DB_SSL_CA}" --ssl-verify-server-cert=OFF -D "${DB_NAME}" -e "SELECT DATABASE();"
  
DB_NAME="${DB_NAME:?Falta DB_NAME}"
DB_USER="${DB_USER:?Falta DB_USER}"
DB_PASS="${DB_PASS:?Falta DB_PASS}"

export DJANGO_SETTINGS_MODULE=config.settings
export PYTHONUNBUFFERED=1

# aplicar migraciones
python manage.py migrate --noinput

# crear usuarios por rol
# crear usuarios por rol
python manage.py shell <<'PYCODE'
from django.contrib.auth import get_user_model
User = get_user_model()

def ensure_user(email, password, rol, is_staff=False, is_superuser=False):
    u, created = User.objects.get_or_create(
        email=email,
        defaults={
            "rol": rol,
            "is_staff": is_staff,
            "is_superuser": is_superuser,
        }
    )
    u.set_password(password)
    u.rol = rol
    u.is_staff = is_staff
    u.is_superuser = is_superuser
    u.save()
    print(f"Usuario {'creado' if created else 'actualizado'}: {email} ({rol})")

# admin
ensure_user("c.urdanetafernandez@uandresbello.edu", "admin123", rol="ADMIN", is_staff=True, is_superuser=True)

# revisor
ensure_user("n.guerrajara@uandresbello.edu", "revisor123", rol="REVIEWER", is_staff=True)

# estudiante
ensure_user("m.montoyamendoza1@uandresbello.edu", "estudiante123", rol="STUDENT")
PYCODE