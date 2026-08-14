# Trabajo pendiente

> Lo que quedó a medias o se aplazó **a propósito**, con el motivo. No es una lista de deseos:
> cada entrada es una decisión ya tomada que alguien —tú dentro de seis meses, o un asistente
> en otra máquina— necesita conocer para no reproponer lo hecho ni rehacer lo descartado.
>
> Los bugs ya resueltos viven en [caso-diagnostico.md](caso-diagnostico.md); lo publicado, en
> el [CHANGELOG](../CHANGELOG.md). Aquí solo hay futuro.
>
> **Última revisión: 2026-08-13** (build.65), y esta vez **comprobando cada entrada contra el
> código**, que es como se descubrió que cuatro de ellas ya estaban hechas:
>
> - **Copias programadas como lista de tareas** — entregado (tareas con partes, frecuencia y
>   retención propias, perfiles compartidos, bloqueo de copias y migración del intervalo viejo).
> - **El lease del planificador de copias** — arreglado en `build.64`; nunca había funcionado.
> - **Layouts por sección** — las tres «pendientes» (Servers, Syslog, History) están entregadas,
>   documentadas y con 64 guards desde el 2026-07-29 (`a5c724f`, *«the last table sections»*).
> - **`SS_*` en los servicios standalone y el ipban del Syslog dedicado** — entregado:
>   `overlay_all_env` existe, `services/base.py::_read_config_file` lo aplica para los tres
>   servicios, el router de notificaciones también, `SS_EVENTS_AUTOSTART` se respeta en el
>   arranque embebido, y `SyslogService` construye su jail con `ipban/factory.py`.
>
> Cuatro entradas caducadas en un solo documento no es mala suerte: es lo que pasa cuando algo
> se marca como pendiente y nadie lo tacha al terminarlo. Y no es inofensivo — es trabajo que
> alguien vuelve a proponer, a estimar y a empezar. **Antes de dar por pendiente lo que hay
> aquí, compruébalo contra el código**; y al terminar algo, la entrada se borra en el mismo
> commit.

## Frontend

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

### Catálogo MIB en tabla de módulo — o no

Existe el mecanismo general de tablas-de-módulo en la BD principal
(`lib/db/module_tables.py`), y el **catálogo de símbolos MIB de SNMP sigue en su fichero SQLite
local** (`{var_dir}/snmp_mibs/mib_catalog.db`). Se aplazó en su día por decisión explícita: se
pidió *«solo el mecanismo general»*.

**Antes de migrarlo hay que resolver una contradicción**, porque el código dice lo contrario que
esta entrada: el docstring de `watchfuls/snmp/mib_catalog.py` sostiene que ese fichero es *a
propósito* un caché derivado local —se reconstruye desde los MIB compilados, la BD de la
aplicación puede ser remota y no tiene por qué cargar con un caché por instalación—. O esa
razón sigue valiendo y esta entrada sobra, o ya no vale y el docstring miente. Decidirlo es el
trabajo; migrar, después, es mecánico.

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
