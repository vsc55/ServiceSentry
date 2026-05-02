# Interfaz Web de Administración

ServiceSentry incluye un panel de administración web basado en **Flask**.
Permite gestionar módulos, configuración y usuarios sin tocar archivos directamente.

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
| **Roles personalizados** | Crear roles con permisos granulares por acción (ver/añadir/editar/eliminar) |
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
| `editor` | `modules_edit`, `config_edit`, `checks_run`, `audit_view` |
| `viewer` | Sin permisos (solo puede ver el dashboard y cambiar su contraseña) |

### Roles personalizados

Se pueden crear roles adicionales desde la pestaña **Usuarios → Roles** asignando
cualquier combinación de los 15 permisos disponibles. Los roles personalizados se
persisten en `roles.json`.

```
/api/roles             POST   → crear rol
/api/roles/<name>  PUT    → editar rol
/api/roles/<name>  DELETE → eliminar rol (falla si hay usuarios asignados)
```

---

## Sistema de Permisos

El sistema de control de acceso usa **15 flags granulares** por acción y recurso.

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
| **Auditoría** | `audit_view` | Leer el registro de auditoría |
| | `audit_delete` | Borrar entradas del registro |
| **Módulos** | `modules_edit` | Guardar cambios en módulos |
| **Config** | `config_edit` | Guardar cambios en configuración |
| **Sesiones** | `sessions_view` | Ver sesiones activas |
| | `sessions_revoke` | Revocar sesiones |
| **Checks** | `checks_run` | Lanzar comprobaciones bajo demanda |

### Implementación interna

- `PERMISSIONS` — tupla con los 15 flags.
- `PERMISSION_GROUPS` — lista de `(key_i18n, [perms])` para renderizar el modal de edición de roles agrupado.
- `BUILTIN_ROLE_PERMISSIONS` — dict `{role: frozenset}` para los roles integrados.
- `_perm_required(*perms)` — factoría de decoradores: acepta si el usuario tiene **alguno** de los permisos indicados.
- `_get_role_permissions(role)` — devuelve el `frozenset` de permisos para un rol (integrado o personalizado).
- `GET /api/me` — incluye el campo `permissions: list[str]` con los permisos de la sesión activa.

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

- Contraseñas hasheadas con `werkzeug.security` (PBKDF2).
- Redireccionamientos validados contra el mismo origen (evita open redirect).
- Nombres de usuario escapados en mensajes de la UI (evita XSS en títulos de modales).
- Sesiones revocables desde el panel de administración.
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
| `GET` | `/api/overview` | auth | Obtener resumen de estado de módulos |

### Configuración

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/config` | auth | Obtener el `config.json` actual |
| `PUT` | `/api/config` | `config_edit` | Guardar `config.json` |

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

### Roles

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| `GET` | `/api/roles` | auth | Listar todos los roles (integrados + personalizados) |
| `POST` | `/api/roles` | `roles_add` | Crear un rol personalizado |
| `PUT` | `/api/roles/<name>` | `roles_edit` | Editar etiqueta o permisos de un rol personalizado |
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
| `permission_labels` | Dict `{flag: etiqueta}` con los 15 permisos |
| `perm_group_users` … `perm_group_checks` | Nombre de cada grupo de permisos para el modal de rol |

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
