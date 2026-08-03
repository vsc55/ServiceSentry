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
source .venv/bin/activate          # Linux
.venv\Scripts\Activate.ps1         # Windows PowerShell

# Instalar dependencias de producción
pip install -r requirements.txt

# Instalar dependencias de desarrollo (pytest, etc.)
pip install -r requirements-dev.txt
```

---

## Ejecución de la Aplicación

Ejemplos rápidos para desarrollo (el catálogo completo de flags, env `SS_*` y ejemplos está en
[ref-configuracion.md](ref-configuracion.md#opciones-de-línea-de-comandos)):

```bash
cd src
python3 main.py --web              # Panel web (modo por defecto)
python3 main.py --monitor -t 0     # Una sola pasada de monitorización
python3 main.py --monitor -t 300   # Monitor continuo, cada 5 minutos
```

En modo desarrollo (cuando `src` está en la ruta), los archivos de configuración se leen desde `../data/` relativo a `src/`.

---

## Tests

El proyecto tiene **casi 5000 tests** usando `pytest`, con ejecución paralela automática via `pytest-xdist`.

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

### Familias de tests opt-in (se saltan solas por defecto)

Tres grupos necesitan algo extra y, si no lo tienen, **se saltan sin fallar** — así el build sigue verde en cualquier máquina. Para que corran de verdad:

```bash
# 1) Tests de navegador (ejecutan el JavaScript del panel en Chromium).
#    El paquete lo instala requirements-dev.txt; el NAVEGADOR es un binario aparte:
python -m playwright install chromium
python -m pytest tests/e2e/test_ui_playwright.py -n0

# 2) Tests contra motores reales (portabilidad + auditoría de seguridad).
#    Necesitan MySQL / MariaDB / PostgreSQL y correr en SERIE (-n0):
#    define SS_TEST_{MYSQL,MARIADB,PG}_* (lo cómodo: src/tests/.env.test, gitignored).
python -m pytest tests/e2e/test_db_portability_live.py tests/e2e/test_security_live.py -n0
```

Ver [ref-tests.md](ref-tests.md) §81 (portabilidad), §142 (navegador) y §143 (seguridad en vivo).

### Organización de tests

Los tests están junto a cada módulo:

```
src/
├── conftest.py                          # Fixtures compartidos: admin, client, _login()
├── tests/                               # Tests de core y web admin (~160 ficheros)
│   ├── conftest.py                      # Fixtures compartidas (config_dir, var_dir, admin, client); se hereda en las subcarpetas
│   ├── unit/                            # Aislado (sin app/BD/HTTP): core, hosts, stores, syslog parser, monitor, secretos…
│   ├── integration/                     # Flask vía test_client/_login: test_wa_*.py (users, roles, config, security, hosts, sso…)
│   ├── e2e/                             # Recursos vivos: test_ui_playwright, test_db_portability_live, test_security_live
│   ├── meta/                            # Estructura del repo: test_docs_*, changelog/versión, *_views, partials_convention
│   └── # (ver docs/ref-tests.md → «Organización de directorios» para el criterio e inventario completo)
└── watchfuls/
    ├── ping/tests/test_ping.py
    ├── datastore/tests/test_datastore.py
    └── ...                              # un test_<modulo>.py por watchful
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

Consulta [explica-arquitectura.md](explica-arquitectura.md#convenciones-de-código) para la lista completa. Resumen:

- Prefijo `_` para métodos y atributos privados.
- Type hints en todas las firmas.
- Docstrings en todas las clases y métodos públicos.
- `IntEnum` / `StrEnum` para enumeraciones.
- `match/case` para lógica de despacho (Python 3.10+).
- `encoding='utf-8'` explícito en todo I/O de archivos.

---

## Añadir un Nuevo Módulo

Consulta [caso-guia-watchful.md](caso-guia-watchful.md) para la guía completa paso a paso.

Resumen rápido:

1. Crear `watchfuls/mi_modulo/` con `__init__.py`, `schema.json`, `info.json` y `lang/`
2. Definir `class Watchful(ModuleBase)` en `__init__.py`
3. Cargar `_SCHEMA = json.load(...)` desde `schema.json`
4. Llamar a `super().__init__(monitor, __package__)`
5. Implementar `check()` devolviendo `self.dict_return`
6. Habilitar el módulo en su configuración (UI / `config_modules`) con `enabled: true`
7. Escribir tests en `watchfuls/mi_modulo/tests/`
8. Ejecutar `pytest tests/ watchfuls/ -q` para verificar

---

## Dependencias

### Dependencias del core

Siempre necesarias, independientemente de qué módulos estén activos:

| Paquete | Versión | Propósito |
| ------- | ------- | --------- |
| `Flask` | >=3.0 | Interfaz web de administración |
| `werkzeug` | >=3.0 | Hashing de contraseñas (scrypt), utilidades de request, `DebuggedApplication` |
| `jinja2` | >=3.0 | Plantillas (uso directo de `ChoiceLoader`/`FileSystemLoader` en `app.py`) |
| `cryptography` | >=41.0 | Cifrado Fernet de valores sensibles en disco (`lib/security/secret_manager.py`) |
| `requests` | >=2.28 | Llamadas HTTP a la API de Telegram (`lib/providers/telegram.py`) y a Microsoft Graph (`lib/providers/entraid/`) |
| `psutil` | >=5.9 | Información del sistema: RAM, disco, temperatura, servicios Windows |

> **Nota:** Microsoft 365 / Entra ID **no** usa `msal`; habla con Graph directamente vía
> `requests` + `PyJWT`. Casi todas las dependencias no-core se importan de forma **lazy /
> condicional** (drivers de BD, SSO, SNMP, DNS, ping), de modo que su ausencia solo desactiva
> la funcionalidad correspondiente.

### Dependencias por módulo

Solo se necesitan si el módulo correspondiente está activo en su configuración:

| Paquete | Versión | Módulo | Propósito |
| ------- | ------- | ------ | --------- |
| `paramiko` | >=3.0 | `raid`, `datastore` (SSH) | Ejecución remota de comandos y túneles SSH |
| `pythonping` | >=1.1.4 | `ping` | Ping ICMP multiplataforma sin root en Windows (fallback a socket raw si falta) |
| `dnspython` | >=2.3 | `dns` | Resolución DNS avanzada (fallback a A/AAAA vía socket de stdlib si falta) |
| `pysnmp` | >=6.0 | `snmp` | Consultas SNMP v1/v2c/v3 |
| `pysmi` | >=1.1 | `snmp` | Compilación de MIBs |
| `PyMySQL` | >=1.0 | `datastore` | Conectividad MySQL / MariaDB |
| `psycopg2-binary` | >=2.9 | `datastore` | Conectividad PostgreSQL |
| `pymssql` | >=2.2 | `datastore` | Conectividad Microsoft SQL Server |
| `pymongo` | >=4.0 | `datastore` | Conectividad MongoDB |
| `redis` | >=5.0 | `datastore` | Conectividad Redis / Valkey |
| `pymemcache` | >=4.0 | `datastore` | Conectividad Memcached |

> En `datastore`, los conectores de BD son opcionales entre sí: solo hace falta instalar el paquete del motor que uses. Elasticsearch/OpenSearch e InfluxDB no requieren paquete extra (usan `urllib` de stdlib).

### Dependencias opcionales del panel web

Solo se necesitan si activas la funcionalidad correspondiente:

| Paquete | Funcionalidad | Propósito |
| ------- | ------------- | --------- |
| `ldap3` | `config.json → ldap` | Autenticación LDAP / Active Directory |
| `authlib` | `config.json → oidc` | SSO OIDC / OAuth2 (Entra ID, Google, Keycloak…) |
| `python3-saml` | `config.json → saml2` | SSO SAML2 (ADFS, Okta…) **[alpha]** |
| `PyJWT[crypto]` | Teams SSO / bot | Validación de tokens JWT de Teams SSO y del Bot Framework |
| `psycopg2-binary` | `config.json → database` (driver `postgresql`) | Persistencia del core en PostgreSQL |
| `PyMySQL` | `config.json → database` (driver `mysql`/`mariadb`) | Persistencia del core en MySQL/MariaDB |

> La **capa de persistencia del core** (usuarios, roles, grupos, sesiones,
> auditoría, historial) usa SQLite por defecto sin dependencias extra. Para
> usar PostgreSQL o MySQL basta con instalar su driver (los mismos paquetes que
> el módulo `datastore`) y configurar la sección `database`. Ver
> [explica-arquitectura.md](explica-arquitectura.md) → *Capa de Persistencia y Esquema de BD*.

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
