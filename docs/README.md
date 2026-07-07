# ServiceSentry — Documentación

> Sistema de monitorización de servicios e infraestructura con notificaciones por Telegram e interfaz web de administración.

**Autor:** Javier Pastor (VSC55) | **Licencia:** GPL v3 | **Python:** 3.10+

---

## Índice

| Documento | Contenido |
| --------- | --------- |
| [deployment.md](deployment.md) | Resumen de métodos de despliegue: install.sh, systemd y OpenRC |
| [docker.md](docker.md) | Despliegue con Docker: 3 topologías (monolítica, microservicios con 2 BD, microservicios + Traefik), variables de entorno, volúmenes, redes, actualización y proxy inverso |
| [kubernetes.md](kubernetes.md) | Despliegue en Kubernetes: un Deployment por rol, Secret/ConfigMap, plano de control distribuido (poke `/control`), Services, probes y NetworkPolicy |
| [architecture.md](architecture.md) | Diagrama de componentes, jerarquía de clases, estructura de directorios, flujo de ejecución, modelo de concurrencia |
| [discovery.md](discovery.md) | Sistemas de descubrimiento (self-describing): permisos, widgets de Overview, servicios embebidos, tipos de credencial, perfiles de host, tablas de módulo, provisión Entra y registro de config — descriptores, flujos y datos |
| [services.md](services.md) | Servicios de fondo (monitor, syslog, eventos, fail2ban): qué hacen, cómo se crean/descubren, embebido vs standalone, estado y comunicación en modo microservicios (BD compartida, comandos, lease de líder, control-plane) y alta disponibilidad |
| [notifications.md](notifications.md) | Notificaciones: canales (Telegram, Email SMTP/M365/Gmail, Webhooks), el dispatcher central, flujo evento→notificación, matriz de routing por evento, firma HMAC y plantillas |
| [hosts.md](hosts.md) | Modelo host-céntrico: un host = dirección + perfiles de conexión por protocolo (SSH/SNMP/DB…), referencia por `host_uid`, ejecución host-aware (local/SSH), resolución y migración asistida inline→host |
| [configuration.md](configuration.md) | config.json (database, syslog, syslog_db, ldap, oidc, saml2, email, notifications, webhooks, modules…), receptor syslog, gestor de eventos, configuración de módulos en BD (tablas `module_config`/`module_config_items`), estado de checks, opciones CLI, variables de entorno (`SS_*`), sistema de debug |
| [modules.md](modules.md) | Los 19 módulos integrados: referencia de configuración, campos y flujo de cada uno |
| [web_admin.md](web_admin.md) | Interfaz web Flask: características, roles (63 permisos), notificaciones, syslog, eventos, seguridad, endpoints REST, i18n, formularios por schema |
| [security.md](security.md) | Autenticación (local/LDAP/OIDC/SAML2), RBAC, sesiones, cifrado, XSS, SSRF, path traversal, auditoría y tests de seguridad |
| [sso-entra.md](sso-entra.md) | SSO con Microsoft Entra ID (OIDC y SAML2): asistente de registro automático, flujo, campos de config y **limitaciones** de Graph (config básica de SAML manual, dominios no verificados, `instantiate`, `servicePrincipalNames`) + resolución de problemas |
| [ssh-hardening.md](ssh-hardening.md) | Endurecer los hosts monitorizados: cuenta dedicada, comando forzado + envoltorio con allowlist ([ssentry-wrap](ssentry-wrap)), sudoers mínimo para remediación |
| [development.md](development.md) | Setup local, tests, pytest, depuración en VS Code, convenciones de código, dependencias |
| [watchful_guide.md](watchful_guide.md) | Guía paso a paso para crear un nuevo módulo de monitorización |
| [schema.md](schema.md) | Referencia completa de `schema.json`: todas las propiedades de campo, meta-claves, archivos de idioma y pipeline de `discover_schemas` |
| [i18n.md](i18n.md) | Sistema de internacionalización: arquitectura de dos niveles, pipeline de `discover_schemas`, añadir idiomas |
| [tests.md](tests.md) | Inventario completo de tests: qué comprueba cada test, condiciones de OK y error, organizado por grupos |

---

## Descripción General

ServiceSentry es una herramienta de monitorización para sistemas que:

- Ejecuta comprobaciones periódicas sobre servicios, discos, RAID, RAM, temperaturas, webs, bases de datos, ping, SNMP, etc.
- Detecta **cambios de estado** — no envía notificación si el estado no ha cambiado (sin spam).
- Envía alertas por **Telegram**, **Email** (SMTP / Microsoft 365 / Gmail) y **Webhooks** (con firma HMAC), con matriz de routing por evento.
- **Receptor syslog** integrado (RFC 3164/5424, UDP/TCP/TLS) con BD dedicada opcional, y un **gestor de eventos** que notifica reglas sobre eventos de auditoría o syslog.
- Incluye **interfaz web de administración** (Flask) con RBAC (63 permisos), grupos, modo oscuro, historial con gráficas e i18n.
- **Autenticación externa** opcional: LDAP/AD, SSO OIDC/OAuth2 y SAML2, con sincronización de usuarios y mapeo de grupos a roles.
- **Persistencia pluggable**: SQLite por defecto, o PostgreSQL/MySQL; el esquema se valida y reconcilia automáticamente en cada arranque.
- Soporta ejecución **local** y **remota** (SSH vía paramiko).
- Ejecuta los módulos en **paralelo** usando `ThreadPoolExecutor`.
- Arquitectura de **plugins**: cada módulo es un package independiente en `watchfuls/`.
- Usa `match/case` nativo de Python 3.10+.
- 15 de los 19 módulos son **multiplataforma** 🌐 (Linux / Windows / macOS).

---

## Módulos incluidos

| Módulo | Plataforma | Descripción |
| ------ | ---------- | ----------- |
| `cpu` 🌐 | Linux / Win / macOS | Uso total de CPU (psutil) |
| `datastore` 🌐 | Linux / Win / macOS | Conectividad a bases de datos (MySQL, PostgreSQL, MSSQL, MongoDB, Redis, InfluxDB, Elasticsearch) |
| `dns` 🌐 | Linux / Win / macOS | Resolución DNS con validación de IP esperada |
| `filesystemusage` 🌐 | Linux / Win / macOS | Uso de particiones (psutil) |
| `hddtemp` | Linux | Temperatura de discos (demonio hddtemp) |
| `keepalived` | Linux | Cluster keepalived VRRP: servicio por nodo, titular de la VIP, split-brain y prioridad |
| `m365` 🌐 | Linux / Win / macOS | Microsoft 365 vía Graph: almacenamiento SharePoint por sitio + uso del tenant |
| `ntp` 🌐 | Linux / Win / macOS | Offset de sincronización NTP (UDP nativo) |
| `ping` 🌐 | Linux / macOS / Windows\* | Disponibilidad de hosts (`pythonping` o ICMP raw socket) |
| `process` 🌐 | Linux / Win / macOS | Procesos en ejecución con mínimo de instancias (psutil) |
| `proxmox` 🌐 | Linux / Win / macOS | Proxmox VE vía REST: quorum, Ceph, nodos, red, actualizaciones |
| `raid` | Linux | Estado RAID mdstat (local + SSH remoto) |
| `ram_swap` 🌐 | Linux / Win / macOS | Uso de RAM y SWAP (psutil) |
| `service_status` 🌐 | Linux / Windows | Estado de servicios (systemd / OpenRC / SysV / Windows SCM) |
| `snmp` 🌐 | Linux / Win / macOS | Monitorización SNMP (v1/v2c/v3) de OIDs con gestión y compilación de MIBs |
| `ssl_cert` 🌐 | Linux / Win / macOS | Expiración de certificados SSL/TLS |
| `temperature` | Linux / macOS | Sensores térmicos (psutil) |
| `ups` 🌐 | Linux / Win / macOS | Estado de SAI/UPS vía NUT TCP |
| `web` 🌐 | Linux / Win / macOS | Disponibilidad HTTP/HTTPS (urllib) |
