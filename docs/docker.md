# Despliegue con Docker

Se ofrecen dos topologías a partir de la misma imagen; elige una:

- **Monolítica** (`docker/docker-compose.monolithic.yml`) — un solo contenedor
  `servicesentry`: el panel web con su scheduler embebido activado
  (`SS_AUTOSTART=true`), que ejecuta los checks periódicos en el propio proceso.
  La opción más simple.
- **Microservicios** (`docker/docker-compose.microservices.yml`) — dos
  contenedores: `servicesentry-web` (panel Flask, `--web`) y
  `servicesentry-worker` (daemon de monitorización, `--daemon`). Separa el
  monitoreo del panel: sobrevive a reinicios del web y no compite por recursos.

En microservicios ambos contenedores comparten los mismos volúmenes con nombre,
por lo que leen y escriben el mismo estado.

> **No mezcles las dos.** No actives `SS_AUTOSTART` en el `web` a la vez que
> corres el `worker`: son procesos distintos sin lock compartido y duplicarían
> cada check (histórico doble y tormenta de notificaciones).

## Inicio rápido

```bash
# Monolítica (un contenedor)
docker compose -f docker/docker-compose.monolithic.yml up -d

# Microservicios (web + worker)
docker compose -f docker/docker-compose.microservices.yml up -d
```

El panel web de administración queda disponible en `http://tu-servidor:8080`.

## Construir y ejecutar

```bash
# Construir la imagen e iniciar (ejemplo con la topología monolítica)
docker compose -f docker/docker-compose.monolithic.yml up -d --build

# Ver logs
docker logs -f servicesentry            # monolítica
docker logs -f servicesentry-web        # microservicios
docker logs -f servicesentry-worker     # microservicios

# Parar
docker compose -f docker/docker-compose.monolithic.yml down
```

## Configuración

La configuración se pasa como variables de entorno. Los secretos y ajustes
custom viven en `docker/.env` (copia de `docker/env.example`, gitignored), que
ambos compose cargan con `env_file`; en los compose solo quedan los valores que
dependen del servicio/topología (`SS_SERVICE_ROLE`, `SS_WEB_HOST`/`SS_WEB_PORT`,
`SS_AUTOSTART`). Los valores de `environment:` del compose tienen prioridad sobre
los del `.env`.
El script de arranque `entrypoint.sh` solo traduce `SS_SERVICE_ROLE`, `SS_WEB_HOST`,
`SS_WEB_PORT` y `SS_VERBOSE` a flags del CLI; el resto de variables (config.json,
`SS_*`) las aplica en runtime el proceso Python y **nunca
se escriben a `config.json`**. Las variables que no estén definidas dejan el valor
de configuración existente sin modificar, por lo que los cambios realizados desde
el panel web sobreviven a los reinicios del contenedor.

### Referencia de variables de entorno

| Variable | Valor por defecto | Descripción |
| -------- | ----------------- | ----------- |
| `SS_SERVICE_ROLE` | *(obligatorio)* | `web` o `worker` |
| `TZ` | `UTC` | Zona horaria del contenedor |
| **Servidor web** | | |
| `SS_WEB_HOST` | `0.0.0.0` | Dirección a la que se enlaza el panel web |
| `SS_WEB_PORT` | `8080` | Puerto en el que escucha el panel web (argumento `--web-port`). Tiene prioridad sobre `SS_PORT` y el valor guardado en `config.json` |
| `SS_PORT` | `8080` | Override en runtime del puerto web (`web_admin` → `port`); equivalente al campo **Puerto web** en Configuración → Acceso Externo. Si `SS_WEB_PORT` también está definido, este tiene prioridad |
| **Credenciales** | | |
| `SS_USERNAME` | *(obligatorio)* | Usuario del panel de administración |
| `SS_PASSWORD` | *(obligatorio)* | Contraseña del panel de administración |
| **Apariencia** | | |
| `SS_LANG` | `en_EN` | Idioma de la interfaz (`en_EN` / `es_ES`) |
| `SS_DARK_MODE` | `false` | Activar el modo oscuro por defecto |
| **Seguridad** | | |
| `SS_SECURE_COOKIES` | `false` | Poner a `true` al servir sobre HTTPS |
| `SS_REMEMBER_ME_DAYS` | `30` | Duración de la sesión en días |
| `SS_PROXY_COUNT` | `0` | Número de proxies inversos delante de la aplicación |
| `SS_PUBLIC_URL` | *(vacío)* | Nombre de host público, sin esquema — p. ej. `monitor.example.com` o `monitor.example.com:8080`. Necesario para los enlaces de Telegram y el acceso directo a la página de estado cuando se accede por un dominio distinto a la IP del servidor |
| `SS_FORCE_HTTPS` | `false` | `true` cuando el proxy inverso termina HTTPS — la app generará URLs `https://` aunque internamente use HTTP |
| `SS_FORCE_FQDN` | `false` | `true` para redirigir al hostname de `SS_PUBLIC_URL` si se accede por IP u otro nombre, conservando la ruta y los parámetros. Requiere `SS_PUBLIC_URL` |
| **Página de estado pública** | | |
| `SS_PUBLIC_STATUS` | `false` | Habilitar el endpoint `/status` sin autenticación |
| `SS_PUBLIC_STATUS_DETAIL` | `false` | Mostrar el detalle por ítem en la página de estado pública |
| `SS_STATUS_REFRESH_SECS` | `60` | Intervalo de refresco automático en la página de estado |
| `SS_STATUS_LANG` | *(vacío)* | Idioma específico para la página de estado; por defecto usa `SS_LANG` |
| **Log de auditoría** | | |
| `SS_AUDIT_MAX_ENTRIES` | `500` | Número máximo de entradas a conservar en el log de auditoría |
| **Planificador / Worker** | | |
| `SS_AUTOSTART` | `false` | Arrancar el scheduler embebido del panel web (ejecuta los checks en el propio proceso). `true` en la topología monolítica; déjalo en `false` si corres un `worker` aparte |
| `SS_CHECK_INTERVAL` | `300` | Segundos entre comprobaciones (periodo del worker y del scheduler embebido) |
| **Telegram** | | |
| `SS_TELEGRAM_TOKEN` | *(no definido)* | Token del bot de Telegram |
| `SS_TELEGRAM_CHAT_ID` | *(no definido)* | ID del chat o grupo de Telegram |
| `SS_TELEGRAM_GROUP_MESSAGES` | `false` | Agrupar varias alertas en un único mensaje |
| **Varios** | | |
| `SS_VERBOSE` | `false` | Activar salida detallada / debug (fuerza el nivel máximo, equivale a `--verbose`). Para un nivel concreto usa `global.log_level` desde el panel (**Configuración → Interfaz**) |
| `NO_COLOR` | *(no definido)* | Si se define (cualquier valor), desactiva los colores ANSI del debug. Los logs de Docker no son un TTY, así que el color ya se desactiva solo |

> **Nota:** las variables `SS_WEB_HOST`, `SS_WEB_PORT` y `SS_VERBOSE` las traduce el
> `entrypoint.sh` a los flags `--web-host`/`--web-port`/`--verbose`.
> Alternativamente, el CLI lee directamente variables `SS_*` (`SS_WEB`,
> `SS_WEB_PORT`, `SS_WEB_HOST`, `SS_VERBOSE`, `SS_NOCOLOR`, `SS_CONFIG_DIR`…)
> sin pasar por el entrypoint — ver [configuration.md](configuration.md#variables-de-entorno).
> Los campos de `config.json` (variables `SS_*` como `SS_LANG`, `SS_CHECK_INTERVAL`,
> `SS_TELEGRAM_TOKEN`) se aplican en runtime por el proceso Python y nunca se escriben a disco.

### Variables sensibles

`SS_USERNAME`, `SS_PASSWORD`, `SS_TELEGRAM_TOKEN` y `SS_TELEGRAM_CHAT_ID` no tienen
valor por defecto en la imagen y deben definirse explícitamente. Para despliegues
en producción considera usar
[Docker Secrets](https://docs.docker.com/engine/swarm/secrets/) en lugar de
variables de entorno en texto plano.

## Volúmenes

```yaml
volumes:
  config:    # → /etc/ServiSesentry      (config.json)
  vardata:   # → /var/lib/ServiSesentry  (data.db: usuarios, roles, grupos, sesiones, auditoría, hosts, credenciales, historial, estado de checks y config de módulos/ítems — tablas module_config/module_config_items)
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
# (usa el mismo fichero compose con el que arrancaste)
docker compose -f docker/docker-compose.monolithic.yml pull   # o reconstruir
docker compose -f docker/docker-compose.monolithic.yml up -d --build
```

Los ficheros de configuración en los volúmenes con nombre se conservan entre
actualizaciones.

## Proxy inverso

Consulta la [guía de proxy inverso](deployment.md#proxy-inverso) para las instrucciones completas de NPM y Traefik.

Al ejecutar detrás de cualquier proxy inverso con terminación HTTPS, configura estas variables en tu fichero compose:

```yaml
environment:
  SS_PROXY_COUNT: "1"
  SS_PUBLIC_URL: "monitor.example.com"   # sin esquema, sin barra final
  SS_FORCE_HTTPS: "true"
  SS_SECURE_COOKIES: "true"
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
      SS_PROXY_COUNT: "1"
      SS_PUBLIC_URL: "monitor.example.com"
      SS_FORCE_HTTPS: "true"
      SS_SECURE_COOKIES: "true"

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
3. Configura las variables de entorno en tu fichero compose:

```yaml
environment:
  SS_PROXY_COUNT: "1"
  SS_PUBLIC_URL: "monitor.example.com"
  SS_FORCE_HTTPS: "true"
  SS_SECURE_COOKIES: "true"
```
