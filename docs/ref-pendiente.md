# Trabajo pendiente

> Lo que quedó a medias o se aplazó **a propósito**, con el motivo. No es una lista de deseos:
> cada entrada es una decisión ya tomada que alguien —tú dentro de seis meses, o un asistente
> en otra máquina— necesita conocer para no reproponer lo hecho ni rehacer lo descartado.
>
> Los bugs ya resueltos viven en [caso-diagnostico.md](caso-diagnostico.md); lo publicado, en
> el [CHANGELOG](../CHANGELOG.md). Aquí solo hay futuro.
>
> **Última revisión: 2026-08-13** (build.64). En ella se retiraron dos entradas que ya estaban
> hechas —las **copias programadas como lista de tareas** (tareas con sus partes, su frecuencia
> y su retención, perfiles compartidos, bloqueo de copias y la migración del intervalo antiguo)
> y el **lease del planificador de copias**, que además nunca había funcionado— y se añadieron
> las tres que faltaban: el entorno en los servicios standalone, el frontend sin navegador y el
> nombre de la marca.

## Frontend

### Layouts por sección

Ronda de unificación de listados y tablas por sección (rama `feat/list-table-layouts`).

- **Hechas:** Credentials, Audit, Events. Users / Roles / Groups ya tenían el par.
- **Pendientes:** **Servers, Syslog, History.**

Saber cuáles faltan evita volver a proponer las que ya están.

### Ningún test ejecuta JavaScript

Los tests de frontend leen la plantilla **como texto**: comprueban que una regla CSS está, que
una función se llama, que una clase se usa. No abren un navegador, así que no ven ni geometría
ni transiciones.

Los dos bugs de la barra lateral de agosto de 2026 son exactamente lo que se escapa por ahí: una
columna de detalle que heredaba `height: 100vh` y desbordaba la página 52 px, y un
`display: none` sin animar que hacía que plegar y desplegar se vieran distintos. Ninguna guarda
de texto podía verlos; los dos se aislaron **midiendo en Chromium**.

**Playwright ya está instalado** en el venv y funciona (se usó para reproducir, medir y
verificar los dos). Lo que falta es decidir qué merece un test con navegador —el desbordamiento
de la página en cada sección con rail y la simetría del plegado son los dos primeros
candidatos— y dónde vive: `tests/e2e/` es la carpeta, porque necesita un navegador de verdad.

### La marca dice «SENTINEL NEXUS»

El lockup (`assets/brand/logo.png`) lleva ese nombre, y el panel se llama **ServiceSentry** en el
`<title>`, en la barra lateral y en el arranque. Pasaba desapercibido mientras el arte solo
estaba en el login; desde que ocupa el pie de la barra lateral a lo ancho, es lo primero que se
lee.

**Decisión pendiente, del dueño del proyecto**, no trabajo de código: o el arte se rehace con el
nombre del panel, o el panel pasa a llamarse como el arte. Lo segundo ya es barato: el nombre
vive en `lib.APP_NAME` y todo lo que firma con él lo lee de ahí (ver `test_app_name.py`, que
también documenta las dos excepciones que **no** deben seguirlo — los identificadores
registrados en Entra ID y en Proxmox).

## Backend

### Catálogo MIB en tabla de módulo

Existe el mecanismo general de tablas-de-módulo en la BD principal
(`lib/db/module_tables.py`), pero el **catálogo de símbolos MIB de SNMP sigue en su fichero
SQLite local** (`snmp_mibs/mib_catalog.sqlite`).

**Aplazado por decisión explícita:** se pidió *"solo el mecanismo general"*. Migrarlo es
trabajo aparte, no un olvido.

### Entorno `SS_*` en los servicios standalone, y el ipban del Syslog dedicado

Plan aprobado y **sin escribir**. Dos agujeros reales del modelo multi-contenedor:

- **Los overrides por entorno no se aplican al consumir la config.** `ConfigManager.read()`
  devuelve la config guardada *sin* env a propósito (la UI necesita distinguir *guardado* de
  *fijado por entorno*), y el env solo se superpone en parches por sección. Consecuencia
  confirmada: **`telegram|*` no se aplica en ningún punto de envío** —ni web ni standalone—, así
  que un despliegue que fije `SS_TELEGRAM_TOKEN`/`CHAT_ID` no envía con esas credenciales; y
  `SS_EVENTS_AUTOSTART` se ignora en el arranque embebido.
- **El Syslog standalone no bloquea IPs baneadas.** El jail vive en la BD compartida y el
  listener descarta IPs *si* recibe los callbacks `is_banned`/`on_offense`, que `syslog/manager.py`
  cablea desde `self._ipban` — pero `SyslogService` no construye ese objeto, así que un
  contenedor de syslog dedicado no aplica fail2ban.

Forma decidida: un `overlay_all_env(cfg)` en `lib/config/manager.py` aplicado **solo en los
surfaces de CONSUMO** (el router de notificaciones y los tres `_read_config_file` de servicio),
nunca en `ConfigManager.read` / `_read_config_file` del web ni en `_config_section` — ahí
rompería la edición de config, que usa el valor guardado como base del merge. Y un
`lib/services/ipban/factory.py` con `make_ipban()` + `configure_ipban()` framework-free, que el
WebAdmin reutiliza y el `SyslogService` llama al construirse y al reconciliar.

`EventService` no lo necesita: no tiene listener de red ni acción de baneo.

## Seguridad

### CVE abiertos en el lock

**Ninguno.** Auditoría del 2026-08-05: los 4 avisos que había se cerraron subiendo el lock a la
última estable de cada dependencia. Detalle en
[explica-seguridad.md → CVE de dependencias](explica-seguridad.md#cve-de-dependencias).

Lo que queda es **hábito, no deuda**: volver a pasar `pip-audit` sobre el lock de vez en cuando
y al preparar una release. Un lock con hashes envejece en silencio — no avisa solo.

### Deferidos de la auditoría de bugs (2026-07)

De aquella ronda quedaron sin arreglar, clasificados como latentes o de borde:

- **BD (severidad baja):** fallback de líder en PostgreSQL, introspección PG sin schema,
  upsert de `event_cursor`/cooldowns en MySQL, `ADD COLUMN` idempotente.
- **Frontend (severidad baja):** los recogidos como *frontend-lows* en la misma ronda.

**Riesgo aceptado explícitamente:** exfiltración vía `api_test_host_ssh`. El endpoint se
endureció parcialmente (`api_test_credential` perdió `servers_edit`), pero el riesgo de fondo
se asumió a conciencia — no lo "arregles" sin releer aquella decisión.

## Empaquetado

### Debian 12 y anteriores no pueden instalar el `.deb`

El lock se genera con Python 3.14 y sus hashes ponen a pip en `--require-hashes`; un intérprete
por debajo de **3.11.3** activa dependencias condicionales que el lock no lleva (`redis` pide
`async-timeout`). Debian 12 trae 3.11.2 y queda fuera; el postinstall lo detecta y lo dice.

**Aplazado a propósito:** cubrirlo exigiría regenerar el lock con un Python más antiguo, lo que
afecta también a la imagen Docker. Para esas máquinas: Docker o `install.sh`. Detalle en
[caso-despliegue.md](caso-despliegue.md).

### Los paquetes solo se han validado en CI

`nfpm` y el demonio Docker no estaban disponibles donde se escribió el empaquetado, así que
**ningún `.deb`/`.rpm` se construyó ni instaló en local**. Lo que lo prueba es el job
`packages-install` del pipeline (Debian 13 / Ubuntu 24.04 / Fedora), no una prueba manual.
