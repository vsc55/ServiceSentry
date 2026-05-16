# Referencia de `schema.json`

Guía completa de todas las opciones disponibles en los archivos `schema.json` de los módulos watchful de ServiceSentry.

---

## Estructura general

Cada módulo tiene un archivo `schema.json` en la raíz de su carpeta. El archivo es un objeto JSON con una clave por **colección**:

```json
{
    "__module__": { ... },
    "list":       { ... }
}
```

| Colección | Descripción |
|-----------|-------------|
| `__module__` | Campos de configuración a nivel de módulo (afectan a todo el módulo) |
| `list` | Campos de configuración por ítem (una entrada por recurso monitorizado) |
| `config` | Colección alternativa para módulos sin ítems individuales (p. ej. `ram_swap`) |

---

## Propiedades de campo

Cada campo dentro de una colección es un objeto con las siguientes propiedades:

### `type` — **obligatorio**

Tipo de dato del campo.

| Valor | Control UI | Tipo Python |
|-------|-----------|-------------|
| `"bool"` | Toggle switch | `bool` |
| `"str"` | Input text | `str` |
| `"int"` | Input number (entero) | `int` |
| `"float"` | Input number (decimal) | `float` |
| `"list"` | (reservado) | `list` |

---

### `default` — **obligatorio**

Valor por defecto cuando el campo falta en `modules.json`. Usado por Python para rellenar valores ausentes y por la UI para inicializar formularios nuevos.

```json
"timeout": {"type": "int", "default": 10}
```

---

### `min` / `max`

Valor mínimo y máximo permitido para campos numéricos (`int` o `float`). Aplicado como atributo HTML en el input y validado al perder el foco.

```json
"port": {"type": "int", "default": 80, "min": 1, "max": 65535}
```

---

### `sensitive`

Si es `true`, el campo se renderiza como `<input type="password">` (contenido oculto). Usado para contraseñas, tokens y claves privadas.

```json
"password": {"type": "str", "default": "", "sensitive": true}
```

---

### `options`

Lista de valores permitidos para campos `str`. La UI genera un `<select>` desplegable en lugar de un input libre.

```json
"conn_type": {"type": "str", "default": "tcp", "options": ["tcp", "socket", "ssh"]}
```

Las etiquetas visibles de cada opción se definen en los archivos de idioma bajo `option_labels`:

```json
"option_labels": {
    "conn_type": {"tcp": "TCP directo", "socket": "Socket Unix", "ssh": "Túnel SSH"}
}
```

---

### `group`

Nombre del grupo visual al que pertenece el campo. Los campos con el mismo `group` se agrupan bajo un encabezado con ese nombre. La etiqueta visible del encabezado se define en `group_labels` de los archivos de idioma.

```json
"host":     {"type": "str", "default": "", "group": "server"},
"port":     {"type": "int", "default": 0,  "group": "server"},
"password": {"type": "str", "default": "", "group": "server", "sensitive": true}
```

---

### `show_when`

Condición de visibilidad. El campo solo se muestra cuando el campo de control tiene uno de los valores indicados. Las condiciones múltiples se evalúan con AND lógico.

```json
"socket": {
    "type": "str",
    "default": "",
    "show_when": {"conn_type": ["socket"], "db_type": ["mysql", "postgres"]}
}
```

Cuando el campo está oculto, su valor no se incluye en el payload enviado al servidor.

---

### `placeholder`

Texto de marcador de posición estático para el input. El valor especial `"__key__"` muestra la clave del ítem como placeholder (útil como fallback cuando el campo está vacío).

```json
"host": {"type": "str", "default": "", "placeholder": "192.168.1.1"}
```

---

### `placeholder_module`

Nombre de un campo a **nivel de módulo** (`__module__`) cuyo valor se usa como placeholder dinámico en los ítems. Permite heredar el valor por defecto del módulo como sugerencia visual.

```json
"timeout": {"type": "int", "default": 0, "placeholder_module": "timeout"}
```

Cuando el usuario modifica el campo de módulo, todos los placeholders de ítems se actualizan automáticamente.

---

### `placeholder_map`

Objeto que mapea el valor de otro campo al placeholder de este campo. Usado para mostrar el puerto por defecto según el motor de base de datos seleccionado.

```json
"port": {
    "type": "int",
    "default": 0,
    "placeholder_map": {
        "mysql": 3306, "postgres": 5432, "mssql": 1433,
        "mongodb": 27017, "redis": 6379, "influxdb": 8086
    }
}
```

La clave del `placeholder_map` es el valor del campo inmediatamente anterior que actúa como control (en el caso del ejemplo, `db_type`).

---

### `input_action`

Botón de icono acoplado al input (Bootstrap input-group). Permite ejecutar una acción directamente desde el campo, como listar bases de datos o seleccionar un recurso.

```json
"db": {
    "type": "str",
    "default": "",
    "input_action": {
        "id":           "list_databases",
        "url":          "/api/watchfuls/datastore/list_databases",
        "extra":        {},
        "icon":         "bi-database",
        "result":       "field_picker",
        "result_field": "db"
    }
}
```

Propiedades de `input_action`:

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `id` | str | Identificador; se busca en `action_labels` del idioma para la etiqueta del botón |
| `url` | str | Endpoint al que se hace POST con los datos del ítem como body |
| `extra` | dict | Campos extra añadidos al payload antes del envío |
| `icon` | str | Clase Bootstrap Icons (p. ej. `"bi-database"`) |
| `result` | str | Modo de resultado: `"toast"`, `"list"` o `"field_picker"` |
| `result_field` | str | Solo para `"field_picker"`: campo del ítem que se rellena con el valor elegido |

Modos de resultado (`result`):
- `"toast"` — muestra la respuesta como notificación emergente
- `"list"` — muestra `res.data.items` como badges bajo el campo
- `"field_picker"` — abre un modal con la lista `res.data.items`; al seleccionar, escribe en `result_field`

---

### `supported_platforms`

Lista de plataformas en las que el campo está disponible. En plataformas no incluidas, el campo se renderiza como un badge "No compatible" desactivado en lugar de un control interactivo.

```json
"local": {
    "type": "bool",
    "default": true,
    "supported_platforms": ["linux"]
}
```

Valores válidos: `"linux"`, `"win32"`, `"darwin"`.

Cuando `discover_schemas()` detecta que la plataforma actual no está en la lista, añade `__unsupported__: true` al campo en los schemas devueltos. La UI renderiza entonces el badge "No compatible" en lugar del control.

---

## Meta-claves de colección (`__*__`)

Las claves que empiezan y terminan con `__` controlan el comportamiento de la UI. No corresponden a campos de datos y son ignoradas por Python en tiempo de ejecución.

---

### `__field_order__`

Lista de nombres de campo que fija el orden de renderizado en el formulario. Los campos no incluidos en la lista se añaden al final en orden de declaración.

```json
"__field_order__": ["enabled", "db_type", "conn_type", "host", "port", "password"]
```

---

### `__group_when__`

Objeto `{nombre_grupo: condición_show_when}`. Controla cuándo el **encabezado** de un grupo es visible, independientemente de la visibilidad de los campos que contiene. Si un grupo no aparece aquí, su encabezado siempre se muestra.

```json
"__group_when__": {
    "ssh": {"conn_type": ["ssh"]}
}
```

---

### `__actions__`

Lista de botones de acción para el formulario del ítem. Cada acción genera un botón que hace POST al endpoint indicado con los datos actuales del ítem.

```json
"__actions__": [
    {
        "id":         "test_connection",
        "url":        "/api/watchfuls/datastore/test_connection",
        "extra":      {},
        "icon":       "bi-plug",
        "variant":    "outline-info",
        "full_width": true,
        "result":     "toast"
    },
    {
        "id":         "test_ssh",
        "url":        "/api/watchfuls/datastore/test_connection",
        "extra":      {"_test_mode": "ssh"},
        "show_when":  {"conn_type": ["ssh"]},
        "group":      "ssh",
        "icon":       "bi-hdd-network",
        "variant":    "outline-secondary",
        "full_width": true,
        "result":     "toast"
    }
]
```

Propiedades de cada acción:

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `id` | str | Identificador único. Se busca en `action_labels` del idioma |
| `url` | str | Endpoint al que se hace POST con los datos del ítem |
| `extra` | dict | Campos extra fusionados con el payload antes del envío |
| `icon` | str | Clase Bootstrap Icons |
| `variant` | str | Variante Bootstrap del botón (`"outline-info"`, `"outline-secondary"`, etc.) |
| `full_width` | bool | Si `true`, el botón ocupa el 100 % del ancho disponible |
| `result` | str | Modo de resultado: `"toast"` (notificación), `"list"` (badges), `"field_picker"` (modal de selección) |
| `result_field` | str | Solo para `"field_picker"`: campo que recibe el valor seleccionado |
| `show_when` | dict | Igual que en campos: oculta el botón según el valor de otro campo |
| `group` | str | Si se especifica, el botón se inyecta dentro del bloque visual del grupo en lugar de al pie del formulario |

---

### `__test__`

URL del endpoint de test rápido. Aparece como botón en el encabezado de la colección (no en cada ítem individualmente). Hace POST con los datos del ítem seleccionado.

```json
"__test__": "/api/watchfuls/datastore/test_connection"
```

La acción invocada debe estar en `WATCHFUL_ACTIONS` del módulo.

---

### `__discovery__`

URL del endpoint de descubrimiento automático. Activa el botón "Descubrir" en el encabezado de la colección. La UI hace GET a esa URL y muestra los resultados en un modal para incorporarlos con un clic.

```json
"__discovery__": "/api/watchfuls/filesystemusage/discover"
```

El endpoint debe devolver una lista de objetos con al menos `{"key": "...", "label": "..."}`. La acción invocada debe estar en `WATCHFUL_ACTIONS` del módulo.

---

### `__discovery_field__`

Nombre del campo que recibe un botón de búsqueda inline (input-group). Al pulsar el botón se abre el modal de descubrimiento en modo "selección de campo": los ítems ya añadidos aparecen desactivados y seleccionar uno escribe su valor en el campo. Requiere `__discovery__`.

```json
"__discovery_field__": "partition"
```

---

### `__key_mirrors_field__`

Nombre de un campo. Cuando está definido, la clave del ítem se sincroniza automáticamente con el valor de ese campo cada vez que se selecciona un valor desde el modal de descubrimiento. El botón de renombrar se oculta para los ítems de esta colección.

```json
"__key_mirrors_field__": "service"
```

Usado en `service_status`: la clave del ítem es siempre igual al valor del campo `service`.

---

### `__new_item_fields__`

Lista de campos que deben rellenarse obligatoriamente al crear un ítem nuevo. La UI muestra solo esos campos en el diálogo de creación antes de desplegar el formulario completo.

```json
"__new_item_fields__": ["db_type"]
```

---

## Colección `__module__`

Define los ajustes a nivel de módulo. Campos habituales:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `enabled` | bool | Habilita o deshabilita el módulo completo |
| `threads` | int | Número de hilos paralelos para procesar ítems |
| `timeout` | int | Timeout por defecto para las comprobaciones |
| `attempt` | int | Número de reintentos por comprobación (módulo `ping`) |
| `alert` | int | Umbral de alerta en porcentaje o grados |
| `code` | int | Código HTTP esperado (módulo `web`) |
| `local` | bool | Usar monitorización local (módulo `raid`) |

---

## Archivos de idioma (`lang/*.json`)

Complementan `schema.json` con etiquetas, hints y textos de UI. No forman parte de `schema.json` directamente pero son fusionados por `discover_schemas()`.

| Sección | Descripción |
|---------|-------------|
| `pretty_name` | Nombre visible del módulo en la UI |
| `labels` | Etiqueta visible de cada campo (`{campo: "Etiqueta"}`) |
| `hints` | Texto de ayuda bajo el campo en la UI (`{campo: "Descripción..."}`) |
| `option_labels` | Etiquetas de las opciones de campos con `options` (`{campo: {valor: "Etiqueta"}}`) |
| `group_labels` | Nombre visible de cada grupo (`{nombre_grupo: "Etiqueta"}`) |
| `action_labels` | Etiqueta del botón de cada acción (`{id_accion: "Etiqueta"}`) |
| `collections` | Nombre visible de cada colección (`{"list": "Servidores"}`) |
| `rename_item_prompt` | Texto personalizado para el modal de renombrar ítem |
| `new_item_key_label` | Etiqueta personalizada para el campo de clave en el modal de nuevo ítem |

---

## Procesamiento en Python (`discover_schemas`)

`ModuleBase.discover_schemas()` genera el objeto `ITEM_SCHEMAS` que consume la UI:

1. Lee `schema.json` de cada módulo (siempre desde disco, sin caché)
2. Importa el módulo para acceder a `WATCHFUL_ACTIONS` y `SUPPORTED_PLATFORMS`
3. Fusiona `label_i18n` desde `lang/*.json` en cada campo
4. Marca con `__unsupported__: true` los campos cuya `supported_platforms` excluye la plataforma actual
5. Si el módulo tiene `SUPPORTED_PLATFORMS` y la plataforma no está incluida, añade `__unsupported__: true` a toda la colección
6. Construye la entrada `__i18n__` combinando `info.json` + `lang/*.json`

El resultado es un dict plano con claves `"modulo|coleccion"`:

```python
{
    "datastore|__module__": {...},
    "datastore|list":       {...},
    "datastore|__i18n__":   {"en_EN": {...}, "es_ES": {...}},
    "ping|__module__":      {...},
    "ping|list":            {...},
    ...
}
```

---

## Exposición de acciones web (`WATCHFUL_ACTIONS`)

Para que un classmethod del módulo sea invocable desde la UI, debe estar listado en `WATCHFUL_ACTIONS`:

```python
class Watchful(ModuleBase):
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'test_connection', 'list_databases'})
```

El endpoint genérico `GET|POST /api/watchfuls/<module>/<action>` comprueba que la acción esté en este frozenset antes de ejecutarla. Cualquier acción no listada devuelve `404`.

- **GET**: llama al classmethod sin argumentos → usado por `discover()`
- **POST**: llama al classmethod con el body JSON como `dict` → usado por `test_connection()` y `list_databases()`

Las respuestas de acciones que devuelven listas de recursos (como `list_databases`) usan siempre la clave `"items"`, no `"databases"` ni ningún nombre específico de motor.

---

## Guardia de plataforma a nivel de módulo (`SUPPORTED_PLATFORMS`)

Esta variable de **clase Python** (no una propiedad de `schema.json`) protege el módulo entero en plataformas no soportadas. Se declara directamente en la clase `Watchful`:

```python
class Watchful(ModuleBase):
    SUPPORTED_PLATFORMS = ('linux', 'darwin')   # no disponible en Windows
```

Cuando la plataforma actual no está en la tupla, `discover_schemas()` añade `__unsupported__: true` a **todas las colecciones** del módulo. La UI renderiza entonces un badge "No compatible" en lugar de los formularios interactivos.

| Valor      | Plataforma |
|------------|------------|
| `"linux"`  | Linux      |
| `"darwin"` | macOS      |
| `"win32"`  | Windows    |

**Distinción con `supported_platforms` de campo:**

| Mecanismo | Dónde se declara | Alcance |
| --- | --- | --- |
| Clase `SUPPORTED_PLATFORMS` | `watchful.py` / `__init__.py` | Módulo completo — toda la colección queda inactiva |
| Campo `supported_platforms` | `schema.json`, por campo | Solo ese campo — el resto del formulario sigue activo |

Usa `SUPPORTED_PLATFORMS` en la clase cuando el módulo entero es inútil en esa plataforma (p. ej. `temperature` en Windows). Usa `supported_platforms` por campo cuando solo una opción específica no está disponible (p. ej. el campo `local` de `raid`, que usa `/proc/mdstat` y solo existe en Linux aunque el módulo soporta monitorización remota en cualquier plataforma).

---

## Módulos y sus características de schema

| Módulo | Colecciones | `__actions__` | `__test__` | `__discovery__` | `__discovery_field__` | `__key_mirrors_field__` |
|--------|-------------|:-------------:|:----------:|:---------------:|:---------------------:|:-----------------------:|
| `datastore` | `__module__`, `list` | ✓ | ✓ | — | — | — |
| `filesystemusage` | `__module__`, `list` | — | — | ✓ | ✓ (`partition`) | — |
| `hddtemp` | `__module__`, `list` | — | — | — | — | — |
| `ping` | `__module__`, `list` | — | — | — | — | — |
| `raid` | `__module__`, `list` | — | — | — | — | — |
| `ram_swap` | `__module__` | — | — | — | — | — |
| `service_status` | `__module__`, `list` | — | — | ✓ | ✓ (`service`) | ✓ (`service`) |
| `temperature` | `__module__`, `list` | — | — | ✓ | — | — |
| `web` | `__module__`, `list` | — | — | — | — | — |
