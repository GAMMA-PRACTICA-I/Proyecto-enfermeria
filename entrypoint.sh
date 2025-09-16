#!/bin/sh
set -e

DATADIR="/var/lib/mysql"
SOCK="/var/run/mysqld/mysqld.sock"

chown -R mysql:mysql /var/lib/mysql /var/run/mysqld
chown -R app:app /app

if [ ! -d "$DATADIR/mysql" ]; then
  gosu mysql mysqld --initialize-insecure --datadir="$DATADIR"
fi

gosu mysql mysqld \
  --datadir="$DATADIR" \
  --socket="$SOCK" \
  --pid-file=/var/run/mysqld/mysqld.pid &

echo "Esperando MariaDB..."
until mysqladmin --protocol=SOCKET -S "$SOCK" ping --silent; do
  sleep 1
done

DB_NAME="${DB_NAME:-ficha_medica}"
DB_USER="${DB_USER:-appuser}"
DB_PASS="${DB_PASS:-apppass}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-rootpass}"

mysql --protocol=SOCKET -S "$SOCK" -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '${MYSQL_ROOT_PASSWORD}'; FLUSH PRIVILEGES;"
mysql --protocol=SOCKET -S "$SOCK" -u root -p"${MYSQL_ROOT_PASSWORD}" -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql --protocol=SOCKET -S "$SOCK" -u root -p"${MYSQL_ROOT_PASSWORD}" -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASS}';"
mysql --protocol=SOCKET -S "$SOCK" -u root -p"${MYSQL_ROOT_PASSWORD}" -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'%'; FLUSH PRIVILEGES;"

export DJANGO_SETTINGS_MODULE=config.settings
export PYTHONUNBUFFERED=1

# aplicar migraciones
gosu app python manage.py migrate --noinput

# crear usuarios por rol
gosu app python manage.py shell <<'PYCODE'
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
ensure_user("admin@demo.local", "admin123", rol="ADMIN", is_staff=True, is_superuser=True)

# revisor
ensure_user("revisor@demo.local", "revisor123", rol="REVIEWER", is_staff=True)

# estudiante
ensure_user("estudiante@demo.local", "estudiante123", rol="STUDENT")
PYCODE

# collectstatic (opcional)
gosu app python manage.py collectstatic --noinput || true

# arrancar servidor
exec gosu app python manage.py runserver 0.0.0.0:8000
