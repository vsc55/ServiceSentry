# Referencia de i18n: esquemas de tags y ficheros de idioma

Referencia de consulta rápida del sistema de internacionalización: la
**estructura del fichero de idioma por módulo** (`lang/*.json`), los **tres
esquemas de tags** que documentan los placeholders de los textos de
notificación (`notif_msg_vars` / `notif_email_vars` / `messages_vars`) y las
**dos convenciones de placeholder** (`{}` secuencial vs. `{0}`/`{1}` indexado)
que aplica `_fill`.

La **mecánica** (arquitectura de dos capas, pipeline de `discover_schemas()`,
resolución de etiquetas en el navegador, añadir un idioma) vive en
[explica-i18n.md](explica-i18n.md); la **entrega** de notificaciones (canales,
router, editor de textos) en [explica-notificaciones.md](explica-notificaciones.md).

---

## Fichero de idioma por módulo (`lang/*.json`)

### Estructura de archivos

```text
src/watchfuls/mi_modulo/
  +-- lang/
        +-- en_EN.json   ← etiquetas en inglés
        +-- es_ES.json   ← etiquetas en español
        +-- fr_FR.json   ← (añadir para soporte de francés)
```

### Formato del archivo

```json
{
    "pretty_name": "Mi Módulo",
    "module_description": "Qué monitoriza este módulo",
    "labels":      { "enabled": "Habilitado", "host": "Host", "timeout": "Tiempo máximo (s)" },
    "hints":       { "timeout": "Segundos antes de abortar la comprobación" },
    "group_labels":{ "connection": "Conexión" },
    "option_labels": { "scheme": { "http": "HTTP", "https": "HTTPS" } },
    "action_labels": { "test_connection": "Probar conexión" },
    "collections": { "list": "Servidores" },
    "field_terms": { "db": { "mysql": { "label": "Base de datos" }, "redis": { "label": "Índice" } } },
    "new_item_key_label": "Nombre del servidor",
    "rename_item_prompt": "Nuevo nombre",
    "messages": {
        "ups_online": "UPS: {} - Online ({}){} ✅",
        "ups_alert":  "UPS: {} - {} ({}) {}"
    },
    "messages_vars": {
        "ups_online": ["UPS", "status", "detail"],
        "ups_alert":  ["UPS", "reasons", "status", "icon"]
    }
}
```

| Clave | Propósito |
|-------|-----------|
| `pretty_name` | Nombre legible del módulo mostrado en la cabecera de la UI |
| `module_description` | Descripción/ayuda del módulo |
| `labels.<campo>` | Etiqueta del campo en el formulario de configuración del módulo |
| `hints.<campo>` | Texto de ayuda (tooltip) bajo el campo |
| `group_labels.<grupo>` | Nombre visible de cada grupo de campos (`group`) |
| `option_labels.<campo>.<valor>` | Etiquetas de las opciones de un campo con `options` |
| `action_labels.<id>` | Etiqueta de cada botón de acción (`__actions__`/`input_action`) |
| `collections.<col>` | Nombre visible de cada colección (p. ej. `list`) |
| `field_terms.<campo>.<valor>` | Label/hint/acción según otro campo (ver `term_field` en [ref-schema-json.md](ref-schema-json.md)) |
| `new_item_key_label` | Etiqueta del campo de clave en el modal de nuevo ítem |
| `rename_item_prompt` | Texto del modal de renombrar ítem |
| `messages.<msg_key>` | **Textos i18n de los checks** que el módulo emite a las notificaciones (con placeholders `{}`); los resuelve `ModuleBase._msg()` |
| `messages_vars.<msg_key>` | **Esquema de tags** de cada mensaje: nombre de cada placeholder, para el editor de textos |

Solo `pretty_name` y `labels` son habituales; el resto son opcionales. Las
claves de presentación (`labels`, `hints`, `group_labels`, …) se fusionan en
`label_i18n`/`__i18n__` por `discover_schemas()` (ver
[explica-i18n.md → Cómo `discover_schemas()` construye el pipeline](explica-i18n.md#cómo-discover_schemas-construye-el-pipeline)).
En cambio `messages` y `messages_vars` **no** entran en el schema del navegador:
son la parte de **notificación** del fichero de módulo.

---

## Los tres esquemas de tags

Cada texto de notificación admite **placeholders**, y cada uno tiene un esquema
que los nombra para el editor. Hay **tres** esquemas, todos traducibles y por
idioma:

| Esquema | Ubicación | Forma | Placeholders |
|---------|-----------|-------|--------------|
| `notif_msg_vars` | `lib/i18n/lang/<idioma>.py` | `{msg_key: [nombre, …]}` | Posicionales `{}` / `{0}` `{1}` de los mensajes `notif_msg_*` del core |
| `notif_email_vars` | `lib/i18n/lang/<idioma>.py` | `{string_key: [[token, descripción], …]}` | Token **fijo** con nombre (`{item}`, `{n}`, `{ts}`, `{sender}`) + descripción traducida |
| `messages_vars` | `watchfuls/<mod>/lang/<idioma>.json` | `{msg_key: [nombre, …]}` | Posicionales de los `messages` del módulo; es el **hook de descubrimiento** de tags de un módulo |

Ejemplos:

```python
# lib/i18n/lang/en_EN.py
'notif_msg_vars':   { 'notif_msg_auth_login': ['user', 'auth method', 'IP address'] },
'notif_email_vars': { 'alert_down': [['{item}', 'affected service/host']] },
```

```json
// watchfuls/ups/lang/en_EN.json
"messages_vars": { "ups_online": ["UPS", "status", "detail"] }
```

> **Dos convenciones de placeholder:** los mensajes `notif_msg_*` y los
> `messages` de módulo usan `{}` **posicional** (el orden importa); las cadenas
> de email usan placeholders **con nombre** (`{item}`, `{n}`, `{ts}`,
> `{sender}`), que se sustituyen por clave.

---

## Placeholders: secuencial vs. indexado (`_fill`)

`_fill(text, args)` (`lib/core/notify/formatting.py`) soporta **dos** formas de
placeholder, combinables en una misma cadena:

- **Secuencial `{}`** — cada `{}` consume el siguiente argumento en orden.
- **Indexado `{0}` / `{1}` …** — inserta `args[N]` por posición, lo que permite
  **reordenar** los valores. Es imprescindible en overrides y traducciones,
  donde el orden natural de la frase difiere entre idiomas (un `{}` plano no
  puede expresarlo). Los índices fuera de rango se dejan intactos.

Esta ayuda se muestra al usuario en el editor vía
`notif_tpl_placeholders_hint`.

---

## Ver también

- [explica-i18n.md](explica-i18n.md) — mecánica de traducción: arquitectura de
  dos capas, pipeline de `discover_schemas()`, resolución de etiquetas en el
  navegador y cómo añadir un idioma nuevo.
- [explica-notificaciones.md](explica-notificaciones.md) — entrega de
  notificaciones: canales, router, matriz de routing, severidad y el editor de
  textos con sus endpoints.
