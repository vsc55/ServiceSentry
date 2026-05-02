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
| **Prueba de Telegram** | Enviar un mensaje de prueba para verificar la conectividad del bot |
| **Modo oscuro** | Preferencia por usuario, persistida entre sesiones |
| **i18n** | Inglés y español; seleccionable por usuario y configurable globalmente con `web_admin.lang` |
| **Registro de auditoría** | Seguimiento de cambios a nivel de campo con enmascarado de datos sensibles |
| **Gestión de sesiones** | Ver sesiones activas; los administradores pueden revocar cualquier sesión |

---

## Roles de Usuario

| Rol | Permisos |
|-----|----------|
| `admin` | Acceso total: usuarios, configuración, módulos, revocación de sesiones |
| `editor` | Puede guardar configuración y módulos; no gestiona usuarios |
| `viewer` | Solo lectura; no puede modificar nada |

### Restricción de roles

- Decorador `@admin_required`: rechaza no-admins con 403.
- Decorador `@write_required`: rechaza viewers con 403.
- Los viewers ven la UI pero todas las acciones de guardar/editar están deshabilitadas.
- Los usuarios no pueden eliminar su propia cuenta ni quitar al último administrador.

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

Todos los endpoints requieren autenticación (cookie de sesión). Los requisitos de rol se indican.

### Autenticación

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/login` | Iniciar sesión con usuario y contraseña |
| `GET` | `/logout` | Cerrar sesión e invalidar la sesión actual |

### Módulos

| Método | Ruta | Rol | Descripción |
|--------|------|-----|-------------|
| `GET` | `/api/modules` | cualquiera | Obtener todas las configuraciones de módulos |
| `POST` | `/api/modules` | editor | Guardar todas las configuraciones de módulos |
| `GET` | `/api/overview` | cualquiera | Obtener resumen de estado de módulos |

### Configuración

| Método | Ruta | Rol | Descripción |
|--------|------|-----|-------------|
| `GET` | `/api/config` | cualquiera | Obtener el `config.json` actual |
| `POST` | `/api/config` | editor | Guardar `config.json` |

### Telegram

| Método | Ruta | Rol | Descripción |
|--------|------|-----|-------------|
| `POST` | `/api/telegram/test` | editor | Enviar un mensaje de prueba por Telegram |

### Usuarios

| Método | Ruta | Rol | Descripción |
|--------|------|-----|-------------|
| `GET` | `/api/users` | admin | Listar todos los usuarios |
| `POST` | `/api/users` | admin | Crear un nuevo usuario |
| `PUT` | `/api/users/<username>` | admin | Editar un usuario |
| `DELETE` | `/api/users/<username>` | admin | Eliminar un usuario |
| `GET` | `/api/me` | cualquiera | Obtener información del usuario actual |
| `PUT` | `/api/users/me/password` | cualquiera | Cambiar la contraseña propia |

### Sesiones

| Método | Ruta | Rol | Descripción |
|--------|------|-----|-------------|
| `GET` | `/api/sessions` | admin | Listar sesiones activas |
| `DELETE` | `/api/sessions/<session_id>` | admin | Revocar una sesión |

### Preferencias de UI

| Método | Ruta | Rol | Descripción |
|--------|------|-----|-------------|
| `POST` | `/set_lang/<lang>` | cualquiera | Establecer preferencia de idioma |
| `POST` | `/set_theme/<theme>` | cualquiera | Establecer preferencia de tema (light/dark) |

---

## i18n

Los ficheros de idioma están en dos lugares:

| Ubicación | Propósito |
|-----------|-----------|
| `src/lib/web_admin/lang/en_EN.py` / `es_ES.py` | Cadenas globales de la UI (navegación, botones, mensajes) |
| `src/watchfuls/<modulo>/lang/en_EN.json` / `es_ES.json` | Etiquetas de campos por módulo y nombre de visualización |

Los metadatos de módulo se cargan automáticamente por `ModuleBase.discover_schemas()` — no hay que modificar ficheros JS globales al añadir un nuevo módulo.

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
