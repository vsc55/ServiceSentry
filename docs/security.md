# Seguridad del Panel Web

Referencia completa de los mecanismos de seguridad implementados en la interfaz web de administración (`lib/web_admin`) y los tests que los verifican (`tests/test_web_admin.py`).

---

## Autenticación

### Flujo de login

1. `POST /login` recibe `username` + `password`.
2. Se busca el usuario en `users.json`; si no existe → respuesta genérica **"Invalid credentials"** (mismo mensaje para usuario inexistente que para contraseña errónea — evita enumeración de usuarios).
3. La contraseña se verifica con `werkzeug.security.check_password_hash` (PBKDF2-SHA256).
4. Si es correcta → se crea una entrada en el **registro de sesiones** del servidor (`_sessions`) con un token de 32 bytes aleatorios (64 hex) y se guarda en la cookie de sesión Flask.
5. El evento `login_ok` o `login_failed` se escribe en el **registro de auditoría**.

### Sesiones persistentes ("Remember me")

- El formulario de login incluye un checkbox `remember_me`.
- Si se activa, `session.permanent = True` (duración configurable).
- La `secret_key` de Flask se genera aleatoriamente la primera vez y se persiste en disco (`secret_key.txt`); las instancias posteriores reutilizan la misma clave — las sesiones no se invalidan al reiniciar el proceso.

### Tests de autenticación

| Test | Qué verifica |
|------|-------------|
| `test_root_redirects_to_login` | Ruta `/` redirige a `/login` sin sesión |
| `test_login_success` | Login correcto da acceso al dashboard |
| `test_login_wrong_password` | Contraseña incorrecta → página de login + mensaje de error |
| `test_login_wrong_username` | Usuario inexistente → mismo mensaje genérico (sin enumerar) |
| `test_login_empty_fields` | Credenciales vacías → rechazado |
| `test_logout` | Logout invalida la sesión; rutas protegidas redirigen a login |
| `test_login_with_remember_me` | `remember_me` marca la sesión como permanente |
| `test_secret_key_persisted` | La `secret_key` se escribe en disco al crear la instancia |
| `test_secret_key_reused` | Una segunda instancia reutiliza la clave existente |

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

| Endpoint | Rol | Acción |
|----------|-----|--------|
| `GET /api/sessions` | admin | Lista sesiones activas |
| `POST /api/sessions/revoke/<sid>` | admin | Revoca una sesión concreta |
| `POST /api/sessions/revoke-user/<user>` | admin | Revoca todas las sesiones de un usuario |
| `POST /api/sessions/invalidate` | admin | Revoca **todas** las sesiones |

Una petición con un token revocado (incluso si la cookie Flask sigue siendo válida) es redirigida a `/login`.

### Tests de sesiones

| Test | Qué verifica |
|------|-------------|
| `test_session_created_on_login` | Login crea exactamente una entrada en `_sessions` |
| `test_session_token_in_flask_session` | La cookie contiene un token de 64 hex |
| `test_session_records_username` | La entrada registra el nombre de usuario |
| `test_session_removed_on_logout` | Logout elimina la entrada del registro |
| `test_session_invalid_after_revocation` | Token revocado → redirige a login |
| `test_forged_session_token_rejected` | Token fabricado a mano → redirige a login |
| `test_reused_session_token_after_logout` | Token antiguo re-inyectado → redirige a login |
| `test_sessions_persisted_to_file` | Las sesiones se guardan en `sessions.json` |
| `test_api_revoke_session_404` | Revocar sesión inexistente → 404 |
| `test_sessions_api_admin_only` | No-admin → 403 en todos los endpoints de sesiones |
| `test_invalidate_all_sessions` | Invalida todas las sesiones, vacía `_sessions` |

---

## Control de Acceso por Roles (RBAC)

Tres roles con permisos acumulativos:

| Rol | Puede leer | Puede guardar config/módulos | Gestiona usuarios | Gestiona sesiones | Accede al log de auditoría |
|-----|-----------|-----------------------------|--------------------|-------------------|-----------------------------|
| `viewer` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `editor` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `admin` | ✅ | ✅ | ✅ | ✅ | ✅ |

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
| `test_viewer_cannot_write_modules` | Viewer → 403 en `PUT /api/modules` |
| `test_viewer_cannot_write_config` | Viewer → 403 en `PUT /api/config` |
| `test_viewer_cannot_manage_users` | Viewer → 403 en `POST /api/users` |
| `test_editor_can_write_modules` | Editor → 200 en `PUT /api/modules` |
| `test_editor_can_write_config` | Editor → 200 en `PUT /api/config` |
| `test_editor_cannot_manage_users` | Editor → 403 en todos los endpoints de usuarios |
| `test_editor_cannot_access_sessions` | Editor → 403 en `GET /api/sessions` |
| `test_viewer_cannot_access_audit` | Viewer → 403 en `GET /api/audit` |
| `test_self_promotion_via_update` | Viewer intentando `PUT /api/users/viewer` con `role: admin` → 403 |
| `test_viewer_cannot_create_user` | Viewer intentando crear usuario con rol admin → 403 |
| `test_cannot_delete_self` | Admin intentando eliminar su propia cuenta → 400 |
| `test_cannot_remove_last_admin` | Degradar al único admin → 400 |
| `test_invalid_role_rejected` | Rol `superadmin` → 400 |
| `test_update_to_invalid_role_rejected` | Actualizar a rol inválido → 400 |

---

## Hashing de Contraseñas

- `werkzeug.security.generate_password_hash` (PBKDF2-SHA256) al crear o cambiar contraseñas.
- `werkzeug.security.check_password_hash` al verificar.
- El campo `password_hash` **nunca se expone** en `GET /api/users` ni en ninguna respuesta JSON.

### Gestión de contraseñas

| Acción | Quién puede | Endpoint |
|--------|------------|----------|
| Cambiar propia contraseña | Cualquier usuario autenticado | `PUT /api/users/me/password` |
| Resetear contraseña de otro usuario | Admin | `PUT /api/users/<username>` con campo `password` |

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
| `test_sql_injection_in_user_lookup` | Mismos payloads en `PUT /api/users/<name>` y `DELETE /api/users/<name>` → 404 o 400 |

---

## Protección contra Path Traversal

Los endpoints que aceptan parámetros de ruta (`/lang/<code>`, `/theme/<mode>`, `/api/sessions/revoke/<sid>`) validan los valores contra listas blancas o los tratan como claves opacas, evitando acceso a ficheros del sistema.

| Test | Endpoint | Payloads |
|------|----------|---------|
| `test_path_traversal_lang_endpoint` | `/lang/<code>` | `../../../etc/passwd`, `%2e%2e%2f…`, etc. → 200/302/404, idioma sin cambiar |
| `test_path_traversal_theme_endpoint` | `/theme/<mode>` | `../../etc/shadow` → 200/302/404, tema sin cambiar |
| `test_path_traversal_session_revoke` | `/api/sessions/revoke/<sid>` | `../../../etc/passwd`, URL-encoded → 404 o 400 |
| `test_sql_injection_in_user_lookup` | `/api/users/<name>` | `../../../etc/passwd` → 404 o 400 |

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
DELETE /api/modules    → 405
POST   /api/modules    → 405   (se usa PUT)
PATCH  /api/modules    → 405
DELETE /api/config     → 405
POST   /api/config     → 405   (se usa PUT)
PUT    /api/users      → 405   (se usa POST para crear)
PATCH  /api/users/...  → 405
GET    /api/sessions/invalidate → 405
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
| `login_failed` | Contraseña incorrecta o usuario inexistente |
| `logout` | Cierre de sesión |
| `modules_saved` | Guardado de `modules.json` (con diff de campos) |
| `config_saved` | Guardado de `config.json` (con diff de campos) |
| `user_created` | Creación de usuario |
| `user_updated` | Modificación de usuario (con old/new por campo) |
| `user_deleted` | Eliminación de usuario |
| `password_changed` | Usuario cambia su propia contraseña |
| `password_reset` | Admin resetea la contraseña de otro usuario |
| `all_sessions_revoked` | Invalidación global de sesiones |
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
| `test_audit_api_admin_only` | No-admin → 403 en `GET /api/audit` |
| `test_audit_persisted_to_file` | Log guardado en `audit.json` |
| `test_audit_max_entries` | Log recortado a `_AUDIT_MAX_ENTRIES` |
| `test_no_update_audit_when_no_changes` | Sin cambios reales → no emite `user_updated` |
| `test_diff_dicts_helper` | `_diff_dicts` detecta solo campos modificados, anidados |

---

## Acceso No Autenticado

Todos los endpoints protegidos devuelven 302 (redirect a `/login`), 401 o 403 ante peticiones sin sesión válida.

Lista completa verificada en `test_unauthenticated_api_access`:

```
GET  /api/modules        GET  /api/config         GET  /api/status
GET  /api/overview       GET  /api/users           POST /api/users
PUT  /api/users/<x>      DELETE /api/users/<x>     PUT  /api/users/me/password
GET  /api/sessions       POST /api/sessions/invalidate
POST /api/sessions/revoke/<x>   GET /api/audit     GET  /api/me
```

---

## Política SSH (Ejecución Remota)

La clase `Exec` en `lib/exe.py` usa `paramiko.RejectPolicy` como política de hosts SSH. Los hosts que no estén en `~/.ssh/known_hosts` son rechazados — no se aceptan conexiones a hosts desconocidos de forma silenciosa.
