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
        "lang": "en_EN",
        "dark_mode": false,
        "public_status": false,
        "status_refresh_secs": 60,
        "status_lang": "",
        "secure_cookies": false,
        "remember_me_days": 30,
        "audit_max_entries": 500,
        "pw_min_len": 8,
        "pw_max_len": 128,
        "pw_require_upper": true,
        "pw_require_digit": true,
        "pw_require_symbol": false,
        "proxy_count": 0
    }
}
```

### Sección `daemon`

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `daemon.timer_check` | int | 300 | Segundos entre cada ciclo de comprobación en modo daemon |

### Sección `global`

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `global.debug` | bool | false | Habilitar salida de debug |

### Sección `telegram`

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `telegram.token` | string | `""` | Token del Bot de Telegram |
| `telegram.chat_id` | string | `""` | ID del chat o grupo de Telegram (solo dígitos) |
| `telegram.group_messages` | bool | false | Si `true`, agrupa todos los mensajes en un bloque por ciclo |

### Sección `web_admin`

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `web_admin.lang` | string | `"en_EN"` | Idioma por defecto de la interfaz web (`en_EN` o `es_ES`) |
| `web_admin.dark_mode` | bool | `false` | Modo oscuro por defecto para sesiones nuevas |
| `web_admin.public_status` | bool | `false` | Exponer `/status` públicamente sin autenticación. Los usuarios logueados siempre pueden acceder. |
| `web_admin.status_refresh_secs` | int | `60` | Intervalo de refresco automático de la página `/status` (10–3600 segundos) |
| `web_admin.status_lang` | string | `""` | Idioma de la página pública `/status`. Prioridad: sesión del usuario → este campo → `web_admin.lang`. Dejar vacío para usar el idioma por defecto del panel. |
| `web_admin.secure_cookies` | bool | `false` | Marcar la cookie de sesión como `Secure` (solo HTTPS). Activar cuando Flask esté detrás de HTTPS. |
| `web_admin.remember_me_days` | int | `30` | Duración de sesiones persistentes ("Recuérdame") en días (1–365) |
| `web_admin.audit_max_entries` | int | `500` | Número máximo de entradas en el registro de auditoría (10–10000) |
| `web_admin.pw_min_len` | int | `8` | Longitud mínima de contraseña (1–128) |
| `web_admin.pw_max_len` | int | `128` | Longitud máxima de contraseña (8–256) |
| `web_admin.pw_require_upper` | bool | `true` | Exigir al menos una letra mayúscula y una minúscula en la contraseña |
| `web_admin.pw_require_digit` | bool | `true` | Exigir al menos un dígito en la contraseña |
| `web_admin.pw_require_symbol` | bool | `false` | Exigir al menos un símbolo (`!`, `@`, `#`…) en la contraseña |
| `web_admin.proxy_count` | int | `0` | Número de proxies inversos delante del servidor Flask (0–10). Activa `ProxyFix` de Werkzeug para leer correctamente la IP real del cliente. |

### Sección `ldap`

Requiere el paquete opcional `ldap3` (`pip install ldap3`). Si no está instalado, el campo `enabled` es ignorado.

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `ldap.enabled` | bool | `false` | Activar autenticación LDAP/Active Directory |
| `ldap.server` | string | `""` | Hostname o IP del servidor LDAP |
| `ldap.port` | int | `389` | Puerto (389 sin TLS / 636 con LDAPS) (1–65535) |
| `ldap.use_ssl` | bool | `false` | Usar LDAPS (TLS) en lugar de LDAP plano |
| `ldap.timeout` | int | `5` | Timeout de conexión en segundos (1–60) |
| `ldap.bind_dn` | string | `""` | DN de la cuenta de servicio para búsquedas |
| `ldap.bind_password` | string | `""` | Contraseña de la cuenta de servicio (cifrada en disco) |
| `ldap.base_dn` | string | `""` | Base DN para búsqueda de usuarios |
| `ldap.user_filter` | string | `"(sAMAccountName={username})"` | Filtro LDAP para localizar al usuario; `{username}` se sustituye en tiempo de ejecución |
| `ldap.email_attr` | string | `"mail"` | Atributo LDAP del que se lee el email |
| `ldap.name_attr` | string | `"displayName"` | Atributo LDAP del que se lee el nombre visible |
| `ldap.group_attr` | string | `"memberOf"` | Atributo LDAP del que se leen los grupos |
| `ldap.group_role_map` | string (JSON) | `"{}"` | Objeto JSON `{"CN=Admins,...": "admin", ...}` que mapea grupos LDAP a roles de la app |
| `ldap.fallback_to_local` | bool | `true` | Si LDAP falla por error de red (no por credenciales incorrectas), intentar autenticación local |
| `ldap.allow_email_login` | bool | `false` | Permitir que los usuarios introduzcan su dirección de email en lugar del username LDAP |

Los usuarios autenticados por LDAP se crean o sincronizan automáticamente en `users.json` con `auth_source: "ldap"`. Los usuarios locales (`auth_source: "local"`) nunca pasan por LDAP.

### Sección `oidc`

Requiere el paquete opcional `authlib` (`pip install authlib`).

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `oidc.enabled` | bool | `false` | Activar SSO OIDC/OAuth2 |
| `oidc.provider_url` | string | `""` | URL de discovery del IdP (p.ej. `https://login.microsoftonline.com/{tenant}/v2.0`) |
| `oidc.client_id` | string | `""` | Client ID de la aplicación registrada en el IdP |
| `oidc.client_secret` | string | `""` | Client Secret (cifrado en disco con Fernet) |
| `oidc.scopes` | string | `"openid email profile"` | Scopes OAuth2 separados por espacio |
| `oidc.username_claim` | string | `"preferred_username"` | Claim del ID token del que se extrae el username |
| `oidc.email_claim` | string | `"email"` | Claim del que se extrae el email |
| `oidc.name_claim` | string | `"name"` | Claim del que se extrae el nombre visible |
| `oidc.groups_claim` | string | `"groups"` | Claim del que se leen los grupos (p.ej. Object IDs en Entra ID) |
| `oidc.group_role_map` | string (JSON) | `"{}"` | Objeto JSON que mapea valores del claim de grupos a roles de la app |
| `oidc.auto_create_users` | bool | `true` | Crear automáticamente el usuario en `users.json` en el primer login |

Cuando está habilitado, aparece el botón **Login with SSO** en la pantalla de login. El wizard integrado en la pestaña de configuración puede registrar la aplicación en Microsoft Entra ID automáticamente mediante Device Code Flow.

### Sección `email`

| Clave | Tipo | Por defecto | Descripción |
|-------|------|-------------|-------------|
| `email.enabled` | bool | `false` | Activar notificaciones por email |
| `email.provider` | string | `"smtp"` | Proveedor de envío: `smtp`, `ms365` o `gmail` |
| `email.recipients` | string | `""` | Direcciones de destino separadas por comas |
| `email.subject_prefix` | string | `""` | Prefijo opcional para el asunto del mensaje |
| `email.notify_on_down` | bool | `true` | Enviar alerta cuando un check falla |
| `email.notify_on_recovery` | bool | `true` | Enviar alerta cuando se recupera un check |
| `email.notify_on_warn` | bool | `false` | Enviar alerta en estado de advertencia |
| `email.from_email` | string | `""` | Dirección de envío (campo `From:`) |
| `email.smtp_host` | string | `""` | Servidor SMTP (solo para `provider=smtp`) |
| `email.smtp_port` | int | `587` | Puerto SMTP (1–65535) |
| `email.smtp_use_tls` | bool | `true` | Usar STARTTLS (habitual en el puerto 587) |
| `email.smtp_use_ssl` | bool | `false` | Usar SSL/TLS directo (habitual en el puerto 465) |
| `email.smtp_username` | string | `""` | Usuario para autenticación SMTP |
| `email.smtp_password` | string | `""` | Contraseña SMTP (cifrada en disco) |

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

### Monitorización

| Opción | Descripción |
|--------|-------------|
| `-d`, `--daemon` | Modo daemon (ejecución continua) |
| `-t N`, `--timer N` | Intervalo entre comprobaciones en segundos (requiere `--daemon`) |
| `-v`, `--verbose` | Modo verbose (nivel debug = null → muestra todo) |
| `-p PATH`, `--path PATH` | Ruta personalizada al directorio de configuración |
| `-c`, `--clear` | Limpia `status.json` antes de ejecutar |

### Panel web (`--web`)

| Opción | Descripción |
|--------|-------------|
| `--web` | Arranca el panel de administración web en lugar del modo monitorización |
| `--web-host HOST` | IP/hostname donde escucha Flask (por defecto `0.0.0.0`) |
| `--web-port PORT` | Puerto TCP del panel web (por defecto `8080` o el valor de `config.json`) |

> Los valores `--web-host` y `--web-port` tienen prioridad sobre `web_admin.host` y `web_admin.port` de `config.json`.

### Ejemplos

```bash
# Ejecución única (monitorización)
python3 main.py

# Daemon, comprobación cada 5 minutos
python3 main.py -d -t 300

# Salida detallada + ruta de config personalizada
python3 main.py -v -p /opt/myconfig/

# Limpiar estado y ejecutar en modo daemon
python3 main.py -c -d -t 60

# Panel web en el puerto por defecto
python3 main.py --web

# Panel web en host y puerto específicos
python3 main.py --web --web-host 127.0.0.1 --web-port 9090
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
