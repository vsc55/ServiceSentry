FROM python:3.12-slim

# freetds-dev + libssl-dev: compile pymssql from source when no binary wheel is available.
# iputils-ping: raw ICMP socket access required by the ping watchful module.
RUN apt-get update && apt-get install -y --no-install-recommends \
        freetds-dev \
        libssl-dev \
        iputils-ping \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Python
ENV PYTHONUNBUFFERED=1

# Web server
ENV WEB_HOST=0.0.0.0 \
    WEB_PORT=8080

# Web admin — credentials (no defaults: must be set explicitly in docker-compose)
# WA_USERNAME
# WA_PASSWORD

# Web admin — appearance / locale
ENV WA_LANG=en_EN \
    WA_DARK_MODE=false

# Web admin — security
ENV WA_SECURE_COOKIES=false \
    WA_REMEMBER_ME_DAYS=30 \
    WA_PROXY_COUNT=0

# Web admin — public status page
ENV WA_PUBLIC_STATUS=false \
    WA_STATUS_REFRESH_SECS=60 \
    WA_STATUS_LANG=""

# Web admin — audit log
ENV WA_AUDIT_MAX_ENTRIES=500

# Worker — monitoring interval (seconds)
ENV CHECK_INTERVAL=300

# Telegram — token and chat_id have no defaults (must be set explicitly)
# TELEGRAM_TOKEN
# TELEGRAM_CHAT_ID
ENV TELEGRAM_GROUP_MESSAGES=false

# Misc
ENV VERBOSE=false

WORKDIR /app

# Install Python dependencies in a separate layer for better cache reuse
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ .

# Copy startup script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create the production config/var directories the app expects at runtime.
# These paths are overridden by the volume mounts defined in docker-compose.yml.
RUN mkdir -p /etc/ServiSesentry /var/lib/ServiSesentry

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
