# Referencia de permisos, roles y grupos (RBAC)

> **Fuente única** del catálogo de control de acceso: los flags de permiso, los roles
> integrados, los grupos y las estructuras internas del RBAC.
>
> - La **semántica de seguridad** (bloqueo de escalada, jerarquía IDOR, `_role_is_admin`,
>   integridad, tests de regresión) vive en [explica-seguridad.md](explica-seguridad.md).
> - El **comportamiento de la UI** según permisos (`applyRoleRestrictions`) vive en
>   [explica-web-admin.md](explica-web-admin.md).
> - Los **endpoints** de roles/grupos/usuarios están en [ref-api.md](ref-api.md).

El sistema usa **73 flags granulares** por acción y recurso. `PERMISSIONS` (tupla en el
código) tiene exactamente esos 73 flags.

---

## Roles integrados

| Rol | Permisos |
|-----|----------|
| `admin` | Todos los permisos (73 flags) |
| `editor` | Vista de todo + edición (sin borrar ni crear): `modules_edit`, `config_edit`, `checks_run`, `roles_edit`, `groups_edit`, `users_edit`, `servers_edit`, `clusters_edit`, `events_edit`, `overview_edit`, `services_control`, más los `*_view` correspondientes (`modules_view`, `servers_view`, `clusters_view`, `config_view`, `overview_view`, `checks_view`, `audit_view`, `sessions_view`, `users_view`, `roles_view`, `groups_view`, `history_view`, `syslog_view`, `services_view`, `events_view`, `events_notify_view`) **más** `credentials_view` y `credentials_edit` |
| `viewer` | Solo lectura: `users_view`, `roles_view`, `groups_view`, `audit_view`, `modules_view`, `servers_view`, `clusters_view`, `overview_view`, `sessions_view`, `checks_view`, `history_view`, `syslog_view`, `services_view`, `events_view`, `events_notify_view`, `credentials_view` (sin `config_view`, que expone secretos sin enmascarar) |

> Los roles integrados **no pueden eliminarse** ni cambiar sus permisos vía API. Sí permiten
> actualizar la **etiqueta** (`label`) y gestionar qué usuarios/grupos lo tienen asignado. El
> override de etiqueta se persiste como una fila más en la tabla `roles`
> ([ref-esquema-bd.md](ref-esquema-bd.md#roles--roles-personalizados--overrides-de-built-in)).

## Roles personalizados

Se crean desde **Acceso → Roles** asignando cualquier combinación de los 73 permisos. Se
persisten en la tabla `roles`.

Sus permisos se editan en **un** sitio: la sub-sección **Acceso → Permisos**, que pone todos los
roles a la vez frente a los integrados. El modal del rol edita su identidad y a quién se le asigna,
nunca lo que puede hacer. Ver
[explica-web-admin.md](explica-web-admin.md#sub-sección-permisos-acceso--permisos).

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

## Catálogo de permisos (73 flags)

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
| **Credenciales** | `credentials_view` `credentials_add` `credentials_edit` `credentials_delete` | CRUD de credenciales reutilizables: identidades SSH y registros de aplicación de Entra ID (`azure_app`, `m365_app`), tokens de API (Proxmox, NUT, HTTP, datastore). Sección propia dentro de System |
| **Config** | `config_view` | Leer configuración sin poder editarla |
| | `config_edit` | Guardar cambios en configuración |
| | `db_maintenance` | Optimizar y compactar la base de datos (Config › Mantenimiento). Flag propio y **sin rol por defecto**: compactar deja la base de datos bloqueada mientras se reescribe, y editar un ajuste no es la misma autoridad que congelar el panel |
| **Overview** | `overview_view` | Ver el dashboard de resumen |
| | `overview_edit` | Editar el layout propio |
| | `overview_set_default` | Fijar el layout como default global |
| | `overview_reset_factory` | Restaurar el layout de fábrica |
| **Sesiones** | `sessions_view` | Ver sesiones activas |
| | `sessions_revoke` | Revocar sesiones |
| **Checks** | `checks_view` | Ver resultados de checks y la pestaña Status |
| | `checks_run` | Lanzar comprobaciones bajo demanda |
| | `checks_delete` | Vaciar la tabla de estado de los checks (Config › Mantenimiento). **Sin rol por defecto**: antes iba con `checks_run` —que tiene `editor`— y eso dejaba una acción destructiva al alcance de un rol pensado para *operar* la monitorización, no para borrar lo que reportó |
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
| **Copias de seguridad** | `backup_view` | Ver qué copias existen y las tareas programadas |
| | `backup_verify` | Verificar una copia contra sus checksums. Flag propio: no escribe nada, pero recorre y hashea un archivo de gigabytes |
| | `backup_create` | Crear una copia — y **ejecutar una tarea ahora**, que produce exactamente lo mismo |
| | `backup_download` | Descargar el fichero. **Quien puede bajarlo tiene la instalación** |
| | `backup_restore` | Aplicar una copia: sobrescribe usuarios y roles, así que puede entregar el panel |
| | `backup_delete` | Eliminar una copia del disco — y **bloquearla o desbloquearla**, porque el bloqueo solo decide si un archivo puede destruirse y desbloquear es pedir poder borrarlo |
| | `backup_schedule` | Crear, editar y borrar **tareas** programadas y **perfiles de retención**. No destruye ningún archivo, pero decide cada cuánto se protege la instalación y cuánta historia se guarda —y editar un perfil lo decide de golpe para todas las tareas que lo siguen |

| **Diagnóstico** | `diagnostics_view` | Ver el diagnóstico del sistema: versión, red y TLS, base de datos, dependencias, librerías opcionales, almacenamiento y rutas. No expone secretos, pero sí **la forma de la instalación**, que es el inventario contra el que alguien escribe un exploit — y es, por lo mismo, justo lo que necesita un operador antes de abrir una incidencia. De esa pantalla salen de la máquina **dos comprobaciones**, las dos solo al pulsar su botón y las dos auditadas: la de versión nueva del panel y la de dependencias (última versión en PyPI y avisos de seguridad en OSV.dev). El mismo permiso las abre: es una llamada saliente desde esta máquina, así que va con la página y no con un permiso aparte |

> Ninguno de los siete de **Copias de seguridad** se concede a los roles integrados: una copia
> es una herramienta de administración, y la lista sola ya dice qué existe y desde cuándo. Ver
> [explica-backup.md](explica-backup.md#permisos). `diagnostics_view` tampoco, por la misma
> razón.

> **IP bans (fail2ban)** añade su propia familia granular `ipban_*` (`ipban_ban_view/add/edit/delete`,
> `ipban_history_view`, `ipban_history_delete`, `ipban_whitelist_view/add/delete`, `ipban_watchlist_clear`,
> `ipban_service_edit`). Ver [ref-api.md](ref-api.md#ip-bans-fail2ban--libservicesipbanroutespy).

### Permisos dinámicos

Además de los flags globales, existen permisos **dinámicos** por recurso concreto:

- `module.<nombre>.view|add|edit|delete` — restringe el acceso a un módulo concreto.
- `server.<uid>.<acción>` — permiso por host (ver [explica-hosts.md](explica-hosts.md)).
- `cluster.<uid>.<acción>` — permiso por cluster.

> **Mueren con su recurso.** Borrar un host, quitar un módulo de la configuración o eliminar un
> cluster **poda** sus claves de todos los roles personalizados, con entrada de auditoría
> (`role_permissions_pruned`). Se poda en el borrado, que es el único punto que sabe exactamente
> qué desapareció; hacerlo al cargar obligaría a decidir qué es «desconocido» a partir de un store
> que quizá solo falló al leer. Los nombres de módulo se podan igual **aunque puedan volver**: un
> `module.ping.edit` obsoleto se aplicaría en silencio al siguiente `ping`, y una concesión que
> nadie recuerda haber dado es peor que una que hay que volver a marcar.

---

## Estructuras internas

- `BUILTIN_ROLE_UIDS` / `BUILTIN_GROUP_UIDS` / `BUILTIN_GROUP_UID_SET` — los UUID estables de
  roles y grupos integrados, en `lib/core/constants.py`. **No** están con el catálogo de permisos:
  son identidad, la nombran users/groups/roles/resolución/SCIM/CLI, y no las posee ningún dominio.
- `ROLES` — las claves de rol integrado, mayor privilegio primero. **Derivada** de
  `BUILTIN_ROLE_UIDS`, no escrita otra vez.
- `PERMISSIONS` — tupla con los 73 flags.
- `PERMISSION_GROUPS` — lista de `(key_i18n, [perms])` para renderizar el modal de edición de
  roles agrupado.
- `BUILTIN_ROLE_PERMISSIONS` — dict `{role: frozenset}` de los roles integrados.
- `_perm_required(*perms)` — factoría de decoradores: acepta si el usuario tiene **alguno** de
  los permisos indicados. Ver [ref-api.md](ref-api.md#guards-de-permiso).
- `is_valid_perm(p)` / `filter_valid_permissions(perms)` — qué cadena cuenta como permiso
  (flag conocido o clave por-instancia bien formada). **Única fuente**: la usan tanto el guardado
  de un rol como la resolución de sus permisos.
- `_get_effective_permissions(username, role)` — unión del frozenset del rol del usuario más
  los permisos de todos los roles de todos sus grupos.
- `GET /api/v1/me` — incluye `permissions: list[str]` con los permisos efectivos de la sesión.

---

## Ver también

- [explica-seguridad.md](explica-seguridad.md) — semántica de seguridad del RBAC (escalada, IDOR)
- [explica-web-admin.md](explica-web-admin.md) — restricción de UI por permisos
- [ref-api.md](ref-api.md) — endpoints y guards
- [ref-esquema-bd.md](ref-esquema-bd.md) — tablas `users`/`roles`/`groups`
