# Referencia de Módulos (Watchfuls)

Referencia de configuración y comportamiento de todos los módulos de monitorización incluidos.

Cada módulo es un **package** (carpeta con `__init__.py`) en `watchfuls/`.
Consulta [caso-guia-watchful.md](caso-guia-watchful.md) para crear el tuyo propio.

> **Módulos de sistema host-aware.** Los módulos que miden recursos del sistema
> (`cpu`, `ram_swap`, `temperature`, `filesystemusage`, `process`, `service_status`
> y `raid`) **no** usan `psutil` en el `check()`: ejecutan comandos de SO mediante
> `ModuleBase.host_exec`, **en local** o **por SSH** según el host vinculado al ítem
> (perfil `__host_profile__` de tipo `ssh`). Cada uno elige el comando propio de
> cada SO (Linux/Windows/FreeBSD) y parsea la salida en Python. `psutil` solo
> se usa, cuando aplica, en el `discover()` **local** (autocompletado de la UI).

---

## Estructura de Package del Módulo

Todos los módulos siguen esta estructura:

```
watchfuls/
└── mi_modulo/
    ├── __init__.py        # Implementación
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
        "message": "texto",         # Texto de notificación (TEXTO PLANO, multicanal)
        "send": True / False,       # Si se emite notificación por los canales activos
        "severity": "warning",      # Severidad de un no-OK: 'warning' (ámbar) → kind warn
        "name": "PVE04",            # Nombre amigable del ítem (columna Item del digest)
        "other_data": { ... }       # Datos extra almacenados en check_state
    }
}
```

> **El modelo no es binario OK/DOWN.** Un `status=False` con `severity='warning'` se
> enruta como kind **`warn`** (ámbar, umbral blando), no `down` (rojo). La notificación
> es **multicanal** (Telegram/Email/Webhook/Teams): el `message` viaja en **texto plano**
> y el Markdown (`*negrita*`) se **elimina** al agrupar por ciclo. Ver
> [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning) y
> [→ notificación agrupada por ciclo](explica-notificaciones.md#el-monitor-notificación-agrupada-por-ciclo-monitornotifier).

---

## 🖥️ cpu — Uso de CPU

Monitoriza el porcentaje de uso de CPU. Es **host-aware**: cada ítem se vincula a un
host del registro y la CPU se mide vía `ModuleBase.host_exec` **en local o por SSH**
con el comando propio de cada SO (nunca `psutil` en el check).

**Plataforma:** Linux, Windows, FreeBSD 🌐

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
| `interval` | float | 1.0 | Segundos de espera entre las dos muestras del delta (Linux/FreeBSD); la espera ocurre en Python (0.1–10.0) |
| `list.*.label` | string | `""` | Nombre visible del ítem |
| `list.*.alert` | int | 0 | Umbral por ítem; `0` (en blanco) hereda el `alert` global |

> La clave de cada ítem de `list` (p. ej. `local`) identifica el ítem; la CPU se mide
> en el **host vinculado** (`__host_profile__` de tipo `ssh`; sin vínculo = local).

**Flujo:** `ModuleBase.host_exec(item, cmd)` (local o SSH) ejecuta el comando de CPU
propio del SO (`_cpu_cmd`): `cat /proc/stat` en Linux, `sysctl -n kern.cp_time` en
FreeBSD, `wmic cpu get loadpercentage /value` en Windows. En
Linux/FreeBSD se toman **dos muestras** con la espera de `interval` en Python (el delta
de ocupación); se parsea el uso en Python → compara con el umbral → alerta si supera
`alert`. Un fallo duro (host inalcanzable, salida no parseable) se reporta como `down`.

> **Severidad:** superar el umbral emite `severity='warning'` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## 🔒 ssl_cert — Expiración de Certificados SSL/TLS

Comprueba los días hasta la expiración de certificados SSL/TLS de servidores remotos. Funciona con cualquier servidor HTTPS/TLS.

**Plataforma:** Linux, Windows 🌐

**Dependencia:** `cryptography` (parsea el certificado DER; permite leer la caducidad incluso en modo inseguro/sin verificación, donde `getpeercert()` no devuelve el dict).

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

**Flujo:** `ssl.create_default_context()` + `socket.create_connection()` → `ssock.getpeercert(binary_form=True)` (DER) → `cryptography.x509.load_der_x509_certificate(der)` → lee `not_valid_after` → calcula días restantes → alerta si `days_left <= warning_days`.

> **Severidad:** `days_left > warning_days` → OK; *cerca de caducar* (`0 < days_left <= warning_days`) emite `severity='warning'` (ámbar, kind `warn`); **certificado ya caducado (`days_left <= 0`) o handshake fallido** es `down` (rojo). Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## ⚙️ process — Procesos en Ejecución

Verifica que los procesos del sistema están en ejecución comprobando el número mínimo de instancias activas. Es **host-aware**: cada ítem se vincula a un host del registro y la lista de procesos se lee vía `ModuleBase.host_exec` en local o por SSH.

**Plataforma:** Linux, Windows, FreeBSD 🌐

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

**Discover:** El botón "Discover" en la cabecera de la colección y el botón inline junto al campo `process` enumeran todos los procesos activos del sistema ordenados alfabéticamente, con el número de instancias en ejecución. Al seleccionar uno se rellena automáticamente el campo y la clave del ítem. El descubrimiento usa `psutil.process_iter(['name'])` en el host **local**, o el comando por SSH para un host remoto.

**Flujo:** `ModuleBase.host_exec(item, cmd)` ejecuta el listado de procesos del SO (`ps -A -o comm=` en Unix, `tasklist /FO CSV /NH` en Windows) → cuenta instancias con nombre coincidente (case-insensitive) → alerta si `count < min_count`. `psutil` **no** se usa en el check, solo en `discover()` local.

---

## 🌐 dns — Resolución DNS

Comprueba que los hostnames resuelven correctamente para todos los tipos de registro DNS (A, AAAA, CNAME, MX, TXT, NS, PTR, SOA), con soporte opcional para validar que el valor resuelto contiene un texto esperado.

**Plataforma:** Linux, Windows 🌐

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

**Plataforma:** Linux, Windows 🌐

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

> **Severidad:** superar el offset máximo emite `warning` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## 🔋 ups — Estado SAI / UPS (NUT)

Consulta el estado de SAIs/UPS a través del protocolo NUT (Network UPS Tools) por TCP. Soporta autenticación opcional.

**Plataforma:** Linux, Windows 🌐

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

Monitoriza el porcentaje de uso de particiones. Es **host-aware**: cada ítem se vincula a un host del registro y el uso se mide vía `ModuleBase.host_exec` en local o por SSH.

**Plataforma:** Linux, Windows, FreeBSD 🌐

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

> **Descubrimiento:** la UI web incluye un botón para listar automáticamente las particiones montadas e incorporarlas a la configuración con un solo clic. Muestra dispositivo, tipo de filesystem y porcentaje de uso actual. En un host **local** usa `psutil.disk_partitions()`/`disk_usage()` (ignorando tipos de filesystem irrelevantes: squashfs, tmpfs, devtmpfs, overlay, etc.); en un host remoto usa el comando por SSH.

> **Formato legacy:** el valor de un ítem puede ser directamente un entero (`"/": 90`) — se interpreta como umbral de alerta para esa partición. La UI lo promueve automáticamente al formato dict al renderizarlo.

**Flujo:** `ModuleBase.host_exec(item, cmd)` ejecuta `df -P -k` en Unix o `wmic logicaldisk get DeviceID,FreeSpace,Size /format:value` en Windows → parsea el % de uso de la partición → compara con el umbral. `psutil` **no** se usa en el check, solo en `discover()` local. Un fallo duro (`df` inalcanzable, punto de montaje inexistente) se reporta como `down`.

> **Severidad:** superar el umbral emite `severity='warning'` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## 🌡️ hddtemp — Temperatura de Discos

Consulta el demonio hddtemp por socket TCP para obtener temperaturas de disco. Al conectarse a un host remoto, es compatible con cualquier plataforma cliente (Linux, Windows).

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
> como fallback). Ver [explica-web-admin.md → Servers](explica-web-admin.md#servers-registro-de-hosts).

**Flujo:** `socket.create_connection(host, port)` → lee datos → parsea formato `|dev|model|temp|unit|` → compara con el umbral.

> **Severidad:** superar el umbral de temperatura emite `warning` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## 🗄️ datastore — Conectividad de Bases de Datos

Verifica que los servidores de bases de datos son accesibles y responden correctamente. Soporta múltiples motores, modos de conexión TCP, socket Unix y túnel SSH.

**Plataforma:** Linux / Windows 🌐

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

> **Severidad:** los avisos de umbral blando (p. ej. salud degradada) emiten `warning` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## 🏓 ping — Disponibilidad de Hosts

Comprueba si los hosts son accesibles mediante ping ICMP.

**Plataforma:** Linux / Windows 🌐 (con `pythonping`; el fallback raw socket requiere root o `CAP_NET_RAW`)

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

> **Windows:** el campo `local` aparece como "No compatible" en la UI y no puede activarse. La monitorización remota vía SSH funciona en todas las plataformas.

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
> que sigue leyéndose por compatibilidad. Ver [explica-web-admin.md → Servers](explica-web-admin.md#servers-registro-de-hosts).

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

Monitoriza el porcentaje de uso de RAM y SWAP. Es **host-aware**: cada ítem se vincula a un host del registro y la memoria se mide vía `ModuleBase.host_exec` en local o por SSH (nunca `psutil` en el check).

**Plataforma:** Linux, Windows, FreeBSD 🌐

**Config:**
```json
{
    "ram_swap": {
        "enabled": true,
        "alert_ram": 60,
        "alert_swap": 60,
        "list": {
            "local": { "enabled": true, "label": "Servidor local" }
        }
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `alert_ram` | int | 60 | % de RAM usada para alertar (umbral del módulo) |
| `alert_swap` | int | 60 | % de SWAP usada para alertar (umbral del módulo) |
| `list.*.label` | string | `""` | Nombre visible del ítem |
| `list.*.alert_ram` / `alert_swap` | int | 0 | Umbral por ítem; `0` (en blanco) hereda el valor del módulo |

> Cada ítem de `list` se mide en el **host vinculado** (`__host_profile__` de tipo `ssh`; sin vínculo = local). El check emite **dos resultados** por ítem: `<clave>_ram` y `<clave>_swap` (el SWAP solo si el SO lo reporta).

**Flujo:** `ModuleBase.host_exec(item, cmd)` ejecuta el/los comando(s) de memoria propios del SO (`_MEM_CMDS`): `cat /proc/meminfo` en Linux, `wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value` en Windows, `sysctl`/`swapinfo -k` en FreeBSD → parsea el % de uso en Python → compara con los umbrales. Un SO no soportado o un fallo duro se reporta como problema (`down`/parse).

> **Severidad:** superar el umbral de RAM/SWAP emite `severity='warning'` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## ⚙️ service_status — Estado de Servicios del Sistema

Comprueba si los servicios del sistema están en ejecución. Es **host-aware** (el estado se lee en local o por SSH según el host vinculado vía `ModuleBase.host_exec`), soporta **auto-remediación** (inicio/detención automática) y permite definir el **estado esperado** por servicio (`running` o `stopped`).

**Plataforma:** Linux, Windows, FreeBSD 🌐

> **El check usa siempre `systemctl is-active` en Linux.** La detección del init
> system (`_detect_linux_init`: systemd si existe `/run/systemd/system`, OpenRC si
> `rc-service` está en el `PATH`, si no SysV) se usa **únicamente en `discover()`**
> (el listado de servicios para el autocompletado de la UI), **no** en el check de
> estado — este consulta directamente `systemctl is-active`.

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

> **Descubrimiento:** la UI web incluye un botón para listar automáticamente los servicios del sistema e incorporarlos a la configuración con un solo clic. El `discover()` sí ramifica según el init system detectado (systemd `list-units`, OpenRC `rc-status`, SysV `/etc/init.d`) o el SO del host remoto por SSH — a diferencia del check.

**Comando de estado por SO** (ejecutado vía `host_exec`, servicio *shell-quoted*):

| SO | Comando de estado |
| -- | ----------------- |
| Linux | `systemctl is-active <servicio>` |
| Windows | `sc query <servicio>` |
| FreeBSD | `service <servicio> status` |

**Flujo:**
```text
Por cada servicio habilitado (en el host vinculado, local o SSH):
   Ejecuta el comando de estado del SO vía host_exec  →  running/stopped
   estado_real vs. expected
   ├── Coincide  → OK ✅
   └── Difiere   → FALLO ⚠️
       └── Si remediation=true:
           ├── start / stop según expected (comando de acción del SO vía host_exec)
           ├── Re-check del estado
           └── Notifica el resultado de la recuperación
```

**Comandos de remediación por SO** (`{svc}` shell-quoted, `{action}` = start|stop):

| SO | start | stop |
| -- | ----- | ---- |
| Linux | `systemctl start <svc>` | `systemctl stop <svc>` |
| Windows | `sc start <svc>` | `sc stop <svc>` |
| FreeBSD | `service <svc> start` | `service <svc> stop` |

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
> schema-driven, ver [explica-seguridad.md](explica-seguridad.md)). El módulo es 100 % independiente
> del core.

### Perfiles de dispositivo (la matriz de OIDs)

Un agente SNMP contesta `1.3.6.1.4.1.2021.11.9.0` con un `7`. **No dice** que eso sea la CPU,
que el siete sea un porcentaje, ni que el número de al lado sea un contador de bytes que no
significa nada hasta derivarlo. Eso es un **perfil**: una lista de métricas que mapea cada OID a
una clave, una etiqueta, una unidad, un tipo y cómo se dibuja.

Los perfiles son **datos, no código** — ficheros JSON en `watchfuls/snmp/profiles/`:

```json
{
  "id": "if_generic",
  "label": {"en_EN": "Network interfaces", "es_ES": "Interfaces de red"},
  "match": {"sysobjectid_prefix": "1.3.6.1.4.1.8072"},
  "metrics": [
    {"key": "if_in", "walk": "1.3.6.1.2.1.2.2.1.10", "kind": "counter", "unit": "B/s",
     "width": 32, "index_label": "1.3.6.1.2.1.2.2.1.2", "chart": "line"}
  ]
}
```

| Campo | Qué es |
|---|---|
| `key` | Identificador de la métrica: acaba siendo el nombre del campo en el historial |
| `oid` / `walk` | Un valor suelto **o** una columna de una tabla indexada. Uno de los dos, nunca ambos |
| `kind` | `gauge` (el valor **es** la medida), `counter` (sólo significa algo como **diferencia**), `text` (no es una medida: nombre, modelo, número de serie). Un `text` viaja como **atributo** al lado de los números de su fila, nunca como serie — así que la regla de no medir un mismo valor dos veces no le aplica, y merece la pena capturar la identidad: no gasta ninguna gráfica y es lo que da contexto a lo que sí se mide |
| `unit` | La unidad en la que queda tras `scale` |
| `scale` | Multiplicador: centisegundos→segundos, KB→bytes, décimas de grado→grados |
| `width` | 32 o 64 bits del contador — **es lo que distingue una vuelta de un reinicio** |
| `max_rate` | Techo opcional: una tasa imposible para ese enlace se descarta |
| `index_label` | La columna que **nombra** cada fila de una tabla (sin ella, ocho interfaces son ocho números de índice, que no son el puerto del frontal) |
| `scale_by` | La columna que da el factor, **por fila**, cuando lo decide el aparato y no el perfil (el tamaño de bloque de un sistema de ficheros) |
| `group` | A qué **tabla** pertenece la métrica, para las tablas cuyas filas no tienen nombre: la identidad de una fila es su nombre, y sin él dos tablas caen a su índice SNMP — donde almacenamiento fila 3 y procesador fila 3 no son la misma fila |
| `chart` | `line`, `area`, `value` o `none` |
| `role` | Para los `text`: `name`, `model`, `location`… — lo que hace reconocible a la máquina. **Un papel por perfil**: la fila tiene una casilla por papel, así que dos textos que pidan `model` son el segundo pisando al primero sin decirlo |
| `match.sysobjectid_prefix` | **Quién fabricó** el aparato: qué aparatos reclama el perfil; gana el prefijo **más específico** |
| `match.probe` | **Qué sirve** el aparato: un OID que, si contesta, hace que el perfil aplique. Es el que importa para los genéricos — «¿implementa la HOST-RESOURCES-MIB?» no lo puede contestar un `sysObjectID`: un Synology, un Linux y un Windows la implementan y sus `sysObjectID` no tienen nada que ver |
| `match.supersedes` | Qué perfiles genéricos **desplaza** éste en los aparatos que reclama: un Synology contesta el sondeo de E/S de UCD y el suyo, y los dos miden los mismos discos |
| `includes` | Ids de **otras entradas** del catálogo en lugar de OIDs: eso es un **grupo** (más abajo). Una entrada lleva métricas, miembros, o las dos cosas; ninguna de las dos y no es una entrada |

**Los contadores mienten de dos formas opuestas.** Un valor nuevo menor que el anterior es una
**vuelta** del contador (uno de octetos de 32 bits se llena en ~34 s en un enlace de gigabit) o
un **reinicio** del aparato, y desde aquí son idénticos. Confundirlos no es un error de
redondeo: tratar un reinicio como una vuelta mete un pico de cuatro mil millones en un
intervalo, que reescala el eje y esconde detrás todos los valores reales de la pantalla. La
regla es el ancho: **32 bits → se asume vuelta** (pasa constantemente), **64 bits → se asume
reinicio y se descarta la muestra** (a un terabit tardaría 4,6 años en dar la vuelta). En ambos
casos se guarda la nueva referencia: perder un punto cuesta un punto; inventarlo cuesta la
gráfica.

Se envían **nueve** perfiles genéricos, todos de MIBs estándar para que funcionen sin saber
quién fabricó el aparato, y **disjuntos** entre sí (más `hr_system` —carga por procesador,
procesos y usuarios, el complemento de `hr_storage`—, los quince de Synology, el de los SAI de
APC, el de los switches de Linksys, el de RouterOS de MikroTik, los tres de Windows, y los
grupos de más abajo):

| Perfil | MIB | Qué mide |
|---|---|---|
| `sys_generic` | MIB-II | Nombre, descripción, ubicación, contacto, uptime |
| `if_generic` | IF-MIB | Tráfico, paquetes, errores y descartes por interfaz **en las dos direcciones** (columnas de 32 y 64 bits), más velocidad y estado administrativo |
| `ip_stats` | IP-MIB | Qué hizo la capa IP con los paquetes: entregados, reenviados, descartados, fragmentados. **En los dos anchos y para las dos familias** — los escalares de RFC 1213 son sólo IPv4 y de 32 bits (en una máquina con 700 GB movidos ya han dado la vuelta 167 veces, y el grupo viejo no tiene contador de octetos siquiera); la tabla propia de IP-MIB informa por familia y a 64 bits |
| `icmp_stats` | ICMP-MIB | Ecos, inalcanzables y TTL agotado, de entrada y de salida |
| `tcp_udp_stats` | TCP-MIB, UDP-MIB | Conexiones establecidas, retransmisiones, resets, datagramas a puertos cerrados |
| `ucd_linux` | UCD-SNMP-MIB | CPU, carga y memoria |
| `hr_storage` | HOST-RESOURCES-MIB | Uso y capacidad por volumen |
| `disk_io` | UCD-SNMP-MIB | Bytes y operaciones por segundo, por dispositivo de bloque |
| `lm_sensors` | LM-SENSORS-MIB | Temperaturas, ventiladores y voltajes, una fila por sonda |

Los contadores de interfaz dicen *cuánto* tráfico hubo; `ip_stats` dice *qué pasó* con él, y las
retransmisiones de `tcp_udp_stats` son el número que avisa de que un enlace va mal mucho antes
de que esté caído. Una instalación puede añadir los suyos o **sustituir uno
enviado reutilizando su `id`**, que es lo que se hace cuando una versión de firmware mueve un
OID y el arreglo no puede esperar a la siguiente versión de este producto.

#### Dónde se asocia un perfil

**En el aparato, no en la comprobación.** Cada servidor SNMP lleva un campo `device_profiles`:
lo que una máquina *es* no cambia porque alguien le añada un cuarto OID que vigilar. Y lleva
**varios**, no uno — un NAS es el genérico de MIB-II, más las interfaces, más sus discos —, que
es también la razón de que los perfiles enviados sean pequeños y componibles en lugar de un
monolito por modelo. El conjunto asignado *es* la clasificación: no hace falta una taxonomía de
tipos de aparato (y habría que mantenerla correcta para siempre).

El botón del campo abre el catálogo con las filas marcables, y el mismo catálogo se abre en modo
lectura desde la barra del módulo, al lado del navegador de MIBs. Se marca, no se teclea: un `id`
de perfil escrito de memoria es un aparato que no mide nada hasta que alguien nota la errata.

**Detectar** lee la identidad del aparato (`sysObjectID`, `sysDescr`) y luego pregunta lo que
**cada perfil dice que hay que preguntarle**: su `match.probe`. Los candidatos los declara el
catálogo, no el código — una lista de «los genéricos» escrita dentro de la acción se queda
caducada en cuanto alguien añade un perfil, que es exactamente lo que pasó con el de
almacenamiento. Propone y nunca asigna: un perfil equivocado no falla, mide números que parecen
buenos, y ése es justo el fallo que tiene que pasar por una persona. Un aparato que no contesta
se informa como inalcanzable y no como un aparato que ningún perfil reclama: en pantalla se leen
igual y piden acciones opuestas.

**Probar** (el botón de al lado) contesta la otra mitad, y es una pregunta que el panel no sabía
hacer. Una asignación se equivoca en **dos direcciones** y sólo una se veía: un perfil que nombra
un OID que el aparato no sirve deja una gráfica vacía, y alguien acaba viéndolo; un aparato que
sirve algo que ningún perfil asignado nombra es **invisible** — no falta nada en ninguna
pantalla, porque nunca nadie dijo que pudiera estar. Así que la prueba lee las dos:

- **lo que la asignación recoge**, métrica a métrica, con **lo que dijo el aparato al lado de lo
  que significa**: `405` y `40,5 °C`. Una escala equivocada por diez enseña una temperatura
  plausible, y el crudo es lo único que la delata. Un contador trae su total y ningún valor,
  porque un contador *es* la diferencia entre dos lecturas y aquí sólo hay una. Se lee con
  `sampler.read_metric`, la misma función con la que muestrea el planificador: lo que enseña la
  pantalla es lo que se va a registrar, y no puede derivar en otra lectura distinta;
- **lo que el aparato manda y nadie lee**. Eso no se deduce del catálogo — es un hecho sobre la
  caja —, así que se recorre el aparato y se le resta todo lo que la asignación ya lee. Sale
  agrupado **por el objeto**, con el nombre que le den los MIB compilados: cuarenta y ocho líneas
  diciendo `…2.2.1.16.<n>` son una frase repetida cuarenta y ocho veces, y una sola que diga
  `ifOutOctets (IF-MIB) × 48` con un valor de ejemplo es la que se puede leer.

La prueba **cuenta lo que va haciendo**: corre en segundo plano y el diálogo la sondea,
dibujando seis pasos con su contador — conectar, resolver los perfiles asignados, **preguntar
cuáles sirve** el dispositivo (su `match.probe`), leer sus métricas, **recorrer el árbol SNMP
entero** y restar lo que ya se captura. Cada transición va también al log del servidor, y la
consola del navegador recibe lo mismo más la respuesta completa en dos tablas ordenables. Es
una pantalla de diagnóstico: poder leerla por los dos extremos es justo de lo que va.

El recorrido va **por ramas y con reparto**: el árbol estándar (`1.3.6.1.2.1`) y el del
fabricante (`1.3.6.1.4.1`) tienen cada uno su parte, como suelo y no como cupo — lo que una no
gasta lo heredan las siguientes. Un bote único se lo come mib-2: en un Synology de verdad los
tres mil OIDs se fueron enteros en la tabla de rutas, la tabla ARP y una fila por conexión TCP
abierta, y el árbol del fabricante no se llegó a preguntar. Que es justo donde está lo que se
viene a leer.

La lectura va **en paralelo y en dos pasadas**: primero las columnas que nombran y escalan
las filas, una vez cada una (siete métricas contra un mismo `ifDescr` son un recorrido y no
siete), y precargarlas es también lo que hace seguro leer las métricas a la vez — ya nadie
escribe en la caché compartida. De una en una, un NAS con «NAS Synology (todo)» no cabía en su
propio reloj: ciento cincuenta y siete métricas, y cada una que el modelo no sirva cuesta el
timeout por los reintentos.

Una fila **sin nombre no es un misterio, es un MIB que falta**: sin TCP-MIB compilado, cada
conexión abierta vuelve como una fila propia —no hay ninguna columna de la que ser instancia— y
cuarenta filas iguales se leen como cuarenta problemas. La pantalla dice cuántas hay, y lo que
hay que hacer es importar ese MIB.

Lo que un perfil lee como **columna** se compara por prefijo y nunca por igualdad (comparando
cadenas, cada interfaz del switch saldría como no capturada), y las columnas que **nombran** y
**escalan** las filas cuentan como capturadas: son valores que la asignación ya está usando, y
listarlas mandaría a alguien a escribir una métrica para un número que ya tiene. El recorrido
tiene tope y **avisa cuando lo toca**, en vez de informar de un aparato más pequeño de lo que es.

Sin ningún perfil asignado, la prueba es la lista de todo lo que ese aparato se puede medir —
que es donde más vale: la caja del rack para la que nadie ha escrito un perfil todavía.

Y los perfiles son **disjuntos a propósito**: se asignan varios a la vez, así que dos que den el
mismo valor no es redundancia — es una medida graficada dos veces con dos nombres. Por eso
`hr_storage` mide sólo volúmenes y deja la CPU y la memoria a `ucd_linux`. Por eso mismo un Synology lleva `ucd_linux`: **es una máquina Linux con net-snmp**, sirve el árbol UCD entero (CPU repartida, medias de carga, memoria y swap) y ningún MIB de fabricante da eso — y por eso mismo el perfil del fabricante *no* mide la CPU, que sería el mismo dato peor contado.

Los perfiles propios de la instalación van en `<var_dir>/snmp_profiles/`, junto a sus MIBs, para
que una actualización del paquete no se los lleve. Cada fila del catálogo dice si viene enviada o
escrita aquí, que es lo primero que hay que mirar cuando un aparato mide mal.

#### Agrupaciones

Un Synology contesta **quince** perfiles: sistema, discos, SMART, volúmenes y RAID, E/S de
discos y de volúmenes, caché SSD, puertos, unidades de expansión, iSCSI, NFS, GPU, alta
disponibilidad, SAI y usuarios por servicio. Cada uno es correctamente un perfil aparte, porque
son asuntos aparte. Asignarlos de uno en uno a cada NAS del rack son quince chips en un campo
diciendo lo que dice la palabra «Synology», y quince cosas que recordar cuando la familia
crezca un decimosexto.

Un **grupo** es una entrada del mismo catálogo cuyo `includes` nombra otras entradas:

```json
{
  "id": "grp_synology",
  "label": {"es_ES": "NAS Synology (todo)"},
  "includes": ["synology_system", "synology_disks", "…"],
  "match": {"sysobjectid_prefix": "1.3.6.1.4.1.6574", "supersedes": ["synology_system", "…"]}
}
```

No es un tipo nuevo de cosa, y ahí está todo el diseño: asignar, detectar, graficar, respaldar
y el muestreador siguen hablando de **ids**, y una sola función (`profiles.expand`) sabe que un
grupo no es un perfil. Por eso un grupo se puede renombrar, ganar un perfil o desaparecer sin
que nada más se entere. La expansión deduplica, así que dos grupos que compartan un perfil no
lo muestrean dos veces, y es a prueba de ciclos y con tope de profundidad — un par de grupos
que se nombran mutuamente es algo razonable de escribir por error, una vez, en un formulario.

Un grupo puede además **reclamar aparatos** como cualquier perfil. Si lo hace, desplaza lo que
contiene (`supersedes`), o la detección propondría el grupo *y* sus quince miembros, que es
peor que cualquiera de las dos cosas por separado. Y aunque no reclame nada, la detección
**colapsa**: si un grupo cubre exactamente lo encontrado, se propone el grupo. Sólo cuando lo
cubre **entero** — una cobertura parcial asignaría perfiles que el aparato no contestó, que es
justo el fallo que la detección existe para evitar.

Se envían nueve. Cinco son de fabricante o de familia —`grp_synology`, `grp_mikrotik`,
`grp_linksys`, `grp_linux` y `grp_network`— y cuatro son de Windows, y éstos enseñan lo que un
grupo puede hacer que un perfil no: **un grupo contiene otro grupo**.

`grp_windows` es la base —lo que contesta cualquier Windows: MIB-II, HOST-RESOURCES y la MIB de
LAN Manager— y los papeles la contienen entera y añaden lo suyo: `grp_windows_workstation` le
suma el redirector, `grp_windows_server` el servicio de servidor, y `grp_windows_dc` contiene al
de servidor y nada más, porque un controlador de dominio **es** un servidor y lo único distinto
es el número con el que se presenta.

Y ahí está la gracia: Windows dice qué papel tiene **en su propio `sysObjectID`**. Microsoft
numera `workstation`, `server` y `dc` como 1, 2 y 3 bajo `{ windowsNT }`, así que cada grupo
reclama su número, el más específico gana por prefijo más largo, y la base recoge lo que no sea
ninguno de los tres.

Todos reclaman su rama y **desplazan lo que contienen**, así que un aparato reconocido se
propone como **una sola fila**. Comprobado sobre el catálogo real, nueve casos:

| Aparato | Se propone |
|---|---|
| Windows estación de trabajo | `grp_windows_workstation` |
| Windows servidor | `grp_windows_server` |
| Windows controlador de dominio | `grp_windows_dc` |
| Synology | `grp_synology` |
| MikroTik | `grp_mikrotik` |
| Linksys | `grp_linksys` |
| Linux con net-snmp | `grp_linux` |
| SAI de APC | `grp_network` + `apc_ups` |
| Un switch de cualquier otro | `grp_network` |

#### Lo que se escribe en el panel

Al catálogo llegan **tres** fuentes, y cada una está donde está por una razón:

| Fuente | Dónde | Para qué |
|---|---|---|
| enviada | ficheros del módulo | se revisan en commits, viajan con la versión, una actualización del paquete las repone |
| propia | ficheros en `<var_dir>/snmp_profiles/` | las de esta instalación, editadas en la máquina; sobreviven a una actualización |
| escrita | **la base de datos** | todo lo que se escribe en el panel: grupos y perfiles |

La tercera es la BD y no una cuarta carpeta por una razón que no es de orden: un despliegue con
contenedor web y contenedor worker **comparte la base de datos, no el disco**. Un perfil escrito
en el panel que el muestreador no pudiera leer sería un aparato al que se le asignó algo que no
mide nada, sin error en ninguna parte. Va en el respaldo de la BD por lo mismo (tabla
`mod_snmp_catalog`).

**Una tabla para dos cosas que son una.** Un grupo es una entrada cuyos miembros son ids de
otras entradas; un perfil es una entrada cuyos miembros son OIDs. Todo lo de abajo ya los trata
igual —`profiles.normalise` valida cualquiera de los dos, el catálogo es un mapa, la pantalla
es una lista, el muestreador resuelve ids—, así que guardarlos aparte sería el único sitio del
producto que insistiera en que son distintos. Lo que guarda una fila es el **documento**, la
misma forma que tienen los ficheros enviados.

El formulario del perfil es ese documento campo a campo, y lo valida **la misma función que lee
los ficheros enviados**: una segunda validación en el formulario serían dos declaraciones de
las mismas reglas, y discreparían en cuanto una ganara un campo. Lo que sí añade es el motivo:
una métrica se rechaza **por su nombre y diciendo qué le pasa**, porque `normalise` descarta lo
que no puede usar y se queda con el resto —que está bien leyendo un fichero que alguien editó a
las 3 de la mañana, y mal contestando a una persona que está mirando la fila que acaba de
escribir—. El motivo se pregunta sólo **después** de que la validación haya dicho que no, así
que no puede discrepar de ella.

Los tres campos de OID del formulario **abren los MIB compilados** en vez de pedir que
alguien recuerde `1.3.6.1.4.1.6574.2.1.1.6`: cada dígito cuenta y ninguno lo comprueba nada
hasta que un aparato contesta —o no—. Y lo que aporta elegir por encima de pegar no es
comodidad, es el **SYNTAX**: `Counter64` rellena «contador, 64 bits», `Gauge32` rellena medida,
`DisplayString` rellena texto-y-no-se-dibuja, y un enumerado rellena la presentación de valor
que usan los perfiles enviados para un estado. Es lo único de una métrica que nadie acierta
mirando el OID, y lo que convierte una vuelta de contador en un aparato reiniciado. Un
**escalar se pide por su instancia** (`sysDescr` se convierte en `1.3.6.1.2.1.1.1.0`), que es
la forma más común de que un perfil escrito a mano esté vacío en silencio; una columna de tabla
se convierte en un `walk`; y la columna que nombra las filas se busca **entre las columnas de
esa tabla**, no entre nueve mil símbolos.

Cualquier perfil se puede **duplicar**, y es como se escribe uno de verdad: una matriz de OIDs
desde un formulario en blanco es una tarde, y esa misma matriz con tres OIDs cambiados son
cinco minutos. Lo que no se copia es cómo se reconoce el original —dos perfiles reclamando un
aparato es una detección proponiendo lo mismo dos veces.

**El id no se edita**, ni el de un grupo ni el de un perfil. Es el valor que guarda cada
aparato, así que renombrarlo no renombraría nada: dejaría a cada aparato que lo referenciaba
apuntando a nada. El nombre —lo que se lee— se cambia siempre que se quiera. Y la **clase**
detrás de un id tampoco cambia: un aparato al que se le asignó `mis_linux` cuando era un grupo
seguiría muestreando lo que midiera un perfil que se llamara así después.

Borrar tampoco reescribe la configuración de nadie: los aparatos conservan el id, que deja de
resolver, exactamente igual que un perfil enviado que desaparece.

#### El muestreo

Un check pregunta un OID y compara la respuesta con algo; el muestreo pregunta **un perfil
entero** y guarda los números. Son independientes: un check dice si algo *es cierto* del
aparato, el muestreo dice lo que *está haciendo*, y una máquina puede merecer lo uno sin lo
otro — un servidor con perfiles y **cero checks** ya es trabajo del ciclo.

Por cada aparato con perfiles y por ciclo:

- las métricas de valor suelto (`oid`) salen en **un resultado** por aparato, con clave
  `<servidor>/metrics`;
- las de tabla (`walk`) salen en **un resultado por fila**, con clave `<servidor>/<nombre>` —
  donde el nombre es el que da el propio aparato en la columna `index_label`, no el índice SNMP.
  Las métricas de una misma fila viajan juntas: entrada, salida y errores de una interfaz son
  un resultado, no tres gráficas de un tercio de puerto cada una.

**La muestra anterior sobrevive al proceso.** Un contador sólo significa algo como diferencia,
y el monitor construye un `Watchful` nuevo cada ciclo (en modo systemd one-shot, un **proceso**
nuevo). La lectura previa se guarda donde vive `fail_streak` —el `check_state` de la BD— por esa
razón exacta: en el objeto, cada ciclo parecería el primero y ningún contador se graficaría
jamás.

**Respuestas parciales son normales.** Un perfil asignado a un aparato que sirve la mitad cuesta
esas métricas y nada más; un switch sin agente UCD sigue teniendo interfaces que graficar. Y un
aparato que no contesta **nada** se informa una vez por aparato (no una por métrica: cuarenta
avisos de un cable desenchufado es como se aprende a ignorar los avisos), con dos ciclos de
gracia, porque un datagrama UDP perdido no es una caída.

Los campos que salen de un perfil se nombran solos en las gráficas: el módulo los declara en
caliente con `discover_history_fields()` — ver
[explica-descubrimiento.md](explica-descubrimiento.md#6c-campos-de-historial-en-caliente-discover_history_fields).

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
[explica-seguridad.md](explica-seguridad.md) → *Path Traversal* y *SSRF*.

---

## 🌡️ temperature — Sensores Térmicos

Monitoriza sensores de temperatura del sistema leyendo `/sys/class/thermal/*` en el host vinculado vía `ModuleBase.host_exec`. Es **host-aware**: el sensor se lee en local o por SSH según el host del registro.

**Plataforma:** Linux (**solo Linux**)

> **Solo Linux:** el check lee las *thermal zones* de `/sys/class/thermal`, que solo existen en Linux. En cualquier otro SO el ítem emite un aviso `warning` (`temp_unsupported_os`); no se leen sensores.

**Config:**
```json
{
    "temperature": {
        "enabled": true,
        "alert": 80,
        "list": {
            "coretemp": {
                "enabled": true,
                "label": "CPU Package",
                "alert": 90
            },
            "acpitz": {
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
| `list.*.sensor` | string | `""` | Sensor a leer (nombre de la *thermal zone*, p. ej. `coretemp`); vacío = usa la clave del ítem |
| `list.*.label` | string | nombre del sensor | Nombre mostrado en notificaciones; vacío = usa el nombre del sensor |
| `list.*.alert` | float | `0` (hereda global) | Umbral específico por sensor; `0` (en blanco) usa el umbral global |

> **Claves de sensor:** el nombre proviene del `type` de cada *thermal zone* (p. ej. `coretemp`, `acpitz`); los duplicados se numeran (`coretemp`, `coretemp_1`…). Los nombres exactos disponibles dependen del hardware.
> **Descubrimiento:** la UI web incluye un botón para listar automáticamente los sensores disponibles e incorporarlos a la configuración con un solo clic. Muestra el nombre y la temperatura actual (lee las thermal zones en local o por SSH).

**Flujo:** `ModuleBase.host_exec(item, cmd)` ejecuta un único `grep -H . /sys/class/thermal/thermal_zone*/{type,temp}` → correlaciona `type`↔`temp` por zona en Python → compara la temperatura del sensor con el umbral → alerta si lo supera. Un fallo de lectura del sensor se reporta como `down`.

> **Severidad:** superar el umbral de temperatura emite `severity='warning'` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## 🌐 web — Disponibilidad Web

Comprueba que las URLs responden con el código HTTP esperado.

**Plataforma:** Linux, Windows 🌐

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
                "scheme": "https",
                "server": "example.com",
                "port": 0,
                "path": "/health",
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
| `list.*.server` | string | `""` | Host/dirección base. Si está vacío, se usa la clave del ítem o el host vinculado (`__host_profile__` `http`) |
| `list.*.path` | string | `""` | Ruta a añadir a la URL base (p. ej. `/health`) |
| `list.*.scheme` | string | `https` | Esquema: `http` o `https` |
| `list.*.port` | int | 0 | Puerto; `0` (en blanco) usa el estándar del esquema |
| `list.*.url` | string | — | **Campo legacy (compat):** URL completa. Migra automáticamente a `server` (`__migrates_from__`) |
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

> **Severidad:** los avisos de umbral blando (updates pendientes, uso de almacenamiento, nodo en mantenimiento) emiten `warning` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

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

> **Severidad:** los avisos de umbral blando (p. ej. prioridad inesperada) emiten `warning` (ámbar, kind `warn`), no `down`. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).

---

## 🌩️ azure — Estado de servicio de Azure

Vigila el **estado de servicio de Azure**, que **no** es lo mismo que el de Microsoft 365: el
check `check_health` de [m365](#️-m365--microsoft-365-microsoft-graph) lee la salud de *Microsoft
365* (Exchange, Teams, SharePoint). Azure vive en otra API, y por dos motivos es un módulo aparte:

- el token se emite para otro *audience*, **`management.azure.com`** (no Microsoft Graph); y
- el acceso **no** se concede con un rol de aplicación de Entra, sino con una **asignación RBAC de
  Azure** (basta **Lector**) **sobre la suscripción**. El asistente de Entra ID **no** hace esa
  asignación: hoy se hace a mano en el portal.

**Plataforma:** Multiplataforma 🌐 (HTTP)

**Comprobaciones disponibles:**

| Check (`list.*.check_*`) | Qué mide | Umbral / opciones | Requiere |
| --- | --- | --- | --- |
| `check_service_health` (def. true) | Eventos de **Service Health de tu suscripción** (`Microsoft.ResourceHealth/events`): caídas, mantenimientos y avisos que afectan a **tus** recursos y regiones. Un evento activo por resultado | `health_window_hours` (ventana, def. 24 h) | credencial + `subscription_id` + rol RBAC |
| `check_public_status` | Feed **público** de estado de Azure (sin credenciales) | `public_filter` (texto: servicio o región; vacío = todo) | nada |

Severidad: un *advisory*, *mantenimiento planificado* o *aviso de seguridad* se emite como
**warning**; una incidencia de servicio, como **error**.

> ⚠️ El check público **solo ve incidencias anunciadas globalmente**: no puede decir si *tus*
> recursos están afectados. Sirve de señal aproximada o de respaldo cuando no hay app registrada
> en Azure — no sustituye al check autenticado.

Credencial reutilizable **`azure_app`** (`tenant_id`, `client_id`, `client_secret`,
`subscription_id`). `list.*.timeout` / `alert` por ítem (`0` hereda el global).

**Sección propia:** declara `__page__`, así que aporta la sección **`/azure`** con su entrada en la
barra lateral. No trae código de frontend: la pinta el **renderizador genérico del core** a partir
de su hook `page_data` (ver [explica-descubrimiento.md §2c](explica-descubrimiento.md#2c-una-sección-propia-aportada-por-un-módulo-__page__)),
con un botón de refresco que consulta Azure en el momento.

La sección tiene **dos vistas** bajo un desplegable: **Estado** (la de siempre, con sus cuatro disposiciones y su refresco en vivo) y **Almacenamiento** (`/module/m365/storage`), una tabla única con una fila por sitio de SharePoint y por cuenta de OneDrive — tenant, tipo, nombre, ocupado, cuota y % de su propia cuota— ordenable y con buscador. Es **en vivo y sin históricos**: corre los dos checks de almacenamiento al abrirse, con los topes levantados, y no guarda nada; el histórico y las alertas siguen viviendo en los checks del monitor. Acción: `storage_report`.

**Flujo:** token *client-credentials* para `management.azure.com` → eventos de Resource Health en la
ventana → clasifica por tipo de evento; el check público descarga el RSS y filtra.

---

## ☁️ m365 — Microsoft 365 (Microsoft Graph)

Monitoriza **Microsoft 365** vía la **Microsoft Graph API** (app-only). Se autentica con una
credencial **`m365_app`** (tenant/client/secret), que el **asistente de Entra ID** puede
aprovisionar (ver [caso-entra-id.md](caso-entra-id.md) para el motor de provisioning compartido).
Cada comprobación es un **interruptor opcional** en el ítem (`check_*`); cada una emite su
resultado bajo una clave propia `<ítem>/<servicio>`, así son independientes.

**Plataforma:** Multiplataforma 🌐 (HTTP a Graph)

**Comprobaciones disponibles** (cada `check_*` con su umbral):

| Check (`list.*.check_*`) | Qué mide | Umbral | Permiso Graph |
| --- | --- | --- | --- |
| `check_site` (def. true) | Cuota del drive de **un** sitio de SharePoint (% usado / libre) | `site_usage_pct` (%), `site_free_min`+`site_free_unit`; `site` (vacío = el sitio **raíz**, que es un sitio más y no el total del tenant; botón **discover** `list_sites`) | `Sites.Read.All` |
| `check_tenant_usage` | **SharePoint completo**: suma lo ocupado por TODOS los sitios frente a la capacidad total, con % real. Los sitios en papelera cuentan (ocupan hasta purgarse) y se informan aparte | `tenant_pct` (% → warning), `tenant_warn_at`+`tenant_warn_unit` (ocupado → warning), `tenant_free_min`+`tenant_free_unit` (**libre por debajo de** → warning; necesita capacidad conocida), **100 % → error**; `tenant_capacity`+`tenant_capacity_unit` = capacidad total. Graph **no publica** el pool del tenant: o lo escribes tú (léelo en Centro de administración de SharePoint → Sitios activos, arriba a la derecha) o sale de la suma de cuotas reales por sitio si el tenant las gestiona a mano; sin ninguna de las dos, el check informa de lo ocupado y **admite que no hay total** en vez de inventarlo. La fila dice de dónde salió en `source`. **Desglose por sitio**: `sites_top` (módulo, override por ítem) = cuántos sitios se guardan por ciclo — en blanco hereda, **0 no guarda ninguno** y el desglose solo sale con «Actualizar ahora», que consulta en vivo y los trae todos; `breakdown_page` (módulo) = cuántas filas dibuja la página de una vez, y vale para los dos desgloses | `Reports.Read.All` + `Sites.Read.All` (nombres cuando el tenant oculta los informes) + `SharePointTenantSettings.Read.All` (¿gestión automática de almacenamiento?) + `Organization.Read.All` (estimación por licencias) |
| `check_health` | Estado de servicios M365 (degradación = warning, interrupción = down) | `health_services` (filtro opcional por nombre) | `ServiceHealth.Read.All` |
| `check_licenses` | Capacidad de licencias (SKU): unidades libres = habilitadas − consumidas | `licenses_free_min` (0 = avisa al agotarse) | `Organization.Read.All` |
| `check_secrets` | Caducidad del secreto/certificado **de esta misma app** | `secret_expiry_days` (avisa N días antes; caducado avisa siempre) | `Application.Read.All` |
| `check_mailbox` | Buzones de Exchange sobre cuota (envío/recepción prohibidos) | `mailbox_over_max` (0 = avisa si hay alguno) | `Reports.Read.All` |
| `check_onedrive` | Almacenamiento total USADO de OneDrive en el tenant **y quién lo usa**: informe de detalle por cuenta, una fila por persona. Sin % ni «tenant lleno» — las cuotas son por persona y no hay pool que agotar | `onedrive_max`+`onedrive_unit` (0 = informativo); `accounts_top` (módulo, override por ítem) = cuántas cuentas se guardan por ciclo, **0 = ninguna** (solo en vivo). La barra de cada fila es esa cuenta contra **su propia cuota** | `Reports.Read.All` + `User.Read.All`/`Sites.Read.All` (nombres cuando el tenant oculta los informes) |
| `check_secure_score` | Microsoft Secure Score (actual/máx en %) | `secure_score_min` (% mínimo; 0 = informativo) | `SecurityEvents.Read.All` |
| `check_risky_users` | Usuarios en riesgo (Identity Protection, `atRisk`) | `risky_users_max` (0 = avisa si hay alguno) | `IdentityRiskyUser.Read.All` |

`tenant_id` / `client_id` / `client_secret` son las credenciales de la app (o una credencial
`m365_app` reutilizable). `list.*.timeout` / `alert` por ítem (`0` hereda el global).

**Mejora pendiente — capacidad exacta de SharePoint (`Get-SPOTenant`).** Hoy `tenant_capacity` se
escribe a mano porque **Graph no publica la cuota agrupada del tenant**, y eso está verificado
contra un tenant real: `/admin/sharepoint/settings` devuelve 28 ajustes, tres sobre
almacenamiento —gestión automática sí/no, techo por sitio (25 TB) y cuota por defecto de OneDrive
(5 TB)— y **ninguno es el pool**. Ojo con confundirlos: un techo no es capacidad disponible, y
sumar 18 sitios a 25 TB daría 450 TB de «capacidad». El número real solo lo sirve la API de
administración de SharePoint (`Get-SPOTenant` → CSOM contra `<tenant>-admin.sharepoint.com`), y
el precio es doble: token app-only que SharePoint solo acepta si se acuñó con **certificado**
(este módulo se autentica con secreto, y `lib/providers/entraid/` no tiene camino de
`client_assertion`) y permiso **`Sites.FullControl.All`**, control total de todos los sitios del
tenant para leer un dato. Mientras no se pague ese precio, `tenant_capacity` es donde va ese número:
se lee en Centro de administración de SharePoint → Sitios activos, arriba a la derecha. La
acción de diagnóstico `sharepoint_settings` sigue ahí para volver a comprobarlo si Microsoft
añade el dato a Graph.

**Sección propia:** declara `__page__`, así que aporta la sección **`/module/m365`** con su entrada en la
barra lateral: salud de servicios, licencias y almacenamiento, seguridad (Secure Score, usuarios de
riesgo) y caducidad de secretos, agrupado por tipo de check, con un botón que consulta Graph en el
momento. A diferencia de [azure](#️-azure--estado-de-servicio-de-azure), **trae su propio
renderizador** (`web/_ui.html`) en vez de usar el genérico del core.

**Flujo:** token *client-credentials* (`.default` de Graph) → una consulta por check activo →
compara con su umbral → emite OK / warning / down bajo `<ítem>/<servicio>`.

**Permisos:** el asistente de registro en Entra pide de una vez todos los permisos de
aplicación de arriba (con consentimiento de admin). Los checks que no uses no requieren su
permiso — pero el asistente los concede todos para no tener que volver.

**Comprobar / arreglar permisos** (genérico de Entra ID, en el editor de la credencial
`m365_app`): **«Comprobar permisos»** llama a `POST /api/v1/auth/entraid/check-permissions`,
que resuelve los permisos requeridos desde `__entraid_provision__`, pide un token app-only y
compara su claim `roles`, mostrando cada uno ✅/❌ (solo lectura, sin admin). Si faltan,
**«Arreglar permisos»** lanza el asistente device-code en modo *ensure*: concede a la app
**existente** (por `client_id`) los permisos que falten y los re-consiente (sin crear app
nueva ni rotar el secreto), con informe de concedidos / ya presentes / aún faltan.
El módulo m365 no implementa nada de esto: solo **declara** sus permisos en
`__entraid_provision__`; el proveedor Entra ID (`lib/providers/entraid`) hace el trabajo.

> **Severidad:** superar un umbral de cuota/uso/postura emite `warning` (ámbar, kind `warn`); una **interrupción de servicio** sí es `down`. Un fallo de auth/Graph de un check concreto es `down` solo de ese check. Ver [explica-notificaciones.md → Severidad warning](explica-notificaciones.md#severidad-warning).
