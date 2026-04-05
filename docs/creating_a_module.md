# Creating a new monitoring module (Watchful)

Step-by-step guide to creating a monitoring module from scratch in ServiceSentry.

---

## 1. General architecture

```text
main.py -> Monitor
              |-- Discovers modules in watchfuls/*.py
              |-- Reads modules.json to check if enabled
              |-- Instantiates Watchful(monitor) for each module
              +-- Runs module.check() in parallel
                       |
                       v
              Watchful(ModuleBase)
                  |-- Reads its configuration from modules.json
                  |-- Executes the monitoring logic
                  |-- Stores results in dict_return
                  |-- Detects state changes (check_status)
                  +-- Sends notifications via Telegram (send_message)
```

### Class hierarchy

```text
ObjectBase          <- shared debug instance
  +-- ModuleBase    <- configuration, paths, dict_return, messaging
        +-- Watchful  <- your concrete module
```

---

## 2. File structure

For a module called `my_module`, you need to create:

```text
watchfuls/
  +-- my_module.py       <- Module code (required)

tests/
  +-- test_my_module.py  <- Unit tests (recommended)
```

There is no need to register the module anywhere. The `Monitor` automatically
discovers every `*.py` in `watchfuls/` (except `__*.py`).

---

## 3. Minimal module template

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitoring module: my_module."""

import concurrent.futures

from lib.debug import DebugLevel
from lib.modules import ModuleBase


class Watchful(ModuleBase):
    """Monitors <description of what it does>."""

    # -- Schema ----------------------------------------------------------
    # Defines the fields for each item in the 'list' collection.
    # This is used for:
    #   - Default values when creating items in the web UI
    #   - Type and range validation in the web UI
    #   - Documenting available fields

    ITEM_SCHEMA = {
        'list': {
            'enabled':  {'default': True,  'type': 'bool'},
            'target':   {'default': '',    'type': 'str'},
            'timeout':  {'default': 10,    'type': 'int', 'min': 1, 'max': 300},
            # Add more fields as needed...
        },
    }

    # Shortcut for quick access to default values
    _DEFAULTS = {k: v['default'] for k, v in ITEM_SCHEMA['list'].items()}

    # Module constants (optional)
    _MY_DEFAULT_VALUE = 42

    def __init__(self, monitor):
        super().__init__(monitor, __name__)
        # __name__ will be 'watchfuls.my_module' -> used as name_module

        # Register system tools if needed
        # self.paths.set('mytool', '/usr/bin/mytool')

        # Internal state (not persisted between monitoring cycles)
        # self._fail_count: dict[str, int] = {}

    def check(self):
        """Main entry point. Executes the monitoring logic."""

        # 1. Read the configured item list
        items = self._get_items()

        # 2. Run checks in parallel
        self._run_checks(items)

        # 3. REQUIRED: call super().check() (runs debug log)
        super().check()

        # 4. REQUIRED: return dict_return
        return self.dict_return

    # -- Private methods -------------------------------------------------

    def _get_items(self):
        """Parse configuration and return enabled items."""
        result = []
        for key, value in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                is_enabled = value
                target = key  # backward compat: key is the operational data
            elif isinstance(value, dict):
                is_enabled = value.get('enabled', self._DEFAULTS['enabled'])
                # The 'target' field holds the real data; if empty,
                # the key is used as fallback (backward compatibility)
                target = (value.get('target', '') or '').strip() or key
            else:
                is_enabled = self._DEFAULTS['enabled']
                target = key

            self._debug(f"Item: {key} - Enabled: {is_enabled}", DebugLevel.info)
            if is_enabled:
                result.append((key, target))

        return result

    def _run_checks(self, items):
        """Run checks in parallel using ThreadPoolExecutor."""
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
                    message = f'MyModule: {name} - *Error: {exc}* '
                    self.dict_return.set(name, False, message)

    def _item_check(self, name, target):
        """Execute the individual check for one item."""
        timeout = self.get_conf_in_list('timeout', name, self._DEFAULTS['timeout'])

        # === Your monitoring logic goes here ===
        status, detail = self._do_check(target, timeout)

        # Build message
        s_message = f'MyModule: *{name}* '
        if status:
            s_message += 'OK'
        else:
            s_message += f'FAIL {detail}'

        # Store result
        other_data = {'detail': detail}
        self.dict_return.set(name, status, s_message, False, other_data)

        # Notify if state changed
        if self.check_status(status, self.name_module, name):
            self.send_message(s_message, status)

    def _do_check(self, target, timeout):
        """Perform the actual verification. Returns (status: bool, detail: str)."""
        # Implement your specific logic here
        # Examples:
        #   - Make an HTTP request
        #   - Run a command: stdout, stderr = self._run_cmd(cmd)
        #   - Connect to a socket
        #   - Read a file
        raise NotImplementedError("Implement _do_check")
```

---

## 4. ITEM_SCHEMA fields

Each field is defined as a dict with these properties:

| Property   | Type     | Required | Description |
|------------|----------|----------|-------------|
| `default`  | any      | Yes | Default value |
| `type`     | str      | Yes | Type: `'bool'`, `'int'`, `'float'`, `'str'`, `'list'` |
| `min`      | number   | No  | Minimum value (for `int`/`float`) |
| `max`      | number   | No  | Maximum value (for `int`/`float`) |
| `sensitive`| bool     | No  | If `True`, displayed as a password field in the UI |

### Full example

```python
ITEM_SCHEMA = {
    'list': {
        'enabled':    {'default': True,   'type': 'bool'},
        'host':       {'default': '',     'type': 'str'},
        'port':       {'default': 3306,   'type': 'int', 'min': 1, 'max': 65535},
        'password':   {'default': '',     'type': 'str', 'sensitive': True},
        'threshold':  {'default': 80.0,   'type': 'float', 'min': 0.0, 'max': 100.0},
        'alert':      {'default': 1,      'type': 'int', 'min': 1, 'max': 100},
        'exclude':    {'default': [],     'type': 'list'},
    },
}
```

---

## 5. ModuleBase API reference

### Configuration

| Method | Purpose | Example |
|--------|---------|---------|
| `get_conf(key, default)` | Read module-level config | `self.get_conf('timeout', 10)` |
| `get_conf_in_list(field, item_key, default)` | Read a field from an item | `self.get_conf_in_list('port', 'mydb', 3306)` |
| `_parse_int(value, default)` | Parse to int | `self._parse_int('5', 0)` |
| `_parse_float(value, default)` | Parse to float | `self._parse_float('3.14', 0.0)` |

### Results

| Method | Description |
|--------|-------------|
| `self.dict_return.set(key, status, message, send_msg, other_data)` | Store a check result |

Parameters of `dict_return.set()`:

| Parameter | Type | Description |
|-----------|------|-------------|
| `key` | str | Item name/ID (the dict key) |
| `status` | bool | `True` = OK, `False` = Error |
| `message` | str | Telegram message (supports `*bold*`) |
| `send_msg` | bool | `False` = do not send automatically |
| `other_data` | dict | Extra data visible in the status API |

### State and notifications

| Method | Description |
|--------|-------------|
| `self.check_status(status, module_name, key)` | Returns `True` if the state **changed** |
| `self.check_status_custom(status, key, message)` | Like `check_status` but also detects message changes |
| `self.send_message(message, status)` | Send message to Telegram |

### System tools

| Method | Description |
|--------|-------------|
| `self.paths.set(name, path)` | Register a tool path |
| `self.paths.find(name, default='')` | Get a registered path |
| `self._run_cmd(cmd, ignore_error=False)` | Run a system command -> `(stdout, stderr)` |

### Debug

```python
self._debug("My message", DebugLevel.info)
self._debug("Critical error", DebugLevel.error)
self._debug("Extra data", DebugLevel.debug)
```

---

## 6. Configuration in modules.json

The `Monitor` reads `modules.json` to decide which modules are enabled and
with what configuration. The structure for your module:

```json
{
    "my_module": {
        "enabled": true,
        "threads": 5,
        "timeout": 10,
        "list": {
            "Main Server": {
                "enabled": true,
                "target": "192.168.1.100",
                "timeout": 5
            },
            "Backup Server": {
                "enabled": true,
                "target": "192.168.1.200"
            },
            "192.168.1.50": true
        }
    }
}
```

### Item data model

The **dictionary key** is the **descriptive name** of the item (shown as
the title in the UI and in Telegram messages).

The **operational data** (IP, URL, service name...) goes in a **field inside
the item dict** (e.g. `target`, `host`, `url`, `service`).

For **backward compatibility**, if the operational field is empty or missing,
the key is used as the operational value.

```python
# New format (recommended)
"My Router": {"enabled": true, "host": "192.168.1.1", "timeout": 2}

# Simple format (backward compat)
"192.168.1.1": true

# Simple format with dict (backward compat)
"192.168.1.1": {"enabled": true, "timeout": 2}
```

---

## 7. How modules are discovered

```text
watchfuls/
  |-- __init__.py       <- ignored (starts with __)
  |-- ping.py           <- discovered -> importlib.import_module('watchfuls.ping')
  |-- web.py            <- discovered
  |-- service_status.py <- discovered
  +-- my_module.py      <- automatically discovered!
```

The `Monitor`:
1. Scans `watchfuls/*.py` using `glob`
2. Ignores `__*.py`
3. Checks `modules.json[my_module].enabled` (default: `True`)
4. Uses `importlib.import_module('watchfuls.my_module')`
5. Instantiates `Watchful(monitor)`
6. Calls `check()`

---

## 8. Web UI customization

### Icons and names

In `lib/web_admin/templates/partials/_js_core.html` the icons are defined:

```javascript
const ICONS = {
    // ... existing modules ...
    my_module: 'magnifier-emoji',  // <- add your icon here
};
```

### Field labels

In `lib/web_admin/lang/en_EN.py` and `es_ES.py`, inside `'labels'`:

```python
'labels': {
    # ... existing fields ...
    'target': 'Target address',
    'my_field': 'My custom field',
},
```

### Readable module name

In `lib/web_admin/lang/en_EN.py` and `es_ES.py`, inside `'pretty_names'`:

```python
'pretty_names': {
    # ... existing modules ...
    'my_module': 'My Module',
},
```

---

## 9. Tests

### Basic test structure

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/my_module.py."""

from unittest.mock import patch
import pytest
from tests.conftest import create_mock_monitor


class TestMyModuleInit:

    def test_init(self):
        from watchfuls.my_module import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.my_module': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.my_module'


class TestMyModuleCheck:

    def setup_method(self):
        from watchfuls.my_module import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        """No configured items means no results."""
        config = {'watchfuls.my_module': {'list': {}}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_item(self):
        """Disabled item is not processed."""
        config = {
            'watchfuls.my_module': {
                'list': {'test': False}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_item_ok(self):
        """Item that passes the check -> status True."""
        config = {
            'watchfuls.my_module': {
                'list': {'My Server': {'enabled': True, 'target': '1.2.3.4'}}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Mock the actual check method
        with patch.object(w, '_do_check', return_value=(True, 'OK')):
            result = w.check()
            items = result.list
            assert 'My Server' in items
            assert items['My Server']['status'] is True

    def test_check_item_fail(self):
        """Item that fails the check -> status False."""
        config = {
            'watchfuls.my_module': {
                'list': {'My Server': {'enabled': True, 'target': '1.2.3.4'}}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_do_check', return_value=(False, 'timeout')):
            result = w.check()
            items = result.list
            assert items['My Server']['status'] is False

    def test_backward_compat_key_as_target(self):
        """Without a target field, the key is used as fallback."""
        config = {
            'watchfuls.my_module': {
                'list': {'1.2.3.4': True}
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_do_check', return_value=(True, 'OK')):
            result = w.check()
            assert '1.2.3.4' in result.list


class TestMyModuleDefaults:

    def test_defaults_from_schema(self):
        from watchfuls.my_module import Watchful
        for key, meta in Watchful.ITEM_SCHEMA['list'].items():
            assert key in Watchful._DEFAULTS
            assert Watchful._DEFAULTS[key] == meta['default']

    def test_schema_types(self):
        from watchfuls.my_module import Watchful
        for key, meta in Watchful.ITEM_SCHEMA['list'].items():
            assert 'type' in meta
            assert 'default' in meta
```

### How `create_mock_monitor` works

This function creates a `MagicMock` that simulates the real `Monitor`:
- The config key in the mock is the full `name_module`:
  `'watchfuls.my_module'` (not `'my_module'`)
- `check_status` returns `False` by default (does not trigger notifications)
- `send_message` is a silent mock

---

## 10. Full example: TCP port checker module

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitoring module: tcp_check -- checks that TCP ports are open."""

import concurrent.futures
import socket

from lib.debug import DebugLevel
from lib.modules import ModuleBase


class Watchful(ModuleBase):

    ITEM_SCHEMA = {
        'list': {
            'enabled': {'default': True, 'type': 'bool'},
            'host':    {'default': '', 'type': 'str'},
            'port':    {'default': 80, 'type': 'int', 'min': 1, 'max': 65535},
            'timeout': {'default': 5, 'type': 'int', 'min': 1, 'max': 60},
        },
    }

    _DEFAULTS = {k: v['default'] for k, v in ITEM_SCHEMA['list'].items()}

    def __init__(self, monitor):
        super().__init__(monitor, __name__)

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

            self._debug(f"TCP: {key} - Enabled: {is_enabled}", DebugLevel.info)
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
            s_message += 'FAIL'

        other_data = {'host': host, 'port': port}
        self.dict_return.set(name, status, s_message, False, other_data)

        if self.check_status(status, self.name_module, name):
            self.send_message(s_message, status)

    @staticmethod
    def _tcp_connect(host, port, timeout):
        """Try to connect to host:port. Returns True if the port responds."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False
```

### Configuration for this example (`modules.json`)

```json
{
    "tcp_check": {
        "enabled": true,
        "list": {
            "Web Server": {
                "enabled": true,
                "host": "192.168.1.10",
                "port": 443,
                "timeout": 3
            },
            "SSH Gateway": {
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

## 11. Creation checklist

- [ ] Create `watchfuls/my_module.py` with a `Watchful(ModuleBase)` class
- [ ] Define `ITEM_SCHEMA` with all item fields
- [ ] Define `_DEFAULTS` derived from the schema
- [ ] Implement `__init__` calling `super().__init__(monitor, __name__)`
- [ ] Implement `check()` returning `self.dict_return`
- [ ] Call `super().check()` before returning
- [ ] Use `dict_return.set()` to store each result
- [ ] Use `check_status()` + `send_message()` for notifications
- [ ] Add a section in `modules.json` with `enabled: true`
- [ ] Add an icon in `_js_core.html` -> `ICONS`
- [ ] Add a readable name in lang -> `pretty_names`
- [ ] Add field labels in lang -> `labels`
- [ ] Create `tests/test_my_module.py` with unit tests
- [ ] Run `pytest tests/ -q` and verify everything passes
