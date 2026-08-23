# Guía de despliegue

Este documento cubre todas las formas soportadas de desplegar ServiceSentry en producción.

| Método | Indicado para |
| ------ | ------------- |
| [Docker](caso-docker.md) | Cualquier servidor — instalación más sencilla, entorno aislado |
| [install.sh](#instalación-automática-installsh) | Instalación automática rápida en Debian / Ubuntu / Gentoo |
| [systemd](#systemd-debian-ubuntu-rhel-arch) | Instalación manual en distribuciones con systemd |
| [OpenRC](#openrc-gentoo-alpine) | Instalación manual en distribuciones con OpenRC |

---

## Requisitos previos

- **Python 3.10+** — necesario en todos los métodos excepto Docker
- Aplicación instalada en `/opt/ServiSesentry/` y configuración en `/etc/ServiSesentry/`
- Token de bot de Telegram y chat ID si se quieren notificaciones de alertas
- **RAM del receptor syslog**: si activas el servidor syslog y esperas muchas conexiones
  TCP/TLS **persistentes**, dimensiona la memoria — es *thread-per-connection*, ≈47 KB por
  conexión viva (~46 MB por cada 1000). Detalle y recomendaciones en [docs/caso-docker.md](caso-docker.md)
  → *Dimensionado del receptor syslog*.

---

## Docker

Consulta [docs/caso-docker.md](caso-docker.md) para la referencia completa de Docker: variables de entorno, volúmenes y configuración de proxy inverso.

```bash
# Monolítica (un contenedor), microservicios (web + worker + syslog, 2 BD)
# o microservicios + Traefik (publicado por HTTPS con Let's Encrypt):
docker compose -f docker/docker-compose.monolithic.yml           up -d
docker compose -f docker/docker-compose.microservices.yml        up -d
docker compose -f docker/docker-compose.microservices-traefik.yml up -d
```

---

## Paquetes (`.deb`, `.rpm`, ebuild de Gentoo)

Cada **versión final** (`vX.Y.Z`) publica sus paquetes adjuntos a la
[release de GitHub](https://github.com/vsc55/ServiceSentry/releases). El tag `test` **no**
genera paquetes a propósito: es un tag de build que se mueve, y un `.deb` que dice ser una
versión que mañana será otra cosa es peor que no tenerlo.

```bash
# Debian / Ubuntu
sudo apt install ./servicesentry_1.2.3_all.deb

# Fedora / RHEL
sudo dnf install ./servicesentry-1.2.3.noarch.rpm

# Gentoo — emerge instala desde un ebuild, así que lo que se publica es el overlay
sudo mkdir -p /var/db/repos/servicesentry
sudo tar xzf servicesentry-1.2.3-gentoo-overlay.tar.gz -C /var/db/repos/servicesentry
# añade el repo a /etc/portage/repos.conf y luego:
sudo emerge app-admin/servicesentry
```

**El paquete instala la aplicación; las dependencias se resuelven al instalar.** El
postinstall crea un entorno virtual en `/opt/ServiSesentry/venv` y hace `pip install` desde
el `requirements.lock` que viaja dentro. Consecuencias que conviene conocer:

- hace falta **red** durante la instalación, y tarda unos minutos;
- se instalan las **versiones exactas** del lock, iguales en toda distro — que es justo lo
  que se pierde si el paquete dependiera de los `python3-*` de cada sistema (varios no
  existen, y los que existen traen otra versión);
- si falla, el mensaje dice el comando exacto para reintentarlo. La app queda instalada pero
  **no arranca** hasta que ese paso termine bien.

**Requiere Python 3.11.3 o superior**, y el postinstall lo comprueba antes de nada. El motivo
no es la app sino el lock: sus hashes ponen a pip en modo `--require-hashes`, donde una
dependencia transitiva que un intérprete viejo **activa por marcador** —`redis` pide
`async-timeout` por debajo de 3.11.3— es un error duro, porque el lock no la lleva. Distros
afectadas: **Debian 12 y anteriores** (traen 3.11.2). Debian 13, Ubuntu 24.04 y Fedora actual
están por encima del corte. En un sistema antiguo, usa Docker o `install.sh`.

Tras instalar:

```bash
sudo systemctl enable --now ServiSesentry-web   # panel (puerto 8080)
sudo systemctl enable --now ServiSesentry       # planificador de monitorización
```

Al desinstalar se borra el venv (lo creó el postinstall), pero **`/etc/ServiSesentry` y
`/var/lib/ServiSesentry` se conservan**: configuración y base de datos sobreviven, que es lo
que hace seguro reinstalar.

> CI instala cada paquete en su distro (Debian 12, Ubuntu 24.04, Fedora 41) y comprueba que
> el venv resultante importa de verdad `flask`, `cryptography` y `paramiko` — construir un
> paquete demuestra que se generó, no que funcione. Si esa verificación falla, no hay release.

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
| `config.json` | Daemon de monitorización en el primer arranque | Configuración mínima (debug desactivado, intervalo 300 s) — único fichero que se crea en disco |
| `data.db` | Panel web / daemon en el primer inicio | Base de datos (SQLite) con la cuenta `admin` y contraseña predeterminada **y** la configuración de módulos/ítems (tablas `module_config`/`module_config_items`); las tablas se crean automáticamente |

> **Persistencia:** usuarios, roles, grupos, sesiones, auditoría, historial **y la
> configuración de módulos/ítems** (tablas `module_config`/`module_config_items`) se
> almacenan en **`data.db`** (SQLite) dentro del
> directorio var (`/var/lib/ServiSesentry/` en Linux). El esquema se crea y
> reconcilia automáticamente. Opcionalmente puede usarse PostgreSQL o MySQL
> configurando la sección `database` de `config.json` (ver
> [ref-configuracion.md](ref-configuracion.md)).

Tras el primer arranque puedes abrir el panel web para configurar las alertas de
Telegram, añadir objetivos de monitorización y cambiar la contraseña de administrador.

### Instalación preconfigurada

Si quieres que la instalación llegue con una configuración específica ya
establecida — por ejemplo en un despliegue automatizado o por script — coloca tu
fichero `config.json` en el directorio `data/` antes de ejecutar `install.sh`:

```text
data/
└── config.json      # configuración global, token de Telegram, opciones del panel web
```

`install.sh` copiará los ficheros `data/*.json` que encuentre allí a
`/etc/ServiSesentry/`. `config.json` es el único fichero que se siembra: si no
está, la aplicación lo genera en el primer arranque tal como se describe más
arriba. La configuración de módulos/ítems vive en la base de datos
(`data.db`, tablas `module_config`/`module_config_items`), que se crea automáticamente;
se configura desde el panel web. Los usuarios, roles, grupos, sesiones,
auditoría, historial y estado de las comprobaciones tampoco son ficheros: viven
en `data.db`, que se crea automáticamente en el directorio var en el primer inicio.

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
| `ServiSesentry.service` | simple | Servicio de monitorización long-running (`--monitor`, bucle continuo) |
| `ServiSesentry-web.service` | simple | Ejecuta el panel web de administración de forma continua |

> El monitor ya es un servicio continuo propio (programa sus ciclos internamente),
> así que **no hace falta un `.timer` de systemd**. Las versiones antiguas usaban
> `ServiSesentry.timer` para lanzar pasadas oneshot cada 5 min; ya no se instala
> (los scripts `uninstall.sh`/`update.sh` lo limpian si existe de instalaciones previas).

### Instalación

```bash
sudo cp init/systemd/ServiSesentry.service     /lib/systemd/system/
sudo cp init/systemd/ServiSesentry-web.service /lib/systemd/system/
sudo systemctl daemon-reload
```

### Habilitar monitorización

```bash
sudo systemctl enable --now ServiSesentry.service
```

El servicio ejecuta el monitor en bucle continuo. El **intervalo entre ciclos** se
configura en el panel (Configuration → `monitoring.timer_check`, por defecto 300 s),
no en el unit de systemd.

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
systemctl status ServiSesentry.service
systemctl status ServiSesentry-web

# Logs
journalctl -u ServiSesentry.service -f
journalctl -u ServiSesentry-web.service -f

# Reiniciar el monitor (p. ej. tras cambiar el intervalo)
systemctl restart ServiSesentry.service

# Parar / deshabilitar
systemctl disable --now ServiSesentry.service
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
> [ref-configuracion.md](ref-configuracion.md#variables-de-entorno).

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

```mermaid
flowchart LR
    client["Cliente"] -- HTTPS --> proxy["Proxy inverso"]
    proxy -- "HTTP:8080" --> app["ServiceSentry"]
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
   - **Deja *Cache Assets* desactivado** (ver el aviso de abajo)

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

#### *Cache Assets*: déjalo apagado

Con esa opción activada, las peticiones de estáticos que llevan la marca de versión
—`/static/css/web_admin.css?v=1787470367`, los logos, los iconos— vuelven con **502**,
mientras que las mismas URL **sin** `?v=` parecen funcionar. Eso último es el engaño: sin la
query las sirve la caché del propio proxy, así que lo único que llega de verdad a la
aplicación es lo que falla, y el panel se queda sin hoja de estilos ni imágenes.

Es fácil confundirlo con un panel roto: fallan a la vez el CSS y los PNG, que no comparten
ninguna causa dentro de la aplicación.

La opción, además, **no aporta nada aquí**: el panel ya versiona sus propios estáticos con la
fecha de modificación del fichero (`asset_v`, ver `lib/web_admin/mixins/context.py`), que es
justo lo que hace que el navegador recoja una hoja de estilos nueva sin vaciar la caché a
mano. Cachearlos otra vez en el proxy sólo añade una capa que puede equivocarse.

Para comprobar si el problema es éste o es la aplicación, pide `https://tu-dominio/api/v1/health`:
no es estático, no lleva query y no lo cachea nadie. Si contesta `200`, la aplicación está
viva y el 502 es del proxy.

---

### Traefik

> **Atajo:** el compose `docker/docker-compose.microservices-traefik.yml` ya trae
> un Traefik integrado con TLS Let's Encrypt automático; solo necesitas definir
> `SS_DOMAIN` y `SS_ACME_EMAIL`. Ver [caso-docker.md → Traefik](caso-docker.md#traefik). Lo
> de abajo es para integrar con un Traefik **ya existente**.

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
