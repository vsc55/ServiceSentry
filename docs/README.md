# ServiceSentry (ServiSesentry)

> Sistema de monitorización de servicios e infraestructura Linux con notificaciones por Telegram.

**Autor:** Javier Pastor (VSC55)  
**Licencia:** GPL v3  
**Python:** 3.6+  

---

## 📋 Índice

1. [Descripción General](#descripción-general)
2. [Arquitectura](#arquitectura)
3. [Estructura de Directorios](#estructura-de-directorios)
4. [Flujo de Ejecución](#flujo-de-ejecución)
5. [Configuración](#configuración)
6. [Módulos (Watchfuls)](#módulos-watchfuls)
7. [Sistema de Notificaciones (Telegram)](#sistema-de-notificaciones-telegram)
8. [Ejecución de Comandos (Exec)](#ejecución-de-comandos-exec)
9. [Sistema de Debug](#sistema-de-debug)
10. [Uso por Línea de Comandos](#uso-por-línea-de-comandos)
11. [Dependencias](#dependencias)
12. [Notas de Diseño](#notas-de-diseño)

---

## Descripción General

ServiceSentry es una herramienta de monitorización para sistemas Linux que:

- Ejecuta comprobaciones periódicas sobre servicios, discos, RAID, RAM, temperaturas, webs, MySQL, ping, etc.
- Detecta **cambios de estado** (no envía notificación si el estado no ha cambiado).
- Envía alertas por **Telegram** cuando algo cambia.
- Soporta ejecución **local** y **remota** (SSH vía paramiko).
- Ejecuta los módulos en **paralelo** usando `ThreadPoolExecutor`.
- Arquitectura de **plugins**: cada módulo de monitorización es un archivo Python independiente en `watchfuls/`.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────┐
│                     main.py                         │
│  (CLI, argparse, daemon loop, config init)          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                  lib/monitor.py                     │
│  (Motor principal: carga módulos, ThreadPool,       │
│   gestión de estado, despacho de notificaciones)    │
└───────┬──────────┬──────────┬───────────────────────┘
        │          │          │
        ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Telegram │ │  Status  │ │  Watchfuls   │
│ (lib/)   │ │ (JSON)   │ │  (plugins)   │
└──────────┘ └──────────┘ └──────┬───────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ModuleBase    lib/exe.py   lib/linux/
              (herencia)    (local/SSH)  (sensores, RAID, mem)
```

### Jerarquía de Clases

```
ObjectBase (lib/object_base.py)
├── debug: Debug  ← instancia compartida por TODAS las clases
│
├── Main (main.py)
├── Monitor (lib/monitor.py)
├── Telegram (lib/telegram.py)
├── ConfigStore (lib/config/config_store.py)
│   └── ConfigControl (lib/config/config_control.py)
└── ModuleBase (lib/modules/module_base.py)
    ├── watchfuls/filesystemusage.py::Watchful
    ├── watchfuls/hddtemp.py::Watchful
    ├── watchfuls/mysql.py::Watchful
    ├── watchfuls/ping.py::Watchful
    ├── watchfuls/raid.py::Watchful
    ├── watchfuls/ram_swap.py::Watchful
    ├── watchfuls/service_status.py::Watchful
    ├── watchfuls/temperature.py::Watchful
    └── watchfuls/web.py::Watchful
```

---

## Estructura de Directorios

```
ServiceSentry/
├── src/
│   ├── main.py                          # Punto de entrada
│   ├── lib/
│   │   ├── __init__.py                  # Exports: ObjectBase, Switch, DictFilesPath, Monitor, Telegram, Exec
│   │   ├── object_base.py              # Clase base con Debug compartido
│   │   ├── monitor.py                  # Motor de monitorización
│   │   ├── telegram.py                 # Envío de mensajes Telegram
│   │   ├── exe.py                      # Ejecución de comandos local/remoto
│   │   ├── switch.py                   # Implementación Switch/Case
│   │   ├── dict_files_path.py          # Diccionario de rutas de archivos
│   │   ├── tools.py                    # Utilidades (bytes2human)
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── config_store.py         # I/O JSON (lectura/escritura)
│   │   │   ├── config_control.py       # Operaciones sobre config (get/set/exist)
│   │   │   └── config_type_return.py   # Enum tipos de retorno
│   │   ├── debug/
│   │   │   ├── __init__.py
│   │   │   ├── debug.py                # Sistema de debug con niveles
│   │   │   └── debug_level.py          # Enum: null, debug, info, warning, error, emergency
│   │   ├── linux/
│   │   │   ├── __init__.py
│   │   │   ├── mem.py                  # Lectura /proc/meminfo (RAM/SWAP)
│   │   │   ├── thermal_info_collection.py  # Sensores térmicos /sys/class/thermal
│   │   │   └── raid_mdstat.py          # Parser /proc/mdstat (RAID)
│   │   └── modules/
│   │       ├── __init__.py
│   │       ├── module_base.py          # Clase base para todos los watchfuls
│   │       ├── dict_return_check.py    # Estructura ReturnModuleCheck
│   │       └── enum_config_options.py  # Enum opciones de config comunes
│   └── watchfuls/                      # Plugins de monitorización
│       ├── filesystemusage.py
│       ├── hddtemp.py
│       ├── mysql.py
│       ├── ping.py
│       ├── raid.py
│       ├── ram_swap.py
│       ├── service_status.py
│       ├── temperature.py
│       └── web.py
├── data/                               # Config en modo desarrollo
│   ├── config.json
│   ├── monitor.json
│   └── modules.json
└── docs/
    └── README.md                       # Este archivo
```

---

## Flujo de Ejecución

### Inicio

```
1. main.py: argparse procesa argumentos CLI
2. Main.__init__():
   ├── Inicializa atributos defensivamente
   ├── Añade watchfuls/ al sys.path
   ├── __args_set() → aplica argumentos (path, verbose, timer, daemon)
   ├── __init_config() → lee config.json, aplica defaults, lee valores
   ├── __init_monitor() → crea Monitor(dir_base, dir_config, dir_modules, dir_var)
   │   └── Monitor.__init__():
   │       ├── Lee config.json, monitor.json, modules.json
   │       ├── Lee/crea status.json en /var/lib/ServiSesentry/
   │       └── Inicializa Telegram (token + chat_id)
   └── __args_cmd() → ejecuta comandos (ej: clear_status)
3. Main.start():
   ├── Modo single: monitor.check() una vez
   └── Modo daemon: loop infinito con sleep(timer_check)
```

### Ciclo de Check

```
Monitor.check():
│
├── 1. Escanea watchfuls/*.py (excluye __init__.py)
├── 2. Filtra por módulos habilitados en modules.json
├── 3. Lee status.json (estado anterior)
├── 4. Crea ThreadPoolExecutor(max_workers=threads)
│
├── 5. Para CADA módulo (en paralelo):
│   └── check_module(nombre):
│       ├── importlib.import_module(nombre)
│       ├── Watchful(self) ← le pasa el Monitor
│       ├── module.check() → ReturnModuleCheck
│       │
│       └── Para CADA resultado en ReturnModuleCheck:
│           ├── Guarda other_data en status.json
│           ├── ¿Ha CAMBIADO el status? (check_status)
│           │   ├── SÍ → Actualiza status + envía Telegram (si send=True)
│           │   └── NO → No hace nada (evita spam)
│           └── return True (hubo cambios)
│
├── 6. Si hubo cambios → guarda status.json
├── 7. send_message_end() → resumen Telegram
└── 8. Fin del ciclo
```

### Detección de Cambio de Estado

El sistema solo notifica cuando **cambia** el estado. La lógica está en `Monitor.check_status()`:

```python
# Busca en status.json: [modulo][sub_key][status]
# Si no existe, asume el opuesto (not status) → primer check siempre notifica
# Si el valor almacenado ≠ status actual → ha cambiado → return True
```

Esto evita enviar la misma alerta repetidamente en cada ciclo.

---

## Configuración

### Rutas de Configuración

| Modo | Directorio Config | Directorio Var |
|------|-------------------|----------------|
| **Desarrollo** (detecta `src` en path) | `../data/` (relativo) | `/var/lib/ServiSesentry/dev/` |
| **Producción** | `/etc/ServiSesentry/` | `/var/lib/ServiSesentry/` |
| **Custom** (`-p path`) | `path` especificado | Según modo dev/prod |

### config.json

Configuración global de la aplicación.

```json
{
    "daemon": {
        "timer_check": 300
    },
    "global": {
        "debug": false
    },
    "telegram": {
        "token": "BOT_TOKEN_AQUÍ",
        "chat_id": "CHAT_ID_AQUÍ",
        "group_messages": false
    }
}
```

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `daemon.timer_check` | int | 300 | Segundos entre cada ciclo de comprobación en modo daemon |
| `global.debug` | bool | false | Habilitar debug (actualmente forzado a true) |
| `telegram.token` | string | "" | Token del Bot de Telegram |
| `telegram.chat_id` | string | "" | ID del chat/grupo de Telegram |
| `telegram.group_messages` | bool | false | Si `true`, agrupa mensajes en uno solo al final del ciclo |

### monitor.json

Configuración del motor de monitorización.

```json
{
    "threads": 5
}
```

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `threads` | int | 5 | Número máximo de hilos del ThreadPoolExecutor principal |

### modules.json

Configuración de cada módulo de monitorización. Estructura:

```json
{
    "nombre_modulo": {
        "enabled": true,
        ...configuración específica del módulo...
    }
}
```

### status.json (auto-generado)

Almacena el **último estado conocido** de cada check. Se guarda en el directorio var. Estructura:

```json
{
    "nombre_modulo": {
        "sub_key": {
            "status": true,
            "other_data": { ... }
        }
    }
}
```

---

## Módulos (Watchfuls)

Cada módulo es un archivo Python en `watchfuls/` que:
1. Define una clase `Watchful` que hereda de `ModuleBase`
2. Implementa `check()` que retorna `ReturnModuleCheck`
3. Usa `self.get_conf()` para leer su configuración de `modules.json`

### ReturnModuleCheck

Estructura de datos que cada módulo devuelve:

```python
{
    "sub_key": {
        "status": True/False,      # True=OK, False=Error
        "message": "texto",         # Mensaje para Telegram
        "send": True/False,         # Si debe enviarse por Telegram
        "other_data": { ... }       # Datos extra para status.json
    }
}
```

---

### 📁 filesystemusage — Uso de Disco

Monitoriza el porcentaje de uso de particiones con `df`.

**Config** (`modules.json`):
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

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `alert` | int | 85 | % de uso global para alerta |
| `list` | dict | {} | Particiones con % de alerta personalizado |

**Flujo:** `df -x squashfs -x tmpfs -x devtmpfs` → regex → compara % con umbral.

---

### 🌡️ hddtemp — Temperatura de Discos

Consulta el demonio hddtemp por TCP (socket) para obtener temperaturas.

**Config:**
```json
{
    "hddtemp": {
        "enabled": true,
        "alert": 50,
        "timeout": 5,
        "threads": 5,
        "list": {
            "server1": {
                "enabled": true,
                "host": "192.168.1.10",
                "port": 7634,
                "exclude": ["/dev/sdc"]
            }
        }
    }
}
```

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `alert` | int | 50 | Temperatura máxima (ºC) antes de alertar |
| `timeout` | int | 5 | Timeout de conexión TCP en segundos |
| `threads` | int | 5 | Hilos para consultar hosts en paralelo |
| `list.*.host` | string | — | IP/hostname del demonio hddtemp |
| `list.*.port` | int | 7634 | Puerto TCP del demonio hddtemp |
| `list.*.exclude` | list | [] | Dispositivos a ignorar (ej: `/dev/sdc`) |

**Flujo:** `socket.create_connection(host, port)` → lee datos → parsea formato `|dev|model|temp|unit|` → compara con umbral.

---

### 🗄️ mysql — Conectividad MySQL

Verifica que se puede conectar y ejecutar consultas en servidores MySQL.

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

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `list.*.host` | string | "" | Host MySQL |
| `list.*.port` | int | 3306 | Puerto MySQL |
| `list.*.user` | string | "" | Usuario MySQL |
| `list.*.password` | string | "" | Contraseña |
| `list.*.db` | string | "" | Base de datos |
| `list.*.socket` | string | "" | Socket Unix (si se usa, ignora host/port) |

**Flujo:** `pymysql.connect()` → `SHOW GLOBAL STATUS` → clasifica errores (1045=acceso denegado, 2003=sin conexión, etc.).

---

### 🏓 ping — Ping a Hosts

Verifica la disponibilidad de hosts por ICMP ping.

**Config:**
```json
{
    "ping": {
        "enabled": true,
        "threads": 5,
        "timeout": 5,
        "attempt": 3,
        "list": {
            "192.168.1.1": {
                "enabled": true,
                "label": "Router",
                "timeout": 3,
                "attempt": 5
            }
        }
    }
}
```

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `timeout` | int | 5 | Timeout por intento (segundos) |
| `attempt` | int | 3 | Número de intentos antes de declarar fallo |
| `list.*.label` | string | IP | Nombre amigable para el mensaje |

**Flujo:** `/bin/ping -c 1 -W timeout host` × `attempt` intentos con 1s entre cada uno.

---

### 💽 raid — Estado RAID mdstat

Monitoriza arrays RAID Linux (local y remoto vía SSH).

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

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `local` | bool | true | Monitorizar RAID local |
| `timeout` | float | 30 | Timeout SSH para remotos |
| `remote.N.*` | dict | — | Configuración de cada host remoto |

**Estados detectados:** `ok`, `error` (degraded), `recovery` (reconstruyendo con %, tiempo estimado, velocidad).

**Flujo:** Lee `/proc/mdstat` (local con `open()`, remoto con `cat` vía SSH/paramiko) → parsea líneas.

---

### 🐏 ram_swap — Uso de RAM y SWAP

Monitoriza el porcentaje de uso de memoria RAM y SWAP.

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

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `alert_ram` | int | 60 | % de RAM usada para alertar |
| `alert_swap` | int | 60 | % de SWAP usada para alertar |

**Flujo:** Lee `/proc/meminfo` → calcula `used = total - free - buffers - cached` (RAM) o `total - free` (SWAP).

---

### ⚙️ service_status — Estado de Servicios systemd

Verifica si servicios systemd están corriendo. Soporta **auto-remediación** (restart automático).

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

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `list.*.enabled` | bool/str | — | Habilitar monitorización |
| `list.*.remediation` | bool/str | — | Si `true`, ejecuta `systemctl start` cuando el servicio está caído |

**Flujo:**
```
systemctl status <servicio>
├── Active: active (running) → OK ✅
├── Active: inactive (dead) → FAIL ❌
│   └── Si remediation=true:
│       ├── systemctl start <servicio>
│       ├── Re-check status
│       └── Notifica resultado de recovery
└── stdout vacío → Error (servicio no existe, etc.)
```

---

### 🌡️ temperature — Sensores Térmicos

Monitoriza sensores de temperatura del sistema (thermal zones de Linux).

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

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `alert` | float | 80 | Temperatura máxima global (ºC) |
| `list.*.label` | string | tipo del sensor | Nombre amigable |
| `list.*.alert` | float | global | Umbral específico por sensor |

**Flujo:** Lee `/sys/class/thermal/thermal_zone*/temp` y `/sys/class/thermal/thermal_zone*/type` → divide entre 1000 → compara con umbral.

---

### 🌐 web — Disponibilidad Web

Comprueba que URLs responden con el código HTTP esperado.

**Config:**
```json
{
    "web": {
        "enabled": true,
        "threads": 5,
        "list": {
            "example.com": {
                "enabled": true,
                "code": 200
            },
            "api.example.com": true
        }
    }
}
```

| Clave | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `list.*.code` | int | 200 | Código HTTP esperado |

**Flujo:** `curl -sL -w "%{http_code}" http://url -o /dev/null` → compara código con esperado.

> **Nota:** Actualmente solo soporta HTTP (no HTTPS). Hay un TODO pendiente.

---

## Sistema de Notificaciones (Telegram)

### Funcionamiento

```
Telegram.__init__():
├── Crea hilo daemon (pool_run) que corre permanentemente
└── Lista de mensajes (list_msg) como cola

Flujo de envío:
1. Monitor llama tg.send_message(msg) → se añade a list_msg
2. Hilo pool_run detecta mensaje en lista
3. Modo normal: envía cada mensaje individualmente
4. Modo group_messages: acumula mensajes, envía bloque cuando la lista queda vacía
5. Al final del ciclo: send_message_end() → añade resumen + espera a que se vacíe la cola
```

### Formato de Mensajes

```
✅ 💻 [hostname]: Servicio OK                  (status=True)
❎ 💻 [hostname]: Servicio con problemas        (status=False)
ℹ️ Summary *hostname*, get *N* new Message. ☝☝☝  (resumen final)
```

### API Telegram

- Endpoint: `https://api.telegram.org/bot{token}/sendMessage`
- Parámetros: `chat_id`, `text`, `parse_mode=Markdown`
- Códigos de retorno internos: `200`=OK, `-1`=token null, `-2`=chat_id null, `-3`=ambos null

---

## Ejecución de Comandos (Exec)

La clase `Exec` en `lib/exe.py` abstrae la ejecución de comandos:

| Modo | Implementación |
|------|---------------|
| **Local** | `subprocess.Popen(shlex.split(cmd))` → stdout, stderr, exit_code |
| **Remoto** | `paramiko.SSHClient()` → `client.exec_command(cmd)` → stdout, stderr, exit_code |

### Retorno

Siempre retorna una tupla de 4 elementos:
```python
(stdout: str, stderr: str, exit_code: int, exception: Exception)
```

### Uso directo (estático)

```python
from lib.exe import Exec

# Local
stdout, stderr, code, exc = Exec.execute("ls -la")

# Remoto
stdout, stderr, code, exc = Exec.execute(
    command="cat /proc/mdstat",
    host="192.168.1.10",
    port=22,
    user="root",
    password="secret",
    timeout=30
)
```

---

## Sistema de Debug

### Niveles (DebugLevel)

| Nivel | Valor | Uso |
|-------|-------|-----|
| `null` | 0 | Muestra todo |
| `debug` | 1 | Información detallada de debugging |
| `info` | 2 | Información general de flujo |
| `warning` | 3 | Advertencias |
| `error` | 4 | Errores |
| `emergency` | 5 | Emergencias críticas |

### Lógica de Filtrado

Un mensaje se muestra si:
- `debug.enabled == True` **Y**
- `debug.level.value <= msg_level.value`

Es decir, el nivel configurado actúa como **filtro mínimo**. Con level=`info`, se muestran mensajes `info`, `warning`, `error` y `emergency`, pero NO `debug`.

### Instancia Compartida

`ObjectBase.debug` es un atributo de **clase** (no de instancia). Esto significa que **TODOS** los objetos que heredan de `ObjectBase` comparten la misma instancia de `Debug`. Al cambiar el nivel en uno, cambia para todos.

---

## Uso por Línea de Comandos

```bash
python3 main.py [opciones]
```

| Opción | Descripción |
|--------|-------------|
| `-d`, `--daemon` | Modo daemon (ejecución continua) |
| `-t N`, `--timer N` | Intervalo entre checks en segundos (requiere daemon) |
| `-v`, `--verbose` | Modo verbose (debug level = null → muestra todo) |
| `-p PATH`, `--path PATH` | Ruta personalizada al directorio de configuración |
| `-c`, `--clear` | Limpia status.json antes de ejecutar |

### Ejemplos

```bash
# Ejecución única
python3 main.py

# Daemon con check cada 5 minutos
python3 main.py -d -t 300

# Verbose + config custom
python3 main.py -v -p /opt/myconfig/

# Limpiar estado y ejecutar en daemon
python3 main.py -c -d -t 60
```

---

## Dependencias

| Paquete | Usado por | Propósito |
|---------|-----------|-----------|
| `paramiko` | lib/exe.py | Ejecución remota de comandos vía SSH |
| `requests` | lib/telegram.py | Envío de mensajes por API de Telegram |
| `pymysql` | watchfuls/mysql.py | Verificación de conectividad MySQL |

### Instalación

```bash
pip install paramiko requests pymysql
```

### Dependencias del Sistema

| Comando | Módulo | Ruta esperada |
|---------|--------|---------------|
| `df` | filesystemusage | `/bin/df` |
| `ping` | ping | `/bin/ping` |
| `systemctl` | service_status | `/bin/systemctl` |
| `curl` | web | `/usr/bin/curl` |
| hddtemp daemon | hddtemp | TCP puerto 7634 |

---

## Notas de Diseño

### Plugins

Para crear un nuevo módulo de monitorización:

1. Crear `watchfuls/mi_modulo.py`
2. Definir clase `Watchful(ModuleBase)`
3. Implementar `check()` que retorne `self.dict_return`
4. Usar `self.get_conf('key', default)` para leer config
5. Usar `self.dict_return.set(key, status, message, send, other_data)` para añadir resultados
6. Añadir config en `modules.json` bajo el nombre del archivo (sin `.py`)

```python
from lib.modules import ModuleBase

class Watchful(ModuleBase):
    def __init__(self, monitor):
        super().__init__(monitor, __name__)

    def check(self):
        # Tu lógica aquí
        status = True  # o False
        self.dict_return.set("mi_check", status, "Mensaje", other_data={})
        super().check()  # debug logging
        return self.dict_return
```

### Concurrencia

- **Monitor** usa `ThreadPoolExecutor` para ejecutar módulos en paralelo
- **Dentro de cada módulo** (ping, mysql, hddtemp, raid, service_status, web) también se usa `ThreadPoolExecutor` para checks múltiples en paralelo
- **Telegram** usa un hilo daemon separado para envío asíncrono de mensajes

### Estado Persistente

- `status.json` persiste entre ejecuciones
- Solo se notifica cuando el estado **cambia**
- `-c` / `--clear` resetea el estado (útil para forzar re-notificación)
