FROM python:3.14-slim

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

# All runtime settings use the SS_ prefix.

# Web server
ENV SS_WEB_HOST=0.0.0.0 \
    SS_WEB_PORT=8080

# Web admin — credentials (no defaults: must be set explicitly)
# SS_USERNAME
# SS_PASSWORD

# Web admin — appearance / locale
ENV SS_LANG=en_EN \
    SS_DARK_MODE=false

# Web admin — security
ENV SS_SECURE_COOKIES=false \
    SS_REMEMBER_ME_DAYS=30 \
    SS_PROXY_COUNT=0 \
    SS_PUBLIC_URL="" \
    SS_FORCE_HTTPS=false \
    SS_FORCE_FQDN=false

# Web admin — public status page
ENV SS_PUBLIC_STATUS=false \
    SS_PUBLIC_STATUS_DETAIL=false \
    SS_STATUS_REFRESH_SECS=60 \
    SS_STATUS_LANG=""

# Web admin — audit log
ENV SS_AUDIT_MAX_ENTRIES=500

# Service hosting: by default the web admin hosts every service embedded (the
# monitoring scheduler, syslog receiver and event worker).  In the microservices
# topology the web container sets SS_MONITORING_EMBEDDED / SS_SYSLOG_EMBEDDED /
# SS_EVENTS_EMBEDDED to 0 so dedicated containers own each one.  Whether each
# embedded service starts at boot is the per-service ``autostart`` config flag
# (enabled + autostart), edited in the web UI — not an image default.

# Monitoring interval in seconds (worker + embedded scheduler period)
ENV SS_CHECK_INTERVAL=300

# Telegram — token and chat_id have no defaults (must be set explicitly)
# SS_TELEGRAM_TOKEN
# SS_TELEGRAM_CHAT_ID
ENV SS_TELEGRAM_GROUP_MESSAGES=false

# Misc
ENV SS_VERBOSE=false

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
# These paths are overridden by the volume mounts defined in the compose files.
RUN mkdir -p /etc/ServiSesentry /var/lib/ServiSesentry

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
