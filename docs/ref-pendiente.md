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

### Los `register()` de rutas han crecido hasta ser el fichero

Auditoría del 2026-08-15. `register(app, wa)` guarda las rutas de un dominio como *closures*,
así que su tamaño es el del dominio entero y no el de una función: **46 funciones pasan de 100
líneas y las seis primeras son todas `register`** — `providers/entraid/routes.py` (646),
`core/hosts/routes.py` (474), `core/users/routes.py` (351), `core/modules/routes.py` (350),
`core/config/routes.py` (300), `core/notify/email/template_routes.py` (291).

No es deuda automática: el patrón es deliberado y `wa` se captura una vez. Pero a partir de
cierto tamaño deja de caber en la cabeza de nadie, y **entraid ya se partió una vez** en
`declarations.py` / `provision_saml.py` / `routes.py` sin que la de rutas adelgazara.

**El corte natural, cuando toque, es por concepto y no por líneas**: en entraid, el asistente de
aprovisionamiento, SCIM y SAML2 son tres cosas que comparten un prefijo de URL y poco más. Se
aplaza porque mover rutas es el cambio con más superficie de regresión del repositorio —cada una
lleva permiso, auditoría y contrato de API— y hoy no hay nada roto que lo justifique. Si se hace,
el guarda que lo protege ya existe: `test_routes_documented.py` y la matriz de permisos por
endpoint.

### Las claves i18n que quizá no usa nadie

De 3.129 claves, **474 no aparecen escritas literalmente fuera de los ficheros de idioma**. La
cifra no es una lista de trabajo: la mayoría se construyen por concatenación (`'cfg_desc_' + id`,
`'diag_sev_' + severity`, las rutas de configuración `sección|campo` que se resuelven por path),
y ese es el mismo motivo por el que la guarda de i18n solo comprueba la dirección contraria —que
lo referenciado exista—.

Para poder borrar algo hay que separar antes lo dinámico de lo muerto, y eso significa enumerar
los prefijos que se construyen en código y restarlos. Mientras no exista esa lista, **cualquier
poda es a ciegas**: una clave borrada de más no falla en los tests, sale como el nombre crudo en
la pantalla de alguien.

### Los dos techos de la consulta de dependencias

Auditoría del 2026-08-16, leyendo `lib/core/diagnostics`. La consulta remota tiene dos límites
que hoy **no se dicen en pantalla**, y ninguno de los dos es un fallo mientras la instalación
sea normal:

- **`MAX_DETAILS = 60`.** La gravedad se pide una vez por identificador distinto, y por encima
  de sesenta el resto se queda sin ficha. Eso no es sólo una columna vacía: sin ficha tampoco
  hay `aliases`, así que `collapse_aliases` deja de unir el GHSA con su PYSEC y **el total
  vuelve a contar doble** — que es justo lo que esa función existe para evitar. Sesenta avisos
  distintos es una instalación donde la columna no es lo primero que arreglar, pero el recorte
  es silencioso: la pantalla no distingue «60 de 87 calificados» de «87 calificados».
- **El número de filas no tiene tope.** Las que sólo ejecutan otros contenedores salen de la
  tabla de latidos, así que su tamaño no lo decide este proceso: `latest_versions` lanza una
  petición a PyPI por nombre distinto, y una instancia que publicara diez mil paquetes serían
  diez mil peticiones desde un botón. Escribir en esa tabla ya exige la BD compartida —quien
  puede hacerlo tiene cosas mejores que hacer—, pero la regla que el propio módulo se pone es
  *«no puede costar nada»*, y una lista de tamaño ajeno la incumple.

Lo honesto sería **decirlo en la respuesta** (cuántos se calificaron de cuántos, cuántas filas
se preguntaron) antes que inventar un recorte con un número elegido a ojo; se deja pendiente
porque el sitio donde se dice es la tarjeta, y eso es diseño de pantalla y no una constante.

### Dos ajustes vivos sin sitio en la pantalla de configuración

Auditoría del 2026-08-16, cruzando el registro (`lib/config/spec.py`, 208 campos) contra el
layout (`lib/config/layout.py`). De los que no caen en ninguna tarjeta, todos menos dos están
fuera **a propósito** y el código lo dice: `web_admin|username`/`password` son credenciales de
primer arranque que después se gestionan en Usuarios, y `msteams_channels|*` es una sección de
array con CRUD propio dentro de la tarjeta de Teams. Quedan dos que no tienen excusa escrita:

| Campo | Estado | Cómo se cambia hoy |
|---|---|---|
| `web_admin\|cache_reload_secs` | int, 5 (0–300), `admin_only`, vivo en `web_admin/mixins/freshness.py` y aplicado desde la config guardada (está en `INT_RULES`) | **Por nada**: no tiene `card` y tampoco variable de entorno. Sólo escribiendo la fila en la BD |
| `web_admin\|ipban_whitelist` | str, `admin_only`, vivo en `services/ipban/factory.py` | Sólo por `SS_IPBAN_WHITELIST` |

Lo que delata que iban a estar en pantalla: **las dos llevan etiqueta i18n y texto de ayuda
escritos en los dos idiomas** (`cache_reload_secs` y `web_admin|cache_reload_secs`, y los
gemelos de ipban). Ese texto se escribió para una pantalla que nunca los muestra.

Ojo con la segunda: **no es** la lista blanca de la pestaña fail2ban. Aquélla es el store
(`extra_whitelist`); ésta es la de configuración, y el jail las fusiona. Darle tarjeta significa
decidir antes si tener dos listas blancas en dos sitios sigue teniendo sentido.

**No hay guarda que impida un tercero**: `test_config_layout.py` comprueba que los campos de una
tarjeta existan en el registro, nunca la dirección contraria. Un campo nuevo con `card=None` se
añade sin que nada proteste.

### Valores fijos en código que se comportan como ajuste

Del mismo repaso, sobre las 39 constantes de nivel de módulo con pinta de tunable. La mayoría
**no** lo son y están bien donde están —límites de protocolo (`_MAX_HOSTNAME=255` y `_MAX_APP=48`
de RFC 5424, `_MAX_DATAGRAM=65535`, `_TG_LIMIT=3800` de Telegram, `BATCH_MAX=20` que es el techo
de Graph y lo dice), anchos de columna y los topes de fila de los stores de fail2ban—. Tres sí:

- **`_MODULE_CHECK_TIMEOUT = 45`** (`services/monitoring/checks_mixin.py`) corta el botón
  «ejecutar ahora» mientras `modules|timeout` admite hasta **600**. Sube el timeout a 120 para un
  recorrido SNMP lento y el planificador espera 120 mientras el botón informa «timeout» a los 45:
  el mismo check, dos veredictos, y nada en pantalla dice por qué. Es el más claro de los tres, y
  el arreglo probablemente sea usar el ajuste que ya existe.
- **`PYPI_URL` y `OSV_BATCH_URL`** están escritas en `core/diagnostics/advisories.py` mientras
  `update_check_url` sí es un campo con tarjeta propia — cuyo comentario dice que existe *«para
  que la única dirección que este panel está dispuesto a contactar sea visible para quien decide
  si puede salir a internet»*. Son tres direcciones y sólo se ve una, y una instalación con
  mirror interno (devpi, Nexus) no puede repuntar las otras dos. Con ellas, el `TIMEOUT = 6.0`:
  seis segundos a pypi.org a través de un proxy corporativo es corto y el fallo se lee como «no
  contesta».
- **`_daemonRefresh` cada 5000 ms** (`partials/status/_daemon.html`) mientras los otros cuatro
  sondeos del cliente (`config_poll_secs`, `access_poll_secs`, `session_check_secs`,
  `conn_check_secs`) sí son configurables. Menor, pero es la misma familia.

### El plano de control sólo existe como variable de entorno

`SS_CONTROL_TOKEN`, `SS_CONTROL_PORT`, `SS_CONTROL_BIND` y `SS_CONTROL_ADVERTISE` se leen con
`os.environ` en `services/control_server.py`: no están en el registro ni en pantalla. Están
documentadas en `docker/env.example`, así que no son un descuido — pero sí una asimetría con
`SS_DB_*`, que **sí** está en el registro y la tarjeta Database muestra bloqueado cuando el
entorno lo fija.

El coste concreto: sin token el listener no arranca, y ése es justo el motivo por el que la
pantalla de Diagnóstico lee los otros procesos de la BD y no por HTTP. Se puede ver ahí que un
servicio no responde y **no hay ningún sitio en el panel que diga por qué**.

Las otras variables de sólo-entorno se quedan donde están por naturaleza: `SS_*_EMBEDDED` es una
decisión por proceso y no por instalación, `SS_SERVICE_ROLE`/`SS_WEB_*`/`SS_SYSLOG_*`/
`SS_LOG_LEVEL`/`SS_VERBOSE` los traduce `entrypoint.sh` a flags de CLI, y `SS_USERNAME`/
`SS_PASSWORD` son el bootstrap de primera ejecución.

### Catálogo MIB en tabla de módulo — o no

Existe el mecanismo general de tablas-de-módulo en la BD principal
(`lib/db/module_tables.py`), y el **catálogo de símbolos MIB de SNMP sigue en su fichero SQLite
local** (`{var_dir}/snmp_mibs/mib_catalog.db`). Se aplazó en su día por decisión explícita: se
pidió *«solo el mecanismo general»*.

**Antes de migrarlo hay que resolver una contradicción**, porque el código dice lo contrario que
esta entrada: el docstring de `lib/core/snmp/mibs/catalog.py` sostiene que ese fichero es *a
propósito* un caché derivado local —se reconstruye desde los MIB compilados, la BD de la
aplicación puede ser remota y no tiene por qué cargar con un caché por instalación—. O esa
razón sigue valiendo y esta entrada sobra, o ya no vale y el docstring miente. Decidirlo es el
trabajo; migrar, después, es mecánico.

## Seguridad

### `POST /api/v1/history/test-write` escribe detrás de un permiso de lectura

Auditoría del 2026-08-15. La ruta graba un registro `__test__` y lo borra para verificar el
camino completo de escritura del histórico, y está detrás de `history_view`. Escribir detrás de
un permiso de lectura es una discordancia de categoría; lo natural sería `history_delete`, que
es el permiso de escritura que ese dominio tiene.

No se ha cambiado porque **no he comprobado cómo la oculta el frontend**: si el botón se dibuja
con `history_view`, subir el permiso deja un 403 sin explicación a quien hoy lo ve. Es un cambio
de una línea más el gating del botón, y hay que hacer los dos a la vez.

### Webhook y Teams siguen en BETA

Marcados como tal en su tarjeta de configuración desde el 2026-08-16 (`beta: True` en
`lib/config/layout.py`, insignia dibujada por `cfgCardOpen`). Entregan; lo que les falta es
validación, y está detallado en la entrada siguiente y en la de más abajo sobre `url`/`headers`.
**Quitar la insignia es una línea**, y el criterio para quitarla es que esas dos entradas estén
cerradas — no que el canal «ya funcione», que ya funciona.

### La regla «credenciales externas = sólo admin» sólo se aplica en el PUT de config

Auditoría del 2026-08-15, en `lib/core/notify`. **Decisión de política de permisos**, no un
descuido puntual: el guard vive en `core/config/routes.py` y protege las secciones
`ldap`, `oidc`, `saml2`, `email`, `telegram`, `msteams` **cuando se escriben por
`PUT /api/v1/config`**. Todo lo que vive en su propio almacén tiene rutas propias que no pasan
por ahí:

- **Canales de Teams** (`POST|PUT /api/v1/notify/msteams/channels`) aceptan `webhook_url` con
  sólo `config_edit`. Ese campo está en `ENCRYPT_KEYS` **precisamente porque lleva un token
  dentro**, y `msteams` es una de las secciones reservadas a admin. La misma credencial, dos
  puertas con distinta cerradura.
- **Webhooks genéricos** (`/api/v1/notify/webhooks`) son la primitiva de salida más potente del
  panel —URL, método, cabeceras y cuerpo arbitrarios, disparables con `/test`— y también van
  con `config_edit` a secas.

Y una asimetría dentro del propio webhook: su `secret` se cifra en reposo y se enmascara al
leer, mientras que `url` y `headers` no. Para media Internet (Slack, Discord, Teams) **la URL
es la credencial**, y unas cabeceras suelen llevar un `Authorization`. Ambos se devuelven en
claro a cualquiera con `config_view` y se escriben enteros en el detalle de auditoría.

Las dos decisiones (¿webhooks y canales sólo para admin? ¿`url`/`headers` como secreto?) tienen
coste de UX: enmascarar la URL obliga al patrón «null = conserva lo guardado» que ya usa
`secret`, y el editor de webhooks tendría que respetarlo. Por eso se anota en vez de aplicarse.

### Dos campos de configuración que quizá deberían ser `admin_only`

Auditoría del 2026-08-15, **decisión pendiente porque cambia quién puede editar qué**, no
trabajo de código: son dos líneas en `lib/config/spec.py`.

- **`web_admin|update_check_url`** — es el campo que hace que el servidor salga a una URL
  arbitraria (SSRF de administrador, sólo `https://`, y sólo al pulsar el botón). Sus vecinos de
  la misma familia —`public_url`, `proxy_count`— sí están marcados. Hoy lo puede editar
  cualquiera con `config_edit`.
- **`web_admin|backup_dir`** — de él cuelgan `/api/v1/backups/browse` y `/mkdir`, que enumeran y
  crean directorios **en cualquier ruta** del servidor. El motivo documentado es que quien puede
  editar el campo ya puede apuntarlo donde quiera y leer el error; es cierto, pero un error es un
  oráculo de un bit por ruta y el explorador es enumeración completa del sistema de ficheros.

Marcarlos exige ser admin para editarlos —y, con `backup_dir`, para usar el explorador de
carpetas—, lo que puede molestar a una instalación que hoy delega la configuración de copias.



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
endureció parcialmente (`api_test_credential` perdió `devices_edit`), pero el riesgo de fondo
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
