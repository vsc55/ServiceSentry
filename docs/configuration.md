# Referencia de Configuración

Referencia completa de todos los archivos de configuración y opciones CLI de ServiceSentry.

---

## Rutas de los Archivos de Configuración

| Modo | Directorio config | Directorio var |
|------|------------------|----------------|
| **Desarrollo** (detecta `src` en la ruta) | `../data/` (relativo) | igual que directorio config (`../data/`) |
| **Producción Linux / macOS** | `/etc/ServiSesentry/` | `/var/lib/ServiSesentry/` |
| **Producción Windows** | `/etc/ServiSesentry/` | `%PROGRAMDATA%\ServiSesentry` |
| **Personalizado** (`-p path`) | ruta especificada | según modo dev/prod |

---

## config.json

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
    },
    "web_admin": {
        "lang": "en_EN"
    }
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `daemon.timer_check` | int | 300 | Segundos entre cada ciclo de comprobación en modo daemon |
| `global.debug` | bool | false | Habilitar salida de debug |
| `telegram.token` | string | `""` | Token del Bot de Telegram |
| `telegram.chat_id` | string | `""` | ID del chat o grupo de Telegram |
| `telegram.group_messages` | bool | false | Si `true`, agrupa todos los mensajes en un bloque por ciclo |
| `web_admin.lang` | string | `"en_EN"` | Idioma por defecto de la interfaz web (`en_EN` o `es_ES`) |
| `web_admin.public_status` | bool | `false` | Exponer `/status` públicamente sin autenticación. Los usuarios logueados siempre pueden acceder. |
| `web_admin.status_refresh_secs` | int | `60` | Intervalo de refresco automático de la página `/status` (10–3600 segundos) |

---

## monitor.json

Configuración del motor de monitorización.

```json
{
    "threads": 5
}
```

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `threads` | int | 5 | Número máximo de hilos del `ThreadPoolExecutor` principal |

---

## modules.json

Configuración por módulo. Cada clave de primer nivel debe coincidir con el nombre de la carpeta del módulo en `watchfuls/`.

```json
{
    "nombre_modulo": {
        "enabled": true,
        ...configuración específica del módulo...
    }
}
```

Consulta [modules.md](modules.md) para la referencia completa de configuración de cada módulo.

---

## status.json (auto-generado)

Almacena el **último estado conocido** de cada comprobación. Se escribe en el directorio var automáticamente. No editar manualmente.

```json
{
    "nombre_modulo": {
        "clave_item": {
            "status": true,
            "other_data": { }
        }
    }
}
```

Reinicia con `-c` / `--clear` para forzar re-notificación en el siguiente ciclo.

---

## Opciones de Línea de Comandos

```bash
python3 main.py [opciones]
```

| Opción | Descripción |
|--------|-------------|
| `-d`, `--daemon` | Modo daemon (ejecución continua) |
| `-t N`, `--timer N` | Intervalo entre comprobaciones en segundos (requiere `--daemon`) |
| `-v`, `--verbose` | Modo verbose (nivel debug = null → muestra todo) |
| `-p PATH`, `--path PATH` | Ruta personalizada al directorio de configuración |
| `-c`, `--clear` | Limpia `status.json` antes de ejecutar |

### Ejemplos

```bash
# Ejecución única
python3 main.py

# Daemon, comprobación cada 5 minutos
python3 main.py -d -t 300

# Salida detallada + ruta de config personalizada
python3 main.py -v -p /opt/myconfig/

# Limpiar estado y ejecutar en modo daemon
python3 main.py -c -d -t 60
```

---

## Notificaciones Telegram

### Funcionamiento

```
Telegram.__init__():
├── Crea un hilo daemon (pool_run) que corre permanentemente
└── Lista de mensajes (list_msg) actuando como cola

Flujo de envío:
1. Monitor llama tg.send_message(msg) → se añade a list_msg
2. El hilo pool_run recoge el mensaje
3. Modo normal: envía cada mensaje individualmente
4. Modo group_messages: acumula mensajes, envía bloque cuando la cola queda vacía
5. Al final del ciclo: send_message_end() → añade resumen + espera a que la cola se vacíe
```

### Formato de mensajes

```
✅ 💻 [hostname]: Servicio OK                       (status=True)
❎ 💻 [hostname]: Servicio con problemas             (status=False)
ℹ️ Summary *hostname*, get *N* new Message. ☝☝☝   (resumen del ciclo)
```

### API de Telegram

- Endpoint: `https://api.telegram.org/bot{token}/sendMessage`
- Parámetros: `chat_id`, `text`, `parse_mode=Markdown`
- Códigos de retorno internos: `200`=OK, `-1`=token null, `-2`=chat_id null, `-3`=ambos null

---

## Exec (Ejecución de Comandos)

La clase `Exec` en `lib/exe.py` abstrae la ejecución de comandos local y remota.

| Modo | Implementación |
|------|---------------|
| **Local** | `subprocess.Popen(shlex.split(cmd))` → stdout, stderr, exit_code |
| **Remoto** | `paramiko.SSHClient()` → `client.exec_command(cmd)` → stdout, stderr, exit_code |

> **Nota de seguridad:** la política de host SSH por defecto es `RejectPolicy`. Los hosts desconocidos son rechazados. Añade los hosts conocidos a `~/.ssh/known_hosts` antes de usar la ejecución remota.

### ExecResult

```python
ExecResult(
    stdout: str,          # Salida estándar
    stderr: str,          # Salida de error
    exit_code: int,       # Código de salida
    exception: Exception  # Excepción si hubo un error
)
```

### Uso directo (estático)

```python
from lib.exe import Exec

# Comando local
result = Exec.execute("ls -la")

# Comando remoto vía SSH
result = Exec.execute(
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

### Lógica de filtrado

Un mensaje se muestra si:
- `debug.enabled == True` **Y**
- `debug.level.value <= msg_level.value`

El nivel configurado actúa como **filtro mínimo**. Con `level=info`, se muestran mensajes `info`, `warning`, `error` y `emergency`, pero NO `debug`.

### Instancia compartida

`ObjectBase.debug` es un atributo de **clase** (no de instancia). Todos los objetos que heredan de `ObjectBase` comparten la misma instancia de `Debug`. Al cambiar el nivel en uno, cambia para todos.
