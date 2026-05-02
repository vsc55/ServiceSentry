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
| [development.md](development.md) | Setup local, tests (870), pytest, depuración en VS Code, convenciones de código, dependencias |
| [watchful_guide.md](watchful_guide.md) | Guía paso a paso para crear un nuevo módulo de monitorización |
| [i18n.md](i18n.md) | Sistema de internacionalización: arquitectura de dos niveles, pipeline de `discover_schemas`, añadir idiomas |
| [tests.md](tests.md) | Inventario completo de tests (870): qué comprueba cada test, condiciones de OK y error, organizado por grupos |

---

## Descripción General

ServiceSentry es una herramienta de monitorización para sistemas que:

- Ejecuta comprobaciones periódicas sobre servicios, discos, RAID, RAM, temperaturas, webs, MySQL, ping, etc.
- Detecta **cambios de estado** — no envía notificación si el estado no ha cambiado (sin spam).
- Envía alertas por **Telegram** cuando algo cambia.
- Incluye **interfaz web de administración** (Flask) con roles, modo oscuro e i18n.
- Soporta ejecución **local** y **remota** (SSH vía paramiko).
- Ejecuta los módulos en **paralelo** usando `ThreadPoolExecutor`.
- Arquitectura de **plugins**: cada módulo es un package independiente en `watchfuls/`.
- Usa `match/case` nativo de Python 3.10+.
- Módulos `filesystemusage`, `ram_swap` y `web` son **multiplataforma** (Linux/Windows/macOS).

---

## Módulos incluidos

| Módulo | Plataforma | Descripción |
|--------|-----------|-------------|
| `filesystemusage` 🌐 | Linux / Win / macOS | Uso de particiones (psutil) |
| `hddtemp` | Linux | Temperatura de discos (demonio hddtemp) |
| `mysql` | Linux / Win / macOS | Conectividad MySQL (pymysql) |
| `ping` 🌐 | Linux / macOS / Windows\* | Disponibilidad de hosts (`pythonping` o ICMP raw socket) |
| `raid` | Linux | Estado RAID mdstat (local + SSH) |
| `ram_swap` 🌐 | Linux / Win / macOS | Uso de RAM y SWAP (psutil) |
| `service_status` | Linux (systemd) | Estado de servicios systemd + auto-remediación |
| `temperature` | Linux | Sensores térmicos /sys/class/thermal |
| `web` 🌐 | Linux / Win / macOS | Disponibilidad HTTP/HTTPS (urllib) |
