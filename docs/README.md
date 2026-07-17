# ServiceSentry — Documentación

> Sistema de monitorización de servicios e infraestructura con notificaciones multicanal (Telegram, Email, Webhooks, Microsoft Teams) e interfaz web de administración.

**Autor:** Javier Pastor (VSC55) | **Licencia:** GPL v3 | **Python:** 3.10+

---

## Convención de nombres

Cada documento lleva un prefijo según **el tipo de documentación** que es:

| Prefijo | Tipo | Para qué sirve |
| ------- | ---- | -------------- |
| `ref-` | **Referencia** | Consulta: catálogos, tablas, esquemas, listados exhaustivos. Se lee "a saltos". |
| `explica-` | **Explicación** | Cómo y por qué funciona algo: conceptos, arquitectura, decisiones de diseño. |
| `caso-` | **Caso / guía** | Cómo hacer algo concreto: instalar, desplegar, crear un módulo, resolver un problema. |

Principio de **fuente única**: cada tema se documenta en profundidad en **un solo** archivo (su
SSOT); el resto lo referencian con un enlace en vez de duplicarlo. Si editas un tema, edítalo en
su SSOT (ver el [mapa temático](#mapa-temático-dónde-está-cada-cosa)).

> `README.md` (este índice) y `ai-module-guide.md` (guía orientada a IA, con su propio
> versionado interno) quedan fuera de la convención de prefijos.

## Índice

| Documento | Contenido |
| --------- | --------- |
| [caso-despliegue.md](caso-despliegue.md) | Resumen de métodos de despliegue: install.sh, systemd y OpenRC |
| [caso-docker.md](caso-docker.md) | Despliegue con Docker: 3 topologías (monolítica, microservicios con 2 BD, microservicios + Traefik), variables de entorno, volúmenes, redes, actualización y proxy inverso |
| [caso-kubernetes.md](caso-kubernetes.md) | Despliegue en Kubernetes: un Deployment por rol, Secret/ConfigMap, plano de control distribuido (poke `/control`), Services, probes y NetworkPolicy |
| [explica-arquitectura.md](explica-arquitectura.md) | Diagrama de componentes, jerarquía de clases, estructura de directorios, flujo de ejecución, modelo de concurrencia |
| [ref-api.md](ref-api.md) | Referencia REST completa y autoritativa: arquitectura de rutas (sin blueprints, rutas finas + servicio sin Flask), CSRF, versionado, y todos los endpoints por dominio con método/ruta/permiso/propósito + ejemplos |
| [ref-esquema-bd.md](ref-esquema-bd.md) | Esquema de la BD en runtime: las 32 tablas físicas (columnas, tipos, índices, relaciones), diagrama ER y mecanismo de reconcile/portabilidad multi-motor (SQLite/MySQL/PostgreSQL) |
| [explica-rendimiento.md](explica-rendimiento.md) | Rendimiento: modelo de concurrencia (ThreadPoolExecutor por módulo/item), cuellos de botella, cachés, polling, límites de recursos (caps de tablas) y escalado |
| [explica-logging.md](explica-logging.md) | Logging: sistema `Debug` propio (niveles, formato, color, cómo se fija el nivel) + el camino residual de `logging` stdlib; recogida de stdout y rotación delegada |
| [explica-descubrimiento.md](explica-descubrimiento.md) | Sistemas de descubrimiento (self-describing): permisos, widgets de Overview, servicios embebidos, tipos de credencial, perfiles de host, tablas de módulo, provisión Entra y registro de config — descriptores, flujos y datos |
| [explica-servicios.md](explica-servicios.md) | Servicios de fondo (monitor, syslog, eventos, fail2ban): qué hacen, cómo se crean/descubren, embebido vs standalone, estado y comunicación en modo microservicios (BD compartida, comandos, lease de líder, control-plane) y alta disponibilidad |
| [explica-notificaciones.md](explica-notificaciones.md) | Notificaciones: arquitectura (contexto→router→registros de canales y eventos), canales (Telegram HTML, Email SMTP/M365/Gmail, Webhooks HMAC, Microsoft Teams), matriz de routing dinámica por evento, notificación agrupada del monitor, severidad *warning*, y el sistema de textos/plantillas (resolución custom→i18n, listados editables y esquema de tags) |
| [explica-hosts.md](explica-hosts.md) | Modelo host-céntrico: un host = dirección + perfiles de conexión por protocolo (SSH/SNMP/DB…), referencia por `host_uid`, ejecución host-aware (local/SSH), resolución y migración asistida inline→host |
| [ref-configuracion.md](ref-configuracion.md) | config.json (database, syslog, syslog_db, ldap, oidc, saml2, email, notifications, webhooks, modules…), receptor syslog, gestor de eventos, configuración de módulos en BD (tablas `module_config`/`module_config_items`), estado de checks, opciones CLI, variables de entorno (`SS_*`), sistema de debug |
| [ref-cli.md](ref-cli.md) | CLI de gestión one-shot: subcomandos `user`/`group` (alta/baja/rol/contraseña/grupos), `status` y `reload` de servicios; contexto headless, capa de servicio compartida en `lib/core` (rutas web + CLI) y auto-discovery de servicios |
| [ref-modulos.md](ref-modulos.md) | Los 19 módulos integrados: referencia de configuración, campos y flujo de cada uno |
| [explica-web-admin.md](explica-web-admin.md) | Interfaz web Flask: características, roles (63 permisos), notificaciones, syslog, eventos, seguridad, endpoints REST, i18n, formularios por schema |
| [explica-seguridad.md](explica-seguridad.md) | Autenticación (local/LDAP/OIDC/SAML2), semántica RBAC (escalada, IDOR), sesiones, cifrado, XSS, SSRF, path traversal, auditoría y tests de seguridad |
| [ref-permisos.md](ref-permisos.md) | Fuente única del RBAC: catálogo de los 63 flags de permiso, roles integrados/personalizados, grupos, permisos dinámicos (módulo/servidor/cluster) y estructuras internas |
| [caso-entra-id.md](caso-entra-id.md) | Microsoft Entra ID: SSO (OIDC y SAML2) + asistentes de registro de app (Device Code) para SSO/SCIM/M365-email/Teams; flujo, campos de config y **limitaciones** de Graph (config básica de SAML manual, dominios no verificados, `instantiate`, `servicePrincipalNames`) + resolución de problemas |
| [caso-scim.md](caso-scim.md) | Aprovisionamiento SCIM 2.0 (agnóstico del IdP): activar endpoint + token, JIT vs SCIM, configurar Entra/Okta/otros IdP, altas/bajas y soft-delete de grupos, badges |
| [caso-ssh-hardening.md](caso-ssh-hardening.md) | Endurecer los hosts monitorizados: cuenta dedicada, comando forzado + envoltorio con allowlist ([ssentry-wrap](ssentry-wrap)), sudoers mínimo para remediación |
| [caso-desarrollo.md](caso-desarrollo.md) | Setup local, tests, pytest, depuración en VS Code, convenciones de código, dependencias |
| [caso-guia-watchful.md](caso-guia-watchful.md) | Guía paso a paso para crear un nuevo módulo de monitorización |
| [ai-module-guide.md](ai-module-guide.md) | Guía de creación de módulos orientada a IA: referencia de build validada + catálogo de fallos comunes (F-01…F-14) |
| [ref-schema-json.md](ref-schema-json.md) | Referencia completa de `schema.json`: todas las propiedades de campo, meta-claves, archivos de idioma y pipeline de `discover_schemas` |
| [explica-i18n.md](explica-i18n.md) | Mecánica de i18n: capa global de UI + capa por módulo, resolución de etiquetas en navegador, pipeline de `discover_schemas`, cómo añadir idiomas |
| [ref-i18n.md](ref-i18n.md) | Referencia de i18n: estructura de `lang/*.json`, los tres esquemas de tags (`notif_msg_vars`/`notif_email_vars`/`messages_vars`) y placeholders `_fill` (secuencial vs indexado) |
| [ref-tests.md](ref-tests.md) | Inventario completo de tests: qué comprueba cada test, condiciones de OK y error, organizado por grupos |
| [caso-diagnostico.md](caso-diagnostico.md) | Bugs resueltos y trampas conocidas: causa raíz, solución y lección generalizable de fallos no evidentes que costaron aislar |

---

## Mapa temático (dónde está cada cosa)

Guía rápida por temas de documentación técnica → documento(s) donde se cubre:

| Tema | Documento(s) |
| ---- | ------------ |
| **Arquitectura** (componentes, flujo de datos, concurrencia, diagramas) | [explica-arquitectura.md](explica-arquitectura.md) · [explica-rendimiento.md](explica-rendimiento.md) |
| **Estructura del repositorio** | [explica-arquitectura.md](explica-arquitectura.md) (§ estructura de directorios) · [explica-web-admin.md](explica-web-admin.md) (§ organización del código) |
| **Backend Python** (paquetes, clases, rutas, servicios) | [explica-web-admin.md](explica-web-admin.md) · [explica-servicios.md](explica-servicios.md) · [ref-modulos.md](ref-modulos.md) · [caso-guia-watchful.md](caso-guia-watchful.md) · [ai-module-guide.md](ai-module-guide.md) |
| **Frontend** (HTML/CSS/JS, componentes, fetch, DOM, i18n) | [explica-web-admin.md](explica-web-admin.md) · [explica-i18n.md](explica-i18n.md) · [ref-i18n.md](ref-i18n.md) |
| **API REST** (endpoints, métodos, permisos, ejemplos) | [ref-api.md](ref-api.md) |
| **Flujo de ejecución** (arranque → respuesta) | [explica-arquitectura.md](explica-arquitectura.md) (§ flujo de ejecución) |
| **Configuración** (config.json, BD, env `SS_*`, secretos) | [ref-configuracion.md](ref-configuracion.md) · [ref-schema-json.md](ref-schema-json.md) |
| **Instalación** (Linux/Windows/Docker) | [caso-despliegue.md](caso-despliegue.md) · [caso-docker.md](caso-docker.md) · [caso-desarrollo.md](caso-desarrollo.md) |
| **Despliegue** (producción, proxy inverso, HTTPS, systemd, Compose, k8s) | [caso-despliegue.md](caso-despliegue.md) · [caso-docker.md](caso-docker.md) · [caso-kubernetes.md](caso-kubernetes.md) · [caso-ssh-hardening.md](caso-ssh-hardening.md) |
| **Seguridad** (auth, CSRF, XSS, SQLi, sesiones, cifrado) | [explica-seguridad.md](explica-seguridad.md) · [caso-entra-id.md](caso-entra-id.md) |
| **SSO / provisioning** (Entra ID, SCIM, LDAP) | [caso-entra-id.md](caso-entra-id.md) · [caso-scim.md](caso-scim.md) · [explica-seguridad.md](explica-seguridad.md) |
| **Permisos / RBAC** (flags, roles, grupos) | [ref-permisos.md](ref-permisos.md) · [explica-seguridad.md](explica-seguridad.md) (semántica) |
| **i18n** (traducción, tags, plantillas de texto) | [explica-i18n.md](explica-i18n.md) · [ref-i18n.md](ref-i18n.md) · [explica-notificaciones.md](explica-notificaciones.md) |
| **Módulos** (crear/configurar watchfuls, schema.json) | [caso-guia-watchful.md](caso-guia-watchful.md) · [ref-modulos.md](ref-modulos.md) · [ref-schema-json.md](ref-schema-json.md) · [explica-descubrimiento.md](explica-descubrimiento.md) |
| **Rendimiento** (cuellos de botella, concurrencia, cachés) | [explica-rendimiento.md](explica-rendimiento.md) |
| **Dependencias** (para qué sirve cada una) | [caso-desarrollo.md](caso-desarrollo.md) (§ dependencias) |
| **Base de datos** (esquema, tablas, relaciones, migraciones) | [ref-esquema-bd.md](ref-esquema-bd.md) |
| **Tests** (cobertura, tipos, cómo ejecutarlos) | [ref-tests.md](ref-tests.md) · [caso-desarrollo.md](caso-desarrollo.md) |
| **Logging** (niveles, destinos, rotación, formato) | [explica-logging.md](explica-logging.md) · [ref-configuracion.md](ref-configuracion.md) |
| **Notificaciones** (canales, routing, plantillas) | [explica-notificaciones.md](explica-notificaciones.md) |
| **Diagramas Mermaid** | [explica-arquitectura.md](explica-arquitectura.md) · [ref-esquema-bd.md](ref-esquema-bd.md) · [explica-seguridad.md](explica-seguridad.md) · [explica-notificaciones.md](explica-notificaciones.md) |

---

## Descripción General

ServiceSentry es una herramienta de monitorización para sistemas que:

- Ejecuta comprobaciones periódicas sobre servicios, discos, RAID, RAM, temperaturas, webs, bases de datos, ping, SNMP, etc.
- Detecta **cambios de estado** — no envía notificación si el estado no ha cambiado (sin spam).
- Envía alertas por **Telegram**, **Email** (SMTP / Microsoft 365 / Gmail), **Webhooks** (con firma HMAC) y **Microsoft Teams**, con matriz de routing por evento y severidad *warning* (aviso ámbar) además de caído/recuperado.
- **Receptor syslog** integrado (RFC 3164/5424, UDP/TCP/TLS) con BD dedicada opcional, y un **gestor de eventos** que notifica reglas sobre eventos de auditoría o syslog.
- Incluye **interfaz web de administración** (Flask) con RBAC (63 permisos), grupos, modo oscuro, historial con gráficas e i18n.
- **Autenticación externa** opcional: LDAP/AD, SSO OIDC/OAuth2 y SAML2, con sincronización de usuarios y mapeo de grupos a roles.
- **Persistencia pluggable**: SQLite por defecto, o PostgreSQL/MySQL; el esquema se valida y reconcilia automáticamente en cada arranque.
- Soporta ejecución **local** y **remota** (SSH vía paramiko).
- Ejecuta los módulos en **paralelo** usando `ThreadPoolExecutor`.
- Arquitectura de **plugins**: cada módulo es un package independiente en `watchfuls/`.
- Usa `match/case` nativo de Python 3.10+.
- 15 de los 19 módulos son **multiplataforma** 🌐 (Linux / Windows).

---

## Módulos incluidos

| Módulo | Plataforma | Descripción |
| ------ | ---------- | ----------- |
| `cpu` 🌐 | Linux / Win | Uso total de CPU (psutil) |
| `datastore` 🌐 | Linux / Win | Conectividad a bases de datos (MySQL, PostgreSQL, MSSQL, MongoDB, Redis, InfluxDB, Elasticsearch) |
| `dns` 🌐 | Linux / Win | Resolución DNS con validación de IP esperada |
| `filesystemusage` 🌐 | Linux / Win | Uso de particiones (psutil) |
| `hddtemp` | Linux | Temperatura de discos (demonio hddtemp) |
| `keepalived` | Linux | Cluster keepalived VRRP: servicio por nodo, titular de la VIP, split-brain y prioridad |
| `m365` 🌐 | Linux / Win | Microsoft 365 vía Graph: almacenamiento SharePoint por sitio + uso del tenant |
| `ntp` 🌐 | Linux / Win | Offset de sincronización NTP (UDP nativo) |
| `ping` 🌐 | Linux / Windows\* | Disponibilidad de hosts (`pythonping` o ICMP raw socket) |
| `process` 🌐 | Linux / Win | Procesos en ejecución con mínimo de instancias (psutil) |
| `proxmox` 🌐 | Linux / Win | Proxmox VE vía REST: quorum, Ceph, nodos, red, actualizaciones |
| `raid` | Linux | Estado RAID mdstat (local + SSH remoto) |
| `ram_swap` 🌐 | Linux / Win | Uso de RAM y SWAP (psutil) |
| `service_status` 🌐 | Linux / Windows | Estado de servicios (systemd / OpenRC / SysV / Windows SCM) |
| `snmp` 🌐 | Linux / Win | Monitorización SNMP (v1/v2c/v3) de OIDs con gestión y compilación de MIBs |
| `ssl_cert` 🌐 | Linux / Win | Expiración de certificados SSL/TLS |
| `temperature` | Linux | Sensores térmicos (psutil) |
| `ups` 🌐 | Linux / Win | Estado de SAI/UPS vía NUT TCP |
| `web` 🌐 | Linux / Win | Disponibilidad HTTP/HTTPS (urllib) |
