# Rendimiento

> Modelo de concurrencia, cuellos de botella, cachés y límites de recursos de ServiceSentry.
>
> Este documento se basa en el código real (ejecutor de checks, capa de BD, frontend). Donde
> algo no puede deducirse del código (p. ej. cifras de latencia absolutas) se indica
> explícitamente.

Complementa la sección "Modelo de Concurrencia" de [explica-arquitectura.md](explica-arquitectura.md).

---

## Modelo de concurrencia

ServiceSentry es **multihilo, no async** (no usa `asyncio`). Toda la paralelización se apoya
en `ThreadPoolExecutor` y en hilos daemon dedicados. Esto encaja porque el trabajo del monitor
es mayoritariamente **I/O-bound** (SSH, HTTP, sockets, consultas a BD), donde el GIL se libera
durante la espera.

### Niveles de paralelismo

| Nivel | Mecanismo | Límite | Fuente |
|---|---|---|---|
| Entre módulos (un ciclo) | `ThreadPoolExecutor` compartido | `max_workers = min(nº módulos, 16)` | [executor.py:112](../src/lib/services/monitoring/executor.py#L112) |
| Entre items (dentro de un módulo) | `ThreadPoolExecutor` por módulo | `max_workers = workers` (config del módulo) | [module_base.py:423](../src/lib/modules/module_base.py#L423) |
| Camino legacy `Monitor.check()` | `ThreadPoolExecutor` propio | `max_workers = max_threads` | [monitor.py:809](../src/lib/modules/monitor.py#L809) |
| Notificaciones | **síncrono** en `flush()` al final del ciclo | — (sin hilo de fondo) | [executor.py:143](../src/lib/services/monitoring/executor.py#L143) |

El **on-demand** (botón "ejecutar checks" de la UI) y el **scheduler** comparten el mismo
`run_checks` de [executor.py](../src/lib/services/monitoring/executor.py); solo difieren en el
timeout (on-demand 45s, scheduler 120s — [manager.py:298](../src/lib/services/monitoring/manager.py#L298)).

### Detalles que evitan problemas

- **Import secuencial primero**: los módulos se importan en serie **antes** de lanzarlos en
  paralelo, para evitar una carrera de `sys.path` (dnspython vs el watchful `dns`)
  ([executor.py:105](../src/lib/services/monitoring/executor.py#L105)).
- **`_save_lock`** serializa el guardado de estado; el historial se registra en serie.
- **Timeout duro por ciclo** con `wait(timeout=…)` + `shutdown(wait=False, cancel_futures=True)`:
  un módulo colgado no bloquea el ciclo indefinidamente; se audita el timeout.
- **Notificación única por ciclo**: el notifier se vacía **una sola vez** al final, agrupando
  todas las alertas del ciclo (evita spam y N conexiones SMTP/HTTP). No hay hilo de envío de
  fondo (se eliminó el antiguo hilo daemon de Telegram que se filtraba por ciclo).

### Hilos daemon de larga vida

Todos `daemon=True`, por lo que no impiden el cierre del proceso:

- Servidores web: uno por interfaz (`web-<host>:<port>`).
- `ss-scheduler` (bucle del monitor), `event-worker`, listeners de syslog (uno por bind),
  `svc-health`, `cert-scan`, `hb-<key>` (heartbeat), `control-server`, `*-config-watch`.

> **Nota:** la tabla de concurrencia de [explica-arquitectura.md](explica-arquitectura.md) se centra en el
> pipeline de checks; el resto de hilos daemon se enumeran aquí.

---

## Cuellos de botella y consideraciones

### El ciclo de monitorización

- El tiempo de un ciclo ≈ el módulo/item **más lento** (los rápidos esperan en el `wait`).
  Ejemplos de checks lentos por naturaleza: SSH a hosts remotos, HTTP con timeouts,
  resolución DNS, SNMP con reintentos.
- Con muchos módulos, el tope de **16 workers** entre módulos puede serializar parcialmente.
  El paralelismo por-item dentro de cada módulo lo compensa para módulos con muchos items.
- **Recomendación**: ajustar el `interval` del scheduler por encima del tiempo típico de
  ciclo; usar `workers` por módulo para módulos con muchos items (p. ej. muchos hosts SSH).

### Base de datos

- **SQLite** (por defecto) es fichero único: escrituras serializadas. Suficiente para la carga
  típica (un ciclo cada N segundos). Para despliegues con **varios procesos** compartiendo BD
  (modo microservicios, HA) usar **PostgreSQL/MySQL**, que manejan concurrencia real de
  escritura. Ver [ref-esquema-bd.md](ref-esquema-bd.md) y [explica-servicios.md](explica-servicios.md).
- **Índices**: las tablas de series y de alto volumen llevan índices compuestos pensados para
  sus consultas (p. ej. `history` por `(item_uid, ts)` y `(module, key, ts)`; `syslog` por
  `ts`/`severity`/`hostname`/`app`/`facility`). Ver el detalle en [ref-esquema-bd.md](ref-esquema-bd.md).
- **Downsampling de historial**: las gráficas agregan por buckets con
  `CAST(FLOOR((ts - ?) / ?) AS <int>)` en SQL (portable), evitando traer todas las filas al
  cliente ([history/store.py:38](../src/lib/core/history/store.py#L38)).

### Reconcile de esquema en el arranque

- En cada arranque se introspecciona y reconcilia cada tabla. El coste es proporcional al nº de
  tablas (32) y normalmente trivial; solo un cambio de esquema que requiera **rebuild**
  (crear-copiar-borrar-renombrar) toca todas las filas de esa tabla una vez. Ver
  [ref-esquema-bd.md § Portabilidad](ref-esquema-bd.md#portabilidad-multi-motor).

---

## Cachés y polling

### Backend

- **Descubrimiento self-describing cacheado**: permisos, widgets, servicios embebidos, tipos
  de credencial, etc. se descubren una vez y se memorizan (ver [explica-descubrimiento.md](explica-descubrimiento.md)).
- **Tokens de versión de config**: `GET /api/v1/config/versions` devuelve solo los tokens por
  campo, para que el frontend detecte cambios sin descargar toda la config
  ([ref-api.md](ref-api.md#configuración--libcoreconfigroutespy)).
- **Re-aplicación de `log_level` por ciclo**: el scheduler relee `global|log_level` cada ciclo
  para reflejar ediciones en vivo sin reiniciar ([manager.py:286](../src/lib/services/monitoring/manager.py#L286)).

### Frontend

- **Sin paso de build / sin bundler**: Bootstrap 5 + JS vanilla (+ Alpine.js y CodeMirror
  vendorizados). El JS se ensambla server-side como un único bundle inline vía
  `partials/_js_sections.html`.
- **Cache-busting por mtime**: CSS/JS se enlazan con `?v=<asset_v>` calculado por `stat` del
  fichero ([app.py:1097](../src/lib/web_admin/app.py#L1097)), de modo que un fichero editado
  siempre llega al navegador sin invalidación manual.
- **Polling ligero + overlay de conexión perdida**: el cliente sondea endpoints ligeros
  (`/api/v1/health`, `/api/v1/config/versions`, estado) y muestra un overlay si el servidor no
  responde ([core/_api.html](../src/lib/web_admin/templates/partials/core/_api.html),
  [core/_polling.html](../src/lib/web_admin/templates/partials/core/_polling.html)).
- **`Cache-Control: no-store`** en todas las respuestas `/api/` (datos siempre frescos).

---

## Límites de recursos (caps de tablas)

Varias tablas de alto volumen se **auto-recortan** para acotar el crecimiento del disco. Al
insertar, el store poda las filas más antiguas por encima del tope:

| Tabla | Tope de filas | Fuente |
|---|---|---|
| `event_rules_notifications` | 1 000 | [events/store/log.py](../src/lib/services/events/store/log.py) |
| `ip_bans` | 5 000 | [ipban/store/bans.py](../src/lib/services/ipban/store/bans.py) |
| `ip_ban_history` | 20 000 | [ipban/store/history.py](../src/lib/services/ipban/store/history.py) |
| `ip_offense_counters` | 20 000 | [ipban/store/offense_counters.py](../src/lib/services/ipban/store/offense_counters.py) |
| `ip_offense_log` | 20 000 | [ipban/store/offense_log.py](../src/lib/services/ipban/store/offense_log.py) |
| `ip_whitelist` | 2 000 | [ipban/store/whitelist.py](../src/lib/services/ipban/store/whitelist.py) |
| `syslog_drops` | 500 | [ipban/store/drops.py](../src/lib/services/syslog/store/drops.py) |

- **`history`** y **`syslog`** (mensajes) **no** llevan un tope fijo de filas: crecen según la
  retención configurada. Revisar la retención en [ref-configuracion.md](ref-configuracion.md).
- **`MAX_CONTENT_LENGTH = 8 MiB`** limita el tamaño de request entrante
  ([app.py:952](../src/lib/web_admin/app.py#L952)).

---

## Uso de memoria

- El estado vivo de checks (`check_state`) y las series (`history`) viven en BD, no en memoria
  del proceso web — el antiguo `status.json` en memoria fue reemplazado por la tabla
  `check_state` ([ref-esquema-bd.md](ref-esquema-bd.md#check_state--estado-vivo-por-check-reemplaza-statusjson)).
- Los pools de hilos se crean por ciclo/operación y se cierran con `shutdown`, sin acumular
  hilos entre ciclos.
- **No hay cifras de consumo medidas en el repositorio**: el footprint real depende del nº de
  módulos/items, del backend de BD y del volumen de syslog/historial. Para dimensionar, medir
  en el entorno concreto.

---

## Recomendaciones de escalado

1. **Muchos hosts/items** → subir `workers` por módulo y separar el monitor a un proceso
   **standalone** (modo microservicios) con BD PostgreSQL/MySQL compartida.
2. **Alta disponibilidad** → varios monitores con lease de líder (`service_leader`); solo el
   líder ejecuta, el resto en espera. Ver [explica-servicios.md](explica-servicios.md) y [caso-kubernetes.md](caso-kubernetes.md).
3. **Volumen alto de syslog** → BD de syslog **dedicada** (`syslog_db`) para no competir con la
   BD principal.
4. **Latencia de UI** → el frontend ya usa polling ligero; el coste está en los endpoints de
   datos, no en assets (sin build, cache-busting por mtime).

---

## Ver también

- [explica-arquitectura.md](explica-arquitectura.md) — componentes y modelo de concurrencia
- [ref-esquema-bd.md](ref-esquema-bd.md) — tablas, índices y portabilidad multi-motor
- [explica-servicios.md](explica-servicios.md) — embebido vs standalone, HA y plano de control
- [ref-configuracion.md](ref-configuracion.md) — intervalos, retención, `workers`
