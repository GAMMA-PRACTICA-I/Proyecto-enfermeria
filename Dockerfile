# ===== Etapa 1: build de wheels (para mysqlclient, etc.)
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /wheels

# Paquetes para compilar mysqlclient
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libmariadb-dev \
      pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /wheels/
RUN pip install --upgrade pip setuptools wheel && \
    pip wheel --wheel-dir=/wheels -r requirements.txt


# ===== Etapa 2: runtime (solo librerías de ejecución)
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Solo libs runtime (NO servidor MySQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
      libmariadb3 \
      default-mysql-client \
      ca-certificates \
      curl \
      tini \
    && rm -rf /var/lib/apt/lists/*

# Usuario no root
RUN useradd -m -u 10001 -s /usr/sbin/nologin app

WORKDIR /app

# Instala wheels construidos
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /wheels/requirements.txt

# (Opcional) si usarás SSL hacia RDS, copia el CA y luego usa DB_SSL_CA=/app/certs/aws-rds-ca.pem en .env
# COPY certs/aws-rds-ca.pem /app/certs/aws-rds-ca.pem

# Copia código
# Certificado raíz de AWS RDS (bundle global)
RUN mkdir -p /app/certs && \
    curl -fsSL -o /app/certs/aws-rds-ca.pem \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
COPY . /app
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/entrypoint.sh"]
