# Logging

> Cómo registra ServiceSentry: sistema `Debug` propio (principal) + un segundo camino con el
> `logging` de la librería estándar (parcial, sin configurar).
>
> Este documento se basa en el código. La clave de configuración del nivel
> (`global.log_level`) se cubre en [ref-configuracion.md](ref-configuracion.md).

---

## Resumen

ServiceSentry **no** usa `logging.basicConfig`/`dictConfig` ni handlers de fichero/rotación.
El registro principal es una clase `Debug` propia que imprime a **stdout**. Existe además un
uso residual del `logging` estándar en tres puntos, **sin handler ni nivel configurados**.

| | Sistema `Debug` (principal) | `logging` stdlib (residual) |
|---|---|---|
| Destino | stdout (`print`) | stderr (`lastResort`, WARNING+) |
| Niveles | null/debug/info/warning/error/emergency | los de Python |
| Configuración | config + CLI + env | **ninguna** (sin handler) |
| Rotación | no | no |
| Color | ANSI por nivel (si TTY) | no |

---

## Sistema `Debug` (principal)

### Componentes

- Clase `Debug` — [lib/debug/debug.py:59](../src/lib/debug/debug.py#L59).
- `DebugLevel` (IntEnum) — [lib/debug/debug_level.py](../src/lib/debug/debug_level.py):
  `null=0, debug=1, info=2, warning=3, error=4, emergency=5`.
- **Singleton compartido**: `ObjectBase.debug = Debug(True, DebugLevel.info)` — atributo de
  clase compartido por todas las subclases ([lib/core/object_base.py:32](../src/lib/core/object_base.py#L32)).

### Comportamiento

- **Destino**: `print()` a stdout ([debug.py:142](../src/lib/debug/debug.py#L142)); las
  excepciones también se imprimen. **Sin fichero, sin rotación.**
- **Filtro por nivel mínimo**: un mensaje se muestra solo si `enabled` y `self.level <=
  msg_level`, salvo `force=True`.
- **Formato**: `[{NIVEL:<7}] {mensaje}` — p. ej. `[INFO   ]`, `[WARNING]`. Los objetos no-str
  se formatean con `pprint`.
- **Color**: ANSI por nivel, aplicado solo si `Debug._color` y `sys.stdout.isatty()`. En
  consolas legacy de Windows se habilita ANSI vía ctypes.

### Cómo se fija el nivel (orden de prioridad)

De menor a mayor prioridad — cada capa sobreescribe la anterior:

1. **Config** — clave `global|log_level`, por defecto `'off'`
   ([lib/config/spec.py:256](../src/lib/config/spec.py#L256)). `set_from_config()` mapea el
   string a enabled+nivel; `'off'`/`''`/`'none'`/`'false'` deshabilita. Valores aceptados:
   `off, debug, info, warning, error`.
2. **CLI** `--log-level` / **env** `SS_LOG_LEVEL` — en el arranque web sobreescribe la config
   ([main.py:180](../src/main.py#L180), [app.py:1310](../src/lib/web_admin/app.py#L1310)).
3. El **scheduler re-aplica** `global|log_level` en cada ciclo, de modo que un cambio en vivo
   surte efecto sin reiniciar ([manager.py:286](../src/lib/services/monitoring/manager.py#L286)).

El monitor **standalone** usa `'info'` por defecto si no hay nivel definido.

### Color

`--nocolor` / `SS_NOCOLOR` / `NO_COLOR` → `Debug.set_color(False)`.

### Banners de arranque

Los mensajes de bind del servidor (host:puerto) se imprimen **directamente** a stdout/stderr,
saltándose el log, "porque el nivel por defecto es `off`"
([app.py:1561](../src/lib/web_admin/app.py#L1561)) — así siempre se ve dónde escucha el
servidor aunque el logging esté desactivado.

> ⚠️ **`--verbose` / `SS_VERBOSE` NO cambian el nivel de log.** Solo activan el **debugger
> interactivo de Flask** (`app.debug=True` + `DebuggedApplication`,
> [main.py:201](../src/main.py#L201), [app.py:1553](../src/lib/web_admin/app.py#L1553)). Para
> subir el detalle del log usar `--log-level` / `SS_LOG_LEVEL` / `global.log_level`.

---

## `logging` estándar (residual, sin configurar)

Existe un segundo camino de logging en solo tres sitios reales, con `logging.getLogger(__name__)`
**sin handler ni nivel** — cae al `lastResort` de Python (solo WARNING+ a stderr), por lo que
sus mensajes `info(...)` se **descartan silenciosamente**:

- [lib/db/base.py:28](../src/lib/db/base.py#L28) — mensajes del reconcile de esquema
  (columnas/índices añadidos o conservados). Sus `info` no se ven; los `warning` sí (p. ej.
  añadir columna NOT NULL sin default).
- [lib/db/module_tables.py:53](../src/lib/db/module_tables.py#L53) — avisos del descubrimiento
  de tablas de módulo.
- [watchfuls/snmp/__init__.py:110](../src/watchfuls/snmp/__init__.py#L110) — avisos de fuentes
  MIB.

> **Implicación práctica:** para ver los `info`/`debug` de la capa de BD (evolución de esquema)
> habría que añadir un handler al logger raíz o al logger `lib.db`. Hoy no hay ninguno; solo
> emergen los `warning`/`error`. Es una diferencia de comportamiento a tener en cuenta al
> diagnosticar arranques.

---

## Recomendaciones operativas

- **Producción**: `global.log_level = warning` (o `info` para más contexto). Recoger stdout con
  el gestor de procesos (systemd journal, Docker logs, k8s). Ver [caso-despliegue.md](caso-despliegue.md),
  [caso-docker.md](caso-docker.md), [caso-kubernetes.md](caso-kubernetes.md).
- **Rotación**: no la hace la app. Delegarla en el recolector (journald, `docker logs` con
  driver de logging, o logrotate sobre el fichero al que redirijas stdout).
- **Depuración puntual**: `--log-level debug` (o editar `global.log_level` en la UI — el
  scheduler lo re-aplica en caliente). `--verbose` solo para el debugger de Flask en desarrollo.
- **Sin color** en destinos no-TTY: automático (se detecta `isatty`); forzar con `SS_NOCOLOR`
  si algún recolector lo interpreta mal.

---

## Qué se traza (con `log_level=debug`)

Capas transversales que cubren todas las áreas:

- **HTTP** — una línea por petición de **cualquier** endpoint: método, ruta, función handler, claves de entrada (query + body, **nunca valores** → sin secretos), estado, motivo del rechazo (4xx/5xx), tiempo y tamaño.
- **SQL** — cada consulta a BD (statement, **nunca los params**).
- **Config** — lecturas de `config.json` (cache miss) y guardado paso a paso.
- **Dominio** — login/auth (LDAP/local/SSO), notificaciones (canales/SMTP/webhook), scheduler (ciclo/módulo/ítem), inicialización de DB y Telegram.

Nada de esto registra contraseñas, tokens ni secretos.

---

## Ver también

- [ref-configuracion.md](ref-configuracion.md) — clave `global.log_level`, flags CLI y resto de configuración
- [ref-cli.md](ref-cli.md) — opciones de línea de comandos
- [caso-despliegue.md](caso-despliegue.md) / [caso-docker.md](caso-docker.md) / [caso-kubernetes.md](caso-kubernetes.md) — recogida de stdout
