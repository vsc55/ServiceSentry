# Referencia de permisos, roles y grupos (RBAC)

> **Fuente única** del catálogo de control de acceso: los flags de permiso, los roles
> integrados, los grupos y las estructuras internas del RBAC.
>
> - La **semántica de seguridad** (bloqueo de escalada, jerarquía IDOR, `_role_is_admin`,
>   integridad, tests de regresión) vive en [explica-seguridad.md](explica-seguridad.md).
> - El **comportamiento de la UI** según permisos (`applyRoleRestrictions`) vive en
>   [explica-web-admin.md](explica-web-admin.md).
> - Los **endpoints** de roles/grupos/usuarios están en [ref-api.md](ref-api.md).

El sistema usa **94 flags granulares** por acción y recurso. `PERMISSIONS` (tupla en el
código) tiene exactamente esos 94 flags. Cada paquete declara los suyos en su `manifest.py`
(`MODULE_PERMISSIONS`: un grupo, o una lista de grupos cuando sus pantallas viven en dos sitios
del menú), y la pantalla **Acceso → Permisos** los enseña agrupados con el nombre y la
descripción de `permission_labels` / `permission_hints` de cada idioma.

---

## Roles integrados

| Rol | Permisos |
|-----|----------|
| `admin` | Todos los permisos (94 flags), `mfa_reset_others` incluido |
| `editor` | 53 flags: `services_view`, `services_control`, `checks_view`, `checks_run`, `syslog_view`, `syslog_sources_all_view`, `ipban_ban_view`, `ipban_ban_edit`, `ipban_whitelist_view`, `ipban_history_view`, `ipban_service_edit`, `ipban_config_edit`, `events_view`, `events_edit`, `events_notify_view`, `infra_view`, `infra_collect`, `infra_watch`, `infra_metrics_view`, `infra_results_view`, `infra_raw_view`, `dcim_view`, `dcim_edit`, `dcim_cable_edit`, `dcim_catalog_view`, `dcim_catalog_manage`, `dcim_build_edit`, `orgs_view`, `orgs_all_view`, `sessions_view`, `users_view`, `users_edit`, `roles_view`, `roles_edit`, `groups_view`, `groups_edit`, `audit_view`, `jobs_view`, `modules_view`, `modules_edit`, `devices_view`, `devices_edit`, `snmp_view`, `snmp_manage`, `clusters_view`, `clusters_edit`, `credentials_view`, `credentials_edit`, `config_view`, `config_edit`, `overview_view`, `overview_edit`, `history_view` |
| `viewer` | 29 flags, solo lectura: `services_view`, `checks_view`, `syslog_view`, `syslog_sources_all_view`, `ipban_ban_view`, `ipban_whitelist_view`, `ipban_history_view`, `events_view`, `events_notify_view`, `infra_view`, `infra_metrics_view`, `infra_results_view`, `dcim_view`, `dcim_catalog_view`, `orgs_view`, `orgs_all_view`, `sessions_view`, `users_view`, `roles_view`, `groups_view`, `audit_view`, `jobs_view`, `modules_view`, `devices_view`, `snmp_view`, `clusters_view`, `credentials_view`, `overview_view`, `history_view` (sin `config_view`, que expone secretos sin enmascarar, ni `infra_raw_view`) |

> Los roles integrados **no pueden eliminarse** ni cambiar sus permisos vía API. Sí permiten
> actualizar la **etiqueta** (`label`) y gestionar qué usuarios/grupos lo tienen asignado. El
> override de etiqueta se persiste como una fila más en la tabla `roles`
> ([ref-esquema-bd.md](ref-esquema-bd.md#roles--roles-personalizados--overrides-de-built-in)).

## Roles personalizados

Se crean desde **Acceso → Roles** asignando cualquier combinación de los 94 permisos. Se
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

## Catálogo de permisos (94 flags)

Los grupos son los de la pantalla de permisos, con su nombre. Los que no dicen rol no se conceden
a `editor` ni a `viewer` (sí a `admin`, que los tiene todos).

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
| **Dispositivos** | `devices_view` | Ver la lista de dispositivos en **Infraestructura** —donde vive el registro desde que dejó de ser una pestaña propia—, la configuración de cada uno y **Catálogo → Tipos de dispositivo** |
| | `devices_add` | Añadir checks a dispositivos. **No** da de alta dispositivos: eso es `devices_edit` |
| | `devices_edit` | Dar de alta, clonar y editar dispositivos y sus checks, probar conexiones, detectar duplicados y gestionar los tipos de dispositivo |
| | `devices_delete` | Eliminar dispositivos |
| **SNMP** | `snmp_view` | Acceder a la sección SNMP: biblioteca de MIB, navegador de símbolos y catálogo de perfiles de dispositivo. Incluye preguntarle a un dispositivo qué sirve — habla con la red, no cambia nada |
| | `snmp_manage` | Compilar, importar, editar y borrar MIB; escribir perfiles en el catálogo. **Corte limpio:** `modules_view` ya no abre nada de esto, así que un rol personalizado que dependiera de él necesita el flag nuevo |
| **Clústeres** | `clusters_view` `clusters_add` `clusters_edit` `clusters_delete` | **Catálogo → Clústeres**: los checks que vigilan varios dispositivos a la vez (multi-bind) |
| **Credenciales** | `credentials_view` `credentials_add` `credentials_edit` `credentials_delete` | CRUD de credenciales reutilizables: identidades SSH y registros de aplicación de Entra ID (`azure_app`, `m365_app`), tokens de API (Proxmox, NUT, HTTP, datastore). **Catálogo → Credenciales** |
| **Configuración** | `config_view` | Leer configuración sin poder editarla |
| | `config_edit` | Guardar cambios en configuración |
| | `db_maintenance` | Optimizar y compactar la base de datos (Config › Mantenimiento). Flag propio y **sin rol por defecto**: compactar deja la base de datos bloqueada mientras se reescribe, y editar un ajuste no es la misma autoridad que congelar el panel |
| **Resumen** | `overview_view` | Ver el panel de Resumen |
| | `overview_edit` | Guardar una disposición propia del Resumen. El servidor lo exige al guardarla; volver a la predeterminada queda abierto a todos |
| | `overview_set_default` | Fijar el layout como default global |
| | `overview_reset_factory` | Restaurar el layout de fábrica |
| **Infraestructura** | `infra_view` | Ver el estado en vivo de las máquinas (sección `/infra`) y la pestaña **Detalles**: qué es cada máquina y si está bien, que es la pregunta con la que se abre la página. No concede nada del registro: eso es `devices_view` / `devices_edit` |
| | `infra_collect` | «Obtener datos ahora»: lanzar los checks de un dispositivo sin esperar al ciclo. **No** de `viewer` — cuesta un sondeo al dispositivo, puede tardar minutos y hace que los checks avisen de lo que encuentren |
| | `infra_watch` | Decir que una fila concreta —un puerto, un disco— merece aviso, y si es la de internet. **No** de `viewer`: decide qué despierta a alguien |
| | `infra_metrics_view` | La pestaña **Medidas** |
| | `infra_results_view` | La pestaña **Últimos datos**. El único de los tres que retiene el dato: es lo único de la página que ninguna otra pestaña lee, así que sin la bandera el servidor no lo envía |
| | `infra_raw_view` | La pestaña **Datos brutos**: todo lo que contestó el dispositivo, sin agrupar. **No** de `viewer` |
| | | ⚠️ `infra_metrics_view` y `infra_raw_view` deciden **qué ofrece la pantalla**, no qué sabe: los hechos que dibujan son los mismos con los que se construye *Detalles*, así que llegan igual. Retenérselos a alguien que tiene `infra_view` exigiría vaciar *Detalles* también. Está dicho aquí y en `lib/core/infra/manifest.py` a propósito — un permiso que parece un muro y es una cortina es peor que no tenerlo |
| **Empresas** | `orgs_view` | Ver el registro de empresas del grupo y qué tiene fichado cada una. Es la lista que se elige al decir de quién es un armario o una máquina |
| | `orgs_all_view` | Ver las cosas de **todas** las empresas, en cualquier sección. Sin esta bandera solo se ven las de las empresas concedidas una a una (`org.<uid>.view`), y de las demás solo que ocupan sitio |
| | `orgs_edit` | Crear empresas y decir de quién es cada cosa —una sede, un armario, un equipo, una máquina—. **Sin rol por defecto, ni siquiera `editor`**: en un grupo decide qué se factura a qué sociedad y quién puede ver qué |
| | | Se llamaban `dcim_all_view` y `dcim_org_edit`. Salieron del inventario porque la misma sociedad que paga el armario tiene usuarios en el directorio y licencias en Microsoft 365; un rol que tuviera concedidas las viejas conserva lo suyo (`_LEGACY_PERM_RENAME`) |
| **Inventario físico** | `dcim_view` | Ver dónde está el equipamiento: sedes, salas, racks y qué ocupa cada U, y **Catálogo → Plantillas** (el formulario de un equipo elige una). No abre nada del registro — direcciones y credenciales siguen tras `devices_view` |
| | `dcim_edit` | Crear y mover sedes, salas, racks e items: ordenar el armario |
| | `dcim_cable_edit` | Declarar y retirar cableado y etiquetas |
| **Modelos y plantillas** | `dcim_catalog_view` | **Catálogo → Modelos**: consultar el catálogo de modelos de equipo, y las **marcas** con lo que sabemos de ellas —web de soporte, número de contrato—. Se lee sin el permiso de gestión a propósito: esa dirección es la que hace falta a las tres de la mañana |
| | `dcim_catalog_manage` | Crear, editar e importar en Catálogo → Modelos: modelos, marcas, plataformas, conectores y esquemas. **No** de `viewer`: importar trae miles de ficheros y reemplaza aquello con lo que se dibuja cada alzado |
| | `dcim_build_edit` | Escribir las **plantillas** (Catálogo → Plantillas): qué es «un servidor de CPD» en esta casa, con su memoria, sus discos y sus tarjetas. Su propia bandera porque DECIDIR lo que se compra y COLOCAR una caja en un U los hacen personas distintas en momentos distintos, y con una sola quien monta un rack rescribe lo que compra la empresa. **Leerlas va con `dcim_view`**: hay que poder elegir una al colocar un equipo |
| | | ⚠️ **El rack compartido.** Un armario con equipos de varias sociedades rompe que ver un sitio sea ver lo que hay dentro: el de la filial B ve el rack y ve que la U 12 está ocupada —si no, no puede planificar— y no ve de quién es ni cómo se llama. Un item ajeno se devuelve como posición y tamaño, y nada más. Ver [explica-dcim.md](explica-dcim.md#7-permisos) |
| **Sesiones** | `sessions_view` | Ver sesiones activas |
| | `sessions_revoke` | Revocar sesiones |
| **Verificación en dos pasos** | `mfa_reset_others` | Quitar el segundo factor de **otra** cuenta, con sus códigos de recuperación. **Solo de `admin`**, que tiene todos —ni `editor` ni `viewer`—: es el camino de vuelta de quien perdió el móvil *y* los códigos, y es también lo que haría alguien con `users_edit` para desarmar la protección antes de ir a por la contraseña. No existe el contrario —nadie puede **activar** el MFA de otro—, porque solo el dueño puede dar de alta un autenticador que tiene en la mano. Ver [explica-mfa.md](explica-mfa.md#quitar-el-factor-de-otra-cuenta) |
| **Estado** | `checks_view` | Ver resultados de checks y la sección Estado |
| | `checks_run` | Lanzar comprobaciones bajo demanda |
| | `checks_delete` | Vaciar la tabla de estado de los checks (Config › Mantenimiento). **Sin rol por defecto**: antes iba con `checks_run` —que tiene `editor`— y eso dejaba una acción destructiva al alcance de un rol pensado para *operar* la monitorización, no para borrar lo que reportó |
| **Historial** | `history_view` | Ver gráficas y series del historial |
| | `history_delete` | Borrar datos del historial |
| **Syslog** | `syslog_view` | Ver mensajes syslog y descartes (la fuente interna) |
| | `syslog_sources_all_view` | Leer **todas** las fuentes externas (bases de datos de otros programas, como rsyslog). Sin esta bandera solo las concedidas una a una (`syslogsrc.<uid>.view`); en cualquier caso hace falta también `syslog_view` |
| | `syslog_delete` | Vaciar mensajes / descartes (solo la fuente interna: una externa nunca se vacía) |
| **Servicios** | `services_view` | Ver el estado de los servicios |
| | `services_control` | Iniciar/detener servicios |
| **Eventos** | `events_view` | Ver la sección Eventos y sus reglas de notificación |
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
| **Trabajos** | `jobs_view` | Ver **Sistema → Trabajos**: los hilos y el progreso de este proceso. `editor` y `viewer` |
| **Diagnóstico** | `diagnostics_view` | Ver el diagnóstico del sistema: versión, red y TLS, base de datos, dependencias, librerías opcionales, almacenamiento y rutas. No expone secretos, pero sí **la forma de la instalación**, que es el inventario contra el que alguien escribe un exploit — y es, por lo mismo, justo lo que necesita un operador antes de abrir una incidencia. De esa pantalla salen de la máquina **dos comprobaciones**, las dos solo al pulsar su botón y las dos auditadas: la de versión nueva del panel y la de dependencias (última versión en PyPI y avisos de seguridad en OSV.dev). El mismo permiso las abre: es una llamada saliente desde esta máquina, así que va con la página y no con un permiso aparte |

> Ninguno de los siete de **Copias de seguridad** se concede a los roles integrados: una copia
> es una herramienta de administración, y la lista sola ya dice qué existe y desde cuándo. Ver
> [explica-backup.md](explica-backup.md#permisos). `diagnostics_view` tampoco, por la misma
> razón.

**fail2ban** (`ipban_*`, declarados por su servicio). Ver [ref-api.md](ref-api.md#ip-bans-fail2ban--libservicesipbanroutespy).

| Permiso | Descripción | Roles |
|---------|-------------|-------|
| `ipban_ban_view` | Ver los baneos | `editor`, `viewer` |
| `ipban_ban_add` | Añadir baneos | — |
| `ipban_ban_edit` | Editar la respuesta de un baneo | `editor` |
| `ipban_ban_delete` | Desbanear | — |
| `ipban_watchlist_clear` | Limpiar la watchlist | — |
| `ipban_whitelist_view` | Ver la lista blanca | `editor`, `viewer` |
| `ipban_whitelist_add` | Añadir a la lista blanca | — |
| `ipban_whitelist_delete` | Quitar de la lista blanca | — |
| `ipban_history_view` | Ver el historial de baneos | `editor`, `viewer` |
| `ipban_history_delete` | Borrar el historial de baneos | — |
| `ipban_service_edit` | Editar los servicios expuestos | `editor` |
| `ipban_config_edit` | Editar los ajustes de fail2ban | `editor` |

### Permisos dinámicos

Además de los flags globales, existen permisos **dinámicos** por recurso concreto:

- `module.<nombre>.view|add|edit|delete` — restringe el acceso a un módulo concreto.
- `server.<uid>.<acción>` — permiso por dispositivo (ver [explica-dispositivos.md](explica-dispositivos.md)). `add` es añadir checks a **ese** dispositivo, no dar de alta uno.
- `cluster.<uid>.<acción>` — permiso por clúster.
- `org.<uid>.view` — **qué empresas ve** alguien en el inventario físico, para el rack que comparten varias sociedades de un grupo (ver [explica-dcim.md](explica-dcim.md#7-permisos)). **Solo `view`**, a diferencia de los tres de arriba: hoy solo se estrecha la lectura, y una clave para una acción que nadie ejecuta es una casilla que no concede nada y lo parece. Se concede en **Acceso → Permisos**, en las filas por empresa del grupo Empresas.
- `syslogsrc.<uid>.view` — **qué fuentes externas de syslog lee** alguien: bases de datos de otros programas (rsyslog, LogAnalyzer) que el panel consulta sin escribir en ellas. **Solo `view`**, porque una fuente externa nunca se escribe. Se concede en **Acceso → Permisos**, en las filas por fuente del grupo Syslog; `syslog_sources_all_view` las da todas. Al quitar una fuente se retiran de los roles las claves que la nombraban.

> **Mueren con su recurso.** Borrar un dispositivo, quitar un módulo de la configuración, eliminar
> un clúster o eliminar una empresa **poda** sus claves de todos los roles personalizados, con entrada de auditoría
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
- `PERMISSIONS` — tupla con los 94 flags.
- `PERMISSION_GROUPS` — lista de `(key_i18n, [perms])` con la que **Acceso → Permisos** (y los
  diálogos de tokens de API) agrupan los flags.
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
- [explica-mfa.md](explica-mfa.md) — qué concede y qué no concede `mfa_reset_others`
