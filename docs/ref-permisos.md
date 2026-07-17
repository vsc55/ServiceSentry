# Referencia de permisos, roles y grupos (RBAC)

> **Fuente única** del catálogo de control de acceso: los flags de permiso, los roles
> integrados, los grupos y las estructuras internas del RBAC.
>
> - La **semántica de seguridad** (bloqueo de escalada, jerarquía IDOR, `_role_is_admin`,
>   integridad, tests de regresión) vive en [explica-seguridad.md](explica-seguridad.md).
> - El **comportamiento de la UI** según permisos (`applyRoleRestrictions`) vive en
>   [explica-web-admin.md](explica-web-admin.md).
> - Los **endpoints** de roles/grupos/usuarios están en [ref-api.md](ref-api.md).

El sistema usa **63 flags granulares** por acción y recurso. `PERMISSIONS` (tupla en el
código) tiene exactamente esos 63 flags.

---

## Roles integrados

| Rol | Permisos |
|-----|----------|
| `admin` | Todos los permisos (63 flags) |
| `editor` | Vista de todo + edición (sin borrar ni crear): `modules_edit`, `config_edit`, `checks_run`, `roles_edit`, `groups_edit`, `users_edit`, `servers_edit`, `clusters_edit`, `events_edit`, `overview_edit`, `services_control`, más los `*_view` correspondientes (`modules_view`, `servers_view`, `clusters_view`, `config_view`, `overview_view`, `checks_view`, `audit_view`, `sessions_view`, `users_view`, `roles_view`, `groups_view`, `history_view`, `syslog_view`, `services_view`, `events_view`, `events_notify_view`) **más** `credentials_view` y `credentials_edit` |
| `viewer` | Solo lectura: `users_view`, `roles_view`, `groups_view`, `audit_view`, `modules_view`, `servers_view`, `clusters_view`, `overview_view`, `sessions_view`, `checks_view`, `history_view`, `syslog_view`, `services_view`, `events_view`, `events_notify_view` (sin `config_view` ni `credentials_view`) |

> Los roles integrados **no pueden eliminarse** ni cambiar sus permisos vía API. Sí permiten
> actualizar la **etiqueta** (`label`) y gestionar qué usuarios/grupos lo tienen asignado. El
> override de etiqueta se persiste como una fila más en la tabla `roles`
> ([ref-esquema-bd.md](ref-esquema-bd.md#roles--roles-personalizados--overrides-de-built-in)).

## Roles personalizados

Se crean desde **Acceso → Roles** asignando cualquier combinación de los 63 permisos. Se
persisten en la tabla `roles`.

## Grupos de usuarios

Asignan uno o varios **roles** a un conjunto de usuarios. Los permisos son **aditivos**: el
usuario obtiene los permisos de su propio rol más la unión de los permisos de todos los roles
de todos sus grupos.

| Grupo integrado | Roles | Notas |
|-------|-------|-------|
| `administrators` | `admin` | No puede borrarse; permite editar roles asignados y miembros; `label`/`description` inmutables |

Cada grupo tiene `roles: []` (nombres de rol cuyos permisos se añaden) y `members` (calculado
desde el campo de pertenencia en la BD, ver [ref-esquema-bd.md](ref-esquema-bd.md#users_groups--pertenencia-usuariogrupo-mn)).

---

## Catálogo de permisos (63 flags)

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
| **Servers** | `servers_view` `servers_add` `servers_edit` `servers_delete` | CRUD del registro de hosts |
| **Clusters** | `clusters_view` `clusters_add` `clusters_edit` `clusters_delete` | CRUD de clusters (checks multi-bind) |
| **Credenciales** | `credentials_view` `credentials_add` `credentials_edit` `credentials_delete` | CRUD de identidades SSH reutilizables |
| **Config** | `config_view` | Leer configuración sin poder editarla |
| | `config_edit` | Guardar cambios en configuración |
| **Overview** | `overview_view` | Ver el dashboard de resumen |
| | `overview_edit` | Editar el layout propio |
| | `overview_set_default` | Fijar el layout como default global |
| | `overview_reset_factory` | Restaurar el layout de fábrica |
| **Sesiones** | `sessions_view` | Ver sesiones activas |
| | `sessions_revoke` | Revocar sesiones |
| **Checks** | `checks_view` | Ver resultados de checks y la pestaña Status |
| | `checks_run` | Lanzar comprobaciones bajo demanda |
| **Historial** | `history_view` | Ver gráficas y series del historial |
| | `history_delete` | Borrar datos del historial |
| **Syslog** | `syslog_view` | Ver mensajes syslog y descartes |
| | `syslog_delete` | Vaciar mensajes / descartes |
| **Servicios** | `services_view` | Ver el estado de los servicios |
| | `services_control` | Iniciar/detener servicios |
| **Eventos** | `events_view` | Ver reglas de notificación |
| | `events_add` | Crear reglas de evento |
| | `events_edit` | Editar reglas |
| | `events_delete` | Eliminar reglas de evento |
| | `events_notify_view` | Ver el log de notificaciones enviadas |
| | `events_notify_delete` | Vaciar el log de notificaciones enviadas |

> **IP bans (fail2ban)** añade su propia familia granular `ipban_*` (`ipban_ban_view/add/edit/delete`,
> `ipban_history_view`, `ipban_whitelist_view/add/delete`, `ipban_watchlist_clear`,
> `ipban_service_edit`). Ver [ref-api.md](ref-api.md#ip-bans-fail2ban--libservicesipbanroutespy).

### Permisos dinámicos

Además de los flags globales, existen permisos **dinámicos** por recurso concreto:

- `module.<nombre>.view|add|edit|delete` — restringe el acceso a un módulo concreto.
- `server.<uid>.<acción>` — permiso por host (ver [explica-hosts.md](explica-hosts.md)).
- `cluster.<uid>.<acción>` — permiso por cluster.

---

## Estructuras internas

- `PERMISSIONS` — tupla con los 63 flags.
- `PERMISSION_GROUPS` — lista de `(key_i18n, [perms])` para renderizar el modal de edición de
  roles agrupado.
- `BUILTIN_ROLE_PERMISSIONS` — dict `{role: frozenset}` de los roles integrados.
- `_perm_required(*perms)` — factoría de decoradores: acepta si el usuario tiene **alguno** de
  los permisos indicados. Ver [ref-api.md](ref-api.md#guards-de-permiso).
- `_get_effective_permissions(username, role)` — unión del frozenset del rol del usuario más
  los permisos de todos los roles de todos sus grupos.
- `GET /api/v1/me` — incluye `permissions: list[str]` con los permisos efectivos de la sesión.

---

## Ver también

- [explica-seguridad.md](explica-seguridad.md) — semántica de seguridad del RBAC (escalada, IDOR)
- [explica-web-admin.md](explica-web-admin.md) — restricción de UI por permisos
- [ref-api.md](ref-api.md) — endpoints y guards
- [ref-esquema-bd.md](ref-esquema-bd.md) — tablas `users`/`roles`/`groups`
