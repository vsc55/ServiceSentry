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

**Config:**
```json
{
    "filesystemusage": {
        "enabled": true,
        "threads": 5,
        "alert": 85,
        "list": {
            "Root": {
                "enabled": true,
                "partition": "/",
                "alert": 90,
                "label": "Root"
            },
            "Data": {
                "enabled": true,
                "partition": "/data",
                "alert": 85
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `alert` | int | 85 | Umbral global de alerta (% de uso), aplicado a todas las particiones sin umbral propio |
| `threads` | int | 5 | Particiones a comprobar en paralelo |
| `list.*.enabled` | bool | `true` | Habilitar monitorización de esta partición |
| `list.*.partition` | string | `""` | Punto de montaje o letra de unidad (p. ej. `/` o `C:\`). Si está vacío, se usa la clave del ítem |
| `list.*.alert` | int | 85 | Umbral de alerta (%) para esta partición, anula el umbral global |
| `list.*.label` | string | `""` | Nombre mostrado en notificaciones. Si está vacío, se usa la clave del ítem |

> **Descubrimiento:** la UI web incluye un botón para listar automáticamente las particiones montadas e incorporarlas a la configuración con un solo clic. Muestra dispositivo, tipo de filesystem y porcentaje de uso actual.

> **Formato legacy:** el valor de un ítem puede ser directamente un entero (`"/": 90`) — se interpreta como umbral de alerta para esa partición. La UI lo promueve automáticamente al formato dict al renderizarlo.

**Flujo:** `psutil.disk_partitions()` → `psutil.disk_usage(mountpoint)` → compara % con el umbral.
Ignora automáticamente tipos de filesystem irrelevantes (squashfs, tmpfs, devtmpfs, overlay, etc.).

---

## 🌡️ hddtemp — Temperatura de Discos

Consulta el demonio hddtemp por socket TCP para obtener temperaturas de disco. Al conectarse a un host remoto, es compatible con cualquier plataforma cliente (Linux, macOS, Windows).

> El demonio `hddtemp` debe estar ejecutándose en el servidor remoto y escuchando en el puerto configurado.

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
| `enabled` | bool | `true` | Habilitar o deshabilitar la monitorización de este host |
| `alert` | int | 50 | Temperatura máxima (°C) antes de alertar |
| `timeout` | int | 5 | Timeout de conexión TCP en segundos |
| `threads` | int | 5 | Hilos en paralelo para consultar hosts |
| `list.*.host` | string | — | IP/hostname del servidor donde corre el demonio hddtemp |
| `list.*.port` | int | 7634 | Puerto TCP del demonio hddtemp |
| `list.*.exclude` | list | `[]` | Dispositivos a ignorar (ej: `"/dev/sdc"`) |

**Flujo:** `socket.create_connection(host, port)` → lee datos → parsea formato `|dev|model|temp|unit|` → compara con el umbral.

---

## 🗄️ datastore — Conectividad de Bases de Datos

Verifica que los servidores de bases de datos son accesibles y responden correctamente. Soporta múltiples motores, modos de conexión TCP, socket Unix y túnel SSH.

**Plataforma:** Linux / Windows / macOS 🌐

**Dependencias opcionales** (instalar solo las necesarias):

| Motor | Paquete |
| --- | --- |
| MySQL / MariaDB | `PyMySQL` (incluido por defecto) |
| PostgreSQL | `psycopg2-binary` |
| Microsoft SQL Server | `pymssql` |
| MongoDB | `pymongo` |
| Redis / Valkey | `redis` |
| Elasticsearch / OpenSearch | *(solo `urllib`, sin dependencia extra)* |
| InfluxDB | *(solo `urllib`, sin dependencia extra)* |
| Memcached | `pymemcache` |
| Túnel SSH (cualquier motor) | `paramiko` |

### Motores soportados

| `db_type` | Motor | Puerto por defecto |
| --- | --- | --- |
| `mysql` | MySQL / MariaDB | 3306 |
| `postgres` | PostgreSQL | 5432 |
| `mssql` | Microsoft SQL Server | 1433 |
| `mongodb` | MongoDB | 27017 |
| `redis` | Redis / Valkey | 6379 |
| `elasticsearch` | Elasticsearch / OpenSearch | 9200 |
| `influxdb` | InfluxDB | 8086 |
| `memcached` | Memcached | 11211 |

> Los valores `mariadb`, `valkey` y `opensearch` almacenados en datos existentes siguen funcionando; la UI los unifica con `mysql`, `redis` y `elasticsearch` respectivamente.

### Modos de conexión

| `conn_type` | Descripción |
|-------------|-------------|
| `tcp` | Conexión TCP directa a `host:port` |
| `socket` | Socket Unix local — disponible en MySQL/MariaDB, PostgreSQL, Redis/Valkey y Memcached |
| `ssh` | TCP tunelizado sobre SSH — requiere `paramiko` |

### Config

**MySQL/MariaDB — TCP:**
```json
{
    "datastore": {
        "enabled": true,
        "threads": 5,
        "list": {
            "produccion": {
                "enabled": true,
                "label": "BD Producción",
                "db_type": "mysql",
                "conn_type": "tcp",
                "host": "db.ejemplo.com",
                "port": 0,
                "user": "monitor",
                "password": "enc:gAAAAA...",
                "db": "myapp"
            }
        }
    }
}
```

> `"port": 0` aplica el puerto por defecto del motor (3306 para MySQL). En la UI, el campo aparece vacío y muestra el puerto por defecto como texto de ayuda.

**PostgreSQL con TLS — Túnel SSH:**
```json
{
    "datastore": {
        "list": {
            "pg_remoto": {
                "db_type": "postgres",
                "conn_type": "ssh",
                "ssh_host": "bastion.ejemplo.com",
                "ssh_port": 22,
                "ssh_user": "ubuntu",
                "ssh_key": "/home/usuario/.ssh/id_rsa",
                "host": "127.0.0.1",
                "port": 0,
                "user": "monitor",
                "password": "enc:gAAAAA...",
                "db": "mydb",
                "tls": true
            }
        }
    }
}
```

**Redis/Valkey — Socket Unix:**
```json
{
    "datastore": {
        "list": {
            "redis_local": {
                "db_type": "redis",
                "conn_type": "socket",
                "socket": "/var/run/redis/redis.sock",
                "password": "",
                "db_index": 0
            }
        }
    }
}
```

**Elasticsearch/OpenSearch:**
```json
{
    "datastore": {
        "list": {
            "elastic_prod": {
                "db_type": "elasticsearch",
                "conn_type": "tcp",
                "scheme": "https",
                "host": "elastic.ejemplo.com",
                "port": 0,
                "user": "elastic",
                "password": "enc:gAAAAA..."
            }
        }
    }
}
```

**InfluxDB 2.x:**
```json
{
    "datastore": {
        "list": {
            "influx_prod": {
                "db_type": "influxdb",
                "conn_type": "tcp",
                "scheme": "http",
                "host": "influx.ejemplo.com",
                "port": 0,
                "token": "enc:gAAAAA...",
                "db": "mi_bucket"
            }
        }
    }
}
```

### Referencia de campos

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `enabled` | bool | `true` | Habilitar este ítem |
| `label` | string | `""` | Nombre de visualización. Si está vacío, se usa la clave |
| `db_type` | string | `"mysql"` | Motor: `mysql`, `postgres`, `mssql`, `mongodb`, `redis`, `elasticsearch`, `influxdb`, `memcached` |
| `conn_type` | string | `"tcp"` | Modo: `tcp`, `socket` o `ssh` |
| `scheme` | string | `"http"` | `http` o `https`. Solo en `elasticsearch` e `influxdb` |
| `host` | string | `""` | IP/hostname. Usado en modos `tcp` y `ssh` |
| `port` | int | `0` | Puerto TCP. `0` aplica el puerto por defecto del motor. La UI muestra el puerto por defecto como placeholder cuando está vacío |
| `socket` | string | `""` | Ruta al socket Unix. Solo en modo `socket` y motores compatibles |
| `user` | string | `""` | Usuario de autenticación. No aplica a Redis/Valkey, Memcached ni InfluxDB con token |
| `password` | string | `""` | Contraseña (**cifrada en disco** con `enc:`) |
| `token` | string | `""` | Token API de InfluxDB 2.x (**cifrado en disco** con `enc:`). Tiene prioridad sobre `user`/`password` |
| `db` | string | `""` | Base de datos, bucket o índice. No aplica a Redis/Valkey, Memcached |
| `auth_db` | string | `"admin"` | Base de datos de autenticación MongoDB |
| `db_index` | int | `0` | Índice lógico de Redis/Valkey (0–15) |
| `tls` | bool | `false` | Activar TLS/SSL. Disponible en PostgreSQL, MSSQL, MongoDB y Redis/Valkey |
| `ssh_host` | string | `""` | Hostname/IP del servidor SSH de salto |
| `ssh_port` | int | `0` | Puerto SSH del servidor de salto. `0` usa el puerto 22 por defecto. La UI muestra `22` como placeholder cuando está vacío |
| `ssh_user` | string | `""` | Usuario SSH |
| `ssh_password` | string | `""` | Contraseña SSH (**cifrada en disco** con `enc:`). Ignorada si se especifica `ssh_key` |
| `ssh_key` | string | `""` | Ruta a la clave privada SSH. Tiene prioridad sobre `ssh_password` |

### Acciones de la UI

| Acción | Descripción |
|--------|-------------|
| **Probar SSH** | Verifica el túnel SSH sin conectar a la base de datos. Solo visible en modo `ssh`. Registrado en auditoría. |
| **Probar conexión** | Establece la conexión completa y ejecuta una consulta de comprobación. Registrado en auditoría. |
| **Listar bases de datos** | Abre un selector con las bases de datos, buckets o índices del servidor. Al seleccionar, escribe el nombre en el campo `db`. Disponible en MySQL/MariaDB, PostgreSQL, MSSQL, MongoDB, Elasticsearch/OpenSearch e InfluxDB. |

### Notas de implementación

**Por motor:**

- **MySQL / MariaDB** — `pymysql.connect()` + `SELECT 1`. Error 1045 = acceso denegado; 2003 = sin conexión.
- **PostgreSQL** — `psycopg2.connect()`. Soporta `sslmode=require` con `tls: true`. Socket pasando `host=/ruta/socket`.
- **MSSQL** — `pymssql.connect()`. Los mensajes de error de DB-Lib se limpian automáticamente (error 18456 = credenciales incorrectas, 20002 = servidor no accesible).
- **MongoDB** — `pymongo.MongoClient` + `ping`. Soporta autenticación con `authSource` y TLS.
- **Redis / Valkey** — `redis.Redis` + `PING`. Soporta socket Unix, contraseña e índice lógico.
- **Elasticsearch / OpenSearch** — `GET /_cluster/health` vía HTTP. `status: red` = error. No requiere librería extra.
- **InfluxDB** — Prueba `/health` (v2.x, busca `status: pass`) con fallback a `/ping` (v1.x, 204). Token para v2.x, usuario/contraseña para v1.x. No requiere librería extra.
- **Memcached** — `pymemcache.Client` + `get('__ping__')`.

**Túnel SSH:** se levanta un túnel local con `paramiko` antes de cualquier intento de conexión. El puerto local se asigna dinámicamente. El túnel se cierra automáticamente al terminar, tanto en éxito como en error.

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
                "label": "Router principal",
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
| `threads` | int | 5 | Hosts a comprobar en paralelo |
| `timeout` | int | 5 | Timeout global por intento (segundos) |
| `attempt` | int | 3 | Número global de intentos antes de declarar fallo |
| `alert` | int | 1 | Fallos consecutivos necesarios antes de alertar |
| `list.*.enabled` | bool | `true` | Habilitar monitorización de este host |
| `list.*.label` | string | `""` | Nombre mostrado en la UI. Si está vacío, se usa la clave del ítem |
| `list.*.host` | string | clave | IP o hostname a comprobar. Si está vacío, se usa la clave del ítem |
| `list.*.timeout` | int | módulo | Timeout específico por host, anula el valor global |
| `list.*.attempt` | int | módulo | Intentos específicos por host, anula el valor global |
| `list.*.alert` | int | módulo | Umbral de alerta específico por host, anula el valor global |

**Flujo:** `pythonping` como método principal (multiplataforma, sin root en Windows); raw socket ICMP nativo (`SOCK_RAW` → `SOCK_DGRAM`) como fallback cuando `pythonping` no está instalado.
Reintenta `attempt` veces; alerta cuando los fallos consecutivos superan `alert`.

> \* **Soporte Windows** requiere `pythonping` (`pip install pythonping`). Sin él se usa el fallback raw socket, que requiere privilegios de Administrador en Windows.

---

## 💽 raid — Estado RAID Linux

Monitoriza arrays RAID software de Linux leyendo `/proc/mdstat`, localmente y vía SSH.

**Plataforma:** Linux *(monitorización local)*. El módulo puede ejecutarse en cualquier plataforma como cliente SSH hacia servidores remotos Linux.

> **Windows / macOS:** el campo `local` aparece como "No compatible" en la UI y no puede activarse. La monitorización remota vía SSH funciona en todas las plataformas.

**Config:**
```json
{
    "raid": {
        "enabled": true,
        "local": true,
        "threads": 5,
        "timeout": 30,
        "list": {
            "NAS": {
                "enabled": true,
                "label": "NAS principal",
                "host": "192.168.1.30",
                "port": 22,
                "user": "root",
                "key_file": "/home/usuario/.ssh/id_rsa"
            },
            "Servidor2": {
                "enabled": true,
                "host": "192.168.1.31",
                "user": "admin",
                "password": "secret"
            }
        }
    }
}
```

> **Compatibilidad:** la clave legacy `remote` sigue funcionando; la UI usa `list` para nuevos ítems.

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `local` | bool | `true` | Monitorizar RAID local vía `/proc/mdstat`. **Solo Linux** — aparece como "No compatible" en la UI en otras plataformas |
| `threads` | int | 5 | Servidores remotos a comprobar en paralelo |
| `timeout` | int | 30 | Timeout de conexión SSH en segundos |
| `list.*.enabled` | bool | `true` | Habilitar monitorización de este servidor remoto |
| `list.*.label` | string | `""` | Nombre mostrado en la UI y en notificaciones. Si está vacío, se usa la clave del ítem |
| `list.*.host` | string | `""` | IP/hostname del servidor remoto. Si está vacío, se usa la clave del ítem |
| `list.*.port` | int | `0` | Puerto SSH. `0` aplica el puerto por defecto (22). La UI muestra `22` como placeholder |
| `list.*.user` | string | `""` | Usuario SSH |
| `list.*.password` | string | `""` | Contraseña SSH. Ignorada si se especifica `key_file` |
| `list.*.key_file` | string | `""` | Ruta a la clave privada SSH. Tiene prioridad sobre la contraseña |

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

## ⚙️ service_status — Estado de Servicios del Sistema

Comprueba si los servicios del sistema están en ejecución. Soporta **auto-remediación** (inicio/detención automática) y permite definir el **estado esperado** por servicio (`running` o `stopped`).

**Plataforma:** Linux (systemd / OpenRC / SysV init), Windows 🌐

El init system de Linux se detecta automáticamente al arrancar:

| Init system | Criterio de detección |
| ----------- | --------------------- |
| **systemd** | Existe `/run/systemd/system` |
| **OpenRC** | `rc-service` disponible en `PATH` |
| **SysV** | Fallback cuando ninguno de los anteriores aplica |

**Config:**
```json
{
    "service_status": {
        "enabled": true,
        "threads": 5,
        "list": {
            "nginx": {
                "enabled": true,
                "service": "",
                "expected": "running",
                "remediation": true
            },
            "docker": {
                "enabled": true,
                "expected": "running",
                "remediation": false
            },
            "bluetooth": {
                "enabled": true,
                "expected": "stopped",
                "remediation": true
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `list.*.enabled` | bool | `true` | Habilitar monitorización de este servicio |
| `list.*.service` | string | `""` | Nombre del servicio en el sistema. Si está vacío, se usa la clave del ítem |
| `list.*.expected` | string | `"running"` | Estado esperado: `running` o `stopped`. Se genera alerta cuando el estado real difiere |
| `list.*.remediation` | bool | `false` | Si `true`, ejecuta start/stop automáticamente para restaurar el estado esperado |

> **Descubrimiento:** la UI web incluye un botón para listar automáticamente los servicios del sistema e incorporarlos a la configuración con un solo clic.

**Flujo:**
```
Detecta init system al arrancar (una sola vez)
│
├── Windows  → psutil.win_service_get(<servicio>)
├── systemd  → systemctl status <servicio>  (parsea "Active:")
├── OpenRC   → rc-service <servicio> status  (exit code: 0=running)
└── SysV     → service <servicio> status     (exit code: 0=running)

Por cada servicio habilitado:
   estado_real vs. expected
   ├── Coincide  → OK ✅
   └── Difiere   → FALLO ⚠️
       └── Si remediation=true:
           ├── start / stop según expected
           ├── Re-check del estado
           └── Notifica resultado de la recuperación
```

**Comandos de remediación por plataforma:**

| Plataforma | start | stop |
| ---------- | ----- | ---- |
| Windows | `sc start <n>` | `sc stop <n>` |
| systemd | `systemctl start <n>` | `systemctl stop <n>` |
| OpenRC | `rc-service <n> start` | `rc-service <n> stop` |
| SysV | `service <n> start` | `service <n> stop` |

---

## 🌡️ temperature — Sensores Térmicos

Monitoriza sensores de temperatura del sistema usando `psutil.sensors_temperatures()`.

**Plataforma:** Linux, macOS

> **Windows no soportado:** `psutil` no expone sensores térmicos en Windows. El módulo aparece deshabilitado en la UI y no permite activarlo ni añadir sensores manualmente.

**Config:**
```json
{
    "temperature": {
        "enabled": true,
        "alert": 80,
        "list": {
            "coretemp_0": {
                "enabled": true,
                "label": "CPU Package",
                "alert": 90
            },
            "acpitz_0": {
                "enabled": false
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `alert` | float | 80 | Temperatura máxima global (°C), aplicada a todos los sensores sin umbral propio |
| `list.*.enabled` | bool | `true` | Habilitar monitorización de este sensor |
| `list.*.label` | string | etiqueta psutil o nombre del chip | Nombre mostrado en notificaciones |
| `list.*.alert` | float | global | Umbral específico por sensor, anula el umbral global |

> **Claves de sensor:** el formato es `{chip}_{índice}`, por ejemplo `coretemp_0`, `coretemp_1`, `acpitz_0`. El chip y el índice provienen de `psutil.sensors_temperatures()`. Los nombres exactos disponibles dependen del hardware y el sistema operativo.
> **Descubrimiento:** la UI web incluye un botón para listar automáticamente los sensores disponibles e incorporarlos a la configuración con un solo clic. Muestra el nombre del chip, la etiqueta del sensor y la temperatura actual.

**Flujo:** `psutil.sensors_temperatures()` → itera chips y lecturas → clave `{chip}_{idx}` → compara temperatura actual con el umbral → alerta si supera el umbral.

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
                "label": "Portal principal",
                "url": "https://example.com",
                "code": 200,
                "timeout": 15
            },
            "https://api.example.com": true
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `threads` | int | 5 | URLs a comprobar en paralelo |
| `list.*.enabled` | bool | `true` | Habilitar monitorización de esta URL |
| `list.*.label` | string | `""` | Nombre mostrado en la UI. Si está vacío, se usa la clave del ítem |
| `list.*.url` | string | clave | URL a comprobar (HTTP o HTTPS). Si está vacío, se usa la clave del ítem |
| `list.*.code` | int | 200 | Código HTTP de respuesta esperado. Se alerta cuando el código real difiere |
| `list.*.timeout` | int | 15 | Timeout de la petición en segundos |

**Flujo:** `urllib.request` (stdlib de Python) → compara el código HTTP real con el esperado. Soporta HTTP y HTTPS sin dependencias externas.
