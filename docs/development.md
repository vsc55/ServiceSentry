# Guía de Desarrollo

Cómo configurar un entorno local, ejecutar tests, usar el depurador de VS Code y contribuir a ServiceSentry.

---

## Requisitos

- Python **3.10+** (usa `match/case`)
- Recomendado: Python **3.14** (baseline actual)
- pip + venv

---

## Instalación Local

```bash
git clone https://github.com/vsc55/ServiceSentry.git
cd ServiceSentry/src

# Crear y activar entorno virtual
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
.venv\Scripts\Activate.ps1         # Windows PowerShell

# Instalar dependencias de producción
pip install -r requirements.txt

# Instalar dependencias de desarrollo (pytest, etc.)
pip install -r requirements-dev.txt
```

---

## Ejecución de la Aplicación

```bash
cd src

# Ejecución única
python3 main.py

# Modo daemon, comprobación cada 5 minutos
python3 main.py -d -t 300

# Salida detallada
python3 main.py -v

# Usar directorio de configuración personalizado
python3 main.py -p /ruta/a/config/
```

En modo desarrollo (cuando `src` está en la ruta), los archivos de configuración se leen desde `../data/` relativo a `src/`.

---

## Tests

El proyecto tiene **1400 tests** usando `pytest`, con ejecución paralela automática via `pytest-xdist`.

### Ejecutar todos los tests

```bash
cd src

# Ejecución rápida (paralelo automático, usa todos los cores)
python -m pytest tests/ watchfuls/ -q

# Verbose con traza corta
python -m pytest tests/ watchfuls/ -v --tb=short

# Sin paralelismo (secuencial)
python -m pytest tests/ watchfuls/ -n 0

# Módulo específico
python -m pytest watchfuls/ping/tests/ -v

# Con cobertura
python -m pytest tests/ watchfuls/ --cov=lib --cov=watchfuls --cov-report=term-missing
```

### Organización de tests

Los tests están junto a cada módulo:

```
src/
├── conftest.py                          # Fixtures compartidos: admin, client, _login()
├── tests/                               # Tests de core y web admin
│   ├── conftest.py                      # Fixtures de web_admin (config_dir, var_dir, admin, client)
│   ├── test_wa_init.py
│   ├── test_wa_users.py
│   ├── test_wa_roles.py
│   ├── test_wa_groups.py
│   ├── test_wa_config.py
│   ├── test_wa_modules.py
│   ├── test_wa_sessions.py
│   ├── test_wa_audit.py
│   ├── test_wa_security.py
│   ├── test_wa_telegram.py
│   ├── test_wa_ui.py
│   ├── test_wa_json_helpers.py
│   └── ...
└── watchfuls/
    ├── ping/tests/test_ping.py
    ├── datastore/tests/test_datastore.py
    └── ...
```

### `create_mock_monitor`

Todos los tests de módulos usan el helper compartido del `conftest.py` raíz:

```python
from conftest import create_mock_monitor

mock = create_mock_monitor({
    'watchfuls.mi_modulo': {
        'list': {
            'Mi Item': {'enabled': True, 'host': '1.2.3.4'}
        }
    }
})
```

La clave del mock es el `name_module` completo (ej: `'watchfuls.ping'`), no el nombre corto.
`check_status` devuelve `False` por defecto (sin notificaciones en tests).

### pytest.ini

`src/pytest.ini` viene preconfigurado:

```ini
[pytest]
testpaths = tests watchfuls
addopts = -ra -v --tb=short -n auto
```

La opción `-n auto` usa `pytest-xdist` para distribuir los tests entre todos los cores disponibles automáticamente. El tiempo de ejecución pasa de ~4 min (secuencial) a ~2 min (paralelo en 8 cores).

> **Nota:** `-s` (no capture stdout) es incompatible con `-n auto`. Si necesitas ver `print()` durante el desarrollo, pasa `-n 0` para ejecutar en serie.

---

## Depurador de VS Code

El repositorio incluye una configuración de depuración preconfigurada en `src/.vscode/launch.json`.

### Configuración de pytest

Nombre: **🩺 Python: pytest (usa pytest.ini)**

Usa `pytest.exe` directamente en lugar de `-m pytest` para evitar problemas de arranque con `debugpy`:

```json
{
    "name": "🩺 Python: pytest (usa pytest.ini)",
    "type": "debugpy",
    "request": "launch",
    "program": "${workspaceFolder}/.venv/Scripts/pytest.exe",
    "args": [
        "-c", "${workspaceFolder}/pytest.ini",
        "tests",
        "watchfuls"
    ],
    "console": "integratedTerminal",
    "cwd": "${workspaceFolder}"
}
```

> **Nota:** Usar `module: "pytest"` con debugpy puede causar `collected 0 items` / KeyboardInterrupt en algunos entornos. El enfoque `program` con `pytest.exe` es más fiable.

---

## Convenciones del Proyecto

Consulta [architecture.md](architecture.md#convenciones-de-código) para la lista completa. Resumen:

- Prefijo `_` para métodos y atributos privados.
- Type hints en todas las firmas.
- Docstrings en todas las clases y métodos públicos.
- `IntEnum` / `StrEnum` para enumeraciones.
- `match/case` para lógica de despacho (Python 3.10+).
- `encoding='utf-8'` explícito en todo I/O de archivos.

---

## Añadir un Nuevo Módulo

Consulta [watchful_guide.md](watchful_guide.md) para la guía completa paso a paso.

Resumen rápido:

1. Crear `watchfuls/mi_modulo/` con `__init__.py`, `watchful.py`, `schema.json`, `info.json` y `lang/`
2. Definir `class Watchful(ModuleBase)` en `__init__.py`
3. Cargar `_SCHEMA = json.load(...)` desde `schema.json`
4. Llamar a `super().__init__(monitor, __package__)`
5. Implementar `check()` devolviendo `self.dict_return`
6. Añadir `mi_modulo: {enabled: true}` en `modules.json`
7. Escribir tests en `watchfuls/mi_modulo/tests/`
8. Ejecutar `pytest tests/ watchfuls/ -q` para verificar

---

## Dependencias

### Dependencias del core

Siempre necesarias, independientemente de qué módulos estén activos:

| Paquete | Versión | Propósito |
| ------- | ------- | --------- |
| `Flask` | >=3.0 | Interfaz web de administración |
| `werkzeug` | >=3.0 | Hashing de contraseñas, utilidades de request |
| `cryptography` | >=41.0 | Cifrado Fernet de valores sensibles en disco (`lib/secret_manager.py`) |
| `requests` | >=2.28 | Llamadas HTTP a la API de Telegram (`lib/telegram.py`) |
| `psutil` | >=5.9 | Información del sistema: RAM, disco, temperatura, servicios Windows |

### Dependencias por módulo

Solo se necesitan si el módulo correspondiente está activo en `modules.json`:

| Paquete | Versión | Módulo | Propósito |
| ------- | ------- | ------ | --------- |
| `paramiko` | >=3.0 | `raid`, `datastore` (SSH) | Ejecución remota de comandos y túneles SSH |
| `pythonping` | >=1.1.4 | `ping` | Ping ICMP multiplataforma sin root en Windows |
| `PyMySQL` | >=1.0 | `datastore` | Conectividad MySQL / MariaDB |
| `psycopg2-binary` | >=2.9 | `datastore` | Conectividad PostgreSQL |
| `pymssql` | >=2.2 | `datastore` | Conectividad Microsoft SQL Server |
| `pymongo` | >=4.0 | `datastore` | Conectividad MongoDB |
| `redis` | >=5.0 | `datastore` | Conectividad Redis / Valkey |
| `pymemcache` | >=4.0 | `datastore` | Conectividad Memcached |

> En `datastore`, los conectores de BD son opcionales entre sí: solo hace falta instalar el paquete del motor que uses. Elasticsearch/OpenSearch e InfluxDB no requieren paquete extra (usan `urllib` de stdlib).

```bash
pip install -r requirements.txt
```

### Dependencias del Sistema

| Herramienta | Módulo | Notas |
| ----------- | ------ | ----- |
| `systemctl` | `service_status` | Solo Linux con systemd |
| `rc-service` | `service_status` | Solo Linux con OpenRC |
| `service` | `service_status` | Fallback SysV init en Linux |
| demonio `hddtemp` | `hddtemp` | Demonio externo escuchando en TCP 7634 |
