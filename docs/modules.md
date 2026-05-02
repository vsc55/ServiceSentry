# Referencia de Módulos (Watchfuls)

Referencia de configuración y comportamiento de todos los módulos de monitorización incluidos.

Cada módulo es un **package** (carpeta con `__init__.py`) en `watchfuls/`.
Consulta [watchful_guide.md](watchful_guide.md) para crear el tuyo propio.

---

## Estructura de Package del Módulo

Todos los módulos siguen esta estructura:

```
watchfuls/
└── mi_modulo/
    ├── __init__.py        # Implementación
    ├── watchful.py        # Alias: from . import Watchful
    ├── schema.json        # Esquema de campos (tipos, defaults, rangos)
    ├── info.json          # Metadatos: nombre, icono, descripción
    ├── lang/
    │   ├── en_EN.json     # Etiquetas en inglés
    │   └── es_ES.json     # Etiquetas en español
    └── tests/
        └── test_mi_modulo.py
```

---

## ReturnModuleCheck

Estructura devuelta por el método `check()` de cada módulo:

```python
{
    "clave_item": {
        "status": True / False,    # True = OK, False = Error
        "message": "texto",         # Texto de notificación Telegram (soporta *negrita*)
        "send": True / False,       # Si se envía por Telegram
        "other_data": { ... }       # Datos extra almacenados en status.json
    }
}
```

---

## 📁 filesystemusage — Uso de Disco

Monitoriza el porcentaje de uso de particiones usando `psutil`.

**Plataforma:** Linux, Windows, macOS 🌐

**Config (`modules.json`):**
```json
{
    "filesystemusage": {
        "enabled": true,
        "alert": 85,
        "list": {
            "/": 90,
            "/boot": 85
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `alert` | int | 85 | Umbral global de alerta (% de uso) |
| `list` | dict | `{}` | Umbrales por partición; el valor puede ser int o `{"enabled": true, "alert": N}` |

**Flujo:** `psutil.disk_partitions()` → `psutil.disk_usage(mountpoint)` → compara % con el umbral.
Ignora automáticamente tipos de filesystem irrelevantes (squashfs, tmpfs, devtmpfs, etc.).

---

## 🌡️ hddtemp — Temperatura de Discos

Consulta el demonio hddtemp por socket TCP para obtener temperaturas de disco.

**Plataforma:** Linux (requiere demonio hddtemp)

**Config:**
```json
{
    "hddtemp": {
        "enabled": true,
        "alert": 50,
        "timeout": 5,
        "threads": 5,
        "list": {
            "servidor1": {
                "enabled": true,
                "host": "192.168.1.10",
                "port": 7634,
                "exclude": ["/dev/sdc"]
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `alert` | int | 50 | Temperatura máxima (°C) antes de alertar |
| `timeout` | int | 5 | Timeout de conexión TCP en segundos |
| `threads` | int | 5 | Hilos en paralelo para consultar hosts |
| `list.*.host` | string | — | IP/hostname del demonio hddtemp |
| `list.*.port` | int | 7634 | Puerto TCP del demonio hddtemp |
| `list.*.exclude` | list | `[]` | Dispositivos a ignorar (ej: `"/dev/sdc"`) |

**Flujo:** `socket.create_connection(host, port)` → lee datos → parsea formato `|dev|model|temp|unit|` → compara con el umbral.

---

## 🗄️ mysql — Conectividad MySQL

Verifica que los servidores MySQL son accesibles y responden a consultas.

**Plataforma:** Linux / Windows / macOS (requiere `PyMySQL`)

**Config:**
```json
{
    "mysql": {
        "enabled": true,
        "threads": 5,
        "list": {
            "db_produccion": {
                "enabled": true,
                "host": "192.168.1.20",
                "port": 3306,
                "user": "monitor",
                "password": "secret",
                "db": "mydb",
                "socket": ""
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `list.*.host` | string | `""` | Host MySQL |
| `list.*.port` | int | 3306 | Puerto MySQL |
| `list.*.user` | string | `""` | Usuario MySQL |
| `list.*.password` | string | `""` | Contraseña |
| `list.*.db` | string | `""` | Base de datos |
| `list.*.socket` | string | `""` | Socket Unix (si se establece, ignora host/port) |

**Flujo:** `pymysql.connect()` → `SHOW GLOBAL STATUS` → clasifica errores con `match/case`
(1045 = acceso denegado, 2003 = sin conexión con sub-clasificación por mensaje, etc.).

---

## 🏓 ping — Disponibilidad de Hosts

Comprueba si los hosts son accesibles mediante ping ICMP.

**Plataforma:** Linux / macOS / Windows 🌐 (con `pythonping`; el fallback raw socket requiere root o `CAP_NET_RAW`)

**Config:**
```json
{
    "ping": {
        "enabled": true,
        "threads": 5,
        "timeout": 5,
        "attempt": 3,
        "alert": 1,
        "list": {
            "Router": {
                "enabled": true,
                "host": "192.168.1.1",
                "timeout": 3,
                "attempt": 5
            },
            "192.168.1.2": true
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `timeout` | int | 5 | Timeout global por intento (segundos) |
| `attempt` | int | 3 | Número global de intentos antes de declarar fallo |
| `alert` | int | 1 | Fallos consecutivos necesarios antes de alertar |
| `list.*.host` | string | clave | IP o hostname a comprobar |
| `list.*.timeout` | int | módulo | Timeout específico por host |
| `list.*.attempt` | int | módulo | Intentos específicos por host |
| `list.*.alert` | int | módulo | Umbral de alerta específico por host |

**Flujo:** `pythonping` como método principal (multiplataforma, sin root en Windows); raw socket ICMP nativo (`SOCK_RAW` → `SOCK_DGRAM`) como fallback cuando `pythonping` no está instalado.
Reintenta `attempt` veces; alerta cuando los fallos consecutivos superan `alert`.

> \* **Soporte Windows** requiere `pythonping` (`pip install pythonping`). Sin él se usa el fallback raw socket, que requiere privilegios de Administrador en Windows.

---

## 💽 raid — Estado RAID Linux

Monitoriza arrays RAID software de Linux leyendo `/proc/mdstat`, localmente y vía SSH.

**Plataforma:** Linux

**Config:**
```json
{
    "raid": {
        "enabled": true,
        "local": true,
        "threads": 5,
        "timeout": 30,
        "remote": {
            "1": {
                "enabled": true,
                "label": "NAS",
                "host": "192.168.1.30",
                "port": 22,
                "user": "root",
                "password": "secret"
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `local` | bool | true | Monitorizar RAID local |
| `timeout` | float | 30 | Timeout SSH para hosts remotos |
| `remote.N.label` | string | — | Nombre identificativo del host remoto |
| `remote.N.host` | string | — | IP/hostname del servidor remoto |
| `remote.N.port` | int | 22 | Puerto SSH |
| `remote.N.user` | string | — | Usuario SSH |
| `remote.N.password` | string | — | Contraseña SSH |

**Estados detectados:** `ok`, `error` (array degradado), `recovery` (reconstruyendo con %, tiempo estimado y velocidad).

**Flujo:** Lee `/proc/mdstat` (localmente con `open()`, remotamente con `cat` vía SSH/paramiko) → parsea líneas con `match/case` sobre `UpdateStatus`.

---

## 🐏 ram_swap — Uso de RAM y SWAP

Monitoriza el porcentaje de uso de RAM y SWAP usando `psutil`.

**Plataforma:** Linux, Windows, macOS 🌐

**Config:**
```json
{
    "ram_swap": {
        "enabled": true,
        "alert_ram": 60,
        "alert_swap": 60
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `alert_ram` | int | 60 | % de RAM usada para alertar |
| `alert_swap` | int | 60 | % de SWAP usada para alertar |

**Flujo:** `psutil.virtual_memory()` y `psutil.swap_memory()` → calcula porcentaje de uso → compara con el umbral.

---

## ⚙️ service_status — Estado de Servicios systemd

Comprueba si los servicios systemd están en ejecución. Soporta **auto-remediación** (reinicio automático).

**Plataforma:** Linux (systemd)

**Config:**
```json
{
    "service_status": {
        "enabled": true,
        "threads": 5,
        "list": {
            "nginx": {
                "enabled": true,
                "remediation": true
            },
            "docker": {
                "enabled": true,
                "remediation": false
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `list.*.enabled` | bool | true | Habilitar monitorización de este servicio |
| `list.*.remediation` | bool | false | Si `true`, ejecuta `systemctl start` cuando el servicio está caído |

**Flujo:**
```
systemctl status <servicio>
├── Active: active (running) → OK ✅
├── Active: inactive (dead)  → FALLO ❌
│   └── Si remediation=true:
│       ├── systemctl start <servicio>
│       ├── Re-check del estado
│       └── Notifica resultado de la recuperación
└── stdout vacío → Error (servicio no encontrado, etc.)
```

---

## 🌡️ temperature — Sensores Térmicos

Monitoriza sensores de temperatura del sistema (zonas térmicas de Linux).

**Plataforma:** Linux

**Config:**
```json
{
    "temperature": {
        "enabled": true,
        "alert": 80,
        "list": {
            "thermal_zone0": {
                "enabled": true,
                "label": "CPU",
                "alert": 90
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `alert` | float | 80 | Temperatura máxima global (°C) |
| `list.*.label` | string | tipo del sensor | Nombre legible del sensor |
| `list.*.alert` | float | global | Umbral específico por sensor |

**Flujo:** Lee `/sys/class/thermal/thermal_zone*/temp` y `*/type` → divide entre 1000 → compara con el umbral.

---

## 🌐 web — Disponibilidad Web

Comprueba que las URLs responden con el código HTTP esperado.

**Plataforma:** Linux, Windows, macOS 🌐

**Config:**
```json
{
    "web": {
        "enabled": true,
        "threads": 5,
        "list": {
            "Mi Web": {
                "enabled": true,
                "url": "https://example.com",
                "code": 200
            },
            "https://api.example.com": true
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `list.*.url` | string | clave | URL a comprobar (HTTP o HTTPS) |
| `list.*.code` | int | 200 | Código HTTP de respuesta esperado |
| `list.*.timeout` | int | 15 | Timeout de la petición en segundos |

**Flujo:** `urllib.request` (stdlib de Python) → compara el código HTTP real con el esperado. Soporta HTTP y HTTPS sin dependencias externas.
