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

### Plurales entre paréntesis: «{} tarea(s)»

Medido el 2026-09-12: **59 cadenas en `es_ES.py` y 55 en `en_EN.py`** escriben el plural entre
paréntesis — `{} error(es)`, `{} miembro(s)`, `Grupo(s) desconocido(s)`. Es lo que escribe un
programa que no quiso elegir, y se lee como tal.

La convención para arreglarlo **ya existe y está en uso**: una segunda clave `…_one` con el
singular escrito entero (`summary_one`, `config_updated_banner_one`, y ahora
`timer_backup_task_one` y `jobs_timers_unleased_one`), y quien la usa elige. Lo que falta es
pasar las otras ciento diez y pico, cada una en su punto de uso — no es un reemplazo de texto,
porque hay que tocar la llamada.

No se ha hecho de una vez a propósito: son ~114 cadenas repartidas por todo el panel y cada una
tiene su llamante. Las de la pantalla de Temporizadores sí están hechas, que es donde se
reportó.

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

### El inventario que SNMP ya descubre y nadie recoge

Medido sobre la instalación real el **2026-09-12**:

| SNMP ha descubierto | Tecleado en el inventario |
|---|---|
| **10** discos con modelo y bahía (de 20 dispositivos) | **8** SSD |
| 464 interfaces con identidad — **no son piezas** | **4** tarjetas de red |
| **79** adyacencias LLDP | **11** cables |
| 214 volúmenes, 30 agregados, 28 pilas | **17** equipos, **24** piezas |

**Cuidado con las cifras de esta tabla, que ya se contaron mal una vez.** «230 discos» eran 220
series de *atributos* SMART (`dev_sda_Power_On_Hours`, `dev_sda_Seek_Error_Rate`…) más diez
discos de verdad: los dispositivos distintos son **20**, y sólo **10** traen modelo y bahía. Los
otros diez sólo tienen estado, sin modelo ni serie, así que de ellos no hay nada que proponer. Y
una interfaz **no es una tarjeta**: una de cuatro puertos es una pieza, y agrupar 464 interfaces
en tarjetas físicas no se puede hacer sin inventar.

Lo que SNMP descubre —modelo y número de serie de un disco, MAC y alias de una interfaz, vecino
LLDP, descripción del sistema, incluso `location` con coordenadas— se guarda en
`history_series.attrs`, un JSON por serie con «lo que la serie ES, como se vio por última vez».
Son 1.311 series con identidad guardada.

**Y no cruza al inventario.** Comprobado: ni `lib/core/snmp/` ni `watchfuls/snmp/` nombran una
tabla `dc_*`, y `lib/core/dcim/service.py` no lee `attrs`. `dc_item` y `dc_part` se rellenan a
mano.

Lo llamativo es que **la tabla ya existe y encaja casi campo a campo**. Un disco descubierto:

```json
{"bay": "Disk 1", "kind": "SATA", "model": "ST12000VN0008-2JH101", "role": "data"}
```

y `dc_part` tiene `slot`, `kind`, `model`, `serial`, `size`, `qty`, `description`. `bay` → `slot`
y las otras dos por su nombre. La forma de tabla está escrita, con su pantalla, sus permisos, su
historial de versiones y su parte en la copia de seguridad. Falta el camino.

> **Hecho en parte (2026-09-12).** Lo de abajo se escribió creyendo que no había ningún
> mecanismo de proponer. **Sí lo había, y para el cableado**: `cable_check` lleva tiempo
> detectando un latiguillo movido y devolviendo las adyacencias sin declarar listas para
> aceptar. Lo que faltaba era que alguien lo dijera sin que hubiera que abrir la pestaña, y eso
> ya está: un explorador periódico con su arriendo, su política de repetición y su estado en
> `dc_drift`. **Lo que sigue pendiente es el inventario de PIEZAS** —discos, tarjetas—, que es
> de lo que trata el resto de esta entrada.

**Decidido (2026-09-12): el descubrimiento PROPONE, no crea.** Un inventario que se rellena solo
y uno donde alguien ha dicho que sí no son el mismo producto, y éste es el segundo. Va en la misma
línea que «un módulo ausente no está apagado, está sin añadir».

Eso **no tiene precedente en el panel**: lo único parecido es `__provision_host__`, que hace lo
contrario —crea o actualiza el host que el módulo describe, sin preguntar
([provisioning.py](../src/lib/core/modules/provisioning.py))—. Así que hay que inventar la forma,
y de proponer se sigue más de lo que parece:

- **Emparejar antes de proponer.** Un disco ya tecleado no puede volver a ofrecerse. La llave
  natural es `serial` cuando lo hay y `(item_uid, slot)` cuando no — y SNMP no siempre trae
  número de serie: el bloque de ejemplo de arriba tiene `bay`, `kind`, `model` y `role`, y ningún
  serial.
- **Una propuesta rechazada tiene que quedarse rechazada.** Si vuelve en el siguiente ciclo, la
  lista de propuestas se convierte en ruido y deja de mirarse a la semana. Eso es estado nuevo:
  «esto se vio y se dijo que no».
- **Y una aceptada tiene que poder actualizarse sin pisar lo tecleado.** Si alguien corrigió el
  modelo a mano, el siguiente descubrimiento no puede deshacerlo.

**Lo que sí está claro** es que `attrs` seguirá siendo un JSON y está bien que lo sea: es una
caché de «lo último que se vio» para que la ficha de un dispositivo enseñe el modelo del disco
sin ir a buscarlo, incluso con la máquina en mantenimiento y sin estado vivo. Lo que no es, es el
inventario. Consumirlo hoy obliga a leer 1.311 documentos y a saberse de memoria que la ruta es
`_attrs → synology_disks → model`, que en otro fabricante se llama distinto — no hay SQL que
pregunte eso, ni índice que lo sirva, ni pantalla que lo filtre.

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

### Una VM no tiene cable: cómo se coloca en el mapa de enlaces

**Estado: decidido dejarlo como está, sin decidir qué hacer después.** Se apunta aquí para que
no se reproponga desde cero.

**El caso.** Un servidor añadido con `grp_linux` sale en el mapa de enlaces con línea de
*deducido* y nunca de LLDP. Comprobado contra la base de datos real: el panel **sí** recorre
`lldp` (el watchful lee todas las métricas de todos los perfiles asignados, sin filtrar por
sonda) y la tabla vuelve vacía. Es una VM sobre Proxmox, y allí hay dos cosas distintas: dentro
de la VM no corre agente LLDP publicando por SNMP (`lldpd -x` + `master agentx`), y el puente
**es Open vSwitch** —no un puente Linux, así que `group_fwd_mask` no aplica; el equivalente es
`ovs-vsctl set port <puerto> other_config:forward-bpdu=true`—.

**Por qué no se ha "arreglado".** Ninguna de las dos es un fallo del panel, y la segunda
seguramente tampoco haya que tocarla: **una VM no tiene cable**. LLDP contesta «qué hay al otro
lado de mi cable», y el de una VM es un puerto virtual en un switch virtual; el enlace físico es
host PVE ↔ switch, y la VM comparte ese puerto. Es el consenso del sector y no una carencia
nuestra: **NetBox lo prohíbe en el modelo de datos** (un cable termina en la interfaz de un
*dispositivo*, y una interfaz de VM no puede terminar un cable), **LibreNMS** cuelga las VMs del
hipervisor en lugar de ponerlas en el mapa, y **Netdisco** las localiza en el puerto físico del
host. Dibujar una VM enchufada a `gi11` sería más falso, no más preciso.

**Lo que queda por decidir**, y por eso está aquí y no borrado:

- **Colgar las VMs de su host** en el mapa, en vez de dejarlas como cajas con enlace deducido.
  El panel ya sabe qué máquina es un hipervisor y qué nodos declara —el módulo Proxmox lo
  recoge— así que el dato existe; lo que no está decidido es si eso es un dibujo mejor o una
  jerarquía que estorba en un mapa de cables.
- **Decir por qué un dispositivo no tiene enlace LLDP.** Es la tercera vez que la pregunta llega a
  mano: «se le preguntó por vecinos y no contestó» es un estado que el panel conoce (perfil
  asignado, tabla vacía) y no enseña en ninguna parte.
- **La heurística de puerto de Netdisco.** `_port_edges` descarta un puerto si hay más de una
  máquina **conocida** en él; Netdisco mira **cuántas MAC hay en total** y se queda con el que
  menos tiene. La diferencia importa en un caso real: un uplink a un switch no gestionado con
  una sola máquina conocida detrás y doscientas MAC desconocidas se dibuja hoy como cable
  directo, y no lo es.
- **Intención frente a observado**, al estilo NetBox: anotar el cable que *debería* existir y
  que el mapa marque «documentado y no visto» / «visto y no documentado». Es lo único que
  detecta que alguien movió un latiguillo.
- **CDP**, el día que entre equipo Cisco: otra tabla, el mismo mecanismo que ya tiene `lldp`.

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
