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
