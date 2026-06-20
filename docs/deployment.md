# Guía de despliegue

Este documento cubre todas las formas soportadas de desplegar ServiceSentry en producción.

| Método | Indicado para |
| ------ | ------------- |
| [Docker](docker.md) | Cualquier servidor — instalación más sencilla, entorno aislado |
| [install.sh](#instalación-automática-installsh) | Instalación automática rápida en Debian / Ubuntu / Gentoo |
| [systemd](#systemd-debian-ubuntu-rhel-arch) | Instalación manual en distribuciones con systemd |
| [OpenRC](#openrc-gentoo-alpine) | Instalación manual en distribuciones con OpenRC |

---

## Requisitos previos

- **Python 3.10+** — necesario en todos los métodos excepto Docker
- Aplicación instalada en `/opt/ServiSesentry/` y configuración en `/etc/ServiSesentry/`
- Token de bot de Telegram y chat ID si se quieren notificaciones de alertas

---

## Docker

Consulta [docs/docker.md](docker.md) para la referencia completa de Docker: variables de entorno, volúmenes y configuración de proxy inverso.

```bash
# Monolítica (un contenedor) o microservicios (web + worker):
docker compose -f docker/docker-compose.monolithic.yml   up -d
docker compose -f docker/docker-compose.microservices.yml up -d
```

---

## Instalación automática (`install.sh`)

`install.sh` detecta si el sistema usa systemd u OpenRC e instala
los scripts de inicio correspondientes de forma automática.

```bash
sudo bash install.sh
```

**Qué hace:**

1. Crea `/opt/ServiSesentry/`, `/etc/ServiSesentry/`, `/var/lib/ServiSesentry/`
2. Copia los ficheros de la aplicación a `/opt/ServiSesentry/`
3. Si hay ficheros `data/*.json`, los copia a `/etc/ServiSesentry/` (omite los que ya existan)
4. Detecta el sistema de inicio e instala los scripts correspondientes
5. Habilita e inicia el servicio de monitorización

El panel web de administración **no** se inicia automáticamente — la salida de
`install.sh` indica el comando para habilitarlo.

### Generación automática en el primer arranque

Si no hay ficheros de configuración en `/etc/ServiSesentry/` cuando la aplicación
arranca por primera vez, se crean automáticamente con valores predeterminados:

| Fichero | Creado por | Contenido |
| ------- | ---------- | --------- |
| `config.json` | Daemon de monitorización en el primer arranque | Configuración mínima (debug desactivado, intervalo 300 s) |
| `modules.json` | Daemon de monitorización en el primer arranque | `{}` vacío — todos los módulos habilitados pero sin objetivos |
| `data.db` | Panel web en el primer inicio | Base de datos (SQLite) con la cuenta `admin` y contraseña predeterminada |

> **Persistencia:** usuarios, roles, grupos, sesiones, auditoría e historial se
> almacenan en **`data.db`** (SQLite) dentro del directorio var
> (`/var/lib/ServiSesentry/` en Linux). El esquema se crea y reconcilia
> automáticamente. Opcionalmente puede usarse PostgreSQL o MySQL configurando la
> sección `database` de `config.json` (ver [configuration.md](configuration.md)).

Tras el primer arranque puedes abrir el panel web para configurar las alertas de
Telegram, añadir objetivos de monitorización y cambiar la contraseña de administrador.

### Instalación preconfigurada

Si quieres que la instalación llegue con una configuración específica ya
establecida — por ejemplo en un despliegue automatizado o por script — coloca tus
ficheros `config.json` y/o `modules.json` en el directorio `data/`
antes de ejecutar `install.sh`:

```text
data/
├── config.json      # configuración global, token de Telegram, opciones del panel web
└── modules.json     # módulos habilitados y sus objetivos
```

`install.sh` copiará los ficheros `data/*.json` que encuentre allí a
`/etc/ServiSesentry/`. Los ficheros que no estén en `data/` se omiten — la
aplicación los genera en el primer arranque tal como se describe más arriba.
Los usuarios, roles, grupos, sesiones, auditoría, historial y estado de las
comprobaciones **no** son ficheros: viven en la base de datos (`data.db`), que se
crea automáticamente en el directorio var en el primer inicio del panel web.

> **Nota:** `data/*.json` está en `.gitignore` porque esos ficheros suelen contener
> credenciales (token de Telegram, secretos de módulos cifrados). No los subas nunca a
> un repositorio público.

### Actualización

```bash
sudo bash update.sh
```

Para los servicios, reemplaza los ficheros de la aplicación, reinstala los scripts
de inicio y los reinicia. Los ficheros de configuración en `/etc/ServiSesentry/`
que ya existan **nunca** se sobreescriben; los ficheros presentes en `data/` que
aún no se hayan desplegado se copian.

### Desinstalación

```bash
sudo bash uninstall.sh       # elimina la app, conserva la configuración en /etc/ServiSesentry
sudo bash uninstall.sh -a    # elimina todo, incluida la configuración
```

---

## systemd (Debian, Ubuntu, RHEL, Arch…)

### Arquitectura

| Unidad | Tipo | Función |
| ------ | ---- | ------- |
| `ServiSesentry.service` | oneshot | Ejecuta una pasada de comprobación de monitorización |
| `ServiSesentry.timer` | timer | Lanza `ServiSesentry.service` cada 5 minutos |
| `ServiSesentry-web.service` | simple | Ejecuta el panel web de administración de forma continua |

### Instalación

```bash
sudo cp init/systemd/ServiSesentry.service     /lib/systemd/system/
sudo cp init/systemd/ServiSesentry.timer       /lib/systemd/system/
sudo cp init/systemd/ServiSesentry-web.service /lib/systemd/system/
sudo systemctl daemon-reload
```

### Habilitar monitorización

```bash
sudo systemctl enable --now ServiSesentry.timer
```

El temporizador se activa cada 5 minutos (`OnCalendar=*:0/5`). Para cambiar el
intervalo, edita `/lib/systemd/system/ServiSesentry.timer` y ejecuta
`systemctl daemon-reload`.

### Habilitar el panel web

```bash
sudo systemctl enable --now ServiSesentry-web
```

El panel arranca en el puerto `8080` escuchando en todas las interfaces. Para
cambiar el puerto, edita la línea `ExecStart` en `ServiSesentry-web.service`:

```ini
ExecStart=/usr/bin/python3 /opt/ServiSesentry/main.py --web --web-host 0.0.0.0 --web-port 9090
```

### Gestión de servicios

```bash
# Estado
systemctl status ServiSesentry.timer
systemctl status ServiSesentry-web

# Logs
journalctl -u ServiSesentry.service -f
journalctl -u ServiSesentry-web.service -f

# Forzar una comprobación ahora
systemctl start ServiSesentry.service

# Parar / deshabilitar
systemctl disable --now ServiSesentry.timer
systemctl disable --now ServiSesentry-web
```

---

## OpenRC (Gentoo, Alpine…)

### Estructura de scripts

| Fichero | Se instala en | Función |
| ------- | ------------- | ------- |
| `init/openrc/init.d/ServiSesentry` | `/etc/init.d/ServiSesentry` | Script de inicio del daemon de monitorización |
| `init/openrc/conf.d/ServiSesentry` | `/etc/conf.d/ServiSesentry` | Configuración del daemon de monitorización |
| `init/openrc/init.d/ServiSesentry-web` | `/etc/init.d/ServiSesentry-web` | Script de inicio del panel web |
| `init/openrc/conf.d/ServiSesentry-web` | `/etc/conf.d/ServiSesentry-web` | Configuración del panel web |

### Instalar scripts de inicio

```bash
sudo cp init/openrc/init.d/ServiSesentry     /etc/init.d/
sudo cp init/openrc/init.d/ServiSesentry-web /etc/init.d/
sudo cp init/openrc/conf.d/ServiSesentry     /etc/conf.d/
sudo cp init/openrc/conf.d/ServiSesentry-web /etc/conf.d/
sudo chmod +x /etc/init.d/ServiSesentry /etc/init.d/ServiSesentry-web
```

### Habilitar el daemon de monitorización

```bash
sudo rc-update add ServiSesentry default
sudo rc-service ServiSesentry start
```

### Activar el panel web

```bash
sudo rc-update add ServiSesentry-web default
sudo rc-service ServiSesentry-web start
```

### Configuración mediante conf.d

Edita `/etc/conf.d/ServiSesentry` para cambiar las opciones de monitorización:

```sh
# Sobreescribir el intervalo de comprobación (segundos)
SS_ARGS="-d -c -t 120"
```

Edita `/etc/conf.d/ServiSesentry-web` para cambiar las opciones del panel web:

```sh
SS_WEB_HOST="127.0.0.1"   # solo localhost (detrás de un proxy inverso)
SS_WEB_PORT="9090"
```

> Estas variables `SS_*` las lee el CLI de forma nativa como valor por defecto de
> los argumentos equivalentes (`--web-host`, `--web-port`, etc.), así que exportarlas
> en el entorno funciona igual que pasarlas como flags. Lista completa en
> [configuration.md](configuration.md#variables-de-entorno).

Reinicia el servicio tras editar:

```bash
sudo rc-service ServiSesentry restart
sudo rc-service ServiSesentry-web restart
```

### Comandos de servicio

```bash
# Estado
rc-service ServiSesentry status
rc-service ServiSesentry-web status

# Logs (OpenRC escribe en syslog)
tail -f /var/log/messages | grep ServiSesentry

# Parar / eliminar del runlevel
rc-service ServiSesentry stop
rc-update del ServiSesentry default
```

---

## Proxy inverso

ServiceSentry puede ejecutarse detrás de un proxy inverso que termine las
conexiones HTTPS. El proxy recibe las peticiones del cliente en HTTPS y las
reenvía a la aplicación en HTTP:

```text
Cliente ──HTTPS──► Proxy inverso ──HTTP:8080──► ServiceSentry
```

Dado que la aplicación solo ve HTTP, hay que indicarle explícitamente que
debe generar URLs `https://`. Esto se hace con tres ajustes en el panel web
(sección **Acceso Externo**):

| Ajuste | Valor | Función |
| ------ | ----- | ------- |
| `proxy_count` | `1` | Activa la lectura de cabeceras `X-Forwarded-*` para obtener la IP real del cliente |
| `public_url` | `monitor.example.com` | Nombre de host público que el proxy expone (sin esquema). Incluye el puerto si no es el 80/443 estándar: `monitor.example.com:8443` |
| `force_https` | activado | La app genera URLs `https://` (enlaces de Telegram, página de estado) aunque internamente reciba HTTP |

Activa también **Cookies seguras** en la sección **Panel Web** para que las
cookies de sesión tengan el flag `Secure` — el navegador las enviará
correctamente porque la conexión al proxy es HTTPS.

### Puerto de la aplicación

Los ejemplos siguientes usan el puerto por defecto `8080`. El puerto se puede
cambiar desde el panel web en **Configuración → Panel Web → Puerto web**; el
cambio se aplica al reiniciar el servicio. También puede sobreescribirse por
método de despliegue sin pasar por el panel:

| Método | Cómo sobreescribir el puerto |
| ------ | ---------------------------- |
| **systemd** | Edita `ExecStart` en `ServiSesentry-web.service`: añade `--web-port 9090` |
| **OpenRC** | Define `SS_WEB_PORT="9090"` en `/etc/conf.d/ServiSesentry-web` |
| **Docker** | Variable de entorno `SS_WEB_PORT=9090` en `docker/.env` (o en tu fichero compose) |
| **Manual** | Argumento `--web-port 9090` al lanzar `main.py` |

> El argumento `--web-port` tiene prioridad sobre el valor guardado en
> `config.json`, por lo que el campo del panel queda sin efecto si el script de
> inicio define el puerto explícitamente.

---

### Nginx Proxy Manager (NPM)

NPM añade automáticamente todas las cabeceras de reenvío necesarias
(`X-Forwarded-For`, `X-Forwarded-Proto`, `X-Real-IP`). No hace falta
configuración avanzada.

**Pasos:**

1. En NPM crea un **Proxy Host**:
   - *Domain Names*: `monitor.example.com`
   - *Scheme*: `http`
   - *Forward Hostname / IP*: IP del servidor (o nombre del contenedor Docker)
   - *Forward Port*: `8080`
   - Activa *Block Common Exploits*

2. En la pestaña **SSL** selecciona o solicita un certificado Let's Encrypt y
   marca *Force SSL*.

3. En ServiceSentry (panel web → **Acceso Externo**):

   ```text
   proxy_count  = 1
   public_url   = monitor.example.com
   force_https  = activado
   ```

   Y en **Panel Web**: *Cookies seguras* = activado.

> Si usas Docker, pasa estas variables de entorno en `docker/.env`:
> `SS_PROXY_COUNT=1`, `SS_PUBLIC_URL=monitor.example.com`,
> `SS_FORCE_HTTPS=true`, `SS_SECURE_COOKIES=true`.

---

### Traefik

Traefik añade automáticamente `X-Forwarded-Proto: https` cuando la petición
llega por el entrypoint HTTPS.

#### Docker (labels)

Añade las siguientes labels al servicio `servicesentry-web` y conéctalo a la
red de Traefik:

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

> `websecure` y `letsencrypt` son los nombres habituales en una instalación
> estándar de Traefik. Cámbialos si los tuyos tienen nombres distintos.

#### Sin Docker (configuración de ficheros)

Configuración estática (`traefik.yml`):

```yaml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entrypoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@example.com
      storage: /etc/traefik/acme.json
      httpChallenge:
        entryPoint: web
```

Configuración dinámica (`/etc/traefik/conf.d/sentry.yml`):

```yaml
http:
  routers:
    sentry:
      rule: "Host(`monitor.example.com`)"
      entrypoints:
        - websecure
      tls:
        certResolver: letsencrypt
      service: sentry

  services:
    sentry:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8080"
```

En ServiceSentry (panel web → **Acceso Externo**):

```text
proxy_count  = 1
public_url   = monitor.example.com
force_https  = activado
```

Y en **Panel Web**: *Cookies seguras* = activado.
