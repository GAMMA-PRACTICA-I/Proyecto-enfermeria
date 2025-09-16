# Etapa 1: construir ruedas Python
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /wheels
COPY requirements.txt /wheels/
RUN pip install --upgrade pip setuptools wheel && \
    pip wheel --wheel-dir=/wheels -r requirements.txt


# Etapa 2: runtime con Python 3.11 + MariaDB
FROM python:3.11-slim AS runtime

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      default-mysql-server default-mysql-client ca-certificates curl tini gosu \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 -s /usr/sbin/nologin app

RUN mkdir -p /var/run/mysqld /var/lib/mysql /app && \
    chown -R mysql:mysql /var/run/mysqld /var/lib/mysql && \
    chown -R app:app /app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /wheels/requirements.txt

COPY my.cnf /etc/mysql/mariadb.conf.d/my.cnf

COPY . /app/
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/entrypoint.sh"]
