# Interfaz Web de Administración

ServiceSentry incluye un panel de administración web basado en **Flask**.
Permite gestionar módulos, configuración y usuarios sin tocar archivos directamente.

---

## Organización del Código

La lógica de `WebAdmin` está dividida en **mixins** (lógica de negocio) y **routes** (registro de rutas Flask):

```
lib/web_admin/
├── app.py                    # class WebAdmin (hereda todos los mixins)
├── auth/
│   ├── __init__.py
│   ├── ldap_auth.py          # autenticación LDAP/AD (requiere ldap3)
│   ├── oidc_auth.py          # SSO OIDC/OAuth2, rutas /auth/oidc/* (requiere authlib)
│   └── saml_auth.py          # SSO SAML2, rutas /auth/saml2/* (requiere pysaml2) [alpha]
├── email_notify.py           # envío de notificaciones por email (SMTP / MS365 / Gmail)
├── email_templates.py        # motor de plantillas HTML para email (test, alert, summary)
├── notification_dispatcher.py# despachador central de notificaciones (Telegram, Email, Webhook)
├── mixins/
│   ├── users.py              # _UsersMixin
│   ├── roles.py              # _RolesMixin
│   ├── groups.py             # _GroupsMixin
│   ├── permissions.py        # _PermissionsMixin
│   ├── sessions.py           # _SessionsMixin (sesiones + clave secreta Flask)
│   ├── audit.py              # _AuditMixin
│   ├── checks.py             # _ChecksMixin
│   └── daemon.py             # _DaemonMixin (planificador en segundo plano)
└── routes/
    ├── __init__.py           # register_all(app, wa)
    ├── auth/
    │   ├── __init__.py       # /login, /logout (integra LDAP + OIDC + SAML2)
    │   ├── ldap.py           # /api/v1/auth/ldap/* (test, groups, group_lookup)
    │   └── entra.py          # /api/v1/auth/entra/* (wizard Device Code, groups, group_lookup)
    ├── modules/
    │   ├── __init__.py       # /api/v1/modules, /api/v1/modules/status, /api/v1/modules/overview
    │   └── checks.py         # /api/v1/modules/checks/run
    ├── users/
    │   ├── __init__.py       # /api/v1/users, /api/v1/me
    │   ├── groups.py         # /api/v1/groups
    │   └── roles.py          # /api/v1/roles
    ├── sessions/
    │   ├── __init__.py       # /api/v1/sessions, /api/v1/sessions/invalidate, /api/v1/sessions/revoke/*
    │   └── audit.py          # /api/v1/audit
    ├── notify/
    │   ├── __init__.py       # registro de subrutas de notificación
    │   ├── telegram.py       # /api/v1/notify/telegram/test
    │   ├── email.py          # /api/v1/notify/email/test
    │   ├── webhook.py        # /api/v1/notify/webhook/test
    │   └── templates.py      # /api/v1/notify/templates, /api/v1/notify/html-templates
    ├── config.py             # /api/v1/config, /api/v1/config/versions, /api/v1/config/schema
    ├── webhooks.py           # /api/v1/webhooks (CRUD de webhooks)
    ├── watchfuls.py          # /api/v1/watchfuls/<module>/<action>
    ├── history.py            # /api/v1/history (índice, consulta, borrado, diagnóstico)
    ├── daemon.py             # /api/v1/daemon (estado, start, stop, config del planificador)
    ├── status.py             # /status (página pública de estado)
    ├── errors.py             # handlers 400, 403, 404, 405, 500
    └── ui.py                 # /, /api/v1/me, /api/v1/health, /lang, /theme
```

---

## Iniciar la Interfaz Web

```bash
python3 main.py --web
```

Abre `http://localhost:8080` (o el host/puerto configurado) en el navegador.

---

## Características

| Característica | Descripción |
|---------------|-------------|
| **Panel de módulos** | Habilitar/deshabilitar módulos, configurar ítems con formularios generados automáticamente desde los schemas; barra de herramientas con **Añadir**, **Recargar** (descarta cambios y recarga desde el servidor) y **Deshacer** (revierte cambios no guardados al último estado guardado) |
| **Servers (hosts)** | Define un servidor una vez (dirección + perfiles de conexión por protocolo: ssh/snmp/db/http/tls…) y vincúlalo desde los checks de cualquier módulo, que heredan dirección + credenciales. Asistente "Detectar duplicados" que agrupa conexiones inline repetidas en hosts compartidos. Secretos cifrados en la BD general. Ver §[Servers (registro de hosts)](#servers-registro-de-hosts) |
| **Dashboard personalizable** | Widgets arrastrables, redimensionables y ocultables; posición, tamaño y visibilidad persistidos por usuario en `localStorage`; modo edición con barra de herramientas por widget (ancho en columnas 2–12, altura sm/md/lg/xl, drag-and-drop HTML5) |
| **Vista general (Overview)** | 6 tarjetas de resumen (Modules, Checks, Sessions, Users, Groups, Roles) + 2 widgets de tabla (lista de módulos con estado por check, actividad reciente); auto-refresco configurable (OFF / 10 s / 30 s / 60 s); columnas ordenables |
| **Pestaña de configuración** | Editar `config.json` (Telegram, daemon, idioma) directamente desde el navegador; paneles colapsables por sección |
| **Paginación configurable** | Tamaño de página por defecto (`default_page_size`) y lista de opciones (`page_sizes`) configurables desde la pestaña de configuración → sección Tablas |
| **Página de estado pública** | `/status` sin autenticación (cuando `public_status=true`); tarjetas colapsables por módulo, auto-refresco configurable, siempre visible para usuarios logueados |
| **Páginas de error personalizadas** | 400/403/404/405/500 con tema dark/light heredado de la sesión; las rutas `/api/v1/*` devuelven JSON en lugar de HTML |
| **Gestión de usuarios** | Crear, editar y eliminar usuarios; asignar roles y grupos; cambiar contraseña propia; activar/desactivar cuenta desde el modal |
| **Roles y permisos** | Roles integrados (`admin`, `editor`, `viewer`) + rol especial `none` (sin permisos, por defecto en nuevos usuarios y grupos) + roles personalizados con 28 flags granulares; activar/desactivar desde el modal |
| **Grupos de usuarios** | Agrupar usuarios bajo uno o más roles; los permisos de los grupos se suman a los del rol individual del usuario; grupo `administrators` integrado; activar/desactivar desde el modal |
| **Autenticación LDAP / AD** | Login con credenciales de Active Directory o cualquier servidor LDAP compatible. Sincronización automática de usuarios en primer login. Mapeo grupo → rol configurable. Soporte de login por email (`allow_email_login`). Requiere el paquete opcional `ldap3`. |
| **SSO OIDC / OAuth2** | Login mediante proveedor externo (Microsoft Entra ID, Google, Keycloak…). Botón "Login with SSO" en la pantalla de login. Mapeo de claims y grupos a roles. Wizard de registro automático en Entra ID (Device Code Flow). Requiere `authlib`. |
| **SSO SAML2** | Login federado mediante SAML2 (cualquier IdP compatible: ADFS, Keycloak, Okta…). Rutas `/auth/saml2/login`, `/auth/saml2/acs`, `/auth/saml2/metadata`. Sincronización automática de usuarios y mapeo de grupos a roles. Requiere `python3-saml`. [alpha] |
| **Notificaciones por Email** | Envío de alertas por correo vía SMTP, Microsoft 365 (Graph API) o Gmail (OAuth2). Plantilla HTML personalizable por idioma y tipo (alert/summary/test). Configurable desde la pestaña Configuración → Notifications. |
| **Webhooks** | Lista de webhooks HTTP personalizables para notificaciones salientes. Cada webhook tiene URL, método (POST/PUT/GET), cabeceras personalizadas, plantilla de cuerpo JSON, timeout, secreto HMAC opcional y flag habilitado/deshabilitado. Se gestionan con un modal dedicado en la pestaña de configuración → Notifications. |
| **Despachador de notificaciones** | `notification_dispatcher.dispatch()` enruta cada evento a los canales habilitados (Telegram, Email, Webhook) según la matriz de routing configurable en `config.json → notifications`. |
| **Plantillas de notificación** | Editor de cadenas de texto (sujetos, badges, frases) con soporte multi-idioma y sobrescritura por idioma. Editor de HTML (con CodeMirror 5, resaltado de sintaxis, autocompletado, formateo, previsualización en vivo) para la plantilla del cuerpo de email. |
| **Prueba de Telegram** | Enviar un mensaje de prueba para verificar la conectividad del bot |
| **Modo oscuro** | Preferencia por usuario, persistida entre sesiones |
| **Persistencia de pestaña activa** | La pestaña activa se guarda en `localStorage` y se restaura al recargar la página (F5); si la pestaña guardada deja de existir o el usuario pierde acceso, se muestra la pestaña por defecto |
| **i18n** | Inglés y español; seleccionable por usuario y configurable globalmente con `web_admin.lang` |
| **Registro de auditoría** | Seguimiento de cambios a nivel de campo con enmascarado de datos sensibles |
| **Gestión de sesiones** | Ver sesiones activas en tarjetas con animación hover; revocación con animación de desvanecimiento; auto-refresco del tab Access cada 30 s; poll de keepalive cada 20 s — si la sesión es revocada por otro admin, el usuario ve un toast y es redirigido al login automáticamente |
| **Soporte proxy inverso** | `proxy_count` activa `ProxyFix` de Werkzeug para leer la IP real del cliente cuando Flask está detrás de uno o más proxies (nginx, Traefik…) |

---

## Roles de Usuario

![Gestión de acceso](images/access_tab.svg)

### Roles integrados

| Rol | Permisos |
|-----|----------|
| `admin` | Todos los permisos (28 flags) |
| `editor` | `modules_view`, `modules_add`, `modules_edit`, `config_edit`, `checks_view`, `checks_run`, `audit_view`, `users_view`, `users_edit`, `roles_view`, `roles_edit`, `groups_view`, `groups_edit` |
| `viewer` | `modules_view`, `users_view`, `roles_view`, `groups_view`, `audit_view`, `sessions_view`, `checks_view` |

> Los roles integrados **no pueden eliminarse** ni cambiar sus permisos via API. Sí permiten actualizar la **etiqueta** (`label`) y gestionar qué usuarios y grupos tienen ese rol asignado. La etiqueta personalizada se persiste en `roles.json` bajo la clave `__builtin_labels__`.

### Roles personalizados

Se pueden crear roles adicionales desde la pestaña **Acceso → Roles** asignando
cualquier combinación de los 28 permisos disponibles. Los roles personalizados se
persisten en `roles.json`.

```
/api/v1/roles             POST   → crear rol
/api/v1/roles/<name>      PUT    → editar rol
/api/v1/roles/<name>      DELETE → eliminar rol (falla si hay usuarios asignados)
```

---

## Grupos de Usuarios

Los grupos permiten asignar uno o varios **roles** a un conjunto de usuarios.
Los permisos son **aditivos**: el usuario obtiene sus permisos de rol propios más
la unión de los permisos de todos los roles de todos sus grupos.

### Grupo integrado

| Grupo | Roles | Notas |
|-------|-------|-------|
| `administrators` | `admin` | No puede borrarse; permite editar roles asignados y miembros; `label`/`description` son inmutables |

### API de grupos

```
/api/v1/groups             GET    → listar grupos con miembros y roles
/api/v1/groups             POST   → crear grupo
/api/v1/groups/<name>      PUT    → editar roles y miembros (label/description ignorados en builtin)
/api/v1/groups/<name>      DELETE → eliminar grupo (403 si es builtin)
```

Cada grupo tiene:
- `roles: []` — lista de nombres de rol cuyos permisos se añaden a los miembros
- `members` — calculado dinámicamente a partir de `users.json` (campo `groups` de cada usuario)

---

## Sistema de Permisos

El sistema de control de acceso usa **28 flags granulares** por acción y recurso.

| Grupo | Permiso | Descripción |
|-------|---------|-------------|
| **Usuarios** | `users_view` | Ver la lista de usuarios |
| | `users_add` | Crear usuarios |
| | `users_edit` | Editar propiedades / rol de usuarios |
| | `users_delete` | Eliminar usuarios |
| **Roles** | `roles_view` | Ver la lista de roles |
| | `roles_add` | Crear roles personalizados |
| | `roles_edit` | Editar roles personalizados |
| | `roles_delete` | Eliminar roles personalizados |
| **Grupos** | `groups_view` | Ver la lista de grupos |
| | `groups_add` | Crear grupos |
| | `groups_edit` | Editar grupos |
| | `groups_delete` | Eliminar grupos |
| **Auditoría** | `audit_view` | Leer el registro de auditoría |
| | `audit_delete` | Borrar entradas del registro |
| **Módulos** | `modules_view` | Ver la lista de módulos |
| | `modules_add` | Crear nuevas entradas de módulo |
| | `modules_edit` | Guardar cambios en módulos |
| | `modules_delete` | Eliminar entradas de módulo |
| **Config** | `config_view` | Leer `config.json` sin poder editarlo |
| | `config_edit` | Guardar cambios en configuración |
| **Overview** | `overview_view` | Ver el dashboard de resumen |
| | `overview_edit` | Editar el layout del dashboard |
| **Sesiones** | `sessions_view` | Ver sesiones activas |
| | `sessions_revoke` | Revocar sesiones |
| **Checks** | `checks_view` | Ver resultados de checks y la pestaña Status |
| | `checks_run` | Lanzar comprobaciones bajo demanda |
| **Historial** | `history_view` | Ver gráficas y series temporales del historial |
| | `history_delete` | Borrar datos del historial |

> Además de los 28 flags globales, cada módulo expone **permisos a nivel de módulo** dinámicos (`module.<nombre>.view`, `.add`, `.edit`, `.delete`) que permiten restringir el acceso a un módulo concreto.

### Implementación interna

- `PERMISSIONS` — tupla con los 28 flags.
- `PERMISSION_GROUPS` — lista de `(key_i18n, [perms])` para renderizar el modal de edición de roles agrupado.
- `BUILTIN_ROLE_PERMISSIONS` — dict `{role: frozenset}` para los roles integrados.
- `_perm_required(*perms)` — factoría de decoradores: acepta si el usuario tiene **alguno** de los permisos indicados.
- `_get_effective_permissions(username, role)` — devuelve la unión del frozenset del rol del usuario más los permisos de todos los roles de todos sus grupos.
- `GET /api/v1/me` — incluye el campo `permissions: list[str]` con los permisos efectivos de la sesión activa.

### Restricción de roles en la UI

La función JS `applyRoleRestrictions()` (en `_js_init.html`) oculta o muestra
botones y pestañas según los permisos del usuario actual obtenidos de `/api/v1/me`:

- Pestaña Usuarios: visible si tiene cualquier permiso `users_*`.
- Pestaña Auditoría: visible si tiene `audit_view`.
- Pestaña Status: visible si tiene `checks_view` o `checks_run`; oculta cuando ninguno de los dos está activo.
- Botón "Nuevo usuario": solo si `users_add`.
- Botones editar/borrar de cada usuario: solo si `users_edit` / `users_delete`.
- Botón limpiar audit / borrar entrada: solo si `audit_delete`.
- Botón "Nuevo rol" y sección de roles: solo si tiene cualquier permiso `roles_*`.
- Widget "Lista de módulos" del dashboard: oculto cuando falta `modules_view` (las tarjetas de resumen sí son siempre visibles).

---

## Seguridad

- Contraseñas hasheadas con `werkzeug.security` (scrypt por defecto en Werkzeug 3.x; los tests usan `pbkdf2:sha256` para acelerar la ejecución paralela).
- Contraseña nueva mínimo 8 caracteres; validada en el servidor.
- Límites de longitud aplicados en el servidor: username ≤ 64 chars, display_name ≤ 128, group name ≤ 64, label ≤ 128, description ≤ 512.
- Redireccionamientos validados contra el mismo origen (evita open redirect).
- Nombres de usuario escapados en mensajes de la UI (evita XSS en títulos de modales).
- Sesiones revocables desde el panel de administración.
- Las acciones destructivas (eliminar usuario/rol/grupo, revocar sesión) se confirman con un modal Bootstrap centrado antes de ejecutarse — nunca con `confirm()` nativo del navegador.
- Política de host SSH por defecto cambiada a `RejectPolicy` (hosts desconocidos rechazados).
- Campos sensibles (contraseñas, tokens) enmascarados en el diff del registro de auditoría.

---

## Endpoints REST

![Pestaña configuración](images/config_tab.svg)

Todos los endpoints requieren autenticación (cookie de sesión) salvo los indicados como *público*.
El permiso requerido se indica entre paréntesis.

### Estado público

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/status` | público* | Página de estado de los servicios. *Requiere `public_status=true` para acceso anónimo; los usuarios autenticados siempre pueden acceder. |

### Autenticación

| Método | Ruta | Descripción |
| ------ | ---- | ----------- |
| `POST` | `/login` | Iniciar sesión con usuario y contraseña (también maneja LDAP si está habilitado) |
| `GET` | `/logout` | Cerrar sesión e invalidar la sesión actual |
| `GET` | `/auth/oidc/login` | Inicia el flujo OIDC; redirige al IdP (requiere `oidc.enabled = true` y `authlib`) |
| `GET` | `/auth/oidc/callback` | Callback OIDC; crea sesión tras verificar el token del IdP |
| `GET` | `/auth/saml2/login` | Inicia flujo SAML2; redirige al IdP (requiere `saml2.enabled = true` y `pysaml2`) |
| `POST` | `/auth/saml2/acs` | Assertion Consumer Service: procesa la respuesta SAML del IdP y crea sesión |
| `GET` | `/auth/saml2/metadata` | Devuelve el XML de metadatos de la aplicación para registrarla en el IdP |

### Módulos

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/modules` | `modules_view` | Obtener todas las configuraciones de módulos |
| `PUT` | `/api/v1/modules` | `modules_edit` | Guardar todas las configuraciones de módulos |
| `GET` | `/api/v1/modules/status` | `checks_view` o `checks_run` | Obtener el contenido de `status.json` (solo lectura) |
| `GET` | `/api/v1/modules/overview` | auth | Obtener resumen del dashboard (módulos, checks, sesiones, usuarios, grupos, roles, últimos eventos) |

### Servers (registro de hosts)

Define un servidor una vez (dirección + perfiles de conexión por protocolo) y
reutilízalo desde los checks de cualquier módulo. Los secretos de los perfiles
se enmascaran en lectura y se restauran al guardar (igual que `modules.json`).

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/hosts` | `modules_view` | Listar hosts (secretos enmascarados) |
| `POST` | `/api/v1/hosts` | `modules_edit` | Crear un host `{name, address, tags, description, profiles}` |
| `PUT` | `/api/v1/hosts/<uid>` | `modules_edit` | Actualizar un host (secretos omitidos se conservan) |
| `DELETE` | `/api/v1/hosts/<uid>` | `modules_edit` | Eliminar un host |
| `GET` | `/api/v1/hosts/migrate/preview` | `modules_edit` | Propuesta de migración: agrupa conexiones inline repetidas (secretos enmascarados) |
| `POST` | `/api/v1/hosts/migrate/apply` | `modules_edit` | Crear hosts para los candidatos aceptados `{accept:[{id,name}]}` y vincular los checks |

Un host se guarda en la BD general (tabla `hosts`); `profiles` es un JSON
`{protocolo: {campo: valor}}` (ssh/snmp/db/http/tls…). Los protocolos y sus
campos los aporta cada módulo vía `__host_profile__` (ver guía de módulos §4d).

**Vincular un check a un host.** En la config de un módulo host-capaz, cada ítem
muestra un selector **Host**: al elegir uno, los campos de conexión se ocultan y
el check hereda dirección + credenciales del host (`resolve_host` en el monitor).
Módulos host-capaces: snmp, ping, datastore, ssl_cert, ntp, web. `dns` se queda
inline (su target es un dominio, no un servidor con credenciales).

**Asistente de migración** (botón "Detectar duplicados" en *Servers*). Escanea
`modules.json`, agrupa ítems por dirección uniéndolos solo si son compatibles
(sin conflicto de credenciales en protocolos compartidos) y agregando perfiles
entre módulos; propone N hosts. Tras confirmar, crea los hosts (credenciales
cifradas) y reescribe los checks con `host_uid`, quitando los campos de conexión
ya poseídos por el host. Es opt-in y reversible por revisión (coexistencia con
los checks inline existentes).

### Configuración

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/config` | `config_view` o `config_edit` | Obtener el `config.json` actual (con tokens de versión por campo) |
| `GET` | `/api/v1/config/versions` | `config_view` o `config_edit` | Poll ligero: devuelve solo los tokens de versión (detección de conflictos) |
| `PUT` | `/api/v1/config` | `config_edit` | Guardar `config.json` (guardado parcial versionado con detección de conflictos) |
| `GET` | `/api/v1/config/schema` | `config_view` o `config_edit` | Obtener el schema de validación de los campos de configuración del web admin |

Los campos numéricos del bloque `web_admin` se validan contra reglas definidas en `INT_RULES` (en `routes/config.py`):

| Clave (`config.json`) | Atributo | Mín | Máx |
|----------------------|----------|-----|-----|
| `web_admin\|remember_me_days` | `_REMEMBER_ME_DAYS` | 1 | 365 |
| `web_admin\|audit_max_entries` | `_AUDIT_MAX_ENTRIES` | 10 | 10000 |
| `web_admin\|status_refresh_secs` | `_STATUS_REFRESH_SECS` | 10 | 3600 |
| `web_admin\|pw_min_len` | `_PW_MIN_LEN` | 1 | 128 |
| `web_admin\|pw_max_len` | `_PW_MAX_LEN` | 8 | 256 |
| `web_admin\|proxy_count` | `_proxy_count` | 0 | 10 |
| `web_admin\|default_page_size` | `_DEFAULT_PAGE_SIZE` | 0 | 200 |
| `web_admin\|lockout_max_attempts` | `_LOCKOUT_MAX_ATTEMPTS` | 0 | 100 |
| `web_admin\|lockout_duration_secs` | `_LOCKOUT_DURATION_SECS` | 60 | 86400 |
| `ldap\|port` | — | 1 | 65535 |
| `ldap\|timeout` | — | 1 | 60 |
| `email\|smtp_port` | — | 1 | 65535 |

Los campos booleanos se validan vía `BOOL_RULES`:

| Clave (`config.json`) | Atributo |
|----------------------|----------|
| `web_admin\|public_status` | `_public_status` |
| `web_admin\|pw_require_upper` | `_PW_REQUIRE_UPPER` |
| `web_admin\|pw_require_digit` | `_PW_REQUIRE_DIGIT` |
| `web_admin\|pw_require_symbol` | `_PW_REQUIRE_SYMBOL` |
| `ldap\|enabled` | — |
| `ldap\|use_ssl` | — |
| `ldap\|fallback_to_local` | — |
| `ldap\|allow_email_login` | — |
| `oidc\|enabled` | — |
| `oidc\|auto_create_users` | — |
| `email\|enabled` | — |
| `email\|smtp_use_tls` | — |
| `email\|smtp_use_ssl` | — |
| `email\|notify_on_down` | — |
| `email\|notify_on_recovery` | — |
| `email\|notify_on_warn` | — |

El endpoint `/api/v1/config/schema` también expone metadatos para:

| Clave | Tipo especial | Descripción |
|-------|---------------|-------------|
| `web_admin\|status_lang` | `options` | Lista de idiomas disponibles + `""` (vacío = usar idioma por defecto) |
| `web_admin\|audit_sort` | `options` | `time`, `event`, `user`, `ip` — campo por el que ordenar el log |
| `web_admin\|default_page_size` | `options_int` | Lista de enteros tomada de `page_sizes`; el select de la UI se regenera al guardar cambios en `page_sizes` |
| `telegram\|chat_id` | `numericString` | Indica al cliente que el valor debe ser una cadena de solo dígitos |

El campo `web_admin.page_sizes` es un array de enteros no negativos que define las opciones de tamaño de página disponibles en todos los listados del panel. Se sanitiza al guardar: se descartan valores no enteros, booleanos y negativos; si el resultado queda vacío, se restaura el valor por defecto `[25, 50, 100, 200, 0]` (donde `0` significa "Todos"). No forma parte de `INT_RULES` ya que su validación es especial (array, no escalar).

### Telegram

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `POST` | `/api/v1/notify/telegram/test` | `config_edit` | Enviar un mensaje de prueba por Telegram |

### Webhooks

Gestión de webhooks HTTP para notificaciones salientes.

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/webhooks` | `config_view` o `config_edit` | Listar todos los webhooks configurados |
| `POST` | `/api/v1/webhooks` | `config_edit` | Crear un nuevo webhook |
| `PUT` | `/api/v1/webhooks/<id>` | `config_edit` | Editar un webhook existente |
| `DELETE` | `/api/v1/webhooks/<id>` | `config_edit` | Eliminar un webhook |
| `POST` | `/api/v1/webhooks/<id>/test` | `config_edit` | Enviar un payload de prueba al webhook |
| `POST` | `/api/v1/notify/webhook/test` | `config_edit` | Probar un webhook con configuración arbitraria (desde el modal) |

Cada webhook almacena: `id` (UUID), `name`, `url`, `method` (POST/PUT/GET), `timeout` (1–60 s), `headers` (JSON), `body_template` (cadena con `{vars}`), `secret` (cifrado en disco), `secret_header`, `enabled`.

### Plantillas de Notificación

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/notify/templates` | `config_view` o `config_edit` | Obtener valores por defecto, sobrescrituras y cadenas por idioma |
| `PUT` | `/api/v1/notify/templates/<lang>` | `config_edit` | Guardar sobrescrituras de cadenas para un idioma |
| `DELETE` | `/api/v1/notify/templates/<lang>` | `config_edit` | Restablecer sobrescrituras de un idioma a los valores por defecto |
| `GET` | `/api/v1/notify/html-templates` | `config_view` o `config_edit` | Obtener plantillas HTML almacenadas y variables disponibles por tipo |
| `PUT` | `/api/v1/notify/html-templates/<type>/<lang>` | `config_edit` | Guardar plantilla HTML personalizada (tipo: `test`, `alert`, `summary`) |
| `DELETE` | `/api/v1/notify/html-templates/<type>/<lang>` | `config_edit` | Eliminar plantilla HTML personalizada (restaura la integrada) |
| `GET` | `/api/v1/notify/html-templates/<type>/built-in` | `config_edit` | Previsualizar la plantilla HTML integrada renderizada con datos de muestra |

### Email (prueba)

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `POST` | `/api/v1/notify/email/test` | `config_edit` | Enviar un email de prueba con la configuración actual (guardada o no) |

### Usuarios

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/users` | `users_view` | Listar todos los usuarios |
| `POST` | `/api/v1/users` | `users_add` | Crear un nuevo usuario |
| `PUT` | `/api/v1/users/<username>` | `users_edit` | Editar un usuario |
| `DELETE` | `/api/v1/users/<username>` | `users_delete` | Eliminar un usuario |
| `GET` | `/api/v1/me` | auth | Obtener información del usuario actual (permisos, preferencias, `table_config`) |
| `PUT` | `/api/v1/users/me/password` | auth | Cambiar la contraseña propia |
| `PUT` | `/api/v1/users/me/preferences` | auth | Guardar preferencias propias: `lang`, `dark_mode` y `table_config` (sin permiso especial) |

**Configuración de tablas por usuario (`table_config`):** cada usuario guarda
su propia configuración de columnas de las tablas del panel (columnas visibles,
orden, ancho y ordenación) en el campo JSON `table_config` dentro de
`users.extra`. Se persiste server-side vía `PUT /api/v1/users/me/preferences` y
se devuelve en `GET /api/v1/me`, de modo que la disposición de columnas se
mantiene entre dispositivos y sesiones.

### Grupos

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/groups` | auth | Listar todos los grupos con miembros y roles |
| `POST` | `/api/v1/groups` | `groups_add` | Crear un grupo |
| `PUT` | `/api/v1/groups/<name>` | `groups_edit` | Editar roles y miembros de un grupo (label/description ignorados en builtin) |
| `DELETE` | `/api/v1/groups/<name>` | `groups_delete` | Eliminar un grupo (403 si es builtin) |

### Roles

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/roles` | auth | Listar todos los roles (integrados + personalizados) |
| `POST` | `/api/v1/roles` | `roles_add` | Crear un rol personalizado |
| `PUT` | `/api/v1/roles/<name>` | `roles_edit` | Editar rol; en integrados solo se acepta `label`; en personalizados acepta `label` y `permissions` |
| `DELETE` | `/api/v1/roles/<name>` | `roles_delete` | Eliminar un rol personalizado |

### Sesiones

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/sessions` | `sessions_view` | Listar sesiones activas |
| `POST` | `/api/v1/sessions/invalidate` | `sessions_revoke` | Revocar todas las sesiones |
| `POST` | `/api/v1/sessions/revoke/<uid>` | `sessions_revoke` | Revocar una sesión concreta |
| `POST` | `/api/v1/sessions/revoke-user/<user>` | `sessions_revoke` | Revocar sesiones de un usuario |

### Auditoría

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/audit` | `audit_view` | Listar entradas del registro de auditoría |
| `DELETE` | `/api/v1/audit` | `audit_delete` | Borrar todas las entradas |
| `DELETE` | `/api/v1/audit/<idx>` | `audit_delete` | Borrar una entrada concreta |

### Checks

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `POST` | `/api/v1/modules/checks/run` | `checks_run` | Lanzar comprobaciones bajo demanda |

### Historial

Series temporales de resultados de checks (almacenadas por `HistoryStore`, ver [architecture.md](architecture.md)).

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/history/index` | `history_view` | Metadatos de todas las series registradas |
| `GET` | `/api/v1/history` | `history_view` | Consultar datos de serie (`module`, `key`, `hours`, `points`, `field`) |
| `DELETE` | `/api/v1/history` | `history_delete` | Borrar el historial de un par `(module, key)` |
| `DELETE` | `/api/v1/history/all` | `history_delete` | Vaciar todo el historial |
| `POST` | `/api/v1/history/test-write` | `history_delete` | Escribir datos de prueba para verificar el almacenamiento |
| `GET` | `/api/v1/history/diag` | `history_delete` | Diagnóstico del almacenamiento de historial |

### Daemon / Planificador

Controla el planificador en segundo plano que ejecuta los checks periódicamente (`_DaemonMixin`).

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/daemon/status` | `checks_run` | Estado actual del planificador |
| `POST` | `/api/v1/daemon/start` | `checks_run` | Arrancar el planificador (opcionalmente ejecuta ya) |
| `POST` | `/api/v1/daemon/stop` | `checks_run` | Detener el planificador |
| `PUT` | `/api/v1/daemon/config` | `checks_run` | Actualizar intervalo (`timer_check`) y autoarranque |

### Salud

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/health` | público | Endpoint ligero para comprobación de versión/arranque (devuelve `startup_id`) |

### LDAP

Requiere `ldap.enabled = true` y el paquete opcional `ldap3`.

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `POST` | `/api/v1/auth/ldap/test` | `config_edit` | Verificar conectividad con el servidor LDAP y, opcionalmente, autenticar un usuario de prueba |
| `POST` | `/api/v1/auth/ldap/groups` | `config_edit` | Listar grupos del directorio LDAP (para poblar el mapeo grupo → rol) |
| `POST` | `/api/v1/auth/ldap/group_lookup` | `config_edit` | Resolver el nombre visible de un grupo LDAP por su DN (usado para auto-completar el mapeo) |

### Entra ID

Wizard interactivo de registro de aplicación en Microsoft Entra ID (Azure AD).

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `POST` | `/api/v1/auth/entra/device-code` | `config_edit` | Inicia el flujo Device Code; devuelve `user_code` para autenticar en el navegador |
| `POST` | `/api/v1/auth/entra/device-poll` | `config_edit` | Sondea el estado del flujo; al completarse crea la app, el service principal y el consentimiento de admin, y devuelve `client_id`, `client_secret`, `tenant_id` y `provider_url` |
| `POST` | `/api/v1/auth/entra/groups` | `config_edit` | Obtiene todos los grupos del tenant mediante las credenciales OIDC guardadas (client credentials flow) |
| `POST` | `/api/v1/auth/entra/group_lookup` | `config_edit` | Resolver el nombre visible de un grupo de Entra ID por su Object ID (usado para auto-completar el mapeo) |

### Watchfuls (acciones dinámicas)

Endpoint genérico para exponer acciones de los módulos watchful a la UI (p.ej. descubrir ítems disponibles, probar conexiones).

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/v1/watchfuls/<module>/<action>` | auth | Invoca `Watchful.<action>()` sin argumentos |
| `POST` | `/api/v1/watchfuls/<module>/<action>` | auth | Invoca `Watchful.<action>(config)` pasando el cuerpo JSON como configuración |

El nombre del módulo y de la acción deben coincidir con la regex `^[a-z][a-z0-9_]*$`. Solo se permiten las acciones declaradas en `WATCHFUL_ACTIONS` de cada módulo.

### Preferencias de UI

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/lang/<lang>` | auth | Establecer preferencia de idioma |
| `GET` | `/theme/<theme>` | auth | Establecer preferencia de tema (light/dark) |

---

## Dashboard Personalizable

La pestaña **Overview** del panel de administración incluye un dashboard totalmente personalizable por usuario. Los cambios se persisten en `localStorage` con la clave `ss_layout2_<username>`.

![Dashboard Overview](images/dashboard_overview.svg)

### Widgets disponibles

| Widget | ID | Descripción |
| ------ | -- | ----------- |
| Modules | `modules` | Tarjeta: total de módulos y cuántos están habilitados |
| Checks | `checks` | Tarjeta: total de checks y resultado (OK / errores) |
| Sessions | `sessions` | Tarjeta: sesiones activas y usuarios conectados |
| Users | `users` | Tarjeta: total de usuarios por rol |
| Groups | `groups` | Tarjeta: total de grupos y membresías |
| Roles | `roles` | Tarjeta: roles integrados + personalizados |
| Module List | `modules_list` | Tabla: módulo, estado activo, resultado de checks, nº de ítems; columnas ordenables |
| Recent Activity | `activity` | Tabla: últimos 10 eventos de auditoría; columnas ordenables |

### Modo edición

Para activar el modo edición, pulsa **✏ Edit Dashboard** en la barra de herramientas. Esto habilita:

- **Drag-and-drop** para reordenar widgets — arrastra desde el icono `⠿` de la barra del widget.
- **Control de ancho** `← N →` para cambiar entre columnas del grid (ciclo: 2 → 3 → 4 → 6 → 8 → 9 → 12).
- **Control de altura** `↑ H ↓` para los widgets de tabla (ciclo: auto → sm → md → lg → xl).
- **Ocultar** `✕` para retirar un widget del dashboard (vuelve a aparecer en "Añadir widget").
- **Barra "Añadir widget"** que lista los widgets ocultos para restaurarlos.
- **Restablecer** para volver al layout por defecto.

![Dashboard en modo edición](images/dashboard_edit.svg)

### Respuesta de `/api/v1/modules/overview`

```json
{
  "modules": [
    {
      "name": "ping",
      "enabled": true,
      "items": 2,
      "checks": { "total": 1, "ok": 1, "error": 0 }
    }
  ],
  "status":   { "total": 1, "ok": 1, "error": 0 },
  "sessions": { "active": 1, "users": ["admin"] },
  "users":    { "total": 1, "by_role": { "admin": 1 } },
  "groups":   { "total": 1, "members": 0 },
  "roles":    { "total": 3, "builtin": 3, "custom": 0 },
  "last_events": [{ "ts": "...", "event": "login_ok", "user": "admin", "ip": "..." }]
}
```

Los contadores de `status` se calculan como la suma de `checks.total/ok/error` de todos los módulos.

---

## Página de Estado Pública (`/status`)

La ruta `/status` muestra el estado actual de todos los módulos en una página pública, sin panel de navegación ni menú de administración.

> **Acceso directo:** [http://localhost:8080/status](http://localhost:8080/status)
> (sustituye `localhost:8080` por el host y puerto de tu instalación)

![Estado de servicios](images/status_public.svg)

### Comportamiento de acceso

| Situación | Resultado |
|-----------|-----------|
| `public_status = false` + usuario anónimo | `404 Not Found` |
| `public_status = false` + usuario logueado | `200 OK` |
| `public_status = true` + cualquier visitante | `200 OK` |

### Características

- **Banner superior** verde (todos OK) o rojo (algún fallo) con el nombre de la aplicación.
- **Tarjetas colapsables por módulo** — colapsadas por defecto; se expanden automáticamente si alguna comprobación falla.
- **Contador de refresco** — cuenta regresiva en pantalla y recarga automática de la página; configurable con `status_refresh_secs` (10–3600 s).
- **Idioma configurable** — prioridad de 3 niveles: idioma de sesión del usuario → `status_lang` → `default_lang`. El `<html lang="...">` y todos los textos de la página se renderizan en el idioma resultante.
- No extiende `base.html`; es una página standalone completamente independiente del panel de administración.

### Configuración

| Parámetro `config.json` | Tipo | Por defecto | Descripción |
|------------------------|------|-------------|-------------|
| `web_admin.public_status` | bool | `false` | Permite el acceso anónimo a `/status` |
| `web_admin.status_refresh_secs` | int | `60` | Intervalo de refresco automático (10–3600 s) |
| `web_admin.status_lang` | string | `""` | Idioma fijo para la página `/status`. Prioridad: idioma de sesión del usuario > este ajuste > `web_admin.lang`. Vacío = usa el idioma por defecto del panel. |

---

## Páginas de Error Personalizadas

Los errores HTTP 400, 403, 404, 405 y 500 muestran páginas con el código de error, un icono Bootstrap, título y descripción traducidos al idioma de la sesión activa.

Las páginas heredan `base.html`, por lo que el tema dark/light se aplica automáticamente.

### Comportamiento JSON vs HTML

Si la ruta que genera el error empieza por `/api/v1/` o el cliente envía `Accept: application/json`, la respuesta es JSON:

```json
{"error": "Page Not Found", "code": 404}
```

En cualquier otro caso se devuelve la plantilla `error.html`.

---

## i18n

Los ficheros de idioma están en dos lugares:

| Ubicación | Propósito |
|-----------|-----------|
| `src/lib/web_admin/lang/en_EN.py` / `es_ES.py` | Cadenas globales de la UI (navegación, botones, mensajes, etiquetas de permisos y grupos) |
| `src/watchfuls/<modulo>/lang/en_EN.json` / `es_ES.json` | Etiquetas de campos por módulo y nombre de visualización |

Las claves de i18n relacionadas con el sistema de permisos son:

| Clave | Descripción |
|-------|-------------|
| `permission_labels` | Dict `{flag: etiqueta}` con los 28 permisos |
| `perm_group_users` … `perm_group_checks` | Nombre de cada grupo de permisos para el modal de rol |
| `group_roles` | Etiqueta del selector de roles en el modal de grupo |
| `group_builtin_badge` | Texto del badge "Predeterminado" en grupos integrados |
| `role_tab_permissions` | Pestaña "Permisos" del modal de rol |
| `role_tab_assignments` | Pestaña "Asignación" del modal de rol |
| `role_assign_users` | Título de la columna de usuarios en la pestaña Asignación |
| `role_assign_groups` | Título de la columna de grupos en la pestaña Asignación |

Las claves de i18n para páginas de error son:

| Clave | Descripción |
|-------|-------------|
| `err_400_title` / `err_400_desc` | Título y descripción del error 400 |
| `err_403_title` / `err_403_desc` | Título y descripción del error 403 |
| `err_404_title` / `err_404_desc` | Título y descripción del error 404 |
| `err_405_title` / `err_405_desc` | Título y descripción del error 405 |
| `err_500_title` / `err_500_desc` | Título y descripción del error 500 |
| `err_generic_title` / `err_generic_desc` | Fallback para errores sin clave específica |

Para añadir un nuevo idioma, basta con crear un nuevo fichero `.py` en `lib/web_admin/lang/`. Se auto-descubre vía `pkgutil`.

---

## Formularios por Schema

![Pestaña Módulos](images/modules_tab.svg)

La interfaz web genera automáticamente los formularios de configuración de módulos a partir del `schema.json` de cada package. Los campos se renderizan con el tipo de input correcto, rangos de validación y etiquetas del fichero `lang/*.json` del módulo.

Esto implica:
- Sin listas de campos hardcodeadas en JS.
- Los iconos y nombres de visualización de los módulos vienen de `info.json` y `lang/*.json`.
- Añadir un nuevo campo a `schema.json` es suficiente para que aparezca en la UI.

---

## Registro de Auditoría

Cada cambio de configuración se registra en `audit.json` con:
- Marca de tiempo
- Usuario que realizó el cambio
- Diff a nivel de campo (`valor_anterior` → `valor_nuevo`)
- Campos sensibles (contraseñas, tokens) mostrados solo como `***`

Los últimos N eventos de auditoría se muestran en el widget **Recent Activity** del dashboard Overview.

Todos los eventos auditados:

| Evento | Cuándo se registra |
|--------|--------------------|
| `login_ok` | Login exitoso (local, LDAP, OIDC o SAML2). Los logins externos incluyen `detail.auth_source`. |
| `login_failed` | Credenciales incorrectas, usuario inexistente, cuenta desactivada/bloqueada o error LDAP. `detail.reason` indica la causa (`invalid_credentials`, `user_not_found`, `account_disabled`, `account_locked`, `ldap_invalid_credentials`, `ldap_user_not_found`, `ldap_connection_error`, `saml2_error`…). |
| `logout` | Cierre de sesión |
| `modules_saved` | Guardado de `modules.json` (con diff de campos) |
| `config_saved` | Guardado de `config.json` (con diff de campos) |
| `user_created` | Creación de usuario |
| `user_updated` | Modificación de usuario (con diff por campo) |
| `user_deleted` | Eliminación de usuario |
| `password_changed` | Usuario cambia su propia contraseña |
| `password_reset` | Admin resetea la contraseña de otro usuario |
| `user_preferences_changed` | Cambio de preferencias de UI de un usuario (idioma, tema) |
| `all_sessions_revoked` | Invalidación global de sesiones |
| `session_revoked` | Revocación de una sesión concreta |
| `user_sessions_revoked` | Revocación de todas las sesiones de un usuario |
| `session_ip_changed` | La IP del cliente cambia respecto a la IP de creación; `detail` contiene `previous_ip` y `current_ip` |
| `group_created` | Creación de grupo |
| `group_updated` | Modificación de grupo (roles, miembros, label o descripción) |
| `group_deleted` | Eliminación de grupo |
| `role_created` | Creación de rol personalizado |
| `role_updated` | Cambio de etiqueta o permisos de un rol |
| `role_deleted` | Eliminación de rol personalizado |
| `checks_run` | Ejecución manual de comprobaciones desde la UI |
| `ldap_test` | Prueba de conexión LDAP (con o sin usuario de prueba) desde la UI de configuración |
| `ldap_groups` | Obtención de grupos desde el directorio LDAP |
| `entra_groups` | Obtención de grupos del tenant de Microsoft Entra ID |
| `telegram_test_ok` / `telegram_test_fail` | Envío de mensaje de prueba por Telegram |
| `email_test_ok` / `email_test_fail` | Envío de email de prueba desde la UI de configuración |
| `webhook_created` | Creación de un nuevo webhook |
| `webhook_updated` | Modificación de un webhook (con diff de campos) |
| `webhook_enabled` / `webhook_disabled` | Activación o desactivación de un webhook |
| `webhook_deleted` | Eliminación de un webhook |
| `webhook_test_ok` / `webhook_test_fail` | Envío de payload de prueba a un webhook |
| `notif_template_saved` | Guardado de sobrescrituras de cadenas de notificación |
| `notif_template_reset` | Restablecimiento de sobrescrituras de un idioma a los valores por defecto |
| `notif_html_template_saved` | Guardado de plantilla HTML de email personalizada |
| `notif_html_template_reset` | Restablecimiento de plantilla HTML a la integrada |
| `audit_cleared` | Borrado completo del registro de auditoría |
| `audit_entry_deleted` | Borrado de una entrada concreta del registro |
| `language_changed` | Cambio del idioma de la interfaz |
| `watchful_action` | Invocación de una acción dinámica de un módulo watchful |
