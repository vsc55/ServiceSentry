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
        "other_data": { ... }       # Datos extra almacenados en check_state
    }
}
```

---

## 🖥️ cpu — Uso de CPU

Monitoriza el porcentaje de uso de CPU. En local usa `psutil`; **host-aware**: un
ítem puede vincularse a un host del registro y la CPU se mide por SSH con el
comando propio de cada SO (`wmic`/`top`…).

**Plataforma:** Linux, Windows, macOS 🌐

**Config:**
```json
{
    "cpu": {
        "enabled": true,
        "alert": 85,
        "interval": 1.0,
        "list": {
            "local": { "enabled": true, "label": "Servidor local" }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `alert` | int | 85 | % de uso de CPU para alertar (umbral global) |
| `interval` | float | 1.0 | Segundos de muestreo para `psutil.cpu_percent()` (0.1–10.0) |
| `list.*.label` | string | `""` | Nombre visible del ítem |
| `list.*.alert` | int | 0 | Umbral por ítem; `0` (en blanco) hereda el `alert` global |

**Flujo:** local → `psutil.cpu_percent(interval=interval)`; host vinculado → comando
remoto por SSH → compara con el umbral → alerta si supera `alert`.

---

## 🔒 ssl_cert — Expiración de Certificados SSL/TLS

Comprueba los días hasta la expiración de certificados SSL/TLS de servidores remotos. Funciona con cualquier servidor HTTPS/TLS sin dependencias externas.

**Plataforma:** Linux, Windows, macOS 🌐

**Config:**
```json
{
    "ssl_cert": {
        "enabled": true,
        "threads": 5,
        "warning_days": 30,
        "timeout": 10,
        "list": {
            "mi_web": {
                "enabled": true,
                "host": "example.com",
                "port": 443,
                "warning_days": 0,
                "timeout": 0
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `warning_days` | int | 30 | Días antes de vencimiento para alertar (umbral global) |
| `timeout` | int | 10 | Timeout de conexión TCP en segundos (global) |
| `list.*.host` | string | `""` | Hostname del servidor (o se hereda del host vinculado). Si está vacío, se usa la clave del ítem |
| `list.*.server_name` | string | `""` | Nombre SNI a presentar en el handshake (vacío = usa `host`); útil para vhosts con varios certificados |
| `list.*.port` | int | 0 | Puerto TLS. `0` aplica el puerto estándar 443. La UI muestra `443` como placeholder |
| `list.*.verify` | bool | true | Verificar la cadena del certificado; `false` permite autofirmados (solo comprueba caducidad) |
| `list.*.warning_days` | int | 0 | Umbral de alerta por host. `0` usa el valor global |
| `list.*.timeout` | int | 0 | Timeout por host en segundos. `0` usa el valor global |

Es **host-aware**: el ítem puede vincularse a un host del registro y heredar la dirección (`__host_profile__`).

**Flujo:** `ssl.create_default_context()` + `socket.create_connection()` → `ssock.getpeercert()` → `ssl.cert_time_to_seconds(cert['notAfter'])` → calcula días restantes → alerta si `days_left <= warning_days`.

---

## ⚙️ process — Procesos en Ejecución

Verifica que los procesos del sistema están en ejecución comprobando el número mínimo de instancias activas.

**Plataforma:** Linux, Windows, macOS 🌐

**Config:**
```json
{
    "process": {
        "enabled": true,
        "threads": 5,
        "list": {
            "nginx": {
                "enabled": true,
                "process": "nginx",
                "min_count": 1
            },
            "python3": {
                "enabled": true,
                "min_count": 2
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `min_count` | int | 1 | Mínimo de instancias por defecto a nivel de módulo |
| `list.*.process` | string | clave | Nombre del proceso a buscar (insensible a mayúsculas). Si está vacío, se usa la clave del ítem |
| `list.*.min_count` | int | 0 | Mínimo de instancias por ítem. `0` (en blanco) hereda el global del módulo |

**Discover:** El botón "Discover" en la cabecera de la colección y el botón inline junto al campo `process` enumeran todos los procesos activos del sistema ordenados alfabéticamente, con el número de instancias en ejecución. Al seleccionar uno se rellena automáticamente el campo y la clave del ítem.

**Flujo:** `psutil.process_iter(['name'])` → cuenta instancias con nombre coincidente (case-insensitive) → alerta si `count < min_count`.

---

## 🌐 dns — Resolución DNS

Comprueba que los hostnames resuelven correctamente para todos los tipos de registro DNS (A, AAAA, CNAME, MX, TXT, NS, PTR, SOA), con soporte opcional para validar que el valor resuelto contiene un texto esperado.

**Plataforma:** Linux, Windows, macOS 🌐

**Dependencia opcional:** `dnspython>=2.3` para tipos distintos de A/AAAA. Si no está instalado, las consultas A/AAAA siguen funcionando; otros tipos devolverán `status=False` con mensaje de error.

**Config:**
```json
{
    "dns": {
        "enabled": true,
        "threads": 5,
        "timeout": 5,
        "nameserver": "",
        "list": {
            "google-a": {
                "enabled": true,
                "host": "google.com",
                "record_type": "A",
                "expected": "",
                "nameserver": "",
                "timeout": 0
            },
            "mi_mail": {
                "enabled": true,
                "host": "example.com",
                "record_type": "MX",
                "expected": "mail.example.com"
            },
            "spf": {
                "enabled": true,
                "host": "example.com",
                "record_type": "TXT",
                "expected": "v=spf1"
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `timeout` | int | 5 | Timeout de resolución DNS en segundos (global) |
| `nameserver` | string | `""` | Servidor DNS por defecto (IP o hostname) al que dirigir las consultas. Vacío = resolver del sistema |
| `list.*.host` | string | clave | Hostname a resolver. Si está vacío, se usa la clave del ítem |
| `list.*.record_type` | string | `"A"` | Tipo de registro: `A`, `AAAA`, `CNAME`, `MX`, `TXT`, `NS`, `PTR`, `SOA` |
| `list.*.expected` | string | `""` | Valor que debe aparecer (subcadena, insensible a mayúsculas) en al menos un registro. Vacío = solo comprueba que resuelve |
| `list.*.nameserver` | string | `""` | Servidor DNS por host al que dirigir la consulta. Vacío usa el valor del módulo o el resolver del sistema |
| `list.*.timeout` | int | 0 | Timeout por host. `0` usa el valor global |

**Flujo:** A/AAAA → `socket.getaddrinfo()` con `AF_INET`/`AF_INET6`; demás tipos → `dns.resolver.resolve()` (dnspython). En ambos casos los resultados se normalizan a lista de strings y se comprueba `expected` como subcadena insensible a mayúsculas.

---

## 🕐 ntp — Sincronización de Tiempo NTP

Comprueba el offset de tiempo consultando servidores NTP vía UDP. Implementación con stdlib de Python sin dependencias externas.

**Plataforma:** Linux, Windows, macOS 🌐

**Config:**
```json
{
    "ntp": {
        "enabled": true,
        "threads": 3,
        "max_offset": 5.0,
        "timeout": 5,
        "list": {
            "pool": {
                "enabled": true,
                "server": "pool.ntp.org",
                "max_offset": 0.0,
                "timeout": 0
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `max_offset` | float | 5.0 | Offset máximo en segundos antes de alertar (global) |
| `timeout` | float | 5 | Timeout UDP en segundos (global) |
| `list.*.server` | string | `"pool.ntp.org"` | Hostname del servidor NTP |
| `list.*.port` | int | 0 | Puerto UDP NTP. `0` aplica el puerto estándar 123. La UI muestra `123` como placeholder |
| `list.*.max_offset` | float | 0.0 | Offset máximo por servidor. `0.0` usa el valor global |
| `list.*.timeout` | int | 0 | Timeout por servidor. `0` usa el valor global |

**Flujo:** Paquete UDP NTP `b'\x1b' + 47*b'\x00'` (LI=0, VN=3, Mode=3) → lee T2 (bytes 32-39) y T3 (bytes 40-47) → offset = `|((T2-T1)+(T3-T4))/2|` → alerta si `offset >= max_offset`.

---

## 🔋 ups — Estado SAI / UPS (NUT)

Consulta el estado de SAIs/UPS a través del protocolo NUT (Network UPS Tools) por TCP. Soporta autenticación opcional.

**Plataforma:** Linux, Windows, macOS 🌐

**Config:**
```json
{
    "ups": {
        "enabled": true,
        "threads": 3,
        "timeout": 10,
        "list": {
            "ups_principal": {
                "enabled": true,
                "host": "192.168.1.5",
                "port": 3493,
                "ups_name": "ups",
                "user": "",
                "password": "",
                "timeout": 0
            }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `timeout` | int | 10 | Timeout de conexión TCP en segundos (global) |
| `alert_battery` | int | 20 | Umbral global: alerta si la carga de batería (%) baja de este valor (0 = desactivado) |
| `alert_runtime` | int | 10 | Umbral global: alerta si la autonomía estimada (minutos) baja de este valor (0 = desactivado) |
| `alert_load` | int | 0 | Umbral global: alerta si la carga del UPS (%) supera este valor (0 = desactivado) |
| `list.*.host` | string | `""` | IP/hostname del demonio NUT (`upsd`) (o se hereda del host vinculado) |
| `list.*.port` | int | 0 | Puerto TCP de `upsd`. `0` aplica el puerto estándar 3493. La UI muestra `3493` como placeholder |
| `list.*.ups_name` | string | `"ups"` | Nombre del UPS en `upsd` |
| `list.*.user` | string | `""` | Usuario NUT (opcional) |
| `list.*.password` | string | `""` | Contraseña NUT (**cifrada en disco** con `enc:`) |
| `list.*.timeout` | int | 0 | Timeout por host. `0` usa el valor global |
| `list.*.alert_on_battery` | bool | true | Alertar cuando el UPS pasa a batería (`OB`) |
| `list.*.alert_battery` / `alert_runtime` / `alert_load` | int | 0 | Umbrales por ítem; `0` (en blanco) hereda el global del módulo |

Es **host-aware** (el ítem puede vincularse a un host del registro).

**Estados:** `OL` = en línea ✅, `OB` = funcionando con batería ⚠️, `LB` = batería baja ⚠️.

**Flujo:** Conexión TCP al puerto 3493 → `USERNAME`/`PASSWORD` si hay credenciales → `LIST VAR <ups_name>` → parsea líneas `VAR` → comprueba `ups.status`.

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
| `alert` | int | 50 | Temperatura máxima (°C) antes de alertar (umbral global) |
| `timeout` | int | 5 | Timeout de conexión TCP en segundos |
| `threads` | int | 5 | Hilos en paralelo para consultar hosts |
| `list.*.label` | string | `""` | Nombre visible del ítem |
| `list.*.port` | int | 0 | Puerto TCP del demonio hddtemp. `0` aplica el estándar 7634 (placeholder `7634`) |
| `list.*.exclude` | list | `[]` | Dispositivos a ignorar (ej: `"/dev/sdc"`) |
| `list.*.alert` | int | 0 | Umbral por ítem (°C); `0` (en blanco) hereda el global |

> La **dirección del host** no es un campo de `list`: el ítem se **vincula a un host**
> del registro y hereda la dirección vía `__host_profile__` (la `key` del item se usa
> como fallback). Ver [web_admin.md → Servers](web_admin.md#servers-registro-de-hosts).

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
        "timeout": 10,
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
                "db": "myapp",
                "timeout": 0
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
| `timeout` | int | `0` | Timeout de conexión en segundos. `0` usa el valor global del módulo (10 por defecto). La UI muestra el valor del módulo como placeholder |
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
| `ssh_verify_host` | bool | `false` | Si `true`, verifica la clave de host SSH contra `known_hosts` (`RejectPolicy`); si `false`, la acepta automáticamente (`AutoAddPolicy`). Configurable por seguridad. |

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

> **Modelo actual (host-aware):** en el `schema.json` vigente, cada ítem de `list`
> tiene solo `enabled` y `label`; la **conexión SSH** (host/puerto/usuario/clave) ya
> **no** son campos del ítem, sino que se heredan al **vincular el ítem a un host**
> del registro (`__host_profile__` + credenciales reutilizables). El ejemplo de
> arriba con `host`/`user`/`key_file` inline es el **formato legacy** (clave `remote`),
> que sigue leyéndose por compatibilidad. Ver [web_admin.md → Servers](web_admin.md#servers-registro-de-hosts).

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `local` | bool | `true` | Monitorizar RAID local vía `/proc/mdstat`. **Solo Linux** — aparece como "No compatible" en la UI en otras plataformas |
| `threads` | int | 5 | Servidores remotos a comprobar en paralelo |
| `timeout` | int | 30 | Timeout de conexión SSH en segundos |
| `mdstat_path` | string | `/proc/mdstat` | Ruta del fichero mdstat a leer |
| `list.*.enabled` | bool | `true` | Habilitar monitorización de este ítem |
| `list.*.label` | string | `""` | Nombre mostrado en la UI y en notificaciones. Si está vacío, se usa la clave del ítem |
| *(host SSH)* | — | — | Dirección/credenciales heredadas del **host vinculado** (no son campos de `list`); legacy: `host`/`port`/`user`/`password`/`key_file` inline |

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

## 📡 snmp — Monitorización SNMP

Consulta OIDs vía **SNMP v1 / v2c / v3** sobre uno o varios servidores, con
gestión y compilación de MIBs integrada. Requiere `pysnmp` (y `pysmi` para
compilar MIBs); ambos opcionales.

### Estructura de configuración

La config se organiza por **servidores**, y cada servidor tiene su propia
sub-colección de **checks** (OIDs a comprobar):

| Sección | Campo | Tipo | Descripción |
|---------|-------|------|-------------|
| `__module__` | `enabled` | bool | Activar el módulo |
| | `threads` | int | Hilos para checks en paralelo |
| | `mib_dirs` | str | Directorios adicionales de MIBs |
| `servers.*` | `enabled` | bool | Activar el servidor |
| | `host` | str | Host/IP del agente SNMP |
| | `port` | int | Puerto (161 por defecto) |
| | `version` | str | `v1`, `v2c` o `v3` |
| | `community` | str | Community string (v1/v2c) |
| | `timeout` / `retries` | int | Timeout y reintentos |
| | `snmpv3_username` | str | Usuario SNMPv3 |
| | `snmpv3_auth_key` | str | Clave de autenticación SNMPv3 *(secreto, cifrado)* |
| | `snmpv3_priv_key` | str | Clave de privacidad SNMPv3 *(secreto, cifrado)* |
| | `snmpv3_auth_protocol` | str | Protocolo auth (MD5/SHA…) |
| | `snmpv3_priv_protocol` | str | Protocolo priv (DES/AES…) |
| `servers.*.checks.*` | `enabled` | bool | Activar el check |
| | `oid` | str | OID a consultar (numérico o nombre MIB) |
| | `snmp_type` | str | Tipo del valor |
| | `operator` | str | Comparador: `any`, `contains`, `regex`, `eq`, `ne`, `gt`, `lt`, `gte`, `lte` |
| | `value` | str | Valor esperado para la comparación |
| | `alert` | bool | Si el check dispara alerta |

> Los campos `snmpv3_auth_key` y `snmpv3_priv_key` se declaran como secretos en
> el `schema.json` del módulo y el core los cifra automáticamente (descubrimiento
> schema-driven, ver [security.md](security.md)). El módulo es 100 % independiente
> del core.

### Gestión de MIBs

El módulo expone acciones de UI (vía `/api/v1/modules/watchfuls/snmp/<action>`) para
gestionar MIBs en `{var_dir}/snmp_mibs/`:

- **Descubrimiento** (`discover`) de OIDs disponibles caminando los subárboles
  mib-2 y enterprises (GETBULK en v2c/v3).
- **Compilación** de MIBs ASN.1 (`raw/`) a módulos Python (`compiled/`) con
  `pysmi`, en segundo plano con polling de progreso.
- **Índice de OIDs** persistido (`oid_index.json`) para descubrimiento rápido.
- **Subida** (`upload_mib`), **borrado** (`delete_mib`) e **importación desde
  URL** (`import_mib_from_url`).

**Seguridad:** los nombres de fichero MIB se validan con una allowlist
(`[A-Za-z0-9_.-]`) + confinamiento de path (`pathlib.resolve()`); las
importaciones por URL pasan por el guard SSRF `validate_external_url()`. Ver
[security.md](security.md) → *Path Traversal* y *SSRF*.

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
| `list.*.sensor` | string | `""` | Sensor a leer (`{chip}_{índice}`); vacío = usa la clave del ítem |
| `list.*.label` | string | etiqueta psutil o nombre del chip | Nombre mostrado en notificaciones |
| `list.*.alert` | float | `0` (hereda global) | Umbral específico por sensor; `0` (en blanco) usa el umbral global |

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
| `code` | int | 200 | Código HTTP esperado por defecto (global) |
| `alert` | int | 1 | Reintentos antes de alertar (global) |
| `timeout` | int | 15 | Timeout por defecto de la petición (global) |
| `list.*.enabled` | bool | `true` | Habilitar monitorización de esta URL |
| `list.*.label` | string | `""` | Nombre mostrado en la UI. Si está vacío, se usa la clave del ítem |
| `list.*.url` | string | clave | URL/host base. Si está vacío, se usa la clave del ítem (o el host vinculado) |
| `list.*.path` | string | `""` | Ruta a añadir a la URL base (p. ej. `/health`) |
| `list.*.scheme` | string | `https` | Esquema: `http` o `https` |
| `list.*.method` | string | `GET` | Método HTTP: `GET`, `HEAD` o `POST` |
| `list.*.verify_ssl` | bool | true | Verificar el certificado TLS |
| `list.*.code` | int | 0 | Código HTTP esperado por ítem; `0` (en blanco) hereda el global |
| `list.*.timeout` | int | 0 | Timeout por ítem; `0` hereda el global |
| `list.*.alert` | int | 0 | Reintentos por ítem; `0` hereda el global |
| `list.*.check_content` | bool | false | Además del código, exigir que el cuerpo contenga un texto |
| `list.*.content_contains` | string | `""` | Texto que debe aparecer en la respuesta (si `check_content`) |
| `list.*.auth_enabled` | bool | false | Autenticación HTTP básica |
| `list.*.auth_user` | string | `""` | Usuario para auth básica |
| `list.*.auth_password` | string | `""` | Contraseña para auth básica (**cifrada en disco**) |

Es **host-aware** (el ítem puede vincularse a un host del registro; admite `__credential__` `web_auth` reutilizable).

**Flujo:** `urllib.request` (stdlib de Python) → compara el código HTTP real con el esperado (y opcionalmente el contenido). Soporta HTTP y HTTPS sin dependencias externas.

---

## 🖥️ proxmox — Proxmox VE (REST API)

Monitoriza un cluster **Proxmox VE** vía su REST API: **quorum** del cluster, **Ceph**,
**nodos** (incluye modo mantenimiento), **red** y **actualizaciones** pendientes. Se
autentica con una credencial **`proxmox_auth`** reutilizable (API token o usuario/contraseña).

**Plataforma:** Multiplataforma 🌐 (HTTP a la API)

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `list.*.host` | string | `""` | Host/IP del nodo Proxmox (puede vincularse a un host del registro) |
| `list.*.port` | int | 8006 | Puerto de la API |
| `list.*.verify_ssl` | bool | false | Verificar el certificado TLS |
| `list.*.auth_method` | string | `token` | `token` (API token) o `password` (usuario/contraseña) |
| `list.*.token_id` / `token_secret` | string | `""` | Credenciales de API token (si `auth_method=token`) |
| `list.*.username` / `password` | string | `""` | Usuario/contraseña (si `auth_method=password`; **cifrada**) |
| `list.*.check_cluster` | bool | true | Comprobar quorum del cluster |
| `list.*.check_nodes` | bool | true | Estado de los nodos (online/mantenimiento) |
| `list.*.check_ceph` | bool | false | Salud de Ceph |
| `list.*.check_network` | bool | false | Estado de red de los nodos |
| `list.*.check_updates` | bool | true | Actualizaciones pendientes (umbral `updates_threshold`) |
| `list.*.check_storage` | bool | false | Uso de almacenamiento (umbral `storage_threshold` %) |
| `list.*.check_permissions` | bool | true | Verificar que el token tiene permisos suficientes |
| `list.*.timeout` / `alert` | int | 0 | Timeout / reintentos por ítem (`0` hereda el global) |

Admite provisioning asistido de la credencial vía SSH (`provision_token`).

**Flujo:** login (token o ticket) → consultas a `/cluster`, `/nodes`, `/ceph`… → evalúa cada check activado → alerta si alguno falla o supera su umbral.

---

## 🌐 keepalived — VIP VRRP (alta disponibilidad)

Monitoriza un cluster **keepalived (VRRP)**: estado del **servicio** por nodo, **qué nodo
tiene la VIP**, detección de **split-brain** y **prioridad** (weight). Es un módulo
**multi-bind** (multi-nodo): un ítem = un cluster, con varios nodos (cada uno un host del
registro) y su peso VRRP.

**Plataforma:** Linux (los nodos se consultan por SSH)

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `list.*.vip` | string | `""` | IP virtual (VIP) a vigilar |
| `list.*.router_id` | int | 0 | `virtual_router_id` VRRP del grupo |
| `list.*.vip_host_uid` | string | `""` | Host desde el que verificar quién tiene la VIP |
| `list.*.__member_field__` | int | 100 | Prioridad (weight) VRRP declarada por nodo miembro |
| `list.*.check_service` | bool | true | Servicio keepalived activo en cada nodo |
| `list.*.check_vip` | bool | true | Exactamente un nodo tiene la VIP (detecta split-brain) |
| `list.*.check_priority` | bool | false | La prioridad efectiva coincide con la declarada |
| `list.*.timeout` / `alert` | int | 0 | Timeout / reintentos por ítem (`0` hereda el global) |

**Flujo:** por cada nodo (SSH) comprueba el servicio y la posesión de la VIP → agrega el
estado del cluster → alerta ante servicio caído, 0 o >1 titulares de la VIP (split-brain)
o prioridad inesperada.

---

## ☁️ m365 — Microsoft 365 (Microsoft Graph)

Monitoriza **Microsoft 365** vía la **Microsoft Graph API** (app-only): almacenamiento de
**SharePoint** por sitio (cuota del drive: % usado / espacio libre) y **tendencia de uso**
del tenant. Se autentica con una credencial **`m365_app`** (tenant/client/secret), que el
**asistente de Entra ID** puede aprovisionar (ver [sso-entra.md](sso-entra.md) para el motor
de provisioning compartido).

**Plataforma:** Multiplataforma 🌐 (HTTP a Graph)

| Clave | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `tenant_id` / `client_id` / `client_secret` | string | `""` | Credenciales de la app (o una credencial `m365_app` reutilizable) |
| `list.*.check_site` | bool | true | Medir el almacenamiento de un sitio de SharePoint |
| `list.*.site` | string | `""` | Sitio a medir (vacío = raíz/tenant); botón **discover** (`list_sites`) para elegirlo |
| `usage_pct` | int | 90 | % de cuota usada para alertar (nivel Defaults del módulo; heredado por ítems) |
| `free_min` + `free_unit` | int / string | 0 / `GB` | Alertar si el espacio libre baja de X |
| `list.*.check_tenant_usage` | bool | false | Comprobar la tendencia de uso del tenant |
| `tenant_max` + `tenant_unit` | int / string | 0 / `TB` | Umbral de uso del tenant |
| `list.*.timeout` / `alert` | int | 0 | Timeout / reintentos por ítem (`0` hereda el global) |

**Flujo:** token *client-credentials* (`.default` de Graph) → consultas a
`/sites/{id}/drive` y a los informes de uso → compara con `usage_pct` / `free_min` /
`tenant_max` → alerta al superarlos.
