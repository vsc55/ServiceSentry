# Despliegue con Docker

El setup de Docker ejecuta dos contenedores a partir de la misma imagen:

- **`servicesentry-web`** — panel web de administración Flask (`--web`)
- **`servicesentry-worker`** — daemon de monitorización en segundo plano (`--daemon`)

Ambos contenedores comparten los mismos volúmenes con nombre, por lo que leen y
escriben el mismo estado.

## Inicio rápido

```bash
# Desde la raíz del proyecto
docker compose -f docker/docker-compose.yml up -d

# O desde dentro de la carpeta docker/
cd docker
docker compose up -d
```

El panel web de administración queda disponible en `http://tu-servidor:8080`.

## Construir y ejecutar

```bash
# Construir la imagen e iniciar ambos contenedores
docker compose -f docker/docker-compose.yml up -d --build

# Ver logs
docker logs -f servicesentry-web
docker logs -f servicesentry-worker

# Parar
docker compose -f docker/docker-compose.yml down
```

## Configuración

Toda la configuración se pasa como variables de entorno en `docker/docker-compose.yml`.
El script de arranque `entrypoint.sh` las escribe en `/etc/ServiSesentry/config.json`
al iniciar. Las variables que no estén definidas dejan el valor de configuración
existente sin modificar, por lo que los cambios realizados desde el panel web
sobreviven a los reinicios del contenedor.

### Referencia de variables de entorno

| Variable | Valor por defecto | Descripción |
| -------- | ----------------- | ----------- |
| `SERVICE_ROLE` | *(obligatorio)* | `web` o `worker` |
| `TZ` | `UTC` | Zona horaria del contenedor |
| **Servidor web** | | |
| `WEB_HOST` | `0.0.0.0` | Dirección a la que se enlaza el panel web |
| `WEB_PORT` | `8080` | Puerto en el que escucha el panel web (argumento `--web-port`). Tiene prioridad sobre `WA_PORT` y el valor guardado en `config.json` |
| `WA_PORT` | `8080` | Persiste el puerto en `config.json`; equivalente al campo **Puerto web** en Configuración → Acceso Externo. Si `WEB_PORT` también está definido, este tiene prioridad |
| **Credenciales** | | |
| `WA_USERNAME` | *(obligatorio)* | Usuario del panel de administración |
| `WA_PASSWORD` | *(obligatorio)* | Contraseña del panel de administración |
| **Apariencia** | | |
| `WA_LANG` | `en_EN` | Idioma de la interfaz (`en_EN` / `es_ES`) |
| `WA_DARK_MODE` | `false` | Activar el modo oscuro por defecto |
| **Seguridad** | | |
| `WA_SECURE_COOKIES` | `false` | Poner a `true` al servir sobre HTTPS |
| `WA_REMEMBER_ME_DAYS` | `30` | Duración de la sesión en días |
| `WA_PROXY_COUNT` | `0` | Número de proxies inversos delante de la aplicación |
| `WA_PUBLIC_URL` | *(vacío)* | Nombre de host público, sin esquema — p. ej. `monitor.example.com` o `monitor.example.com:8080`. Necesario para los enlaces de Telegram y el acceso directo a la página de estado cuando se accede por un dominio distinto a la IP del servidor |
| `WA_FORCE_HTTPS` | `false` | `true` cuando el proxy inverso termina HTTPS — la app generará URLs `https://` aunque internamente use HTTP |
| `WA_FORCE_FQDN` | `false` | `true` para redirigir al hostname de `WA_PUBLIC_URL` si se accede por IP u otro nombre, conservando la ruta y los parámetros. Requiere `WA_PUBLIC_URL` |
| **Página de estado pública** | | |
| `WA_PUBLIC_STATUS` | `false` | Habilitar el endpoint `/status` sin autenticación |
| `WA_STATUS_REFRESH_SECS` | `60` | Intervalo de refresco automático en la página de estado |
| `WA_STATUS_LANG` | *(vacío)* | Idioma específico para la página de estado; por defecto usa `WA_LANG` |
| **Log de auditoría** | | |
| `WA_AUDIT_MAX_ENTRIES` | `500` | Número máximo de entradas a conservar en el log de auditoría |
| **Worker** | | |
| `CHECK_INTERVAL` | `300` | Segundos entre comprobaciones de monitorización |
| **Telegram** | | |
| `TELEGRAM_TOKEN` | *(no definido)* | Token del bot de Telegram |
| `TELEGRAM_CHAT_ID` | *(no definido)* | ID del chat o grupo de Telegram |
| `TELEGRAM_GROUP_MESSAGES` | `false` | Agrupar varias alertas en un único mensaje |
| **Varios** | | |
| `VERBOSE` | `false` | Activar salida detallada / debug |

### Variables sensibles

`WA_USERNAME`, `WA_PASSWORD`, `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` no tienen
valor por defecto en la imagen y deben definirse explícitamente. Para despliegues
en producción considera usar
[Docker Secrets](https://docs.docker.com/engine/swarm/secrets/) en lugar de
variables de entorno en texto plano.

## Volúmenes

```yaml
volumes:
  config:    # → /etc/ServiSesentry      (config.json, modules.json)
  vardata:   # → /var/lib/ServiSesentry  (data.db: usuarios, roles, grupos, sesiones, auditoría, historial; status.json)
```

Ambos volúmenes son volúmenes con nombre gestionados por Docker. Para inspeccionar
su ubicación en disco:

```bash
docker volume inspect docker_config
docker volume inspect docker_vardata
```

Para hacer una copia de seguridad o precargar el volumen de configuración:

```bash
# Copiar un fichero de configuración local al volumen
docker run --rm -v docker_config:/data -v $(pwd)/data:/src alpine \
    cp /src/config.json /data/config.json
```

## Actualización

```bash
docker compose -f docker/docker-compose.yml pull   # o reconstruir
docker compose -f docker/docker-compose.yml up -d --build
```

Los ficheros de configuración en los volúmenes con nombre se conservan entre
actualizaciones.

## Proxy inverso

Consulta la [guía de proxy inverso](deployment.md#proxy-inverso) para las instrucciones completas de NPM y Traefik.

Al ejecutar detrás de cualquier proxy inverso con terminación HTTPS, configura estas variables en `docker-compose.yml`:

```yaml
environment:
  WA_PROXY_COUNT: "1"
  WA_PUBLIC_URL: "monitor.example.com"   # sin esquema, sin barra final
  WA_FORCE_HTTPS: "true"
  WA_SECURE_COOKIES: "true"
```

### Traefik (labels en docker-compose)

Añade las labels al servicio `servicesentry-web` y conecta el contenedor a la red de Traefik:

```yaml
services:
  servicesentry-web:
    networks:
      - traefik_public
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.sentry.rule=Host(`monitor.example.com`)"
      - "traefik.http.routers.sentry.entrypoints=websecure"
      - "traefik.http.routers.sentry.tls.certresolver=letsencrypt"
      - "traefik.http.services.sentry.loadbalancer.server.port=8080"
    environment:
      WA_PROXY_COUNT: "1"
      WA_PUBLIC_URL: "monitor.example.com"
      WA_FORCE_HTTPS: "true"
      WA_SECURE_COOKIES: "true"

networks:
  traefik_public:
    external: true
```

> `websecure` y `letsencrypt` son los nombres de entrypoint y certresolver
> habituales en una instalación estándar de Traefik. Ajústalos si los tuyos tienen
> nombres distintos.

### Nginx Proxy Manager (NPM)

NPM no requiere configuración de cabeceras manual — las añade automáticamente.

1. Crea un **Proxy Host** apuntando a `http://<ip-del-servidor>:8080`
2. En la pestaña **SSL** activa el certificado Let's Encrypt y marca *Force SSL*
3. Configura las variables de entorno en `docker-compose.yml`:

```yaml
environment:
  WA_PROXY_COUNT: "1"
  WA_PUBLIC_URL: "monitor.example.com"
  WA_FORCE_HTTPS: "true"
  WA_SECURE_COOKIES: "true"
```
