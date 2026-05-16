# Docker Deployment

The Docker setup runs two containers from the same image:

- **`servicesentry-web`** — Flask web admin panel (`--web`)
- **`servicesentry-worker`** — background monitoring daemon (`--daemon`)

Both containers share the same named volumes so they read and write the same state.

## Quick start

```bash
# From the project root
docker compose -f docker/docker-compose.yml up -d

# Or from inside the docker/ folder
cd docker
docker compose up -d
```

The web admin panel is available at `http://your-host:8080`.

## Build and run

```bash
# Build the image and start both containers
docker compose -f docker/docker-compose.yml up -d --build

# View logs
docker logs -f servicesentry-web
docker logs -f servicesentry-worker

# Stop
docker compose -f docker/docker-compose.yml down
```

## Configuration

All settings are passed as environment variables in `docker/docker-compose.yml`.
The `entrypoint.sh` bootstrap script writes them into `/etc/ServiSesentry/config.json`
at startup. Variables that are not set leave the existing config value untouched,
so changes made via the web UI survive container restarts.

### Environment variables reference

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `SERVICE_ROLE` | *(required)* | `web` or `worker` |
| `TZ` | `UTC` | Container timezone |
| **Web server** | | |
| `WEB_HOST` | `0.0.0.0` | Address the web panel binds to |
| `WEB_PORT` | `8080` | Port the web panel listens on |
| **Credentials** | | |
| `WA_USERNAME` | *(required)* | Web admin username |
| `WA_PASSWORD` | *(required)* | Web admin password |
| **Appearance** | | |
| `WA_LANG` | `en_EN` | Interface language (`en_EN` / `es_ES`) |
| `WA_DARK_MODE` | `false` | Enable dark mode by default |
| **Security** | | |
| `WA_SECURE_COOKIES` | `false` | Set `true` when serving over HTTPS |
| `WA_REMEMBER_ME_DAYS` | `30` | Session duration in days |
| `WA_PROXY_COUNT` | `0` | Number of reverse proxies in front of the app |
| **Public status page** | | |
| `WA_PUBLIC_STATUS` | `false` | Enable the unauthenticated `/status` endpoint |
| `WA_STATUS_REFRESH_SECS` | `60` | Auto-refresh interval on the status page |
| `WA_STATUS_LANG` | *(empty)* | Language override for the status page; defaults to `WA_LANG` |
| **Audit log** | | |
| `WA_AUDIT_MAX_ENTRIES` | `500` | Maximum number of audit log entries to keep |
| **Worker** | | |
| `CHECK_INTERVAL` | `300` | Seconds between monitoring checks |
| **Telegram** | | |
| `TELEGRAM_TOKEN` | *(unset)* | Telegram bot token |
| `TELEGRAM_CHAT_ID` | *(unset)* | Telegram chat or group ID |
| `TELEGRAM_GROUP_MESSAGES` | `false` | Group multiple alerts into a single message |
| **Misc** | | |
| `VERBOSE` | `false` | Enable verbose / debug output |

### Sensitive variables

`WA_USERNAME`, `WA_PASSWORD`, `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` have no
defaults in the image and must be set explicitly. For production deployments
consider using [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
instead of plain environment variables.

## Volumes

```yaml
volumes:
  config:    # → /etc/ServiSesentry   (config.json, modules.json, users, roles…)
  vardata:   # → /var/lib/ServiSesentry  (status.json, sessions, audit log)
```

Both volumes are Docker-managed named volumes. To inspect their location on disk:

```bash
docker volume inspect docker_config
docker volume inspect docker_vardata
```

To back up or pre-populate the config volume:

```bash
# Copy a local config file into the volume
docker run --rm -v docker_config:/data -v $(pwd)/data:/src alpine \
    cp /src/config.json /data/config.json
```

## Updating

```bash
docker compose -f docker/docker-compose.yml pull   # or rebuild
docker compose -f docker/docker-compose.yml up -d --build
```

Config files in the named volumes are preserved across updates.

## Reverse proxy (nginx example)

```nginx
server {
    listen 80;
    server_name monitor.example.com;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Set `WA_PROXY_COUNT=1` and `WA_SECURE_COOKIES=true` (when using HTTPS) in
`docker-compose.yml` when running behind a reverse proxy.
