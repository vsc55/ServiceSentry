# Seguridad del Panel Web

Referencia completa de los mecanismos de seguridad implementados en la interfaz web de administración (`lib/web_admin`) y los tests que los verifican.

---

## Autenticación

### Flujo de login

1. `POST /login` recibe `username` + `password`.
2. Si **LDAP está habilitado** (`ldap.enabled = true`): se evalúa el campo `auth_source` del usuario en `users.json`:
   - `auth_source: "ldap"` o usuario desconocido → autenticación contra LDAP primero.
   - `auth_source: "local"` → siempre autenticación local, LDAP ignorado.
   - Si LDAP falla por error de red y `fallback_to_local = true` → intenta autenticación local.
3. Se busca el usuario en `users.json`; si no existe o la contraseña es incorrecta → el **formulario muestra siempre "Invalid credentials"** (mensaje genérico — evita enumeración de usuarios). Si la cuenta existe pero está desactivada → mensaje específico "account disabled". Si la cuenta está bloqueada → mensaje con los minutos restantes.
4. La contraseña se verifica con `werkzeug.security.check_password_hash` (PBKDF2-SHA256).
5. Si es correcta → se crea una entrada en el **registro de sesiones** del servidor (`_sessions`) con un token de 32 bytes aleatorios (64 hex) y se guarda en la cookie de sesión Flask.
6. El evento `login_ok` o `login_failed` se escribe en el **registro de auditoría**. En caso de fallo, el campo `detail.reason` almacena la clave i18n que describe la causa real (`user_not_found`, `account_disabled`, `account_locked`, `invalid_credentials`, `ldap_invalid_credentials`, `ldap_user_not_found` o `ldap_connection_error`). Los logins LDAP/OIDC exitosos incluyen `detail.auth_source`.
7. El login usa el patrón **POST / Redirect / GET**: en caso de fallo se usa `flash()` y se redirige al `GET /login`, evitando el diálogo de reenvío de formulario al pulsar F5.

### Sesiones persistentes ("Remember me")

- El formulario de login incluye un checkbox `remember_me`.
- Si se activa, `session.permanent = True` (duración configurable).
- La `secret_key` de Flask se genera aleatoriamente la primera vez y se persiste en disco (`secret_key.txt`); las instancias posteriores reutilizan la misma clave — las sesiones no se invalidan al reiniciar el proceso.

### Campo `auth_source` en usuarios

Cada usuario en `users.json` tiene un campo `auth_source` que determina cómo se autentica:

| Valor | Significado |
| ----- | ----------- |
| `"local"` | Contraseña hash local; LDAP/OIDC nunca se aplican |
| `"ldap"` | Autenticado contra LDAP; no tiene `password_hash` |
| `"oidc"` | Autenticado mediante SSO OIDC; no tiene `password_hash` |

La migración `m002_add_auth_source` añade `auth_source: "local"` a los usuarios existentes al arrancar, garantizando compatibilidad hacia atrás.

### Tests de autenticación

| Test | Qué verifica |
|------|-------------|
| `test_root_redirects_to_login` | Ruta `/` redirige a `/login` sin sesión |
| `test_login_success` | Login correcto da acceso al dashboard |
| `test_login_wrong_password` | Contraseña incorrecta → redirección PRG a login + mensaje de error |
| `test_login_wrong_username` | Usuario inexistente → mismo mensaje genérico (sin enumerar) |
| `test_login_empty_fields` | Credenciales vacías → rechazado |
| `test_login_account_disabled` | Cuenta desactivada → mensaje específico "account disabled" |
| `test_login_uses_post_redirect_get` | Login fallido → 302 redirect (PRG), no render directo |
| `test_logout` | Logout invalida la sesión; rutas protegidas redirigen a login |
| `test_login_with_remember_me` | `remember_me` marca la sesión como permanente |
| `test_secret_key_persisted` | La `secret_key` se escribe en disco al crear la instancia |
| `test_secret_key_reused` | Una segunda instancia reutiliza la clave existente |

### Bloqueo de cuenta por intentos fallidos

Tras `_LOCKOUT_MAX_ATTEMPTS` (por defecto **5**) intentos de login fallidos con la contraseña incorrecta, la cuenta queda bloqueada durante `_LOCKOUT_DURATION_SECS` (por defecto **900 s = 15 min**). Mientras está bloqueada, incluso la contraseña correcta es rechazada. El mensaje de error indica los minutos restantes.

Configuración en `config.json → web_admin`:

| Campo                   | Por defecto | Descripción                                                     |
|-------------------------|-------------|----------------------------------------------------------------- |
| `lockout_max_attempts`  | `5`         | Intentos fallidos antes del bloqueo. `0` desactiva el bloqueo.  |
| `lockout_duration_secs` | `900`       | Duración del bloqueo en segundos (60–86400).                    |

Los campos `_failed_attempts` y `_locked_until` se almacenan en `users.json` y se limpian automáticamente tras un login exitoso o cuando expira el bloqueo. Estos campos no se exponen en `GET /api/v1/users`.

### Tests de bloqueo de cuenta

| Test | Qué verifica |
|------|-------------|
| `test_lockout_triggers_after_n_attempts` | Tras N intentos fallidos el mensaje menciona "locked" |
| `test_locked_account_rejects_correct_password` | Cuenta bloqueada rechaza la contraseña correcta |
| `test_lockout_returns_minutes_remaining` | El mensaje incluye los minutos restantes |
| `test_successful_login_resets_failed_attempts` | Login correcto limpia `_failed_attempts` y `_locked_until` |
| `test_lockout_disabled_when_max_attempts_zero` | Con `max_attempts=0` nunca se bloquea |
| `test_account_unlocks_after_duration` | Tras expirar el bloqueo, el login correcto funciona |
| `test_authenticate_returns_tuple` | `_authenticate()` devuelve siempre una 2-tupla |
| `test_authenticate_wrong_password_reason` | Contraseña incorrecta → `reason='invalid_credentials'` |
| `test_authenticate_unknown_user_reason` | Usuario inexistente → `reason='user_not_found'` |

---

## Autenticación Externa (LDAP / OIDC)

### LDAP / Active Directory

Cuando `ldap.enabled = true` y el paquete `ldap3` está instalado, el flujo de login de `POST /login` intenta autenticar contra LDAP antes de (o en lugar de) la verificación local, dependiendo del campo `auth_source` del usuario. Ver [Flujo de login](#flujo-de-login) para la lógica completa.

**Seguridad:**

- Las credenciales del usuario nunca se almacenan localmente; el bind LDAP es el único verificador.
- La contraseña de la cuenta de servicio (`bind_password`) se cifra en disco con Fernet.
- Los usuarios LDAP reciben `auth_source: "ldap"` y no tienen `password_hash` en `users.json`.
- El mapeo grupo → rol se recalcula en cada login para reflejar cambios en el directorio.

### OIDC / OAuth2

Cuando `oidc.enabled = true` y `authlib` está instalado, aparece el botón **Login with SSO** en `/login`. El flujo es:

1. `GET /auth/oidc/login` genera un `state` + `nonce` aleatorios (guardados en sesión Flask) y redirige al IdP.
2. El IdP redirige a `GET /auth/oidc/callback` con el `code` de autorización.
3. El servidor intercambia el code por tokens, verifica la firma del ID token y valida `state` y `nonce`.
4. Se extrae el username del claim configurado (`username_claim`), se sincroniza el usuario en `users.json` y se crea la sesión.

**Seguridad:**

- El `client_secret` se cifra en disco con Fernet.
- El `state` previene ataques CSRF en el callback.
- El `nonce` previene ataques de replay del ID token.
- Si `auto_create_users = false` y el usuario no existe previamente, el login es rechazado (403).

### Tests de autenticación externa

| Archivo | Qué cubre |
| ------- | --------- |
| `test_wa_ldap.py` | Autenticación LDAP correcta, credenciales incorrectas, servidor caído, fallback a local, sincronización de usuario, mapeo de grupos, `allow_email_login` |
| `test_wa_oidc.py` | Callback OIDC correcto, `state` inválido, `auto_create_users=false`, sincronización de usuario, mapeo de claims |

---

## Gestión de Sesiones (servidor)

El servidor mantiene un diccionario `_sessions` con metadatos de cada sesión activa:

```python
{
    "<token_hex_64>": {
        "username": "admin",
        "created": "2026-05-02T10:00:00",
        "last_seen": "2026-05-02T10:05:00",
        "ip": "127.0.0.1",
        "user_agent": "Mozilla/5.0 ..."
    }
}
```

Las sesiones se persisten en `sessions.json` y se cargan al iniciar.

### Revocación

| Endpoint | Permiso | Acción |
|----------|---------|--------|
| `GET /api/v1/sessions` | `sessions_view` | Lista sesiones activas |
| `POST /api/v1/sessions/revoke/<sid>` | `sessions_revoke` | Revoca una sesión concreta |
| `POST /api/v1/sessions/revoke-user/<user>` | `sessions_revoke` | Revoca todas las sesiones de un usuario |
| `POST /api/v1/sessions/invalidate` | `sessions_revoke` | Revoca **todas** las sesiones |

Una petición con un token revocado (incluso si la cookie Flask sigue siendo válida) recibe **401** en rutas `/api/v1/` o redirección a `/login` en rutas HTML.

El cliente JS detecta el 401 mediante un poll de `/api/v1/me` cada 20 segundos y mediante cualquier llamada API activa. Al detectarlo muestra un toast "Tu sesión ha sido cerrada por un administrador" y redirige al login tras 3,5 segundos.

### Tests de sesiones

| Test | Qué verifica |
|------|-------------|
| `test_session_created_on_login` | Login crea exactamente una entrada en `_sessions` |
| `test_session_token_in_flask_session` | La cookie contiene un token de 64 hex |
| `test_session_records_username` | La entrada registra el nombre de usuario |
| `test_session_removed_on_logout` | Logout elimina la entrada del registro |
| `test_session_invalid_after_revocation` | Token revocado → 401 en `/api/v1/me` |
| `test_forged_session_token_rejected` | Token fabricado a mano → 401 en `/api/v1/me` |
| `test_reused_session_token_after_logout` | Token antiguo re-inyectado → 401 en `/api/v1/me` |
| `test_sessions_persisted_to_file` | Las sesiones se guardan en `sessions.json` |
| `test_api_revoke_session_404` | Revocar sesión inexistente → 404 |
| `test_sessions_api_admin_only` | No-admin → 403 en todos los endpoints de sesiones |
| `test_invalidate_all_sessions` | Invalida todas las sesiones, vacía `_sessions` |

---

## Control de Acceso Basado en Roles (RBAC)

### Sistema de permisos granulares

El sistema usa **23 flags de permiso por acción** en lugar de roles monolíticos.
Cada endpoint está protegido por el permiso exacto que necesita:

| Recurso | Permiso |
|---------|--------|
| Listar usuarios | `users_view` |
| Crear usuarios | `users_add` |
| Editar usuarios | `users_edit` |
| Eliminar usuarios | `users_delete` |
| Ver roles | `roles_view` |
| Crear roles | `roles_add` |
| Editar roles | `roles_edit` |
| Eliminar roles | `roles_delete` |
| Ver grupos | `groups_view` |
| Crear grupos | `groups_add` |
| Editar grupos | `groups_edit` |
| Eliminar grupos | `groups_delete` |
| Ver auditoría | `audit_view` |
| Borrar auditoría | `audit_delete` |
| Ver módulos | `modules_view` |
| Crear entradas de módulo | `modules_add` |
| Editar módulos | `modules_edit` |
| Leer configuración (solo lectura) | `config_view` |
| Editar configuración | `config_edit` |
| Ver sesiones | `sessions_view` |
| Revocar sesiones | `sessions_revoke` |
| Ver resultados de checks / pestaña Status | `checks_view` |
| Lanzar checks | `checks_run` |

### Roles integrados

| Rol | Permisos |
|-----|----------|
| `admin` | Todos (23 flags) |
| `editor` | `modules_view`, `modules_add`, `modules_edit`, `config_edit`, `checks_view`, `checks_run`, `audit_view`, `users_view`, `users_edit`, `roles_view`, `roles_edit`, `groups_view`, `groups_edit` |
| `viewer` | `modules_view`, `users_view`, `roles_view`, `groups_view`, `audit_view`, `sessions_view`, `checks_view` |

Los roles integrados **no pueden eliminarse** ni cambiar sus permisos. Sí se puede actualizar su **etiqueta** (`label`) vía `PUT /api/v1/roles/<name>`. Cualquier campo `permissions` en el cuerpo de la petición es ignorado silenciosamente. La etiqueta personalizada se persiste bajo la clave `__builtin_labels__` en `roles.json`.

### Roles personalizados

- Se crean desde la UI o la API (`POST /api/v1/roles`) con cualquier combinación de permisos.
- Se persisten en `roles.json`.
- Los roles integrados no pueden eliminar ni cambiar permisos; solo permiten actualizar la etiqueta.
- No se puede eliminar un rol que tenga usuarios asignados (409).

### Sistema de Grupos

Los grupos permiten asignar uno o varios roles a un conjunto de usuarios.
Los permisos son **aditivos**: el usuario obtiene sus permisos de rol propios más la unión de los permisos de todos los roles de todos sus grupos.

- `administrators` es el único grupo integrado; no puede borrarse ni renombrarse.
- El grupo integrado **sí permite** actualizar sus `roles` y `members` vía `PUT /api/v1/groups/administrators`; los campos `label` y `description` son ignorados en la petición.
- Un usuario puede pertenecer a cero o más grupos.
- El cálculo de permisos efectivos se realiza en cada petición mediante `_get_effective_permissions(username, role)`.

### Implementación

- `_perm_required(*perms)` — factoría de decoradores: la petición pasa si el
  usuario tiene **al menos uno** de los permisos indicados.
- `_get_effective_permissions(username, role)` — devuelve la unión del `frozenset`
  de permisos del rol del usuario más los permisos de todos los roles de todos sus grupos.
- Los permisos desconocidos en un rol personalizado son ignorados silenciosamente.

### Tests de permisos

| Clase | Qué cubre |
|-------|----------|
| `TestPermissionsConstants` | Estructura de `PERMISSIONS`, `PERMISSION_GROUPS` y `BUILTIN_ROLE_PERMISSIONS`; `_get_role_permissions()`; `/api/v1/me` devuelve `permissions` |
| `TestCustomRoles` | CRUD completo de `/api/v1/roles`: crear, editar, borrar, casos de error (duplicado, en uso); actualizar etiqueta de rol builtin (200, permisos sin cambiar); persistencia, auditoría |
| `TestGranularPermissions` | Cada uno de los 21 endpoints acepta/rechaza según su permiso específico; resolución end-to-end de roles personalizados |

### Matriz de acceso por rol (resumen)

| Rol | Ver dashboard | Módulos/Config | Usuarios/Roles/Grupos | Auditoría | Sesiones | Checks/Status |
| --- |:---:|:---:|:---:|:---:|:---:|:---:|
| `viewer` | ✅ | ❌ editar | solo ver | ✅ | ✅ ver | ✅ ver |
| `editor` | ✅ | ✅ | ✅ ver+editar | ✅ | ❌ | ✅ ver+run |
| `admin` | ✅ | ✅ | ✅ completo | ✅ | ✅ | ✅ |

### Decoradores

- `@login_required` — aplicado a todas las rutas protegidas; redirige a `/login` si no hay sesión válida.
- `@write_required` — rechaza viewers con HTTP 403.
- `@admin_required` — rechaza no-admins con HTTP 403.

### Reglas de integridad

- Un usuario **no puede eliminarse a sí mismo** → 400 `"own account"`.
- El **último administrador no puede ser degradado** → 400 `"admin must exist"`.
- Los roles válidos están en una lista cerrada (`admin`, `editor`, `viewer`); cualquier otro valor → 400.

### Tests de RBAC y escalada de privilegios

| Test | Qué verifica |
|------|-------------|
| `test_viewer_cannot_write_modules` | Viewer → 403 en `PUT /api/v1/modules` |
| `test_viewer_cannot_write_config` | Viewer → 403 en `PUT /api/v1/config` |
| `test_viewer_cannot_manage_users` | Viewer → 403 en `POST /api/v1/users` |
| `test_editor_can_write_modules` | Editor → 200 en `PUT /api/v1/modules` |
| `test_editor_can_write_config` | Editor → 200 en `PUT /api/v1/config` |
| `test_editor_cannot_create_or_delete_users` | Editor → 403 en `POST`/`DELETE /api/v1/users`, 200 en `GET /api/v1/users` |
| `test_editor_cannot_access_sessions` | Editor → 403 en `GET /api/v1/sessions` |
| `test_viewer_cannot_access_audit` | Viewer → 403 en `GET /api/v1/audit` |
| `test_self_promotion_via_update` | Viewer intentando `PUT /api/v1/users/viewer` con `role: admin` → 403 |
| `test_viewer_cannot_create_user` | Viewer intentando crear usuario con rol admin → 403 |
| `test_cannot_delete_self` | Admin intentando eliminar su propia cuenta → 400 |
| `test_cannot_remove_last_admin` | Degradar al único admin → 400 |
| `test_invalid_role_rejected` | Rol `superadmin` → 400 |
| `test_update_to_invalid_role_rejected` | Actualizar a rol inválido → 400 |

---

## Cifrado de Credenciales en Disco

Los campos sensibles almacenados en `modules.json` y `config.json` se cifran en reposo usando **Fernet** (AES-128-CBC + HMAC-SHA256) de la librería `cryptography`.

### Campos cifrados

| Nombre del campo | Dónde aparece |
|-----------------|---------------|
| `password` | Contraseña MySQL/MariaDB, contraseña SSH del módulo RAID, etc. |
| `ssh_password` | Contraseña SSH del módulo MySQL (modo túnel) |
| `token` | Token del bot de Telegram en `config.json` |
| `secret` | Cualquier campo con esta clave en módulos futuros |
| `bind_password` | Contraseña de la cuenta de servicio LDAP (`config.json → ldap`) |
| `client_secret` | Client Secret OIDC (`config.json → oidc`) |
| `smtp_password` | Contraseña SMTP para notificaciones por email (`config.json → email`) |
| `ms365_client_secret` | Client Secret de la app Microsoft 365 para email |
| `gmail_client_secret` | Client Secret de la app Gmail para email |

### Derivación de clave

La clave Fernet se deriva del propio archivo `.flask_secret` (el mismo secreto que protege las cookies de sesión Flask):

1. Se leen los primeros 32 bytes del secreto hex almacenado en `data/.flask_secret`.
2. Se codifican en base64 URL-safe → clave Fernet de 256 bits.

No existe un archivo de clave separado. Si `.flask_secret` se borra o cambia, **los valores cifrados existentes ya no podrán descifrarse** (mismo efecto que rotar la secret key: también invalida las sesiones).

### Formato en disco

Los valores cifrados se almacenan con el prefijo `enc:` seguido del token Fernet en base64:

```json
{
    "mysql": {
        "list": {
            "produccion": {
                "password": "enc:gAAAAABn...",
                "ssh_password": "enc:gAAAAABn..."
            }
        }
    },
    "telegram": {
        "token": "enc:gAAAAABn..."
    }
}
```

Los valores sin el prefijo `enc:` (ficheros escritos antes de activar el cifrado) se cargan tal cual — **no se requiere migración**. El cifrado se aplica automáticamente la próxima vez que se guarda desde el panel web.

### Transparencia en tiempo de ejecución

- `WebAdmin._read_config_file` descifra los valores **antes** de enviarlos al navegador.
- `WebAdmin._save_config_file` cifra los campos sensibles **antes** de escribir a disco.
- `Monitor._read_config` descifra `modules.json` y `config.json` al arrancar.
- El resto del código siempre trabaja con texto en claro en memoria.

### Degradación elegante

Si la librería `cryptography` no está instalada, `fernet_from_secret_file` devuelve `None` y el sistema continúa funcionando con valores en texto plano, sin errores.

---

## Hashing de Contraseñas

- `werkzeug.security.generate_password_hash` al crear o cambiar contraseñas. Werkzeug 3.x usa **scrypt** por defecto (más seguro que PBKDF2).
- `werkzeug.security.check_password_hash` al verificar — compatible con cualquier algoritmo soportado por Werkzeug.
- El campo `password_hash` **nunca se expone** en `GET /api/v1/users` ni en ninguna respuesta JSON.

### Política de contraseñas configurable

La validación de contraseñas se controla mediante campos en `config.json → web_admin`:

| Campo | Por defecto | Descripción |
|-------|-------------|-------------|
| `pw_min_len` | `8` | Longitud mínima (1–128). El servidor devuelve 400 si no se cumple. |
| `pw_max_len` | `128` | Longitud máxima (8–256). |
| `pw_require_upper` | `true` | Exige al menos una mayúscula y una minúscula. |
| `pw_require_digit` | `true` | Exige al menos un dígito. |
| `pw_require_symbol` | `false` | Exige al menos un símbolo (`!`, `@`, `#`…). |

Los cambios en estos campos se aplican **en caliente** al guardar `config.json` desde el panel web (sin reiniciar el servidor).

> **Tests:** Los fixtures de pytest usan `pbkdf2:sha256` (más rápido que scrypt) pre-computado una sola vez a nivel de módulo en `conftest.py`. Esto evita recalcular el hash en cada test y permite la ejecución paralela con `pytest-xdist` sin degradación de rendimiento.

### Gestión de contraseñas

| Acción | Quién puede | Endpoint |
|--------|------------|----------|
| Cambiar propia contraseña | Cualquier usuario autenticado | `PUT /api/v1/users/me/password` |
| Resetear contraseña de otro usuario | Admin | `PUT /api/v1/users/<username>` con campo `password` |

El cambio de contraseña propia requiere enviar la contraseña actual (`current_password`); si no coincide → 403.

### Tests de contraseñas

| Test | Qué verifica |
|------|-------------|
| `test_get_users_as_admin` | `password_hash` no aparece en la respuesta de usuarios |
| `test_change_own_password` | Cambio correcto → 200, nueva contraseña válida |
| `test_change_own_password_wrong_current` | Contraseña actual incorrecta → 403 |
| `test_change_own_password_empty_new` | Nueva contraseña vacía → 400 |
| `test_change_password_requires_auth` | Sin sesión → 302 |
| `test_update_user_password` | Admin resetea contraseña de otro usuario → nueva contraseña válida |

---

## Prevención de XSS

- Jinja2 tiene **auto-escape activado** para todas las plantillas HTML.
- Los payloads XSS en campos de usuario (`username`, `display_name`) se almacenan literalmente pero se renderizan escapados en el HTML.
- Las acciones destructivas (eliminar usuario/rol/grupo, revocar sesión) se confirman con un **modal Bootstrap centrado** antes de ejecutarse. Los nombres de usuario se insertan vía `textContent` (no `innerHTML`), por lo que cualquier payload XSS en el nombre no se evalúa como HTML.
- Los mensajes de error del backend (p.ej. en el formulario de login) pasan por el motor de plantillas — nunca se concatenan directamente en HTML.

### Tests de XSS

| Test | Payload probado |
|------|----------------|
| `test_xss_in_display_name` | `<script>alert("xss")</script>` — no aparece sin escapar en el dashboard |
| `test_xss_in_login_form_username` | `<script>alert(1)</script>` en el campo username del login — no se refleja |
| `test_xss_in_username_create` | 7 payloads XSS distintos — servidor no falla (201 o 400/409) |
| `test_ssti_in_display_name` | `{{ config.items() }}` — no se evalúa como template Jinja |
| `test_audit_log_not_injectable` | Payload XSS en auditoría se almacena literalmente |

---

## Protección contra Inyección SQL

ServiceSentry no usa SQL — los datos se guardan en JSON. Sin embargo los tests verifican que payloads SQL en campos de usuario y en parámetros de URL no causan errores ni comportamiento inesperado.

| Test | Payload |
|------|---------|
| `test_sql_injection_in_username` | `admin' OR '1'='1`, `'; DROP TABLE users;--`, etc. — 201 o 400/409 |
| `test_sql_injection_in_user_lookup` | Mismos payloads en `PUT /api/v1/users/<name>` y `DELETE /api/v1/users/<name>` → 404 o 400 |

---

## Protección contra Path Traversal

Los endpoints que aceptan parámetros de ruta (`/lang/<code>`, `/theme/<mode>`, `/api/v1/sessions/revoke/<sid>`) validan los valores contra listas blancas o los tratan como claves opacas, evitando acceso a ficheros del sistema.

| Test | Endpoint | Payloads |
|------|----------|---------|
| `test_path_traversal_lang_endpoint` | `/lang/<code>` | `../../../etc/passwd`, `%2e%2e%2f…`, etc. → 200/302/404, idioma sin cambiar |
| `test_path_traversal_theme_endpoint` | `/theme/<mode>` | `../../etc/shadow` → 200/302/404, tema sin cambiar |
| `test_path_traversal_session_revoke` | `/api/v1/sessions/revoke/<sid>` | `../../../etc/passwd`, URL-encoded → 404 o 400 |
| `test_sql_injection_in_user_lookup` | `/api/v1/users/<name>` | `../../../etc/passwd` → 404 o 400 |

---

## Validación de Payloads JSON

Todos los endpoints JSON validan el cuerpo antes de procesarlo.

| Condición | Respuesta |
|-----------|-----------|
| `Content-Type` no es `application/json` | 400 |
| Cuerpo vacío | 400 |
| JSON mal formado | 400 |
| JSON profundamente anidado (50 niveles) | 200 o 400 (no falla con 500) |
| Payload muy grande (500 claves × 1000 chars) | 200, 400 o 413 (no falla con 500) |
| Bytes nulos (`\x00`) en valores | 201 o 400 |
| Unicode abusivo (RTL override, emoji, cadenas largas) | 201, 400 o 409 |

### Tests de validación JSON

| Test | Qué verifica |
|------|-------------|
| `test_non_json_content_type` | 5 endpoints rechazan `text/plain` con 400 |
| `test_empty_body_json_endpoints` | 4 endpoints rechazan cuerpo vacío con 400 |
| `test_deeply_nested_json` | JSON 50 niveles → no crash |
| `test_very_large_json_payload` | ~500 KB de JSON → no crash |
| `test_null_bytes_in_json_fields` | Bytes nulos → 201 o 400 |
| `test_unicode_abuse_in_fields` | RTL override, null char, emoji, cadena larga → no crash |

---

## Métodos HTTP Incorrectos

Los endpoints rechazan métodos HTTP no esperados con **405 Method Not Allowed**.

```
DELETE /api/v1/modules    → 405
POST   /api/v1/modules    → 405   (se usa PUT)
PATCH  /api/v1/modules    → 405
DELETE /api/v1/config     → 405
POST   /api/v1/config     → 405   (se usa PUT)
PUT    /api/v1/users      → 405   (se usa POST para crear)
PATCH  /api/v1/users/...  → 405
GET    /api/v1/sessions/invalidate → 405
```

---

## Redirección Abierta (Open Redirect)

El parámetro `next` del formulario de login se valida contra el mismo origen — no se permite redirigir a URLs externas.

---

## Registro de Auditoría

Todos los eventos relevantes para la seguridad quedan registrados en `audit.json` con marca de tiempo, usuario, IP y detalle de los cambios a nivel de campo.

| Evento | Cuándo se genera |
|--------|-----------------|
| `login_ok` | Login exitoso |
| `login_failed` | Credenciales inválidas, usuario inexistente o cuenta desactivada. El campo `detail.reason` almacena la clave i18n: `invalid_credentials`, `user_not_found` o `account_disabled` |
| `logout` | Cierre de sesión |
| `modules_saved` | Guardado de `modules.json` (con diff de campos) |
| `config_saved` | Guardado de `config.json` (con diff de campos) |
| `user_created` | Creación de usuario |
| `user_updated` | Modificación de usuario (con old/new por campo) |
| `user_deleted` | Eliminación de usuario |
| `password_changed` | Usuario cambia su propia contraseña |
| `password_reset` | Admin resetea la contraseña de otro usuario |
| `all_sessions_revoked` | Invalidación global de sesiones |
| `session_revoked` | Revocación de una sesión concreta |
| `user_sessions_revoked` | Revocación de todas las sesiones de un usuario |
| `group_created` | Creación de grupo |
| `group_updated` | Modificación de grupo (roles, miembros, label o descripción) |
| `group_deleted` | Eliminación de grupo |
| `role_created` | Creación de rol personalizado |
| `role_updated` | Modificación de rol (etiqueta o permisos) |
| `role_deleted` | Eliminación de rol personalizado |
| `checks_run` | Ejecución manual de comprobaciones desde la UI |

### Enmascarado de datos sensibles

Los campos sensibles (`token`, `password`, claves de contraseña) se muestran como `***` en el diff almacenado en auditoría — **nunca** se registra el valor real.

### Límite de entradas

El log se recorta automáticamente a `_AUDIT_MAX_ENTRIES` entradas (≤ 500) para evitar crecimiento ilimitado en disco.

### Tests de auditoría

| Test | Qué verifica |
|------|-------------|
| `test_login_audited` | Login correcto → evento `login_ok` |
| `test_failed_login_audited` | Login fallido → evento `login_failed` |
| `test_failed_login_reason_invalid_credentials` | Contraseña errónea → `detail.reason == 'invalid_credentials'` |
| `test_failed_login_reason_user_not_found` | Usuario inexistente → `detail.reason == 'user_not_found'` |
| `test_failed_login_reason_account_disabled` | Cuenta desactivada → `detail.reason == 'account_disabled'` |
| `test_logout_audited` | Logout → evento `logout` |
| `test_modules_save_audited` | Cambio en módulos → evento con diff de campos |
| `test_config_save_audited` | Cambio en config → evento con diff de campos |
| `test_config_save_records_old_and_new` | Diff incluye valores anterior y nuevo |
| `test_sensitive_fields_masked_in_audit` | Token de Telegram → `***` en auditoría |
| `test_user_create_audited` | Creación de usuario → evento con username y rol |
| `test_user_update_audited` | Actualización → evento con diff por campo |
| `test_user_delete_audited` | Eliminación → evento con username |
| `test_password_change_audited` | Cambio de contraseña propia → evento |
| `test_admin_password_reset_audited` | Reset por admin → evento `password_reset` |
| `test_password_reset_separate_from_update` | Cambio de rol + contraseña → dos eventos separados |
| `test_all_sessions_revoked_audited` | Invalidación global → evento |
| `test_audit_api_admin_only` | No-admin → 403 en `GET /api/v1/audit` |
| `test_audit_persisted_to_file` | Log guardado en `audit.json` |
| `test_audit_max_entries` | Log recortado a `_AUDIT_MAX_ENTRIES` |
| `test_no_update_audit_when_no_changes` | Sin cambios reales → no emite `user_updated` |
| `test_diff_dicts_helper` | `_diff_dicts` detecta solo campos modificados, anidados |

---

## Acceso No Autenticado

Las rutas `/api/v1/*` devuelven **401 JSON** ante peticiones sin sesión válida. Las rutas HTML (dashboard, login) devuelven **302** redirect a `/login`. Esto permite que el cliente JS detecte la sesión expirada sin seguir el redirect automáticamente.

Lista completa verificada en `test_unauthenticated_api_access`:

```
GET  /api/v1/modules        GET  /api/v1/config         GET  /api/v1/modules/status
GET  /api/v1/modules/overview       GET  /api/v1/users           POST /api/v1/users
PUT  /api/v1/users/<x>      DELETE /api/v1/users/<x>     PUT  /api/v1/users/me/password
GET  /api/v1/sessions       POST /api/v1/sessions/invalidate
POST /api/v1/sessions/revoke/<x>   GET /api/v1/audit     GET  /api/v1/me
```

---

## Política SSH (Ejecución Remota)

La clase `Exec` en `lib/exe.py` usa `paramiko.RejectPolicy` como política de hosts SSH. Los hosts que no estén en `~/.ssh/known_hosts` son rechazados — no se aceptan conexiones a hosts desconocidos de forma silenciosa.
