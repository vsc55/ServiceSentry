# Creación de un módulo de monitorización (Watchful)

Guía paso a paso para crear un módulo de monitorización desde cero en ServiceSentry.

---

## 1. Arquitectura general

```text
main.py -> Monitor
              |-- Descubre módulos en watchfuls/ (packages o archivos *.py)
              |-- Lee modules.json para comprobar si están habilitados
              |-- Instancia Watchful(monitor) por cada módulo
              +-- Ejecuta module.check() en paralelo
                       |
                       v
              Watchful(ModuleBase)
                  |-- Lee su configuración desde modules.json
                  |-- Ejecuta la lógica de monitorización
                  |-- Almacena resultados en dict_return
                  |-- Detecta cambios de estado (check_status)
                  +-- Envía notificaciones por Telegram (send_message)
```

### Jerarquía de clases

```text
ObjectBase          <- instancia de debug compartida
  +-- ModuleBase    <- configuración, rutas, dict_return, mensajería
        +-- Watchful  <- tu módulo concreto
```

---

## 2. Estructura de archivos

Para un módulo llamado `mi_modulo`, crea una carpeta package:

```text
watchfuls/
  +-- mi_modulo/
        +-- __init__.py       <- Implementación del módulo (obligatorio)
        +-- watchful.py       <- Alias: `from . import Watchful` (obligatorio)
        +-- schema.json       <- Schema de campos
        +-- info.json         <- Metadatos del módulo: icono y descripción
        +-- lang/
              +-- en_EN.json  <- Etiquetas de campos en inglés y nombre visible
              +-- es_ES.json  <- Etiquetas en español (u otros idiomas)
        +-- tests/
              +-- test_mi_modulo.py  <- Tests unitarios (recomendado)
```

No es necesario registrar el módulo en ningún sitio. El `Monitor` descubre
automáticamente cualquier carpeta con `__init__.py` dentro de `watchfuls/`.

---

## 3. Plantilla mínima de módulo

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Módulo de monitorización: mi_modulo."""

import concurrent.futures
import json
import os

from lib.debug import DebugLevel
from lib.modules import ModuleBase

# Carga el schema de campos desde schema.json en la carpeta del package
_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class Watchful(ModuleBase):
    """Monitoriza <descripción de lo que hace>."""

    # Schema cargado desde schema.json — define campos, tipos, valores por defecto y rangos.
    # La UI web lo usa para generar formularios y aplicar valores por defecto automáticamente.
    ITEM_SCHEMA = _SCHEMA

    # Atajo para acceder rápidamente a los valores por defecto
    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()}

    # Constantes del módulo (opcional)
    _MI_VALOR_DEFAULT = 42

    def __init__(self, monitor):
        super().__init__(monitor, __package__)
        # __package__ será 'watchfuls.mi_modulo' -> usado como name_module

        # Registrar herramientas del sistema si se necesitan
        # self.paths.set('miherramienta', '/usr/bin/miherramienta')

        # Estado interno (no persiste entre ciclos de monitorización)
        # self._fail_count: dict[str, int] = {}

    def check(self):
        """Punto de entrada principal. Ejecuta la lógica de monitorización."""

        # 1. Leer la lista de ítems configurados
        items = self._get_items()

        # 2. Ejecutar comprobaciones en paralelo
        self._run_checks(items)

        # 3. OBLIGATORIO: llamar a super().check() (registra el log de debug)
        super().check()

        # 4. OBLIGATORIO: devolver dict_return
        return self.dict_return

    # -- Métodos privados -------------------------------------------------

    def _get_items(self):
        """Parsea la configuración y devuelve los ítems habilitados."""
        result = []
        for key, value in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                is_enabled = value
                target = key  # compatibilidad hacia atrás: la clave es el dato operativo
            elif isinstance(value, dict):
                is_enabled = value.get('enabled', self._DEFAULTS['enabled'])
                # El campo 'target' contiene el dato real; si está vacío,
                # se usa la clave como fallback (compatibilidad hacia atrás)
                target = (value.get('target', '') or '').strip() or key
            else:
                is_enabled = self._DEFAULTS['enabled']
                target = key

            self._debug(f"Ítem: {key} - Habilitado: {is_enabled}", DebugLevel.info)
            if is_enabled:
                result.append((key, target))

        return result

    def _run_checks(self, items):
        """Ejecuta las comprobaciones en paralelo usando ThreadPoolExecutor."""
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)
        ) as executor:
            futures = {
                executor.submit(self._item_check, name, target): (name, target)
                for name, target in items
            }
            for future in concurrent.futures.as_completed(futures):
                name, target = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'MiModulo: {name} - *Error: {exc}* '
                    self.dict_return.set(name, False, message)

    def _item_check(self, name, target):
        """Ejecuta la comprobación individual para un ítem."""
        timeout = self.get_conf_in_list('timeout', name, self._DEFAULTS['timeout'])

        # === Aquí va tu lógica de monitorización ===
        status, detail = self._do_check(target, timeout)

        # Construir mensaje
        s_message = f'MiModulo: *{name}* '
        if status:
            s_message += 'OK'
        else:
            s_message += f'FALLO {detail}'

        # Almacenar resultado
        other_data = {'detail': detail}
        self.dict_return.set(name, status, s_message, False, other_data)

        # Notificar si el estado cambió
        if self.check_status(status, self.name_module, name):
            self.send_message(s_message, status)

    def _do_check(self, target, timeout):
        """Realiza la verificación real. Devuelve (status: bool, detail: str)."""
        # Implementa aquí tu lógica específica
        # Ejemplos:
        #   - Hacer una petición HTTP
        #   - Ejecutar un comando: stdout, stderr = self._run_cmd(cmd)
        #   - Conectar a un socket
        #   - Leer un archivo
        raise NotImplementedError("Implementa _do_check")
```

### schema.json

Crea `schema.json` en la raíz de la carpeta del package. Define los campos a
nivel de módulo y por ítem:

```json
{
    "__module__": {
        "enabled": {"type": "bool", "default": true},
        "threads": {"type": "int",  "default": 5, "min": 1, "max": 100}
    },
    "list": {
        "enabled": {"type": "bool", "default": true},
        "target":  {"type": "str",  "default": ""},
        "timeout": {"type": "int",  "default": 10, "min": 1, "max": 300}
    }
}
```

---

## 4. Referencia de campos (`schema.json`)

Los campos se declaran en `schema.json` en la raíz del package — no como dicts
Python inline. El archivo tiene una clave de primer nivel por **colección**:
`__module__` para ajustes a nivel de módulo y una clave por colección nombrada
(habitualmente `list`, a veces `remote` o `config`).

```json
{
    "__module__": {
        "enabled": {"type": "bool", "default": true},
        "threads": {"type": "int",  "default": 5, "min": 1, "max": 100}
    },
    "list": {
        "__field_order__": ["enabled", "label", "mode", "host", "port", "password"],
        "__group_when__": {
            "advanced": {"mode": ["ssh"]}
        },
        "__actions__": [
            {
                "id":        "test_conn",
                "url":       "/api/watchfuls/mi_modulo/test",
                "extra":     {},
                "icon":      "bi-plug",
                "variant":   "outline-info",
                "full_width": true,
                "result":    "toast"
            }
        ],
        "enabled":  {"type": "bool", "default": true},
        "label":    {"type": "str",  "default": "", "group": "connection"},
        "mode":     {"type": "str",  "default": "tcp", "options": ["tcp", "ssh"], "group": "connection"},
        "host":     {"type": "str",  "default": "", "show_when": {"mode": ["tcp", "ssh"]}, "group": "server"},
        "port":     {"type": "int",  "default": 3306, "min": 1, "max": 65535,
                     "show_when": {"mode": ["tcp", "ssh"]}, "group": "server"},
        "password": {"type": "str",  "default": "", "sensitive": true, "group": "server"},
        "db":       {"type": "str",  "default": "", "group": "server",
                     "input_action": {
                         "id":           "list_dbs",
                         "url":          "/api/watchfuls/mi_modulo/databases",
                         "extra":        {},
                         "icon":         "bi-database",
                         "result":       "field_picker",
                         "result_field": "db"
                     }}
    }
}
```

La clase Python carga el archivo una vez al importar y lo expone como `ITEM_SCHEMA`:

```python
_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

class Watchful(ModuleBase):
    ITEM_SCHEMA = _SCHEMA
    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if not k.startswith('__')}
```

### Claves de meta-colección (`__*__`)

Estas claves controlan el comportamiento de la UI y no corresponden a campos de datos:

| Clave | Descripción |
|-------|-------------|
| `__field_order__` | Lista de claves que fija el orden de renderizado en el formulario. Si se omite, se usan los campos en orden de declaración. |
| `__group_when__` | Dict `{nombre_grupo: show_when}`. Controla cuándo el **encabezado** de un grupo es visible, independientemente de los campos que contiene. Si un grupo no aparece aquí, su encabezado siempre se muestra. |
| `__actions__` | Lista de botones de acción que aparecen al pie del formulario (o dentro de un grupo, ver `group` abajo). |
| `__test__` | URL a la que se envía el formulario al pulsar el botón de test rápido del encabezado de colección. |
| `__discovery__` | URL del endpoint `GET /api/watchfuls/<modulo>/discover`. Activa el botón de descubrimiento en el encabezado de la colección. |
| `__discovery_field__` | Nombre del campo al que se añade un botón de búsqueda inline (input-group). Al pulsarlo abre el modal de descubrimiento en modo selección de campo: los ítems ya añadidos aparecen desactivados y seleccionar uno escribe su valor en el campo. Requiere `__discovery__`. |
| `__key_mirrors_field__` | Nombre de un campo. Cuando está definido, la clave del ítem se renombra automáticamente para coincidir con el valor de ese campo cada vez que se selecciona un valor desde el modal de descubrimiento. El botón de renombrar se oculta para los ítems de esta colección. |

### Propiedades de campo

| Propiedad             | Tipo   | Obligatorio | Descripción |
|-----------------------|--------|-------------|-------------|
| `type`                | str    | Sí | `"bool"`, `"int"`, `"float"`, `"str"`, `"list"` |
| `default`             | any    | Sí | Valor por defecto cuando el campo falta en `modules.json` |
| `min`                 | number | No | Valor mínimo (`int` / `float`) |
| `max`                 | number | No | Valor máximo (`int` / `float`) |
| `sensitive`           | bool   | No | Si `true`, se renderiza como campo de contraseña (oculto) en la UI |
| `options`             | list   | No | Lista de valores permitidos para campos `str` → desplegable en la UI |
| `group`               | str    | No | Nombre del grupo visual al que pertenece el campo. Los campos del mismo grupo se agrupan bajo un encabezado |
| `show_when`           | dict   | No | Condición `{campo: [valores]}` que controla si el campo es visible en la UI. Ejemplo: `{"mode": ["ssh"]}` |
| `input_action`        | dict   | No | Define un botón de icono acoplado al input (ver más abajo) |
| `supported_platforms` | list   | No | Lista de plataformas en las que el campo está disponible (`"linux"`, `"win32"`, `"darwin"`). En plataformas no incluidas el campo se renderiza como un badge "No compatible" desactivado en lugar de un control interactivo. Ejemplo: `["linux"]` |

### Acciones de formulario (`__actions__`)

Cada acción en `__actions__` genera un botón en el formulario del ítem:

| Propiedad      | Tipo   | Descripción |
|----------------|--------|-------------|
| `id`           | str    | Identificador de la acción. Debe coincidir con una clave en `action_labels` del archivo de idioma |
| `url`          | str    | Endpoint al que se hace POST con el contenido actual del ítem |
| `extra`        | dict   | Campos extra añadidos al payload (p. ej. `{"_test_mode": "ssh"}`) |
| `icon`         | str    | Clase Bootstrap Icons (p. ej. `"bi-plug"`) |
| `variant`      | str    | Variante Bootstrap del botón (p. ej. `"outline-info"`, `"outline-secondary"`) |
| `full_width`   | bool   | Si `true`, el botón ocupa el 100 % del ancho disponible |
| `show_when`    | dict   | Igual que en campos: oculta el botón según el valor de otro campo |
| `group`        | str    | Si se especifica, el botón se inyecta dentro del bloque visual del grupo indicado (debajo del último campo de ese grupo) en lugar de al pie del formulario |
| `result`       | str    | Cómo mostrar la respuesta: `"toast"` (notificación emergente) o `"field_picker"` (modal de selección) |
| `result_field` | str    | Solo para `result: "field_picker"`: nombre del campo del ítem que se rellenará con el valor elegido |

### Acción inline en campo (`input_action`)

Un campo `str` puede tener un botón de icono acoplado como input-group Bootstrap:

```json
"db": {
    "type": "str",
    "default": "",
    "group": "server",
    "input_action": {
        "id":           "list_databases",
        "url":          "/api/watchfuls/datastore/databases",
        "extra":        {},
        "icon":         "bi-database",
        "result":       "field_picker",
        "result_field": "db"
    }
}
```

El botón hace POST al endpoint indicado, recibe `{"ok": true, "databases": [...]}` y abre el modal `#fieldPickerModal` con la lista. Al seleccionar un valor se escribe directamente en el campo `db` del ítem.

### Archivos de idioma (`lang/*.json`)

Además de `pretty_name` y `labels`, los archivos de idioma pueden incluir:

```json
{
    "pretty_name": "Mi Módulo",
    "labels": {
        "enabled": "Habilitado",
        "mode":    "Modo",
        "host":    "Host"
    },
    "hints": {
        "mode": "Cómo conectar al servidor: TCP directo o túnel SSH.",
        "host": "Dirección IP o hostname del servidor."
    },
    "options": {},
    "option_labels": {
        "mode": {
            "tcp": "TCP directo",
            "ssh": "Túnel SSH"
        }
    },
    "group_labels": {
        "connection": "Conexión",
        "server":     "Servidor"
    },
    "action_labels": {
        "test_conn":  "Probar conexión",
        "list_dbs":   "Listar bases de datos"
    },
    "collections": {"list": "Servidores"}
}
```

| Sección | Descripción |
|---------|-------------|
| `labels` | Etiqueta visible de cada campo |
| `hints` | Texto de ayuda que aparece bajo el campo en la UI |
| `option_labels` | Etiquetas de las opciones de campos con `options` (desplegables) |
| `group_labels` | Nombre visible de cada grupo visual |
| `action_labels` | Etiqueta del botón de cada acción (`__actions__` e `input_action`) |
| `collections` | Nombre del grupo de colección (p. ej. `"list": "Servidores"`) |
| `rename_item_prompt` | Texto personalizado para el modal de renombrar ítem (reemplaza el texto genérico). Ejemplo: `"Introduce el nuevo nombre de host:"` |
| `new_item_key_label` | Etiqueta personalizada para el campo de clave en el modal de nuevo ítem. Ejemplo: `"Nombre de host o identificador:"` |

---

## 4b. Classmethods de integración con la UI

La UI web puede invocar métodos de clase del módulo a través de endpoints REST. Para habilitarlos, implementa los siguientes classmethods en tu clase `Watchful`:

### `test_connection(config: dict) -> dict`

Invocado por `POST /api/watchfuls/<modulo>/test`. Recibe los datos del formulario del ítem y devuelve `{"ok": bool, "message": str}`.

```python
@classmethod
def test_connection(cls, config: dict) -> dict:
    try:
        # ... lógica de prueba ...
        return {"ok": True, "message": "Conexión correcta"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
```

El resultado se muestra como un toast en la UI. La acción queda registrada en el **log de auditoría** bajo el evento `watchful_test`.

### `list_databases(config: dict) -> dict`

Invocado por `POST /api/watchfuls/<modulo>/databases`. Devuelve `{"ok": bool, "databases": list[str]}`.

```python
@classmethod
def list_databases(cls, config: dict) -> dict:
    try:
        dbs = [...]  # lista de nombres
        return {"ok": True, "databases": dbs}
    except Exception as exc:
        return {"ok": False, "databases": [], "message": str(exc)}
```

La acción queda registrada en el **log de auditoría** bajo el evento `watchful_list_databases`.

### `discover() -> list[dict]`

Invocado por `GET /api/watchfuls/<modulo>/discover`. Devuelve una lista de ítems descubiertos automáticamente (servicios, particiones, sensores…). La UI los muestra en el modal de descubrimiento para incorporarlos con un clic.

```python
@classmethod
def discover(cls) -> list[dict]:
    return [
        {"key": "item1", "label": "Nombre visible", ...},
    ]
```

---

## 5. Referencia de la API de ModuleBase

### Configuración

| Método | Propósito | Ejemplo |
|--------|-----------|---------|
| `get_conf(key, default)` | Leer configuración a nivel de módulo | `self.get_conf('timeout', 10)` |
| `get_conf_in_list(field, item_key, default)` | Leer un campo de un ítem | `self.get_conf_in_list('port', 'mibd', 3306)` |
| `_parse_int(value, default)` | Parsear a entero | `self._parse_int('5', 0)` |
| `_parse_float(value, default)` | Parsear a flotante | `self._parse_float('3.14', 0.0)` |

### Resultados

| Método | Descripción |
|--------|-------------|
| `self.dict_return.set(key, status, message, send_msg, other_data)` | Almacena un resultado de comprobación |

Parámetros de `dict_return.set()`:

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `key` | str | Nombre/ID del ítem (clave del dict) |
| `status` | bool | `True` = OK, `False` = Error |
| `message` | str | Mensaje de Telegram (soporta `*negrita*`) |
| `send_msg` | bool | `False` = no enviar automáticamente |
| `other_data` | dict | Datos extra visibles en la API de estado |

### Estado y notificaciones

| Método | Descripción |
|--------|-------------|
| `self.check_status(status, module_name, key)` | Devuelve `True` si el estado **cambió** |
| `self.check_status_custom(status, key, message)` | Como `check_status` pero también detecta cambios de mensaje |
| `self.send_message(message, status)` | Envía mensaje a Telegram |

### Herramientas del sistema

| Método | Descripción |
|--------|-------------|
| `self.paths.set(name, path)` | Registra una ruta de herramienta |
| `self.paths.find(name, default='')` | Obtiene una ruta registrada |
| `self._run_cmd(cmd, return_str_err=False, return_exit_code=False)` | Ejecuta un comando del sistema. Devuelve `stdout`, `(stdout, stderr)`, `(stdout, exit_code)` o `(stdout, stderr, exit_code)` según las flags |

### Debug

```python
self._debug("Mi mensaje", DebugLevel.info)
self._debug("Error crítico", DebugLevel.error)
self._debug("Datos extra", DebugLevel.debug)
```

---

## 6. Configuración en modules.json

El `Monitor` lee `modules.json` para decidir qué módulos están habilitados y
con qué configuración. La estructura para tu módulo:

```json
{
    "mi_modulo": {
        "enabled": true,
        "threads": 5,
        "timeout": 10,
        "list": {
            "Servidor Principal": {
                "enabled": true,
                "target": "192.168.1.100",
                "timeout": 5
            },
            "Servidor de Backup": {
                "enabled": true,
                "target": "192.168.1.200"
            },
            "192.168.1.50": true
        }
    }
}
```

### Modelo de datos de un ítem

La **clave del diccionario** es el **nombre descriptivo** del ítem (mostrado
como título en la UI y en los mensajes de Telegram).

El **dato operativo** (IP, URL, nombre del servicio…) va en un **campo dentro
del dict del ítem** (p. ej. `target`, `host`, `url`, `service`).

Por **compatibilidad hacia atrás**, si el campo operativo está vacío o ausente,
se usa la clave como valor operativo.

```python
# Formato nuevo (recomendado)
"Mi Router": {"enabled": true, "host": "192.168.1.1", "timeout": 2}

# Formato simple (compat. hacia atrás)
"192.168.1.1": true

# Formato simple con dict (compat. hacia atrás)
"192.168.1.1": {"enabled": true, "timeout": 2}
```

---

## 7. Cómo se descubren los módulos

```text
watchfuls/
  |-- ping/             <- package descubierto -> importlib.import_module('watchfuls.ping')
  |    |-- __init__.py  <- implementación
  |    +-- watchful.py  <- alias
  |-- web/              <- package descubierto
  |-- service_status/   <- package descubierto
  +-- mi_modulo/        <- ¡descubierto automáticamente!
       +-- __init__.py
```

El `Monitor`:
1. Escanea `watchfuls/` en busca de subdirectorios con `__init__.py` (packages)
2. También descubre módulos legacy `watchfuls/*.py` de archivo único
3. Comprueba `modules.json[mi_modulo].enabled` (por defecto: `True`)
4. Usa `importlib.import_module('watchfuls.mi_modulo')`
5. Instancia `Watchful(monitor)`
6. Llama a `check()`

---

## 8. Personalización en la UI web

### Icono y descripción del módulo

Se definen en `info.json` en la raíz del package del módulo:

```json
{
    "name": "mi_modulo",
    "version": "1.0.0",
    "description": "Descripción breve de lo que hace el módulo.",
    "icon": "🔍"
}
```

### Etiquetas de campos e i18n

Crea archivos `lang/en_EN.json` y `lang/es_ES.json` con el nombre visible
del módulo y las etiquetas de cada campo:

```json
{
    "pretty_name": "Mi Módulo",
    "labels": {
        "enabled": "Habilitado",
        "target":  "Dirección destino",
        "timeout": "Tiempo máximo (s)"
    }
}
```

El sistema multilanguage es automático: `ModuleBase.discover_schemas()` fusiona
estos archivos con `schema.json` e `info.json` al arrancar, y la UI los usa
sin ninguna configuración adicional.

> **Documentación completa del sistema i18n** → [i18n.md](i18n.md)
> (arquitectura de dos niveles, pipeline de `discover_schemas`, resolución de
> etiquetas en el navegador, constantes JS, cómo añadir un idioma nuevo)

---

## 9. Tests

### Estructura básica de tests

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls.mi_modulo."""

from unittest.mock import patch
import pytest
from conftest import create_mock_monitor


class TestMiModuloInit:

    def test_init(self):
        from watchfuls.mi_modulo import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.mi_modulo': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.mi_modulo'


class TestMiModuloCheck:

    def setup_method(self):
        from watchfuls.mi_modulo import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        """Sin ítems configurados no hay resultados."""
        config = {'watchfuls.mi_modulo': {'list': {}}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_item(self):
        """Un ítem deshabilitado no se procesa."""
        config = {
            'watchfuls.mi_modulo': {
                'list': {'test': False}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_item_ok(self):
        """Ítem que supera la comprobación → status True."""
        config = {
            'watchfuls.mi_modulo': {
                'list': {'Mi Servidor': {'enabled': True, 'target': '1.2.3.4'}}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_do_check', return_value=(True, 'OK')):
            result = w.check()
            items = result.list
            assert 'Mi Servidor' in items
            assert items['Mi Servidor']['status'] is True

    def test_check_item_fail(self):
        """Ítem que falla la comprobación → status False."""
        config = {
            'watchfuls.mi_modulo': {
                'list': {'Mi Servidor': {'enabled': True, 'target': '1.2.3.4'}}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_do_check', return_value=(False, 'timeout')):
            result = w.check()
            items = result.list
            assert items['Mi Servidor']['status'] is False

    def test_backward_compat_key_as_target(self):
        """Sin campo target, se usa la clave como fallback."""
        config = {
            'watchfuls.mi_modulo': {
                'list': {'1.2.3.4': True}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_do_check', return_value=(True, 'OK')):
            result = w.check()
            assert '1.2.3.4' in result.list


class TestMiModuloDefaults:

    def test_defaults_from_schema(self):
        from watchfuls.mi_modulo import Watchful
        for key, meta in Watchful.ITEM_SCHEMA['list'].items():
            assert key in Watchful._DEFAULTS
            assert Watchful._DEFAULTS[key] == meta['default']

    def test_schema_types(self):
        from watchfuls.mi_modulo import Watchful
        for key, meta in Watchful.ITEM_SCHEMA['list'].items():
            assert 'type' in meta
            assert 'default' in meta
```

### Cómo funciona `create_mock_monitor`

Esta función crea un `MagicMock` que simula el `Monitor` real:
- La clave de configuración en el mock es el `name_module` completo:
  `'watchfuls.mi_modulo'` (no `'mi_modulo'`)
- `check_status` devuelve `False` por defecto (no dispara notificaciones)
- `send_message` es un mock silencioso

---

## 10. Ejemplo completo: módulo verificador de puertos TCP

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Módulo de monitorización: tcp_check — comprueba que los puertos TCP están abiertos."""

import concurrent.futures
import json
import os
import socket

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)


class Watchful(ModuleBase):

    ITEM_SCHEMA = _SCHEMA
    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        items = []
        for key, value in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                is_enabled = value
                host = key
            elif isinstance(value, dict):
                is_enabled = value.get('enabled', self._DEFAULTS['enabled'])
                host = (value.get('host', '') or '').strip() or key
            else:
                is_enabled = self._DEFAULTS['enabled']
                host = key

            self._debug(f"TCP: {key} - Habilitado: {is_enabled}", DebugLevel.info)
            if is_enabled:
                items.append((key, host))

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)
        ) as executor:
            futures = {
                executor.submit(self._tcp_check, name, host): (name, host)
                for name, host in items
            }
            for future in concurrent.futures.as_completed(futures):
                name, host = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'TCP: {name} - *Error: {exc}*'
                    self.dict_return.set(name, False, message)

        super().check()
        return self.dict_return

    def _tcp_check(self, name, host):
        port = self.get_conf_in_list('port', name, self._DEFAULTS['port'])
        timeout = self.get_conf_in_list('timeout', name, self._DEFAULTS['timeout'])

        status = self._tcp_connect(host, port, timeout)

        s_message = f'TCP: *{name}* ({host}:{port}) '
        if status:
            s_message += 'OK'
        else:
            s_message += 'FALLO'

        other_data = {'host': host, 'port': port}
        self.dict_return.set(name, status, s_message, False, other_data)

        if self.check_status(status, self.name_module, name):
            self.send_message(s_message, status)

    @staticmethod
    def _tcp_connect(host, port, timeout):
        """Intenta conectar a host:port. Devuelve True si el puerto responde."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False
```

### `schema.json` para este ejemplo

```json
{
    "__module__": {
        "enabled": {"type": "bool", "default": true},
        "threads": {"type": "int",  "default": 5, "min": 1, "max": 100}
    },
    "list": {
        "enabled": {"type": "bool", "default": true},
        "host":    {"type": "str",  "default": ""},
        "port":    {"type": "int",  "default": 80,  "min": 1, "max": 65535},
        "timeout": {"type": "int",  "default": 5,   "min": 1, "max": 60}
    }
}
```

### `lang/es_ES.json` para este ejemplo

```json
{
    "pretty_name": "Verificador TCP",
    "labels": {
        "enabled": "Habilitado",
        "host":    "Host",
        "port":    "Puerto",
        "timeout": "Timeout (s)"
    }
}
```

### Configuración (`modules.json`)

```json
{
    "tcp_check": {
        "enabled": true,
        "list": {
            "Servidor Web": {
                "enabled": true,
                "host": "192.168.1.10",
                "port": 443,
                "timeout": 3
            },
            "Gateway SSH": {
                "enabled": true,
                "host": "10.0.0.1",
                "port": 22
            },
            "192.168.1.1:80": true
        }
    }
}
```

---

## 11. Lista de comprobación para la creación

**Estructura básica (obligatorio)**

- [ ] Crear carpeta `watchfuls/mi_modulo/`
- [ ] Crear `__init__.py` con una clase `Watchful(ModuleBase)`
- [ ] Crear `watchful.py` con `from . import Watchful`
- [ ] Crear `schema.json` con las definiciones de campos `__module__` y `list`
- [ ] Crear `info.json` con `name`, `description` e `icon`
- [ ] Crear `lang/en_EN.json` con `pretty_name` y `labels`
- [ ] Crear `lang/es_ES.json` con `pretty_name` y `labels` traducidos
- [ ] Cargar `_SCHEMA` desde `schema.json` y asignar `ITEM_SCHEMA = _SCHEMA`
- [ ] Definir `_DEFAULTS` a partir de `_SCHEMA['list']` excluyendo claves `__*__`
- [ ] Implementar `__init__` llamando a `super().__init__(monitor, __package__)`
- [ ] Implementar `check()` devolviendo `self.dict_return`
- [ ] Llamar a `super().check()` antes de devolver
- [ ] Usar `dict_return.set()` para almacenar cada resultado
- [ ] Usar `check_status()` + `send_message()` para las notificaciones
- [ ] Añadir una sección en `modules.json` con `enabled: true`
- [ ] Crear `tests/test_mi_modulo.py` con tests unitarios
- [ ] Ejecutar `pytest tests/ watchfuls/ -q` y verificar que todo pasa

**UI avanzada (opcional, según las necesidades del módulo)**

- [ ] Añadir `__field_order__` si el orden de los campos importa
- [ ] Añadir `group` en los campos y `group_labels` en los archivos de idioma para agrupar campos visualmente
- [ ] Añadir `show_when` en campos que solo tienen sentido según el valor de otro campo
- [ ] Añadir `__group_when__` si algún encabezado de grupo debe mostrarse condicionalmente
- [ ] Añadir `options` + `option_labels` para campos con una lista cerrada de valores (desplegable)
- [ ] Añadir `hints` en los archivos de idioma para los campos que necesiten explicación adicional
- [ ] Añadir `__actions__` con botones de test (endpoint `test_connection`) o descubrimiento
- [ ] Implementar classmethod `test_connection(cls, config)` si hay botón de test
- [ ] Implementar classmethod `list_databases(cls, config)` si hay selector de recurso
- [ ] Implementar classmethod `discover(cls)` si hay botón de descubrimiento automático
- [ ] Añadir `input_action` en el campo de selección de recurso si aplica `field_picker`
- [ ] Añadir `action_labels` en los archivos de idioma para cada acción definida
- [ ] Añadir `__discovery__` + `__discovery_field__` si se quiere botón de búsqueda inline en un campo `str`
- [ ] Añadir `__key_mirrors_field__` si la clave del ítem debe sincronizarse con el campo descubierto
- [ ] Añadir `supported_platforms` en campos que solo tienen sentido en determinadas plataformas
- [ ] Añadir `rename_item_prompt` en los archivos de idioma para personalizar el texto del modal de renombrar
- [ ] Añadir `new_item_key_label` en los archivos de idioma para personalizar la etiqueta del campo de clave en el modal de nuevo ítem
