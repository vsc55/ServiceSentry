# Trabajo pendiente

> Lo que quedó a medias o se aplazó **a propósito**, con el motivo. No es una lista de deseos:
> cada entrada es una decisión ya tomada que alguien —tú dentro de seis meses, o un asistente
> en otra máquina— necesita conocer para no reproponer lo hecho ni rehacer lo descartado.
>
> Los bugs ya resueltos viven en [caso-diagnostico.md](caso-diagnostico.md); lo publicado, en
> el [CHANGELOG](../CHANGELOG.md). Aquí solo hay futuro.

## Frontend

### Layouts por sección

Ronda de unificación de listados y tablas por sección (rama `feat/list-table-layouts`).

- **Hechas:** Credentials, Audit, Events. Users / Roles / Groups ya tenían el par.
- **Pendientes:** **Servers, Syslog, History.**

Saber cuáles faltan evita volver a proponer las que ya están.

## Backend

### Catálogo MIB en tabla de módulo

Existe el mecanismo general de tablas-de-módulo en la BD principal
(`lib/db/module_tables.py`), pero el **catálogo de símbolos MIB de SNMP sigue en su fichero
SQLite local** (`snmp_mibs/mib_catalog.sqlite`).

**Aplazado por decisión explícita:** se pidió *"solo el mecanismo general"*. Migrarlo es
trabajo aparte, no un olvido.

### Copias programadas: una lista de tareas, no un intervalo global

**Lo que hay hoy** (build.57): *un* intervalo para toda la instalación —cada N horas—, con una
retención y un interruptor de secretos. Copia siempre lo mismo: `core` + `config.json`.

**Lo que falta:** una **lista de tareas programadas**, cada una con su propio nivel de copia y su
propia frecuencia. El caso que lo motiva: la configuración y el inventario interesan a diario,
pero el syslog o los MIBs quizá una vez por semana o al mes — y hoy eso no se puede expresar sin
copiarlo todo con la frecuencia del más exigente, que es como se llena el disco.

Forma: una colección de tareas `{nombre, cada N horas, partes[], secretos, retención propia}`.
Las partes ya están declaradas en `PARTS` (`lib/core/backup/service.py`), así que el formulario
de una tarea se dibuja del mismo catálogo que el de una copia manual.

Lo que hay que decidir antes de escribir código, porque cambia el diseño:

- **Dónde viven las tareas.** No son config escalar (`spec.py` no sirve): son *feature data*, como
  los webhooks o los layouts de Overview. Eso significa tabla propia y store, con su store+mixin
  como el resto de dominios.
- **La retención pasa a ser por tarea.** Si no, la diaria borra las copias de la mensual: hoy la
  poda cuenta todas las automáticas juntas. El nombre tendrá que decir de qué tarea salió
  (`auto-<tarea>-<fecha>`), y `is_auto`/`prune` en `schedule.py` se acotan a esa tarea.
- **Solapes.** Dos tareas que vencen a la vez leen todas las tablas dos veces. ¿Se serializan
  bajo el mismo *lease*, o se deja que cada una vaya por su lado?
- **La transición.** Los ajustes actuales (`backup_every_hours`, `backup_keep`,
  `backup_auto_secrets`) son de `spec.py`: o se migran a una tarea llamada «predeterminada» al
  arrancar, o se retiran y se pierde lo que un operador ya hubiera configurado. Migrar es lo
  correcto; retirarlos sin más es una copia que deja de hacerse en silencio.
- El planificador (`runner.py`) recorrería tareas en vez de un único intervalo. `is_due` y
  `prune` ya son funciones puras y valen tal cual, una por tarea.

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
