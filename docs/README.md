# ServiceSentry — Documentación

> Sistema de monitorización de servicios e infraestructura con notificaciones por Telegram e interfaz web de administración.

**Autor:** Javier Pastor (VSC55) | **Licencia:** GPL v3 | **Python:** 3.10+

---

## Índice

| Documento | Contenido |
|-----------|-----------|
| [architecture.md](architecture.md) | Diagrama de componentes, jerarquía de clases, estructura de directorios, flujo de ejecución, modelo de concurrencia |
| [configuration.md](configuration.md) | config.json, monitor.json, modules.json, status.json, opciones CLI, Telegram, sistema de debug |
| [modules.md](modules.md) | Los 9 módulos integrados: referencia de configuración, campos y flujo de cada uno |
| [web_admin.md](web_admin.md) | Interfaz web Flask: características, roles, seguridad, endpoints REST, i18n, formularios por schema |
| [security.md](security.md) | Autenticación, RBAC, sesiones, XSS, path traversal, auditoría y tests de seguridad del panel web |
| [development.md](development.md) | Setup local, tests, pytest, depuración en VS Code, convenciones de código, dependencias |
| [watchful_guide.md](watchful_guide.md) | Guía paso a paso para crear un nuevo módulo de monitorización |
| [schema.md](schema.md) | Referencia completa de `schema.json`: todas las propiedades de campo, meta-claves, archivos de idioma y pipeline de `discover_schemas` |
| [i18n.md](i18n.md) | Sistema de internacionalización: arquitectura de dos niveles, pipeline de `discover_schemas`, añadir idiomas |
| [tests.md](tests.md) | Inventario completo de tests: qué comprueba cada test, condiciones de OK y error, organizado por grupos |

---

## Descripción General

ServiceSentry es una herramienta de monitorización para sistemas que:

- Ejecuta comprobaciones periódicas sobre servicios, discos, RAID, RAM, temperaturas, webs, bases de datos, ping, etc.
- Detecta **cambios de estado** — no envía notificación si el estado no ha cambiado (sin spam).
- Envía alertas por **Telegram** cuando algo cambia.
- Incluye **interfaz web de administración** (Flask) con roles, modo oscuro e i18n.
- Soporta ejecución **local** y **remota** (SSH vía paramiko).
- Ejecuta los módulos en **paralelo** usando `ThreadPoolExecutor`.
- Arquitectura de **plugins**: cada módulo es un package independiente en `watchfuls/`.
- Usa `match/case` nativo de Python 3.10+.
- 6 de los 9 módulos son **multiplataforma** 🌐 (Linux / Windows / macOS).

---

## Módulos incluidos

| Módulo | Plataforma | Descripción |
|--------|-----------|-------------|
| `datastore` 🌐 | Linux / Win / macOS | Conectividad a bases de datos (MySQL, PostgreSQL, MSSQL, MongoDB, Redis, InfluxDB, Elasticsearch) |
| `filesystemusage` 🌐 | Linux / Win / macOS | Uso de particiones (psutil) |
| `hddtemp` | Linux | Temperatura de discos (demonio hddtemp) |
| `ping` 🌐 | Linux / macOS / Windows\* | Disponibilidad de hosts (`pythonping` o ICMP raw socket) |
| `raid` | Linux | Estado RAID mdstat (local + SSH remoto) |
| `ram_swap` 🌐 | Linux / Win / macOS | Uso de RAM y SWAP (psutil) |
| `service_status` 🌐 | Linux / Windows | Estado de servicios (systemd / OpenRC / SysV / Windows SCM) |
| `temperature` | Linux / macOS | Sensores térmicos (psutil) |
| `web` 🌐 | Linux / Win / macOS | Disponibilidad HTTP/HTTPS (urllib) |
