# Interfaz Web de Administración

ServiceSentry incluye un panel de administración web basado en **Flask**.
Permite gestionar módulos, configuración y usuarios sin tocar archivos directamente.

---

## Organización del Código

La lógica de `WebAdmin` está dividida en **mixins** (lógica de negocio) y **routes** (registro de rutas Flask):

```
lib/web_admin/
├── app.py            # class WebAdmin(hereda todos los mixins)
├── mixins/
│   ├── users.py      # _UsersMixin
│   ├── roles.py      # _RolesMixin
│   ├── groups.py     # _GroupsMixin
│   ├── permissions.py# _PermissionsMixin
│   ├── sessions.py   # _SessionsMixin
│   ├── audit.py      # _AuditMixin
│   └── checks.py     # _ChecksMixin
└── routes/
    ├── __init__.py   # register_all(app, wa)
    ├── auth.py       # /login, /logout
    ├── users.py      # /api/users, /api/me
    ├── roles.py      # /api/roles
    ├── groups.py     # /api/groups
    ├── modules.py    # /api/modules, /api/status, /api/overview
    ├── config.py     # /api/config, /api/config/schema
    ├── sessions.py   # /api/sessions
    ├── telegram.py   # /api/telegram/test
    ├── audit.py      # /api/audit
    ├── checks.py     # /api/checks/run
    └── ui.py         # /, /lang, /theme
```

---

## Iniciar la Interfaz Web

```bash
python3 main.py --web-admin
```

Abre `http://localhost:8080` (o el host/puerto configurado) en el navegador.

---

## Características

| Característica | Descripción |
|---------------|-------------|
| **Panel de módulos** | Habilitar/deshabilitar módulos, configurar ítems con formularios generados automáticamente desde los schemas |
| **Vista general (Overview)** | Estado en tiempo real de todos los módulos con auto-refresco configurable (OFF / 10 s / 30 s / 60 s) |
| **Pestaña de configuración** | Editar `config.json` (Telegram, daemon, idioma) directamente desde el navegador |
| **Gestión de usuarios** | Crear, editar y eliminar usuarios; asignar roles; cambiar contraseña propia |
| **Roles y permisos** | Roles integrados (`admin`, `editor`, `viewer`) + roles personalizados con 19 flags granulares; los roles integrados permiten editar la etiqueta y gestionar qué usuarios/grupos tienen asignado ese rol; sus permisos se muestran en solo lectura |
| **Grupos de usuarios** | Agrupar usuarios bajo uno o más roles; los permisos de los grupos se suman a los del rol individual del usuario; grupo `administrators` integrado (permite editar roles y miembros, pero no nombre ni etiqueta) |
| **Prueba de Telegram** | Enviar un mensaje de prueba para verificar la conectividad del bot |
| **Modo oscuro** | Preferencia por usuario, persistida entre sesiones |
| **i18n** | Inglés y español; seleccionable por usuario y configurable globalmente con `web_admin.lang` |
| **Registro de auditoría** | Seguimiento de cambios a nivel de campo con enmascarado de datos sensibles |
| **Gestión de sesiones** | Ver sesiones activas; los usuarios con permiso `sessions_revoke` pueden revocar cualquier sesión |

---

## Roles de Usuario

### Roles integrados

| Rol | Permisos |
|-----|----------|
| `admin` | Todos los permisos |
| `editor` | `modules_edit`, `config_edit`, `checks_run`, `audit_view`, `users_view`, `users_edit`, `roles_view`, `roles_edit`, `groups_view`, `groups_edit` |
| `viewer` | `users_view`, `roles_view`, `groups_view`, `audit_view`, `sessions_view` |

> Los roles integrados **no pueden eliminarse** ni cambiar sus permisos via API. Sí permiten actualizar la **etiqueta** (`label`) y gestionar qué usuarios y grupos tienen ese rol asignado. La etiqueta personalizada se persiste en `roles.json` bajo la clave `__builtin_labels__`.

### Roles personalizados

Se pueden crear roles adicionales desde la pestaña **Acceso → Roles** asignando
cualquier combinación de los 19 permisos disponibles. Los roles personalizados se
persisten en `roles.json`.

```
/api/roles             POST   → crear rol
/api/roles/<name>      PUT    → editar rol
/api/roles/<name>      DELETE → eliminar rol (falla si hay usuarios asignados)
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
/api/groups             GET    → listar grupos con miembros y roles
/api/groups             POST   → crear grupo
/api/groups/<name>      PUT    → editar roles y miembros (label/description ignorados en builtin)
/api/groups/<name>      DELETE → eliminar grupo (403 si es builtin)
```

Cada grupo tiene:
- `roles: []` — lista de nombres de rol cuyos permisos se añaden a los miembros
- `members` — calculado dinámicamente a partir de `users.json` (campo `groups` de cada usuario)

---

## Sistema de Permisos

El sistema de control de acceso usa **19 flags granulares** por acción y recurso.

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
| **Módulos** | `modules_edit` | Guardar cambios en módulos |
| **Config** | `config_edit` | Guardar cambios en configuración |
| **Sesiones** | `sessions_view` | Ver sesiones activas |
| | `sessions_revoke` | Revocar sesiones |
| **Checks** | `checks_run` | Lanzar comprobaciones bajo demanda |

### Implementación interna

- `PERMISSIONS` — tupla con los 19 flags.
- `PERMISSION_GROUPS` — lista de `(key_i18n, [perms])` para renderizar el modal de edición de roles agrupado.
- `BUILTIN_ROLE_PERMISSIONS` — dict `{role: frozenset}` para los roles integrados.
- `_perm_required(*perms)` — factoría de decoradores: acepta si el usuario tiene **alguno** de los permisos indicados.
- `_get_effective_permissions(username, role)` — devuelve la unión del frozenset del rol del usuario más los permisos de todos los roles de todos sus grupos.
- `GET /api/me` — incluye el campo `permissions: list[str]` con los permisos efectivos de la sesión activa.

### Restricción de roles en la UI

La función JS `applyRoleRestrictions()` (en `_js_init.html`) oculta o muestra
botones y pestañas según los permisos del usuario actual obtenidos de `/api/me`:

- Pestaña Usuarios: visible si tiene cualquier permiso `users_*`.
- Pestaña Auditoría: visible si tiene `audit_view`.
- Botón "Nuevo usuario": solo si `users_add`.
- Botones editar/borrar de cada usuario: solo si `users_edit` / `users_delete`.
- Botón limpiar audit / borrar entrada: solo si `audit_delete`.
- Botón "Nuevo rol" y sección de roles: solo si tiene cualquier permiso `roles_*`.

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

Todos los endpoints requieren autenticación (cookie de sesión).
El permiso requerido se indica entre paréntesis.

### Autenticación

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/login` | Iniciar sesión con usuario y contraseña |
| `GET` | `/logout` | Cerrar sesión e invalidar la sesión actual |

### Módulos

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/modules` | auth | Obtener todas las configuraciones de módulos |
| `PUT` | `/api/modules` | `modules_edit` | Guardar todas las configuraciones de módulos |
| `GET` | `/api/status` | auth | Obtener el contenido de `status.json` (solo lectura) |
| `GET` | `/api/overview` | auth | Obtener resumen de estado de módulos |

### Configuración

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/config` | auth | Obtener el `config.json` actual |
| `PUT` | `/api/config` | `config_edit` | Guardar `config.json` |
| `GET` | `/api/config/schema` | auth | Obtener el schema de validación de los campos de configuración del web admin |

Los campos numéricos del bloque `web_admin` se validan contra reglas definidas en `INT_RULES` (en `routes/config.py`):

| Clave (`config.json`) | Atributo | Mín | Máx |
|----------------------|----------|-----|-----|
| `web_admin\|remember_me_days` | `_REMEMBER_ME_DAYS` | 1 | 365 |
| `web_admin\|audit_max_entries` | `_AUDIT_MAX_ENTRIES` | 10 | 10000 |

### Telegram

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `POST` | `/api/telegram/test` | `config_edit` | Enviar un mensaje de prueba por Telegram |

### Usuarios

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/users` | `users_view` | Listar todos los usuarios |
| `POST` | `/api/users` | `users_add` | Crear un nuevo usuario |
| `PUT` | `/api/users/<username>` | `users_edit` | Editar un usuario |
| `DELETE` | `/api/users/<username>` | `users_delete` | Eliminar un usuario |
| `GET` | `/api/me` | auth | Obtener información del usuario actual |
| `PUT` | `/api/users/me/password` | auth | Cambiar la contraseña propia |

### Grupos

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/groups` | auth | Listar todos los grupos con miembros y roles |
| `POST` | `/api/groups` | `groups_add` | Crear un grupo |
| `PUT` | `/api/groups/<name>` | `groups_edit` | Editar roles y miembros de un grupo (label/description ignorados en builtin) |
| `DELETE` | `/api/groups/<name>` | `groups_delete` | Eliminar un grupo (403 si es builtin) |

### Roles

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/roles` | auth | Listar todos los roles (integrados + personalizados) |
| `POST` | `/api/roles` | `roles_add` | Crear un rol personalizado |
| `PUT` | `/api/roles/<name>` | `roles_edit` | Editar rol; en integrados solo se acepta `label`; en personalizados acepta `label` y `permissions` |
| `DELETE` | `/api/roles/<name>` | `roles_delete` | Eliminar un rol personalizado |

### Sesiones

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/sessions` | `sessions_view` | Listar sesiones activas |
| `POST` | `/api/sessions/invalidate` | `sessions_revoke` | Revocar todas las sesiones |
| `POST` | `/api/sessions/revoke/<sid>` | `sessions_revoke` | Revocar una sesión concreta |
| `POST` | `/api/sessions/revoke-user/<user>` | `sessions_revoke` | Revocar sesiones de un usuario |

### Auditoría

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/audit` | `audit_view` | Listar entradas del registro de auditoría |
| `DELETE` | `/api/audit` | `audit_delete` | Borrar todas las entradas |
| `DELETE` | `/api/audit/<idx>` | `audit_delete` | Borrar una entrada concreta |

### Checks

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `POST` | `/api/checks/run` | `checks_run` | Lanzar comprobaciones bajo demanda |

### Preferencias de UI

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/lang/<lang>` | auth | Establecer preferencia de idioma |
| `GET` | `/theme/<theme>` | auth | Establecer preferencia de tema (light/dark) |

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
| `permission_labels` | Dict `{flag: etiqueta}` con los 19 permisos |
| `perm_group_users` … `perm_group_checks` | Nombre de cada grupo de permisos para el modal de rol |
| `group_roles` | Etiqueta del selector de roles en el modal de grupo |
| `group_builtin_badge` | Texto del badge "Predeterminado" en grupos integrados |
| `role_tab_permissions` | Pestaña "Permisos" del modal de rol |
| `role_tab_assignments` | Pestaña "Asignación" del modal de rol |
| `role_assign_users` | Título de la columna de usuarios en la pestaña Asignación |
| `role_assign_groups` | Título de la columna de grupos en la pestaña Asignación |

Para añadir un nuevo idioma, basta con crear un nuevo fichero `.py` en `lib/web_admin/lang/`. Se auto-descubre vía `pkgutil`.

---

## Formularios por Schema

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

Los últimos N eventos de auditoría se muestran en la pestaña Overview.

Eventos auditados relacionados con roles:

| Evento | Cuándo se registra |
|--------|--------------------|
| `role_created` | Se crea un rol personalizado |
| `role_updated` | Se cambia etiqueta o permisos de un rol |
| `role_deleted` | Se elimina un rol personalizado |
