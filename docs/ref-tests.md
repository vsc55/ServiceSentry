# Documentación de Tests — ServiceSentry

**Total: ~4520 tests** (4514 recolectados; ~35 se saltan). Todos deben pasar con `pytest` para que el build sea válido. Los skips habituales: los tests de integridad Watchful que no aplican a un módulo (sin credencial / no host-capable), el arnés de portabilidad multi-motor (§81) sin sus variables de entorno o bajo `-n auto`, y algún test con `skipif` de plataforma (p. ej. rangos reservados de Windows en `test_wa_server.py`).

> Los tests se ejecutan **en paralelo automáticamente** gracias a `-n auto` de `pytest-xdist` (configurado en `src/pytest.ini`). Tiempo típico ~2 min en una máquina con 8 cores. Para ejecutar en serie usa `-n 0`.

> **Motor de BD en tests:** la suite corre sobre **SQLite** (que tolera SQL no portable). Los bugs específicos de **MySQL/MariaDB** y **PostgreSQL** (los motores de producción) se cubren con un arnés **opt-in** que corre los stores contra motores reales cuando se definen variables de entorno — ver §81. Sin esas variables, ese arnés se salta y no afecta al build.

---

## Índice

1. [Core — Configuración](#1-core--configuración)
2. [Core — Debug](#2-core--debug)
3. [Core — Utilidades de datos](#3-core--utilidades-de-datos)
4. [Core — Ejecución de comandos (Exec)](#4-core--ejecución-de-comandos-exec)
5. [Core — Memoria del sistema](#5-core--memoria-del-sistema)
6. [Core — Sensores térmicos](#6-core--sensores-térmicos)
7. [Core — Helpers de parseo](#7-core--helpers-de-parseo)
8. [Core — Herramientas generales](#8-core--herramientas-generales)
8b. [Core — Reconciliación de esquema de BD](#8b-core--reconciliación-de-esquema-de-bd)
9. [Monitor — Descubrimiento y ejecución de módulos](#9-monitor--descubrimiento-y-ejecución-de-módulos)
10. [Integridad de módulos Watchful](#10-integridad-de-módulos-watchful)
11. [Panel Web — Inicialización y autenticación](#11-panel-web--inicialización-y-autenticación)
12. [Panel Web — API módulos y configuración](#12-panel-web--api-módulos-y-configuración)
13. [Panel Web — API estado y ejecución de checks](#13-panel-web--api-estado-y-ejecución-de-checks)
14. [Panel Web — Usuarios, roles y sesiones](#14-panel-web--usuarios-roles-y-sesiones)
15. [Panel Web — i18n, UI y seguridad](#15-panel-web--i18n-ui-y-seguridad)
15b. [Panel Web — Política de contraseñas](#15b-panel-web--política-de-contraseñas)
15c. [Panel Web — Página de estado pública](#15c-panel-web--página-de-estado-pública)
15d. [Panel Web — Páginas de error HTTP](#15d-panel-web--páginas-de-error-http)
16. [Panel Web — Permisos granulares y roles personalizados](#16-panel-web--permisos-granulares-y-roles-personalizados)
16b. [Panel Web — Helpers JSON y validación de payloads](#16b-panel-web--helpers-json-y-validación-de-payloads)
16c. [Panel Web — Endpoint de acciones de watchfuls](#16c-panel-web--endpoint-de-acciones-de-watchfuls)
16d. [Panel Web — Matriz de permisos por endpoint](#16d-panel-web--matriz-de-permisos-por-endpoint)
17. [Watchful: filesystemusage](#17-watchful-filesystemusage)
18. [Watchful: hddtemp](#18-watchful-hddtemp)
19. [Watchful: datastore](#19-watchful-datastore)
20. [Watchful: ping](#20-watchful-ping)
21. [Watchful: raid](#21-watchful-raid)
22. [Watchful: ram\_swap](#22-watchful-ram_swap)
23. [Watchful: service\_status](#23-watchful-service_status)
24. [Watchful: temperature](#24-watchful-temperature)
25. [Watchful: web](#25-watchful-web)
26. [Seguridad: secret\_manager](#26-seguridad-secret_manager)
27. [Watchful: cpu](#27-watchful-cpu)
28. [Watchful: ssl\_cert](#28-watchful-ssl_cert)
29. [Watchful: process](#29-watchful-process)
30. [Watchful: dns](#30-watchful-dns)
31. [Watchful: ntp](#31-watchful-ntp)
32. [Watchful: ups](#32-watchful-ups)
33. [Core — CLI y variables de entorno](#33-core--cli-y-variables-de-entorno)
34. [Core — Resolución de configuración](#34-core--resolución-de-configuración)
35. [Core — Registro central de config (spec)](#35-core--registro-central-de-config-spec)
36. [Core — Almacén de config en BD](#36-core--almacén-de-config-en-bd)
37. [BD — Tablas declaradas por módulos](#37-bd--tablas-declaradas-por-módulos)
38. [BD — ModulesStore](#38-bd--modulesstore)
39. [BD — HostsStore](#39-bd--hostsstore)
40. [BD — CredentialsStore](#40-bd--credentialsstore)
41. [Core — Cliente SSH](#41-core--cliente-ssh)
42. [Hosts — Ejecución local/SSH](#42-hosts--ejecución-localssh)
43. [Hosts — Perfiles de protocolo](#43-hosts--perfiles-de-protocolo)
44. [Hosts — Resolución host→check](#44-hosts--resolución-hostcheck)
45. [Hosts — Sonda de check único](#45-hosts--sonda-de-check-único)
46. [Hosts — Asistente de migración](#46-hosts--asistente-de-migración)
47. [Seguridad — Regresión](#47-seguridad--regresión)
48. [Syslog — Parser RFC 3164/5424](#48-syslog--parser-rfc-31645424)
49. [Syslog — Listener UDP/TCP/TLS](#49-syslog--listener-udptcptls)
50. [Syslog — SyslogStore](#50-syslog--syslogstore)
51. [Syslog — Servicio independiente](#51-syslog--servicio-independiente)
52. [Panel Web — Comprobación de rol admin](#52-panel-web--comprobación-de-rol-admin)
53. [Panel Web — LDAP](#53-panel-web--ldap)
54. [Panel Web — OIDC/SSO](#54-panel-web--oidcsso)
55. [Panel Web — SAML2](#55-panel-web--saml2)
55b. [Capa Microsoft compartida (Entra ID + ARM)](#55b-capa-microsoft-compartida-entra-id--arm)
56. [Panel Web — Servidores (hosts)](#56-panel-web--servidores-hosts)
57. [Panel Web — Historial](#57-panel-web--historial)
58. [Panel Web — Webhooks](#58-panel-web--webhooks)
59. [Panel Web — Plantillas de notificación](#59-panel-web--plantillas-de-notificación)
60. [Panel Web — Syslog](#60-panel-web--syslog)
61. [Panel Web — Gestor de eventos](#61-panel-web--gestor-de-eventos)
62. [Panel Web — Servicios](#62-panel-web--servicios)
63. [Watchful: keepalived](#63-watchful-keepalived)
64. [Watchful: m365](#64-watchful-m365)
65. [Watchful: proxmox](#65-watchful-proxmox)
66. [Watchful: snmp](#66-watchful-snmp)
67. [Watchful: ping — get_conf_in_list](#67-watchful-ping--get_conf_in_list-tipos-de-clave)
68. [Servicios — Cola de comandos (ServiceCommandsStore)](#68-servicios--cola-de-comandos-servicecommandsstore)
69. [Servicios — Registro de heartbeat (ServiceInstancesStore)](#69-servicios--registro-de-heartbeat--estado-serviceinstancesstore)
70. [Servicios — Lease de líder HA (ServiceLeaderStore)](#70-servicios--lease-de-líder-único-ha-serviceleaderstore)
71. [Panel Web — API de comandos de servicio](#71-panel-web--api-de-comandos-de-servicio)
72. [Servicios — Listener de control (ControlServer)](#72-servicios--listener-http-de-control-controlserver)
73. [Servicios — Helpers de heartbeat](#73-servicios--helpers-de-heartbeat-db_summary--app_version)
74. [Panel Web — Layout de la config UI](#74-panel-web--layout-de-la-config-ui-registry-driven)
75. [Providers — Provisioning Entra ID](#75-providers--provisioning-de-apps-entra-id-graph)
76. [Hosts — Primitivas de resolución](#76-hosts--primitivas-de-resolución-libhostsresolvepy)
77. [Hosts — Hook de hosts aprovisionados](#77-hosts--hook-de-hosts-aprovisionados)
78. [Panel Web — Política de bind del servidor web](#78-panel-web--política-de-bind-del-servidor-web)
79. [Panel Web — SCIM 2.0 (aprovisionamiento)](#79-panel-web--scim-20-aprovisionamiento)
80. [Panel Web — Utilidades genéricas](#80-panel-web--utilidades-genéricas-apiv1util)
81. [Seguridad (regresiones) y Portabilidad multi-motor](#81-seguridad-regresiones-y-portabilidad-multi-motor)
82. [Servicios — IP-ban (jail, store, integración)](#82-servicios--ip-ban-jail-store-integración)
83. [CLI — Servicios de usuarios/grupos y comandos](#83-cli--servicios-de-usuariosgrupos-y-comandos)
84. [Monitor — Notificador multi-canal](#84-monitor--notificador-multi-canal-routing-y-formato)
85. [Servicios — SCIM (helpers unitarios)](#85-servicios--scim-helpers-unitarios)
86. [Panel Web — Protección CSRF](#86-panel-web--protección-csrf)
87. [Panel Web — Cabeceras de seguridad y módulo CSRF](#87-panel-web--cabeceras-de-seguridad-y-módulo-csrf)
88. [Core — Estampado de entidades (audit)](#88-core--estampado-de-entidades-audit)
88b. [Watchfuls — Patrones de publicación de resultados](#88b-watchfuls--patrones-de-publicación-de-resultados)
88c. [Meta — Versión y CHANGELOG](#88c-meta--versión-y-changelog)
88c-bis. [Meta — Secciones publicadas del CHANGELOG](#88c-bis-meta--secciones-publicadas-del-changelog)
88d. [Meta — Enlaces con número de línea](#88d-meta--enlaces-con-número-de-línea)
89. [Meta — Este documento](#89-meta--este-documento)
90. [Core — Salud, escaneos programados y HA](#90-core--salud-escaneos-programados-y-ha)
91. [Notificaciones — registro de eventos, idioma, destinatarios y overrides](#91-notificaciones--registro-de-eventos-idioma-destinatarios-y-overrides)
92. [Panel Web — páginas de sección, cuenta y convenciones de partials](#92-panel-web--páginas-de-sección-cuenta-y-convenciones-de-partials)
93. [Panel Web — Microsoft Teams](#93-panel-web--microsoft-teams)
94. [Panel Web — orígenes de grupos, acciones de configuración y rate limit](#94-panel-web--orígenes-de-grupos-acciones-de-configuración-y-rate-limit)
95. [Overview — recuento de checks y filtros de severidad](#95-overview--recuento-de-checks-y-filtros-de-severidad)
96. [Guards de documentación e i18n](#96-guards-de-documentación-e-i18n)
97. [Watchfuls — severidad de avisos y RAID mdstat](#97-watchfuls--severidad-de-avisos-y-raid-mdstat)
98. [Entra ID — paso de RBAC de Azure del asistente](#98-entra-id--paso-de-rbac-de-azure-del-asistente)
99. [Panel Web — sección Permisos (Acceso › Permisos)](#99-panel-web--sección-permisos-acceso--permisos)
100. [Meta — Cada dominio del core guarda su propio código](#100-meta--cada-dominio-del-core-guarda-su-propio-código)
101. [Permisos — poda de claves por instancia](#101-permisos--poda-de-claves-por-instancia)
102. [Cachés compartidas — frescura entre procesos](#102-cachés-compartidas--frescura-entre-procesos)
103. [Escrituras diferenciales — dos escritores sobre una BD](#103-escrituras-diferenciales--dos-escritores-sobre-una-bd)
104. [Stores — la base compartida y el formato de fecha único](#104-stores--la-base-compartida-y-el-formato-de-fecha-único)
105. [Config — un mapeo Grupo→Rol nuevo tiene que sobrevivir al Guardar](#105-config--un-mapeo-gruporol-nuevo-tiene-que-sobrevivir-al-guardar)
106. [Entra ID — comprobar permisos de las secciones SSO](#106-entra-id--comprobar-permisos-de-las-secciones-sso)
107. [Entra ID — rotar el secreto de la app de una credencial](#107-entra-id--rotar-el-secreto-de-la-app-de-una-credencial)
108. [Entra ID — la conversación device-code, escrita una vez](#108-entra-id--la-conversación-device-code-escrita-una-vez)
109. [Config — la cabecera tiene que quedarse arriba toda la sección](#109-config--la-cabecera-tiene-que-quedarse-arriba-toda-la-sección)
110. [Un ajuste no puede dejarte fuera del panel](#110-un-ajuste-no-puede-dejarte-fuera-del-panel)
111. [El icono del sitio existe y pedirlo no da 404](#111-el-icono-del-sitio-existe-y-pedirlo-no-da-404)
112. [El breadcrumb nombra el camino completo hasta la sección](#112-el-breadcrumb-nombra-el-camino-completo-hasta-la-sección)
113. [«Conexión perdida» tiene que significar que se perdió la conexión](#113-conexión-perdida-tiene-que-significar-que-se-perdió-la-conexión)
114. [El menú de órdenes por servicio](#114-el-menú-de-órdenes-por-servicio-qué-ofrece-qué-destruye-y-que-se-parezca-al-resto)
115. [Modules — cuatro layouts, no cuatro renderizadores](#115-modules--cuatro-layouts-no-cuatro-renderizadores)
116. [Status — cuatro layouts que tienen que coincidir](#116-status--cuatro-layouts-que-tienen-que-coincidir-en-qué-está-fallando)
117. [Marcado que no hace lo que sugiere el nombre de la clase](#117-marcado-que-no-hace-lo-que-sugiere-el-nombre-de-la-clase)
118. [Páginas de módulo — cuatro layouts que son del núcleo](#118-páginas-de-módulo--cuatro-layouts-que-son-del-núcleo-no-de-un-módulo)
119. [Ejecutar un check una vez — la proyección es el contrato](#119-ejecutar-un-check-una-vez--la-proyección-es-el-contrato)
120. [Credentials es una sección, no una sub-pestaña](#120-credentials-es-una-sección-no-una-sub-pestaña-de-infrastructure)
121. [Un widget de módulo, añadido varias veces](#121-un-widget-de-módulo-añadido-varias-veces-y-configurado-por-instancia)
122. [Services — cuatro vistas, y la que pivota sobre la instancia](#122-services--cuatro-vistas-y-la-que-pivota-sobre-la-instancia)

---

## 1. Core — Configuración

**Archivo:** `tests/test_config_file.py`

### `TestConfigStore` — Almacenamiento de archivos JSON

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_is_exist_file_none` | `is_exist_file` con path `None` | Devuelve `False` | Si devuelve `True` |
| `test_is_exist_file_nonexistent` | `is_exist_file` con path inexistente | Devuelve `False` | Si devuelve `True` |
| `test_read_and_save` | Guardar y leer datos en disco | Datos leídos coinciden con los guardados | Si difieren |
| `test_save_creates_file` | `save()` crea el archivo si no existe | Archivo creado en disco | Si no existe |
| `test_read_nonexistent_returns_default` | `read()` sobre archivo inexistente con default dado | Devuelve el default | Si lanza excepción o devuelve otro valor |
| `test_read_nonexistent_returns_none` | `read()` sin default | Devuelve `None` | Si lanza excepción |
| `test_is_writable_file_none` | `is_writable` con path `None` | Devuelve `False` | Si devuelve `True` |
| `test_is_writable_file_empty` | `is_writable` con path vacío | Devuelve `False` | Si devuelve `True` |
| `test_is_writable_file_existing` | `is_writable` con archivo existente y con permisos | Devuelve `True` | Si devuelve `False` |
| `test_is_writable_file_nonexistent_writable_dir` | `is_writable` con archivo nuevo en directorio escribible | Devuelve `True` | Si devuelve `False` |
| `test_is_writable_file_nonexistent_dir` | `is_writable` con directorio que no existe | Devuelve `False` | Si devuelve `True` |
| `test_save_empty_file_path` | `save()` sin path configurado | No lanza excepción | Si lanza |
| `test_save_non_serializable_data` | `save()` con datos no serializables a JSON | No lanza excepción (falla silenciosa) | Si lanza |
| `test_read_invalid_json` | `read()` con archivo JSON malformado | No lanza excepción, devuelve default | Si lanza |
| `test_save_formatted_json` | JSON guardado está indentado (legible) | Archivo contiene saltos de línea | Si es JSON en una sola línea |
| `test_file_property_getter_setter` | Getter/setter de la propiedad `file` | El valor asignado se recupera correctamente | Si difiere |

### `TestConfigControl` — Lectura y escritura de claves anidadas

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_get_conf_simple_key` | `get_conf` con clave simple | Devuelve el valor | Si no lo encuentra |
| `test_get_conf_nested_list` | `get_conf` con ruta anidada como lista | Devuelve el valor correcto | Si falla la navegación |
| `test_get_conf_nested_tuple` | `get_conf` con ruta anidada como tupla | Devuelve el valor correcto | Si falla la navegación |
| `test_get_conf_not_found_returns_default` | Clave inexistente devuelve default | Devuelve el default | Si lanza o devuelve otro valor |
| `test_get_conf_deep_not_found` | Ruta profunda inexistente | Devuelve default | Si lanza |
| `test_get_conf_r_type_list` | `r_type=list` convierte el resultado a lista | Devuelve lista | Si devuelve otro tipo |
| `test_get_conf_r_type_dict` | `r_type=dict` | Devuelve dict | Si devuelve otro tipo |
| `test_get_conf_r_type_int` | `r_type=int` | Devuelve int | Si devuelve otro tipo |
| `test_get_conf_r_type_bool` | `r_type=bool` | Devuelve bool | Si devuelve otro tipo |
| `test_get_conf_r_type_str` | `r_type=str` | Devuelve str | Si devuelve otro tipo |
| `test_get_conf_returns_dict_for_intermediate` | Obtener nodo intermedio devuelve el subdiccionario | Devuelve dict con hijos | Si devuelve None o default |
| `test_is_exist_conf_true` | `is_exist_conf` con clave existente | `True` | Si devuelve `False` |
| `test_is_exist_conf_true_tuple` | `is_exist_conf` con tupla | `True` | Si devuelve `False` |
| `test_is_exist_conf_false` | `is_exist_conf` con clave inexistente | `False` | Si devuelve `True` |
| `test_is_exist_conf_string` | `is_exist_conf` con string como clave | Funciona correctamente | Si falla |
| `test_is_exist_conf_with_split` | `is_exist_conf` con separador personalizado | Funciona correctamente | Si no separa bien |
| `test_set_conf_simple` | `set_conf` clave simple | Valor almacenado correctamente | Si no se guarda |
| `test_set_conf_nested` | `set_conf` ruta anidada crea niveles intermedios | Estructura anidada creada | Si falla |
| `test_set_conf_with_split` | `set_conf` con separador en string | Clave procesada correctamente | Si no separa |
| `test_set_conf_overwrite` | `set_conf` sobre clave existente | Valor actualizado | Si conserva el antiguo |
| `test_set_conf_empty_key_returns_false` | `set_conf` con clave vacía | Devuelve `False` | Si modifica datos |
| `test_set_conf_data_dict` | `set_conf` recibe dict como valor | Dict almacenado íntegramente | Si se trunca |

### `TestConfigControlConvertFindKey` — Normalización de claves

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_string_to_list` | String simple → lista de un elemento | `['key']` | Si devuelve otra estructura |
| `test_string_with_split` | String con separador → lista | `['a', 'b']` | Si no separa |
| `test_list_input` | Lista ya creada se devuelve copia | Lista equivalente | Si devuelve la misma referencia |
| `test_tuple_input` | Tupla convertida a lista | Lista equivalente | Si devuelve tupla |
| `test_invalid_type_raises` | Tipo inválido (int) lanza excepción | `TypeError` | Si no lanza |
| `test_list_is_copy` | Modificar el resultado no afecta al original | Original sin cambios | Si el original se modifica |

### `TestConfigControlIsChanged`, `TestConfigControlIsLoad`, `TestConfigControlSaveAndRead`, `TestConfigControlIsData`, `TestConfigControlReadOptions`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_changed_initially_with_none` | `is_changed` tras inicializar sin datos | `True` (sin estado previo) | Si es `False` |
| `test_changed_after_data_set` | `is_changed` tras modificar datos | `True` | Si es `False` |
| `test_not_changed_after_read` | `is_changed` tras leer de disco | `False` | Si es `True` |
| `test_changed_after_read_then_modify` | Modificar después de leer vuelve a marcar como cambiado | `True` | Si es `False` |
| `test_not_changed_after_save` | `is_changed` después de guardar | `False` | Si es `True` |
| `test_not_loaded_initially` | `is_loaded` antes de leer | `False` | Si es `True` |
| `test_loaded_after_read` | `is_loaded` tras leer archivo existente | `True` | Si es `False` |
| `test_not_loaded_after_read_nonexistent` | `is_loaded` si el archivo no existe | `False` | Si es `True` |
| `test_loaded_after_save` | `is_loaded` después de guardar | `True` | Si es `False` |
| `test_save_and_read_cycle` | Guardar y releer produce los mismos datos | Datos idénticos | Si difieren |
| `test_save_failed_does_not_update_timestamps` | Si `save()` falla, los timestamps no cambian | Timestamps sin cambio | Si se actualizan |
| `test_is_data_false_initially` | `is_data` sin datos asignados | `False` | Si es `True` |
| `test_is_data_true_after_set` | `is_data` tras asignar dict | `True` | Si es `False` |
| `test_is_data_true_with_empty_dict` | `is_data` con dict vacío `{}` | `True` | Si es `False` |
| `test_is_data_false_after_set_none` | `is_data` tras asignar `None` | `False` | Si es `True` |
| `test_is_data_with_init_data` | `is_data` con datos pasados en constructor | `True` | Si es `False` |
| `test_data_returns_empty_dict_when_none` | La propiedad `data` devuelve `{}` si internamente es `None` | `{}` | Si devuelve `None` |
| `test_read_return_data_true` | `read(return_data=True)` devuelve los datos directamente | Dict con los datos | Si devuelve `None` |
| `test_read_return_data_false` | `read(return_data=False)` devuelve `None` | `None` | Si devuelve datos |
| `test_read_nonexistent_sets_none` | Leer archivo inexistente → `data` queda en `None` | `data` es `None` | Si tiene datos |
| `test_read_with_def_return` | `read()` con `def_return` customizado | Default personalizado devuelto | Si devuelve otro |

---

## 2. Core — Debug

**Archivo:** `tests/test_debug.py`

### `TestDebug` — Sistema de depuración

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_default_enabled` | Debug desactivado por defecto | `enabled = False` | Si está activo |
| `test_default_level` | Nivel por defecto es `error` | `level = DebugLevel.error` | Si es diferente |
| `test_set_enabled` | Activar/desactivar el debug | El flag cambia correctamente | Si no cambia |
| `test_set_level` | Cambiar el nivel de debug | El nivel se actualiza | Si no cambia |
| `test_print_shows_message_when_enabled` | `print()` con debug activo imprime el mensaje | Mensaje en stdout | Si no aparece |
| `test_print_hides_message_when_disabled` | `print()` con debug inactivo | Sin salida | Si imprime algo |
| `test_print_hides_message_below_level` | Mensaje con nivel inferior al configurado | Sin salida | Si imprime |
| `test_print_shows_message_at_level` | Mensaje con exactamente el nivel configurado | Mensaje impreso | Si no aparece |
| `test_print_shows_message_above_level` | Mensaje con nivel superior | Mensaje impreso | Si no aparece |
| `test_print_force_bypasses_disabled` | `force=True` imprime aunque debug esté desactivado | Mensaje impreso | Si no imprime |
| `test_print_force_bypasses_level` | `force=True` ignora el filtro de nivel | Mensaje impreso | Si no imprime |
| `test_print_non_string` | `print()` con objeto no-string | No lanza excepción | Si lanza |
| `test_exception_prints_traceback` | `exception()` con excepción activa muestra traza | Traza en stdout | Si no aparece |
| `test_exception_without_arg` | `exception()` sin argumento | No lanza excepción | Si lanza |
| `test_debug_obj` | `debug_obj()` serializa y muestra un objeto | No lanza excepción, salida visible | Si lanza |

---

## 3. Core — Utilidades de datos

**Archivo:** `tests/test_dict_files_path.py` y `tests/test_dict_return_check.py`

### `TestDictFilesPath` — Registro de rutas de archivos

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_initial_empty` | Instancia nueva está vacía | `count == 0` | Si tiene elementos |
| `test_set_file` | Registrar un archivo | El archivo aparece en el registro | Si no aparece |
| `test_set_overwrite` | Sobrescribir un registro existente | Valor actualizado | Si conserva el antiguo |
| `test_set_empty_name_returns_false` | `set()` con nombre vacío | Devuelve `False` | Si lo registra |
| `test_set_multiple_files` | Registrar varios archivos | Todos aparecen | Si falta alguno |
| `test_is_exist_true` | `is_exist()` con nombre registrado | `True` | Si es `False` |
| `test_is_exist_false` | `is_exist()` con nombre no registrado | `False` | Si es `True` |
| `test_is_exist_none` / `test_is_exist_empty` | `is_exist()` con `None` o `""` | `False` | Si es `True` |
| `test_find_existing` | `find()` con nombre registrado | Devuelve la ruta | Si devuelve otra |
| `test_find_nonexistent_returns_default` | `find()` con nombre inexistente | Devuelve el default | Si lanza |
| `test_find_nonexistent_returns_empty_string` | `find()` sin default | Devuelve `""` | Si lanza |
| `test_remove_existing` | `remove()` elimina el registro | Ya no aparece en `is_exist` | Si persiste |
| `test_remove_nonexistent` | `remove()` sobre nombre inexistente | No lanza excepción | Si lanza |
| `test_clear` | `clear()` vacía el registro | `count == 0` | Si quedan elementos |

### `TestReturnModuleCheck` — Resultado de un módulo watchful

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_initial_empty` | Instancia nueva vacía | `count == 0` | Si tiene entradas |
| `test_set_basic` | `set(key, status, message)` crea entrada | Entrada accesible | Si no se crea |
| `test_set_and_get` | Valores recuperados tras `set()` | Status y message correctos | Si difieren |
| `test_set_with_send_false` | `send_msg=False` se almacena | `get_send(key) == False` | Si es `True` |
| `test_set_with_other_data` | `other_data` se almacena | Recuperable con `get_other_data` | Si se pierde |
| `test_set_empty_key_returns_false` | `set("")` | Devuelve `False` | Si devuelve `True` |
| `test_set_overwrites` | `set()` sobre clave existente | Valor actualizado | Si conserva el antiguo |
| `test_is_exist` | `is_exist(key)` tras `set()` | `True` | Si es `False` |
| `test_get_status` | `get_status(key)` | Status correcto | Si difiere |
| `test_get_message` | `get_message(key)` | Mensaje correcto | Si difiere |
| `test_get_nonexistent` | `get_status/message` de clave inexistente | Devuelve `None` o default | Si lanza |
| `test_update_status` | `update(key, 'status', valor)` | Nuevo status guardado | Si no actualiza |
| `test_update_message` | `update(key, 'message', valor)` | Nuevo mensaje guardado | Si no actualiza |
| `test_update_invalid_option` | `update` con opción no válida | Devuelve `False` | Si modifica datos |
| `test_update_nonexistent_key` | `update` sobre clave inexistente | Devuelve `False` | Si lanza |
| `test_update_empty_key` | `update` con clave vacía | Devuelve `False` | Si lanza |
| `test_remove` | `remove(key)` elimina la entrada | `is_exist == False` | Si persiste |
| `test_remove_nonexistent` | `remove` sobre clave inexistente | No lanza | Si lanza |
| `test_items` | `items()` devuelve pares clave-valor | Iterable con todas las entradas | Si está vacío o falta alguna |
| `test_keys` | `keys()` devuelve las claves | Todas las claves presentes | Si falta alguna |
| `test_multiple_entries` | Múltiples entradas independientes | Cada una con sus propios valores | Si se mezclan |
| `test_other_data_default_empty` | `other_data` sin especificar | `{}` | Si es `None` |

---

## 4. Core — Ejecución de comandos (Exec)

**Archivo:** `tests/test_exe.py`

### Clases: `TestExecResult`, `TestExecConfig`, `TestEnumLocationExec`, `TestExecInit`, `TestExecProperties`, `TestExecSetRemote`, `TestExecEmptyResult`, `TestExecLocal`, `TestExecStaticMethod`, `TestExecStart`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_default_values` (ExecResult) | Valores por defecto de `ExecResult` | `stdout=""`, `stderr=""`, `returncode=0` | Si difieren |
| `test_with_values` | ExecResult con datos | Valores asignados recuperables | Si difieren |
| `test_with_exception` | ExecResult con excepción | Almacenada en `.exception` | Si no se guarda |
| `test_default_values` (ExecConfig) | Config por defecto | Host, port, user vacíos | Si tienen valores |
| `test_custom_values` | ExecConfig con valores | Valores recuperables | Si difieren |
| `test_local_value` / `test_remote_value` | Enum `LocationExec` | Valores correctos | Si difieren |
| `test_default_location_local` | Exec creado sin args usa local | `location == LOCAL` | Si es remote |
| `test_init_with_command` | Exec inicializado con comando | Comando almacenado | Si está vacío |
| `test_default_command_empty` | Exec sin comando | `command == ""` | Si tiene valor |
| `test_default_timeout` | Timeout por defecto | Valor correcto | Si difiere |
| `test_config_is_exec_config` | Propiedad `config` es `ExecConfig` | Instancia correcta | Si es otro tipo |
| `test_set_location` | Cambiar ubicación de ejecución | `location` actualizada | Si no cambia |
| `test_set_command` | Cambiar comando | `command` actualizado | Si no cambia |
| `test_set_remote_defaults` | `set_remote()` sin args | Valores por defecto en config | Si difieren |
| `test_set_remote_custom` | `set_remote(host, port, user)` | Valores almacenados | Si difieren |
| `test_set_remote_with_key_file` | `set_remote` con `key_file` | Key file almacenado | Si se pierde |
| `test_execute_local_with_python` | Ejecutar `python --version` local | `returncode == 0`, stdout con versión | Si falla |
| `test_execute_local_stderr` | Comando que escribe a stderr | Stderr capturado | Si está vacío |
| `test_execute_local_exit_code` | Comando con exit code != 0 | `returncode != 0` | Si es 0 |
| `test_execute_empty_command` | Comando vacío | No lanza excepción | Si lanza |
| `test_execute_invalid_command` | Comando inexistente | `returncode != 0` o excepción controlada | Si devuelve 0 |
| `test_start_no_command` | `start()` sin comando | No lanza excepción | Si lanza |
| `test_start_local` | `start()` con comando local válido | `returncode == 0` | Si falla |
| `test_start_remote_without_setup` | `start()` en modo remote sin configurar | Falla controlada | Si ejecuta algo |

---

## 5. Core — Memoria del sistema

**Archivo:** `tests/test_mem.py`

### `TestMemInfo`, `TestMemRam`, `TestMemSwap`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_defaults` | Valores por defecto de `MemInfo` | `total=0`, `free=0`, `used_percent=0.0` | Si difieren |
| `test_custom_values` | `MemInfo` con total y free dados | Valores correctos | Si difieren |
| `test_used` | `MemInfo.used` = total - free | Cálculo correcto | Si es negativo o incorrecto |
| `test_used_when_free_equals_total` | `used` cuando free == total | `0` | Si es != 0 |
| `test_used_percent` | Porcentaje de uso = used/total*100 | Valor correcto con precisión | Si difiere |
| `test_used_percent_zero_total` | División entre 0 | Devuelve `0.0` (sin excepción) | Si lanza `ZeroDivisionError` |
| `test_used_percent_negative_total` | Total negativo | Devuelve `0.0` | Si lanza |
| `test_ram_values` | RAM total y libre leídos | Valores positivos | Si son 0 o negativos |
| `test_ram_used` / `test_ram_used_percent` | Uso de RAM calculado | Valores coherentes | Si son incorrectos |
| `test_swap_values` | Swap total y libre leídos | Valores no negativos | Si son negativos |
| `test_swap_zero` | Sistema sin swap | `total=0`, `used_percent=0.0` | Si lanza |
| `test_swap_fully_used` | Swap al 100% | `used_percent == 100.0` | Si difiere |

---

## 6. Core — Sensores térmicos

**Archivo:** `tests/test_thermal.py`

### `TestThermalNodeInit`, `TestThermalNodePaths`, `TestThermalNodeType`, `TestThermalNodeTemp`, etc.

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init_valid_dev` | `ThermalNode` con path válido | Objeto creado | Si lanza |
| `test_init_strips_whitespace` | Espacios en el path se eliminan | Path limpio almacenado | Si conserva espacios |
| `test_init_empty_raises` / `test_init_none_raises` | Path vacío o `None` | Lanza `ValueError` | Si no lanza |
| `test_path_dev` / `test_path_temp` / `test_path_type` | Rutas construidas correctamente | Paths con sufijos `/temp_input`, `/type` | Si son incorrectos |
| `test_type_reads_file` | `type` lee el archivo `/type` del sensor | Nombre del tipo de sensor | Si devuelve vacío |
| `test_type_unknown_when_file_missing` | `/type` no existe | Devuelve `"unknown"` | Si lanza |
| `test_temp_normal_value` | `temp` lee y divide entre 1000 | Valor en °C correcto | Si es en mili-grados |
| `test_temp_zero` | Archivo de temp contiene `0` | `0.0` | Si lanza |
| `test_temp_file_missing` | Archivo de temperatura no existe | `0.0` | Si lanza |
| `test_temp_invalid_content` | Archivo con contenido no numérico | `0.0` | Si lanza |
| `test_init_no_autodetect` | `ThermalInfoCollection(autodetect=False)` | Colección vacía | Si detecta sensores |
| `test_init_autodetect_no_sensors` | Sistema sin `/sys/class/thermal` | Colección vacía sin excepción | Si lanza |
| `test_add_valid_sensor` | `add_sensor()` con path válido | Sensor en la colección | Si no se añade |
| `test_add_empty_returns_false` | `add_sensor("")` | Devuelve `False` | Si devuelve `True` |
| `test_count_with_nodes` | `count` tras añadir sensores | Número correcto | Si difiere |

---

## 7. Core — Helpers de parseo

**Archivo:** `tests/test_parse_helpers.py`

### `TestParseConfInt`, `TestParseConfFloat`, `TestParseConfStr`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_valid_integer_string` | `parse_conf_int("5")` | `5` | Si devuelve otro |
| `test_zero_returns_default` | `parse_conf_int("0")` | Default (0 no es válido) | Si devuelve 0 |
| `test_negative_returns_default` | Valor negativo | Default | Si devuelve negativo |
| `test_empty_string_returns_default` | String vacío | Default | Si lanza |
| `test_float_string_returns_default` | `"3.14"` | Default (no es entero) | Si convierte |
| `test_none_returns_default` | `None` como valor | Default | Si lanza |
| `test_custom_min_val_above` | `min_val=5`, valor `10` | `10` | Si devuelve default |
| `test_custom_min_val_below` | `min_val=5`, valor `3` | Default | Si devuelve `3` |
| `test_min_val_zero_allows_zero` | `min_val=0`, valor `0` | `0` | Si devuelve default |
| `test_valid_float_string` | `parse_conf_float("3.14")` | `3.14` | Si devuelve default |
| `test_small_positive` | `"0.001"` | `0.001` | Si es default |
| `test_valid_string` (ParseConfStr) | String con contenido | String limpio | Si devuelve default |
| `test_empty_string_returns_default` | String vacío | Default | Si devuelve `""` |
| `test_whitespace_returns_default` | Solo espacios | Default | Si devuelve espacios |
| `test_strips_whitespace` | `"  hola  "` | `"hola"` | Si conserva espacios |
| `test_none_converted_to_string` | `None` → `"None"` (str) | `"None"` | Si devuelve default |

---

## 8. Core — Herramientas generales

**Archivo:** `tests/test_tools.py`

### `TestBytes2Human`

Variante **compacta** (una letra, sin espacio). No la llama nadie en el proyecto; se mantiene
porque es API pública exportada en `lib.util.__all__`.

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| Conversión de bytes a unidades legibles (11 tests) | `bytes2human(1024)` → `"1.0K"`, `(0)` → `"0B"`, `(1023)` → `"1023B"`, hasta `T` | String con unidad correcta | Si la unidad o valor es incorrecto |

### `TestFmtBytes`

Variante **legible** (espacio + dos letras): la que de verdad se usa en mensajes de alerta y en
la barra de Status, así que su formato es conducta, no cosmética.

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| Formato base | `fmt_bytes(0)` → `"0 B"`, `(512)` → `"512 B"` (los bytes no llevan decimales), `(1024³)` → `"1.0 GB"`, `(1.5 GB)` → `"1.5 GB"` | Unidad y decimales correctos | Si aparecen decimales en bytes o cambia el espaciado |
| Escala la escalera completa | `PB`, `EB`, `ZB`, `YB` — no se detiene en PB | `2.0 EB` | Si degenera en `2048.0 PB`: un formateador que topa no dice "es enorme", imprime un número ilegible |
| Más allá de YB | Renderiza en la última unidad en vez de colgarse | Termina en `" YB"` | Si lanza o entra en bucle |
| Alcanza tan lejos como `bytes2human` | Compara ambas letra a letra de KB a YB | Misma unidad en las dos | **Impide que una consolidación futura pierda alcance** frente a la función que sustituye |
| Un valor no numérico | `None` / `"abc"` → `"0 B"` | No lanza | Un mensaje de monitorización debe renderizar aunque la API respondiera algo raro |

### `TestToBytes`

Inversa de `fmt_bytes` para umbrales configurados (el admin escribe un número y elige unidad).

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| Cada unidad | `to_bytes(2, "GB")`, `(1, "TB")`, `(4, "MB")` | Bytes exactos | Si una unidad se escala mal |
| Unidad insensible a mayúsculas | `to_bytes(1, "gb")` == `1024³` | Igual que `"GB"` | Si el desplegable y el código discrepan en el caso |
| Valor en blanco | `""` / `None` → 0 | 0 | Si lanza |
| Unidad desconocida se lee como GB | `to_bytes(1, "parsecs")` == `1024³` | Cae a GB | Rechazarla dejaría el umbral en 0, **desactivando en silencio la alerta que debía disparar** |

---

## 8b. Core — Reconciliación de esquema de BD

**Archivo:** `tests/test_db_schema.py`

Tests del motor de reconciliación declarativa de esquema (`lib/db/schema.py` +
`BaseConnector.reconcile_table`). Se ejecutan sobre SQLite (motor por defecto);
MySQL/PostgreSQL reutilizan el mismo `diff_table` y el rebuild genérico.

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_creates_table_from_spec` | Crea la tabla desde el `TableSpec` si no existe | Columnas y orden e índices correctos | Si difiere |
| `test_idempotent_no_changes` | Segunda reconciliación no detecta cambios | `is_empty`, sin rebuild | Si hay falsos positivos |
| `test_add_trailing_column_keeps_data` | Añadir columna al final | `ADD COLUMN` sin rebuild, datos intactos | Si reconstruye o pierde datos |
| `test_add_middle_column_triggers_rebuild_and_keeps_data` | Columna nueva en medio del orden | Rebuild, orden correcto, datos intactos | Si el orden o los datos fallan |
| `test_reorder_columns_keeps_data` | Reordenar (`col2,col1`→`col1,col2`) | Rebuild, orden correcto, datos intactos | Si no reordena o pierde datos |
| `test_type_change_rebuilds` | Cambio de tipo de columna | Rebuild, valores convertidos | Si no aplica el tipo |
| `test_nullable_and_default_change` | Pasar a NOT NULL + default (con `COALESCE` de NULLs) | Rebuild sin violar la restricción | Si falla la copia |
| `test_create_missing_index_without_rebuild` | Crear índice que falta | `CREATE INDEX` sin rebuild | Si reconstruye |
| `test_changed_index_recreated` | Índice con columnas distintas | Drop + recreate | Si conserva el antiguo |
| `test_extra_column_kept_and_reported` | Columna extra en BD (no en spec) | Se conserva y se reporta, nunca se borra | Si la elimina |
| `test_rename_column_preserves_data` | Rename vía `renames` (`sid`→`uid`) | Datos preservados | Si pierde datos |
| `test_canonical_type` (param.) | Normalización de tipos cross-engine | INTEGER/TEXT/REAL canónicos | Si difiere |
| `test_canonical_default` (param.) | Normalización de defaults (comillas, `NULL`, cast PG) | Valor canónico correcto | Si difiere |
| `test_diff_table_pure_function` | `diff_table()` sobre tabla recién creada | `is_empty` | Si reporta diferencias |

---

## 9. Monitor — Descubrimiento y ejecución de módulos

**Archivo:** `tests/test_monitor.py`

### `TestGetEnabledModules` — Descubrimiento de módulos

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_empty_dir_returns_empty` | Directorio de módulos vacío | Lista vacía `[]` | Si devuelve algún módulo |
| `test_none_modules_dir_returns_empty` | `dir_modules = None` | Lista vacía `[]` | Si lanza excepción |
| `test_discovers_package_module` | Carpeta con `__init__.py` | Módulo en la lista | Si no aparece |
| `test_discovers_multiple_package_modules` | Varias carpetas con `__init__.py` | Todos en la lista | Si falta alguno |
| `test_ignores_dir_without_init` | Carpeta sin `__init__.py` | No aparece en la lista | Si aparece |
| `test_ignores_dunder_dirs` | Directorio `__pycache__` con `__init__.py` | No aparece en la lista | Si aparece |
| `test_respects_enabled_false_in_config` | La configuración de módulos marca módulo como `enabled: false` | Módulo excluido | Si se incluye |
| `test_respects_enabled_true_in_config` | La configuración de módulos marca módulo como `enabled: true` | Módulo incluido | Si se excluye |
| `test_flat_py_files_are_not_discovered` | Archivo `.py` suelto en el directorio | No aparece (formato legacy no soportado) | Si aparece |

### `TestCheckModule` — Ejecución de un módulo

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_check_module_returns_result` | `check_module("mod")` sobre módulo válido | `(True, "mod", ReturnModuleCheck)` | Si devuelve `False` o la instancia es otro tipo |
| `test_check_module_bad_name_returns_false` | `check_module("nonexistent")` | `(False, "nonexistent", None)` | Si lanza excepción |

### `TestNotifier` — Envío de alertas y buffer por ciclo

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_monitor_has_no_telegram_thread` | El monitor no arranca un hilo Telegram | Sin atributo `tg`, `_notifier` es `None` | Si existe el hilo |
| `test_close_is_a_safe_noop` | `close()` doble es seguro | Nunca lanza, `_notifier` sigue `None` | Si lanza |
| `test_alert_kind_mapping` | `_alert_kind` mapea el tipo de alerta | `True`→'recovery', `False`→'down', `(False,'warning')`→'warn' | Si difiere |
| `test_process_result_buffers_alert` | Un ítem cambiado y notificable se bufferea | `('down','ping','item1','boom')` en el buffer | Si no bufferea |
| `test_send_message_carries_module_and_item` | Envío ad-hoc conserva módulo e ítem | `('down','ntp','NS1','boom')` | Si difiere |
| `test_module_supplied_name_wins_over_uid_key` | El nombre amigable gana al UID | `('down','cpu','PVE02','CPU high')` | Si usa el UID |
| `test_item_label_resolves_host_uid` | `_item_label` resuelve `host_uid`→'NS1' | Clave desconocida devuelve la propia clave | Si no resuelve |

### `TestMonitorAudit` — Auditoría del monitor

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_audit_system_writes_to_db` | Evento de sistema escribe en la BD | Fila `('module_check_timeout','system','internal')`; sin `audit.json` | Si no persiste |
| `test_audit_system_falls_back_to_file` | Sin store, cae a fichero | Se crea `audit.json` | Si no lo crea |

### `TestCheckStatePersistence` — Persistencia de estado de checks

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_first_record_notifies_and_persists` | El primer cambio notifica y persiste | Estado guardado con `status = False` | Si no notifica/persiste |
| `test_unchanged_state_is_silent` | Estado sin cambios no vuelve a notificar | Solo el primero y la transición notifican | Si repite notificaciones |
| `test_state_survives_restart` | El baseline se recarga de la BD | Mismo resultado OK no re-anuncia | Si re-anuncia |
| `test_clear_status_also_clears_state` | `clear_status()` vacía el `check_state` store | Store vacío | Si persiste |
| `test_maintenance_purges_live_state` | Host en mantenimiento purga su estado vivo | El estado deja de ser bool | Si conserva estado |
| `test_derived_key_split_into_metric` | `U-1_ram/_swap` se guarda como clave + métrica | Reconstruye clave U-1 con métrica ram/swap | Si no separa |
| `test_item_key_with_underscore_is_not_split` | `item_1` no se separa | Clave íntegra, métrica `''` | Si la parte |
| `test_slash_composite_keys_are_distinct_metrics` | Dos claves compuestas con `/` | Dos filas con métricas distintas, reconstruye verbatim | Si colisionan |
| `test_stale_bare_key_does_not_abort_persist` | Clave obsoleta + `/site` conviven | Ambas persisten sin colisión | Si aborta |

### `TestFailStreak` — Racha de fallos

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_streak_persists_and_marks_dirty` | `fail_streak` incrementa 1→2 entre instancias | Marca dirty; recuperación lo resetea a 0 | Si no persiste o no resetea |

### `TestRefreshRuntimeConfig` — Recarga de config en caliente

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_refresh_is_safe_without_a_notifier` | `refresh_runtime_config()` sin notifier | No lanza; sin `tg`; `_notifier` `None` | Si lanza |

### `TestDaemonModuleConfigRefresh` — Recarga de checks del daemon

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_refresh_picks_up_web_added_check` | Recarga detecta un check añadido por web | Label vacío antes, 'Lab' después (re-lee BD) | Si no lo detecta |

### `TestDaemonCycleIntegration` — Ciclo completo del daemon

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_added_check_reaches_status_history_telegram` | Tras recarga, el check corre y llega a estado, historial y Telegram | Estado `True`, 1 punto de historial, envío Telegram con token 'TKN-9'/chat 'CHT-9' | Si no propaga |

### `TestGetItemUid` — Extracción de UID desde la clave

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_exact_key` | Clave exacta | `'u-123'` → `'u-123'` | Si difiere |
| `test_slash_composite_key` | Clave compuesta con `/` | `'u-123/vip'` y `'/node/pve04'` → `'u-123'` | Si difiere |
| `test_underscore_derived_key` | Clave derivada con `_` | `'u-9_ram'` → `'u-9'` | Si difiere |
| `test_unknown_key_returns_none` | Clave desconocida | `'nope/vip'` → `None` | Si devuelve algo |

---

## 10. Integridad de módulos Watchful

**Archivo:** `tests/test_watchfuls_integrity.py`  
> Estos tests se ejecutan (parametrizados) sobre **todos los módulos reales** descubiertos en `watchfuls/` — actualmente 19: `cpu`, `datastore`, `dns`, `filesystemusage`, `hddtemp`, `keepalived`, `m365`, `ntp`, `ping`, `process`, `proxmox`, `raid`, `ram_swap`, `service_status`, `snmp`, `ssl_cert`, `temperature`, `ups`, `web`. La lista (`_MODULE_NAMES`) se autodescubre, así que un módulo nuevo entra en la parametrización sin tocar los tests.

### `TestRealModuleDiscovery` — Descubrimiento en producción

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_discovers_all_expected_modules` | `_get_enabled_modules()` encuentra los 9 módulos reales | Los 9 módulos presentes | Si falta alguno |
| `test_no_extra_unexpected_entries` | No aparecen entradas `__pycache__` ni `.py` planos | Lista limpia | Si hay entradas no válidas |

### `TestRealModuleImport` — Importación (× módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_module_imports[<mod>]` | El módulo importa sin errores | Import exitoso | Si lanza cualquier excepción |
| `test_watchful_has_item_schema[<mod>]` | `Watchful.ITEM_SCHEMA` existe y es dict no vacío | Dict con entradas | Si es `None`, no es dict, o está vacío |
| `test_item_schema_collections_are_dicts[<mod>]` | Cada colección en el schema es dict y cada campo tiene clave `type` | Todo correcto | Si algún campo no tiene `type` o no es dict |

### `TestRealModuleInfoJson` — Validez de `info.json` (× módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_info_json_exists[<mod>]` | Existe `watchfuls/<mod>/info.json` | Archivo presente | Si no existe |
| `test_info_json_is_valid_json[<mod>]` | El archivo es JSON válido | Parseable sin errores | Si está malformado |
| `test_info_json_has_required_keys[<mod>]` | Tiene `name`, `version`, `description`, `icon`, `dependencies` | Todas las claves presentes | Si falta alguna |
| `test_info_json_name_is_nonempty_string[<mod>]` | `name` es string no vacío | String con contenido | Si es vacío o no es string |
| `test_info_json_icon_is_nonempty_string[<mod>]` | `icon` es string no vacío (emoji) | String con contenido | Si es vacío o no es string |

### `TestRealModuleLangFiles` — Validez de `lang/*.json` (× módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_lang_dir_exists[<mod>]` | Existe `watchfuls/<mod>/lang/` | Directorio presente | Si no existe |
| `test_expected_locales_present[<mod>]` | Existen `en_EN.json` y `es_ES.json` | Ambos archivos presentes | Si falta alguno |
| `test_lang_files_are_valid_json[<mod>]` | Todos los `.json` de `lang/` son válidos | Sin errores de parseo | Si alguno está malformado |
| `test_lang_files_have_required_keys[<mod>]` | Tienen `pretty_name` y `labels` | Ambas claves presentes | Si falta alguna |
| `test_lang_pretty_name_is_nonempty_string[<mod>]` | `pretty_name` es string no vacío | Nombre legible | Si es vacío |
| `test_lang_labels_is_dict[<mod>]` | `labels` es un dict | Dict con etiquetas | Si es otro tipo |

### `TestDiscoverSchemasRealModules` — Integración completa del sistema i18n y schemas (× módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_returns_non_empty` | `discover_schemas()` devuelve algo | Dict no vacío | Si está vacío |
| `test_module_has_at_least_one_schema_collection[<mod>]` | Módulo contribuye al menos una colección de schema | Al menos una clave `<mod>\|<col>` | Si no aparece ninguna |
| `test_module_has_i18n_entry[<mod>]` | Existe clave `<mod>\|__i18n__` | Presente | Si no existe |
| `test_i18n_entry_has_expected_locales[<mod>]` | `__i18n__` contiene `en_EN` y `es_ES` | Ambos locales presentes | Si falta alguno |
| `test_i18n_pretty_name_populated[<mod>]` | Cada locale tiene `pretty_name` no vacío | String con contenido | Si es vacío |
| `test_i18n_icon_populated[<mod>]` | Cada locale tiene `icon` no vacío | Emoji o string | Si es vacío |
| `test_schema_fields_have_label_i18n_when_lang_exists[<mod>]` | Todos los campos del schema tienen `label_i18n` mergeado de `lang/` | Clave `label_i18n` en cada campo | Si falta (indica que el merge de idiomas falló) |

### `TestModuleFileLayout` — El `__init__.py` no es un subsistema entero

Un módulo pequeño cabe entero en `__init__.py` y así debe quedarse; pasadas las **350 líneas**
deja de ser una cosa. El último en cruzarlo, `snmp`, tenía **1596**: seiscientas no comprobaban
nada —eran un gestor de ficheros MIB con su ejecutor de trabajos en segundo plano— y otras
ciento cincuenta eran la conversación SNMP. Tres subsistemas compartiendo un namespace.

El corte no es por tamaño sino **por pregunta respondida**, con los mismos nombres en todos los
módulos (`checks_<área>.py`, `client.py`, `actions.py`, `page.py`, `defaults.py`) — ver
[caso-guia-watchful.md §2b](caso-guia-watchful.md#2b-cuando-el-módulo-crece-nombres-estándar-por-contenido).

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init_is_not_a_whole_subsystem[<mod>]` | El `__init__.py` no pasa de 350 líneas | Dentro del límite, o en la lista de pendientes | Nombra el fichero y el tamaño, y remite a la guía |
| `test_the_pending_list_only_shrinks` | Cada módulo de `_INIT_SPLIT_PENDING` sigue por encima del límite | Sigue pendiente | Uno ya partido debe salir de la lista, o el guard deja de vigilarlo |

La lista arrancó con `{snmp 1596, proxmox 1087, datastore 1052, dns 719, service_status 389}`
y **está vacía**: los cinco salieron al partirse, que es la única dirección en la que se le
permite moverse. El mayor `__init__.py` del repo es hoy `ups`, con 298.
| `test_the_pending_list_has_no_ghosts` | La lista no nombra módulos inexistentes | Todos existen | Nombre podrido tras un renombrado |

### `TestWatchfulActions` — Integridad de `WATCHFUL_ACTIONS`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_watchful_actions_is_frozenset[<mod>]` | Si el módulo declara `WATCHFUL_ACTIONS`, es un `frozenset` (ausente en módulos base-only) | `frozenset` o ausente | Si es otro tipo |
| `test_expected_actions_declared[<mod>]` | Los módulos con acciones web declaran el set exacto esperado (`datastore`, `filesystemusage`, `service_status`, `temperature`) | Set exacto | Si difiere |
| `test_action_methods_exist[<mod>]` | Cada acción declarada existe como método invocable | `callable` presente | Si falta o no es invocable |

> Los dos últimos se parametrizan solo sobre los módulos con acciones web conocidas (`_EXPECTED_ACTIONS`), no sobre todos.

### `TestRealModuleRuntimeContract` — Contrato de ejecución y cableado con el sistema (× módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_instantiates_and_check_runs_on_empty_config[<mod>]` | El módulo instancia y `check()` devuelve un `ReturnModuleCheck` con config vacía (los hooks pesados, p.ej. compilar MIBs SNMP, se neutralizan) | Devuelve `ReturnModuleCheck` | Si lanza o devuelve otro tipo |
| `test_declared_credential_type_is_in_catalog[<mod>]` | Si el módulo declara un tipo de credencial (`__credential__`), ese tipo está en el catálogo central | Tipo presente en el catálogo | Si el tipo declarado no está expuesto |
| `test_host_capable_module_is_exposed_in_catalogs[<mod>]` | Si el módulo es host-capable (`__host_profile__`), aparece en el flag multi-bind y en al menos una colección bindable a host | Presente en ambos catálogos | Si es host-capable pero falta en alguno |

> **Skips intencionados** (no son fallos): estos dos últimos tests solo aplican a un subconjunto de módulos, así que se **saltan** para el resto — `skip("module declares no credential type")` en los módulos sin credencial y `skip("module is not host-capable")` en los que no declaran `__host_profile__`. Es el patrón "parametrizar sobre todos los módulos y saltar los que no tienen la característica"; la invariante sí se comprueba en los módulos a los que aplica.

---

## 11. Panel Web — Inicialización y autenticación

**Archivos:** `tests/test_wa_init.py` — `TestWebAdminInit` · `tests/test_wa_auth.py` — `TestAuthentication`, `TestRememberMe`, `TestAccountLockout`

### `TestWebAdminInit`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_instance_creation` | `WebAdmin(config_dir, user, pass)` crea la instancia | `wa.app` no es `None` | Si lanza |
| `test_default_port` | Puerto por defecto | `8080` | Si es diferente |

### `TestAuthentication`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_login_get` | `GET /login` devuelve el formulario | `200` con HTML | Si es otro código |
| `test_login_ok` | Login con credenciales correctas | Redirección al dashboard | Si devuelve `401` |
| `test_login_wrong_password` | Login con contraseña incorrecta | `302` a `/login` + mensaje flash | Si entra al dashboard |
| `test_login_wrong_user` | Login con usuario inexistente | `302` a `/login` + mensaje flash | Si entra |
| `test_login_account_disabled` | Cuenta desactivada | Mensaje "account disabled", no "invalid credentials" | Si muestra mensaje genérico |
| `test_login_uses_post_redirect_get` | Login fallido usa PRG | `302` sin `follow_redirects` | Si devuelve `200` directo |
| `test_logout` | `GET /logout` cierra la sesión | Redirección a `/login` | Si sigue logueado |
| `test_protected_redirect` | Acceder a `/` sin login | Redirección a `/login` | Si devuelve `200` |

### `TestAccountLockout`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_lockout_triggers_after_n_attempts` | Tras N intentos fallidos, mensaje menciona "locked" | `200` con "locked"/"bloqueada" | Si sigue sin bloquear |
| `test_locked_account_rejects_correct_password` | Cuenta bloqueada rechaza contraseña correcta | Mensaje de bloqueo | Si permite el login |
| `test_lockout_returns_minutes_remaining` | Mensaje incluye los minutos restantes | "10" en el cuerpo (600 s) | Si no aparece el tiempo |
| `test_successful_login_resets_failed_attempts` | Login correcto limpia `_failed_attempts` y `_locked_until` | Ambos campos `None` | Si persisten |
| `test_lockout_disabled_when_max_attempts_zero` | `max_attempts=0` no bloquea nunca | Login correcto tras 20 fallos | Si bloquea |
| `test_account_unlocks_after_duration` | Tras expirar el bloqueo, login correcto funciona | `200` con dashboard | Si sigue bloqueado |
| `test_authenticate_returns_tuple` | `_authenticate()` devuelve siempre 2-tupla | `(user, None)` con credenciales correctas | Si devuelve tipo incorrecto |
| `test_authenticate_wrong_password_reason` | Contraseña incorrecta → `reason='invalid_credentials'` | Tupla correcta | Si `reason` es otro valor |
| `test_authenticate_unknown_user_reason` | Usuario inexistente → `reason='user_not_found'` | Tupla correcta | Si `reason` es otro valor |

---

## 12. Panel Web — API módulos y configuración

**Archivos:** `tests/test_wa_modules.py` — `TestApiModules`, `TestApiStatus`, `TestApiOverview`, `TestModuleItemSchemas`, `TestConfigEdgeCases` · `tests/test_wa_config.py` — `TestApiConfigAuth`, `TestApiConfigGet`, `TestApiConfigPutBasic`, `TestApiConfigPutSecureCookies`, `TestApiConfigPutRememberMeDays`, `TestApiConfigPutAuditMaxEntries`, `TestApiConfigPutLang`, `TestApiConfigPutDarkMode`, `TestApiConfigPutWebAdminKey`, `TestApiConfigPutInjection`, **`TestApiConfigSchema`**, **`TestApiConfigPutDefaultPageSize`**, **`TestApiConfigPutPageSizes`**, **`TestApiConfigPutProxyCount`**

### `TestApiModules`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_get_modules_requires_auth` | `GET /api/modules` sin login | `302` | Si devuelve `200` |
| `test_get_modules_returns_dict` | `GET /api/modules` con login | Dict JSON con los módulos | Si es otro tipo |
| `test_put_modules_saves` | `PUT /api/modules` con datos válidos | `200`, datos persistidos | Si devuelve error |
| `test_get_modules_empty_dir` | `GET /api/modules` con directorio vacío | `200`, dict vacío | Si lanza |

### `TestApiConfig`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_get_config_requires_auth` | Sin login | `302` | Si devuelve datos |
| `test_get_config_returns_dict` | `GET /api/config` con login | Dict JSON | Si es otro tipo |
| `test_put_config_saves` | `PUT /api/config` | `200` | Si devuelve error |

### `TestApiConfigSchema`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_schema_returns_200` | `GET /api/config/schema` con login | `200` | Si devuelve otro código |
| `test_schema_returns_dict` | Respuesta es un dict JSON | Dict no vacío | Si es otro tipo |
| `test_schema_requires_auth` | Sin login | `302` | Si devuelve datos |
| `test_schema_bool_fields_present` | `public_status`, `pw_require_*` tienen `type: bool` y `default` bool | Todos presentes con tipo correcto | Si falta alguno o el tipo es incorrecto |
| `test_schema_int_fields_present` | `remember_me_days`, `audit_max_entries`, `status_refresh_secs` tienen `min`/`max` | Todas las claves presentes | Si falta alguna |
| `test_schema_status_lang_options` | `status_lang` incluye `""` y todos los `SUPPORTED_LANGS` | Lista correcta | Si falta algún idioma |
| `test_schema_no_crash_on_instance_attrs` | Regresión: `getattr(type(wa), attr)` fallaba para atributos de instancia | `200` sin traza | Si devuelve 500 |
| `test_schema_default_page_size_has_options_int` | `default_page_size` tiene `options_int` con `0` y al menos un tamaño estándar | Lista presente | Si falta o no incluye `0` |
| `test_schema_default_page_size_default_in_options` | El `default` de `default_page_size` está en `options_int` | Coincide con instancia | Si difiere |
| `test_schema_audit_sort_options` | `audit_sort` expone las 4 opciones de ordenación | `time`, `event`, `user`, `ip` presentes | Si falta alguna |
| `test_schema_pw_min_len_bounds` | `pw_min_len` tiene `min: 1`, `max: 128` | Rangos correctos | Si difieren |
| `test_schema_pw_max_len_bounds` | `pw_max_len` tiene `min: 8`, `max: 256` | Rangos correctos | Si difieren |
| `test_schema_proxy_count_bounds` | `proxy_count` tiene `min: 0`, `max: 10` | Rangos correctos | Si difieren |

### `TestApiConfigPutDefaultPageSize`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_default_page_size_zero_means_all` | `default_page_size: 0` (Todos) se guarda y relée | `200`, valor `0` en disco | Si falla |
| `test_default_page_size_standard_values` | Valores 25, 50, 100, 200 | `200`, persistido | Si rechaza |
| `test_default_page_size_max_boundary` | Valor `200` (límite superior) | `200` | Si rechaza |
| `test_default_page_size_above_max_clamped` | Valor `201` supera el máximo | Rechazado o ajustado a 200 | Si acepta `201` |
| `test_default_page_size_negative_rejected` | Valor `-1` | `400` | Si acepta |
| `test_default_page_size_string_rejected` | Valor `"25"` (string) | `400` | Si acepta |
| `test_default_page_size_float_rejected` | Valor `25.5` | `400` | Si acepta |
| `test_default_page_size_null_rejected` | Valor `null` | `400` | Si acepta |
| `test_default_page_size_bool_rejected` | Valor `true` | `400` | Si acepta |
| `test_default_page_size_list_rejected` | Valor `[25]` | `400` | Si acepta |
| `test_default_page_size_dict_rejected` | Valor `{"a": 1}` | `400` | Si acepta |
| `test_default_page_size_updates_instance` | Guardar `100` actualiza `wa._DEFAULT_PAGE_SIZE` en caliente | `100` en atributo | Si no se aplica |
| `test_default_page_size_persisted_to_disk` | Valor guardado se lee del disco tras recargar | Valor correcto | Si se pierde |
| `test_default_page_size_not_in_body_unchanged` | No enviar `default_page_size` no lo modifica | Valor anterior sin cambios | Si se resetea |
| `test_default_page_size_injection_string` | Strings tipo `"1; DROP TABLE"` | `400` | Si acepta |
| `test_default_page_size_nosql_operator_rejected` | `{"$gt": 0}` como valor | `400` | Si acepta |
| `test_default_page_size_xss_rejected` | `"<script>alert(1)</script>"` | `400` | Si acepta |
| `test_default_page_size_combined_with_page_sizes` | Enviar `page_sizes` y `default_page_size` juntos | Ambos guardados | Si solo uno persiste |

### `TestApiConfigPutPageSizes`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_page_sizes_happy_path` | `[25, 50, 100, 200, 0]` — array estándar | `200`, array guardado | Si falla |
| `test_page_sizes_single_element` | `[10]` — array de un elemento | `200`, guardado | Si rechaza |
| `test_page_sizes_includes_zero` | `0` (Todos) puede estar en el array | `200` | Si filtra el `0` |
| `test_page_sizes_large_valid_value` | `[1000]` — valor grande pero entero no negativo | `200` | Si rechaza |
| `test_page_sizes_non_array_fallback` | Enviar un string en lugar de array | Fallback a `[25,50,100,200,0]` | Si falla con error |
| `test_page_sizes_null_fallback` | Enviar `null` | Fallback a defecto | Si falla con error |
| `test_page_sizes_number_fallback` | Enviar un entero `50` | Fallback a defecto | Si falla con error |
| `test_page_sizes_all_strings_filtered` | `["25", "50"]` — todos strings | Fallback a defecto | Si los acepta |
| `test_page_sizes_strings_and_ints_mixed` | `[25, "50", 100]` — mix strings/ints | Solo enteros sobreviven | Si incluye strings |
| `test_page_sizes_negatives_filtered` | `[-1, 25]` — negativos descartados | Solo `[25]` | Si incluye negativos |
| `test_page_sizes_all_negative_fallback` | `[-1, -5]` — todos negativos | Fallback a defecto | Si falla |
| `test_page_sizes_booleans_filtered` | `[true, false, 25]` — booleanos descartados | Solo `[25]` | Si incluye booleanos |
| `test_page_sizes_floats_filtered` | `[25.5, 50.0, 100]` — floats descartados | Solo `[100]` | Si acepta floats |
| `test_page_sizes_null_elements_filtered` | `[null, 25]` — nulos descartados | Solo `[25]` | Si incluye nulos |
| `test_page_sizes_nested_arrays_filtered` | `[[25], 50]` — arrays anidados descartados | Solo `[50]` | Si incluye arrays |
| `test_page_sizes_nested_dicts_filtered` | `[{"a": 1}, 50]` — dicts descartados | Solo `[50]` | Si incluye dicts |
| `test_page_sizes_xss_elements_filtered` | `["<script>alert(1)</script>", 50]` | Solo `[50]` | Si acepta strings |
| `test_page_sizes_sql_injection_filtered` | `["1; DROP TABLE users;--", 50]` | Solo `[50]` | Si acepta strings |
| `test_page_sizes_nosql_operator_filtered` | `[{"$gt": 0}, 50]` | Solo `[50]` | Si acepta dicts |
| `test_page_sizes_path_traversal_filtered` | `["../../../etc/passwd", 50]` | Solo `[50]` | Si acepta strings |
| `test_page_sizes_large_array_accepted` | Array con 1000 enteros válidos | `200`, guardado | Si rechaza por tamaño |
| `test_page_sizes_large_values_accepted` | `[9999999]` — entero grande no negativo | `200` | Si rechaza |
| `test_page_sizes_combined_with_default` | `page_sizes` y `default_page_size` en el mismo PUT | Ambos guardados correctamente | Si se pisan |

### `TestApiConfigPutProxyCount`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_proxy_count_zero` | `proxy_count: 0` (sin proxy) | `200`, valor persistido | Si falla |
| `test_proxy_count_one` | `proxy_count: 1` | `200` | Si rechaza |
| `test_proxy_count_ten` | `proxy_count: 10` (límite superior) | `200` | Si rechaza |
| `test_proxy_count_above_max_clamped` | `proxy_count: 11` | Rechazado o ajustado a 10 | Si acepta 11 |
| `test_proxy_count_negative_rejected` | `proxy_count: -1` | `400` | Si acepta |
| `test_proxy_count_string_rejected` | `proxy_count: "1"` | `400` | Si acepta |
| `test_proxy_count_float_rejected` | `proxy_count: 1.5` | `400` | Si acepta |
| `test_proxy_count_null_rejected` | `proxy_count: null` | `400` | Si acepta |
| `test_proxy_count_bool_coercion` | `proxy_count: true` → rechazado como bool | `400` | Si acepta como 1 |
| `test_proxy_count_list_rejected` | `proxy_count: [1]` | `400` | Si acepta |
| `test_proxy_count_updates_instance` | Guardar `3` actualiza `wa._proxy_count` | `3` en atributo | Si no se aplica |
| `test_proxy_count_nosql_operator_rejected` | `proxy_count: {"$gt": 0}` | `400` | Si acepta |
| `test_proxy_count_not_in_body_unchanged` | No enviar `proxy_count` no lo modifica | Valor anterior sin cambios | Si se resetea |

### `TestModuleItemSchemas`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_discover_returns_non_empty` | `discover_schemas()` con módulos reales | Dict con entradas | Si está vacío |
| `test_web_list_schema_has_code` | Schema `web\|list` tiene campos `code`, `url`, `enabled` | Todos presentes con metadata | Si falta alguno |
| `test_ping_list_schema_fields` | Schema `ping\|list` tiene los 5 campos esperados | `enabled`, `host`, `timeout`, `attempt`, `alert` | Si falta alguno |
| `test_mysql_list_schema_fields` | Schema `mysql\|list` con campos de conexión | `host`, `port`, `user`, `password`, `db`, `socket`, etc. | Si falta alguno |
| `test_service_status_schema_fields` | Schema `service_status\|list` | `enabled`, `service`, `remediation` | Si falta alguno |
| `test_temperature_list_schema_fields` | Schema `temperature\|list` | `enabled`, `label`, `alert` | Si falta alguno |
| `test_hddtemp_list_schema_fields` | Schema `hddtemp\|list` | `enabled`, `host`, `port`, `exclude` | Si falta alguno |
| `test_raid_remote_schema_fields` | Schema `raid\|remote` con campos SSH | `host`, `port`, `user`, `password`, `key_file`, etc. | Si falta alguno |
| `test_ram_swap_config_schema` | Schema `ram_swap\|config` | `alert_ram`, `alert_swap` con rangos 0-100 | Si falta o los rangos son incorrectos |
| `test_filesystemusage_list_schema_fields` | Schema `filesystemusage\|list` | `enabled`, `alert`, `label`, `partition` | Si falta alguno |
| `test_watchful_class_declares_schema` | `WebWatchful.ITEM_SCHEMA` directamente | Dict con `list.code.default == 200` | Si difiere |
| `test_discover_with_bad_dir_returns_empty` | `discover_schemas('/nonexistent')` | `{}` | Si lanza |
| `test_dashboard_contains_item_schemas_json` | HTML del dashboard contiene `ITEM_SCHEMAS` | String `ITEM_SCHEMAS` en el HTML | Si no aparece |
| `test_schemas_passed_to_template` | Schema en el HTML tiene `"default": 200` | Presente en el HTML | Si no aparece |

### `TestRekeyItemsByUid` (`test_wa_modules.py`)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_rekey_flat_and_nested` | Reindexado de ítems por `uid` (plano y anidado) | Listas rekeyed por uid (generado si falta); escalares (`enabled`/`threads`) intactos | Si reindexa mal o toca escalares |

### `TestLandingPageApplied` (`test_wa_config.py`)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_startup_applies_global_landing` | `_apply_saved_config()` re-deriva el landing global | `_landing_page='overview'`; `_landing_url` devuelve `/overview` sin override de usuario | Si no lo aplica |

---

## 13. Panel Web — API estado y ejecución de checks

**Archivos:** `tests/test_wa_modules.py` — `TestApiStatus`, `TestApiOverview` · `tests/test_wa_checks.py` — `TestApiRunChecks`

### `TestApiStatus`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_get_status_requires_auth` | Sin login | `302` | Si devuelve datos |
| `test_get_status_returns_dict` | `GET /api/status` | Dict JSON con el estado | Si es otro tipo |
| `test_modules_list` | Lista de módulos en el estado | Los módulos esperados presentes | Si están ausentes |
| `test_modules_enabled_flag` | Flag `enabled` por módulo | Valor correcto según la configuración de módulos | Si difiere |
| `test_modules_items_count` | Número de ítems por módulo | Conteo correcto | Si difiere |

### `TestApiOverview`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_requires_auth` | Sin login | `302` | Si devuelve datos |
| `test_returns_200` | `GET /api/overview` autenticado | `200` | Si no accesible |
| `test_response_keys` | Claves del JSON: `modules`, `status`, `sessions`, `users`, `groups`, `roles`, `last_events` | Todas presentes | Si falta alguna |
| `test_modules_list` | Lista de módulos contiene `ping` y `web` | Nombres exactos | Si difiere |
| `test_modules_enabled_flag` | Flag `enabled` por módulo | Ambos `true` en fixture | Si difiere |
| `test_modules_items_count` | Número de ítems por módulo | `ping=2`, `web=1` | Si difiere |
| `test_status_counts` | Contadores globales de checks | `total=1`, `ok=1`, `error=0` | Si difiere |
| `test_status_without_var_dir` | Sin `var_dir` → ceros | `{total:0, ok:0, error:0}` | Si no es cero |
| `test_sessions_contains_current` | Sesión activa tras login | `active≥1`, `admin` en `users` | Si no aparece |
| `test_users_total` | Total de usuarios | `total=1`, `by_role.admin=1` | Si difiere |
| `test_last_events_list` | `last_events` es lista con campo `event` | Lista válida | Si no es lista |
| `test_last_events_max_10` | Con >10 eventos en audit | Máximo 10 devueltos | Si devuelve más |
| `test_dashboard_has_overview_tab` | HTML del dashboard contiene `tab-overview` | Elemento presente | Si no aparece |
| `test_groups_summary_keys` | `groups` tiene `total` y `members` | Ambas claves presentes | Si falta alguna |
| `test_groups_default_administrators` | Sin grupos previos → grupo `administrators` creado | `total=1`, `members=0` | Si difiere |
| `test_roles_summary_keys` | `roles` tiene `total`, `builtin`, `custom` | Todas presentes | Si falta alguna |
| `test_roles_builtin_count` | Roles integrados = 3 (admin/editor/viewer) | `builtin=3`, `custom=0` | Si difiere |
| `test_roles_custom_count` | Añadir rol personalizado en runtime | `custom=1`, `total=4` | Si no incrementa |
| `test_modules_have_checks_key` | Cada módulo tiene clave `checks` | Dict presente en todos | Si falta |
| `test_module_checks_structure` | `checks` tiene `total`, `ok`, `error` | Tres claves presentes | Si falta alguna |
| `test_module_checks_counts` | Counts reales: `ping` 1 OK, `web` 0 | Valores exactos del fixture | Si difiere |
| `test_module_checks_with_error` | Check fallido contabilizado | `ping.error=1` | Si no se refleja |
| `test_module_checks_without_var_dir` | Sin `var_dir` → checks a cero | Todos `{0,0,0}` | Si no es cero |
| `test_status_aggregated_from_module_checks` | `status` = suma de checks por módulo | Invariante aritmética | Si no cuadra |

### `TestApiRunChecks`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_run_checks_requires_auth` | `POST /api/checks/run` sin login | `302` | Si ejecuta checks |
| `test_run_checks_viewer_denied` | Usuario con rol `viewer` | `302` o `403` | Si ejecuta checks |
| `test_run_checks_no_modules_dir` | `_modules_dir = None` | `500` | Si devuelve `200` |
| `test_run_checks_audit_entry` | Ejecutar checks crea entrada en audit log | `"checks_run"` en el log | Si no aparece |
| `test_run_checks_all_discovers_package_modules` | `modules="all"` encuentra módulos tipo paquete | `200`, `results["testmod"]` presente | Si `results` está vacío |
| `test_run_checks_all_ignores_flat_py_files` | `modules="all"` con solo `.py` planos en el dir | `results` vacío, sin error | Si descubre el `.py` plano |
| `test_run_checks_response_shape` | Shape del JSON de respuesta | `ok`, `results` (dict), `errors` (list) siempre presentes | Si falta alguna clave |
| `test_run_checks_specific_module_missing` | Módulo inexistente en la lista | Nombre aparece en `errors` | Si no aparece o lanza |

---

## 14. Panel Web — Usuarios, roles y sesiones

**Archivos:** `tests/test_wa_users.py` — `TestApiUsers`, `TestChangeOwnPassword` · `tests/test_wa_sessions.py` — `TestSessionRegistry` · `tests/test_wa_auth.py` — `TestRememberMe`

### `TestApiUsers`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_get_users_requires_auth` | Sin login | `302` | Si devuelve datos |
| `test_get_users_admin_only` | Rol no-admin | `403` | Si devuelve datos |
| `test_create_user` | `POST /api/users` | Usuario creado, `201` | Si es otro código |
| `test_update_user` | `PUT /api/users/<name>` | Usuario actualizado, `200` | Si es otro código |
| `test_delete_user` | `DELETE /api/users/<name>` | Usuario eliminado, `200` | Si persiste |
| `test_cannot_delete_last_admin` | Eliminar el único admin | `400` | Si lo elimina |

### `TestRolePermissions`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_viewer_can_read_modules` | `GET /api/modules` con rol `viewer` | `200` | Si es `403` |
| `test_viewer_cannot_write_modules` | `PUT /api/modules` con rol `viewer` | `403` | Si guarda datos |
| `test_editor_can_write_modules` | `PUT /api/modules` con rol `editor` | `200` | Si es `403` |

### `TestChangeOwnPassword`, `TestRememberMe`, `TestSessionRegistry`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| Cambio de contraseña propia | `PUT /api/users/me/password` | `200`, contraseña actualizada | Si no cambia |
| Contraseña incorrecta al cambiar | Contraseña actual equivocada | `401` | Si acepta |
| Remember me | Login con `remember_me=true` | Cookie con duración extendida | Si expira en sesión |
| Registro de sesiones | Múltiples logins registran sesiones | Todas las sesiones en `/api/sessions` | Si faltan |
| Revocar sesión | `DELETE /api/sessions/<id>` | Sesión eliminada | Si persiste |

### `TestUserInputValidation`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_create_user_invalid_lang_rejected` | Crear con idioma inválido | `400` con error | Si acepta |
| `test_create_user_valid_lang_accepted` | Crear con idioma válido | `201`, `lang` guardado | Si rechaza |
| `test_create_user_empty_lang_ignored` | Crear con `lang` vacío | `201`, `lang` a `None` | Si falla |
| `test_create_user_unknown_group_rejected` | Crear con grupo desconocido | `400` con error | Si acepta |
| `test_create_user_non_list_groups_rejected` | `groups` no es lista | `400` | Si acepta |
| `test_create_user_known_group_accepted` | Crear con grupo conocido | `201`, uid del grupo guardado | Si rechaza |
| `test_update_user_invalid_lang_rejected` | Editar a idioma inválido | `400`, `lang` sin cambio | Si acepta |
| `test_update_user_valid_lang_accepted` | Editar a idioma válido | `200`, `lang` guardado | Si rechaza |
| `test_update_user_empty_lang_accepted` | Editar a `lang` vacío | `200` | Si rechaza |
| `test_update_user_non_bool_dark_mode_rejected` | `dark_mode` no booleano | `400` | Si acepta |
| `test_update_user_int_dark_mode_rejected` | `dark_mode` como entero | `400` | Si acepta |
| `test_update_user_bool_dark_mode_accepted` | `dark_mode` booleano | `200`, `dark_mode=True` | Si rechaza |
| `test_update_user_unknown_group_rejected` | Editar con grupo desconocido | `400`, grupos siguen `[]` | Si acepta |
| `test_update_user_non_list_groups_rejected` | `groups` no es lista al editar | `400` | Si acepta |
| `test_update_user_known_group_accepted` | Editar con grupo conocido | `200`, uid del grupo presente | Si rechaza |
| `test_preferences_invalid_lang_rejected` | Preferencias con idioma inválido | `400` | Si acepta |
| `test_preferences_non_string_lang_rejected` | Preferencias con `lang` no string | `400` | Si acepta |
| `test_preferences_valid_lang_accepted` | Preferencias con idioma válido | `200` | Si rechaza |
| `test_preferences_non_bool_dark_mode_rejected` | Preferencias `dark_mode` no booleano | `400` | Si acepta |
| `test_preferences_null_dark_mode_resets_to_default` | Preferencias `dark_mode` nulo | `200` (reset a default) | Si falla |

### `TestPasswordResetPrivileges`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_non_admin_cannot_reset_another_users_password` | No-admin resetea a otro usuario | `403`; contraseña original intacta | Si la cambia |
| `test_non_admin_cannot_reset_admin_password` | No-admin resetea al admin | `403`; contraseña del admin intacta | Si la cambia |
| `test_admin_can_reset_any_password` | Admin resetea cualquier contraseña | `200`; nueva contraseña verifica | Si falla |
| `test_non_admin_cannot_grant_admin_role` | No-admin intenta conceder rol admin | `403`; rol no admin | Si lo concede |
| `test_non_admin_can_change_own_password_via_me_endpoint` | No-admin cambia su propia contraseña vía `/me` | `200`; nueva contraseña verifica | Si falla |

### `TestOwnLandingPreference`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_me_exposes_landing_fields` | `/me` expone `pref_landing_page` y default | `landing_default` en {admin, overview, status} | Si falta |
| `test_set_own_landing` | Fijar landing propio | `200`; `landing_page='overview'`; `/me` lo refleja | Si no aplica |
| `test_invalid_landing_rejected` | Landing inválido | `400` | Si acepta |
| `test_empty_landing_inherits` | Landing vacío tras fijarlo | Se elimina del usuario (hereda global) | Si persiste |

---

## 15. Panel Web — i18n, UI y seguridad

**Archivos:** `tests/test_wa_ui.py` — `TestI18n`, `TestDarkMode`, `TestConfigDarkMode`, `TestUIReorganisation` · `tests/test_wa_telegram.py` — `TestTelegramTest` · `tests/test_wa_audit.py` — `TestAuditLog` · `tests/test_wa_security.py` — `TestSecurityInjection`

### `TestI18n`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_default_language_is_english` | Idioma por defecto en sesión nueva | `lang == "en_EN"` | Si es otro |
| `test_switch_to_spanish` | `GET /lang/es_ES` cambia la sesión | `lang == "es_ES"` | Si no cambia |
| `test_switch_back_to_english` | Volver a inglés tras cambiar | `lang == "en_EN"` | Si no cambia |
| `test_invalid_language_ignored` | Código inválido (`fr`) silenciado | Idioma anterior conservado | Si lanza o acepta |
| `test_spanish_error_messages` | Errores de login en español | Mensaje en castellano | Si sigue en inglés |
| `test_login_page_renders_in_english` | Formulario de login en inglés | `"Sign In"` en HTML | Si no aparece |
| `test_login_page_renders_in_spanish` | Formulario de login en español | `"Entrar"` en HTML | Si no aparece |
| `test_lang_switch_without_auth` | Cambio de idioma sin login | `200`, idioma activo | Si redirige a login |
| `test_api_errors_in_spanish` | Errores de API en el idioma activo | Mensaje en castellano | Si devuelve otro idioma |
| `test_lang_persisted_to_user_record` | Preferencia guardada en el usuario | Campo `lang` en `_users` | Si no se persiste |
| `test_lang_loaded_on_login` | Idioma del usuario restaurado al login | Sesión con idioma guardado | Si usa defecto |
| `test_global_default_lang` | `WebAdmin(..., default_lang="es_ES")` | Sesión nueva en español | Si usa inglés |
| `test_global_default_invalid_falls_back` | `default_lang` inválido cae a `"en_EN"` | `lang == "en_EN"` | Si lanza o usa el inválido |
| `test_user_lang_in_users_list` | `GET /api/users` incluye `lang` por usuario | Campo `lang` presente | Si no está |
| `test_admin_can_set_user_lang` | Admin cambia idioma de otro usuario via PUT | `200`, campo actualizado | Si es `403` |
| `test_create_user_with_lang` | `POST /api/users` con `lang` | Usuario creado con idioma | Si se descarta |
| `test_create_user_without_lang` | `POST /api/users` sin `lang` | `lang == ""` (usa defecto del sistema) | Si pone otra cosa |
| `test_update_own_lang_updates_session` | Editar propio usuario actualiza la sesión activa | Sesión refleja el nuevo idioma | Si no se propaga |
| `test_save_config_updates_default_lang` | `PUT /api/config` con `web_admin.lang` | `_default_lang` actualizado | Si no cambia |
| `test_save_config_invalid_lang_ignored` | Guardar idioma inválido | `_default_lang` sin cambio | Si lo acepta |
| `test_dashboard_exposes_default_lang` | Dashboard incluye `SYSTEM_DEFAULT_LANG` | Cadena presente en HTML | Si no aparece |
| `test_dashboard_exposes_supported_langs` | Dashboard incluye `SUPPORTED_LANGS` | Cadena presente en HTML | Si no aparece |

### `TestDarkMode`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_default_theme_is_light` | Sin config, tema es claro | `data-bs-theme="light"` en HTML | Si es dark |
| `test_toggle_to_dark` | `GET /theme/dark` activa modo oscuro | `data-bs-theme="dark"` en HTML | Si no cambia |
| `test_toggle_back_to_light` | `GET /theme/light` vuelve al modo claro | `data-bs-theme="light"` en HTML | Si no cambia |
| `test_theme_persisted_to_user` | Preferencia guardada en el usuario | `_users["admin"]["dark_mode"]` correcto | Si no se persiste |
| `test_theme_loaded_on_login` | Preferencia del usuario restaurada al login | HTML refleja el dark_mode guardado | Si usa defecto |
| `test_api_me_includes_dark_mode` | `GET /api/me` incluye `dark_mode` | Campo presente y correcto | Si no está |
| `test_invalid_theme_ignored` | Tema inválido (`/theme/purple`) silenciado | Tema anterior conservado | Si lanza o acepta |
| `test_global_default_dark_mode` | `WebAdmin(..., default_dark_mode=True)` | Sesión nueva en modo oscuro | Si usa claro |
| `test_save_config_updates_default_dark_mode` | `PUT /api/config` con `web_admin.dark_mode` | `_default_dark_mode` actualizado | Si no cambia |
| `test_user_dark_mode_in_users_list` | `GET /api/users` incluye `dark_mode` por usuario | Campo presente | Si no está |
| `test_admin_can_set_user_dark_mode` | Admin cambia dark_mode de otro usuario via PUT | `200`, campo actualizado | Si es `403` |

### `TestConfigDarkMode`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_config_tab_renders_dark_mode_field` | La pestaña Config renderiza el campo dark_mode | `configData.web_admin.dark_mode` en HTML | Si no aparece |

### `TestUIReorganisation`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_navbar_has_user_dropdown` | Navbar contiene el menú de usuario | Icono y función presentes en HTML | Si no aparecen |
| `test_change_password_modal_exists` | Modal de cambio de contraseña propia | `id="changePasswordModal"` en HTML | Si no está |
| `test_reset_password_modal_exists` | Modal de reset de contraseña por admin | `id="resetPasswordModal"` en HTML | Si no está |
| `test_no_inline_password_form_in_users_tab` | Formulario inline antiguo eliminado | No aparece `onclick="changeOwnPassword()"` | Si sigue presente |
| `test_users_table_has_reset_icon` | Tabla de usuarios tiene botón de reset | `openResetPasswordModal(` en HTML | Si no aparece |
| `test_reset_password_via_admin_api` | Admin reseta contraseña de otro usuario via PUT | `200`, hash actualizado | Si no cambia |
| `test_language_selector_in_user_menu` | Selector de idioma está en el menú de usuario | Icono `bi-translate` y `/lang/` en HTML | Si no aparecen |
| `test_dark_mode_toggle_in_user_menu` | Toggle de dark mode está en el menú de usuario | `id="darkModeSwitch"` y `toggleDarkMode()` | Si no aparecen |

### `TestOverviewPage`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_admin_panel_has_no_overview_tab` | El panel admin ya no lleva pestaña Overview | Sin `data-bs-target="#tab-overview"`; `SS_OVERVIEW_PAGE = false` | Si aparece la pestaña |
| `test_overview_route_renders_standalone` | `/overview` renderiza página independiente | `200`; HTML con `overview-container`, `SS_OVERVIEW_PAGE = true` | Si no renderiza |
| `test_overview_requires_login` | `/overview` sin autenticar | `302` | Si devuelve `200` |

### `TestTelegramTest`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_requires_auth` | Sin login redirige a `/login` | `302` | Si devuelve `200` |
| `test_viewer_denied` | Rol `viewer` no puede enviar mensajes | `403` | Si envía |
| `test_missing_fields` | Body vacío | `400` | Si acepta |
| `test_missing_token` | Sin campo `token` | `400` | Si acepta |
| `test_missing_chat_id` | Sin campo `chat_id` | `400` | Si acepta |
| `test_success` | API Telegram devuelve `200` (mock) | `{"ok": true}` | Si falla |
| `test_api_error` | API Telegram devuelve `401` (mock) | `502`, mensaje de error | Si devuelve `200` |
| `test_network_error` | Excepción de red (mock) | `502`, mensaje de excepción | Si no maneja |
| `test_non_json_error_response` | Respuesta `500` no-JSON (mock) | `502`, código en mensaje | Si lanza |
| `test_dashboard_has_test_button` | Dashboard incluye el botón de prueba | `btnTestTelegram` en HTML | Si no aparece |

### `TestAuditLog`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_login_audited` | Login exitoso genera evento | `"login"` en audit | Si no aparece |
| `test_failed_login_audited` | Login fallido genera evento | `"login_failed"` en audit | Si no aparece |
| `test_failed_login_reason_invalid_credentials` | Contraseña errónea → razón en audit | `detail.reason == 'invalid_credentials'` | Si falta el campo |
| `test_failed_login_reason_user_not_found` | Usuario inexistente → razón en audit | `detail.reason == 'user_not_found'` | Si falta el campo |
| `test_failed_login_reason_account_disabled` | Cuenta desactivada → razón en audit | `detail.reason == 'account_disabled'` | Si falta el campo |
| `test_logout_audited` | Logout genera evento | `"logout"` en audit | Si no aparece |
| `test_modules_save_audited` | Guardar módulos genera evento | `"modules_updated"` en audit | Si no aparece |
| `test_config_save_audited` | Guardar config genera evento | `"config_updated"` en audit | Si no aparece |
| `test_user_create_audited` | Crear usuario genera evento | `"user_created"` en audit | Si no aparece |
| `test_user_update_audited` | Editar usuario genera evento | `"user_updated"` en audit | Si no aparece |
| `test_user_delete_audited` | Eliminar usuario genera evento | `"user_deleted"` en audit | Si no aparece |
| `test_password_change_audited` | Cambio de contraseña propia genera evento | `"password_changed"` en audit | Si no aparece |
| `test_all_sessions_revoked_audited` | Revocar todas las sesiones genera evento | `"sessions_revoked"` en audit | Si no aparece |
| `test_audit_api_returns_entries` | `GET /api/audit` devuelve la lista | Lista con entradas | Si está vacía |
| `test_audit_api_viewer_can_read_but_not_delete` | Viewer puede leer pero no borrar | `200` GET / `403` DELETE | Si puede borrar |
| `test_audit_persisted_to_db` | Entradas se guardan en la tabla `audit` de la BD | BD actualizada tras evento | Si solo en memoria |
| `test_audit_max_entries` | Límite máximo de entradas | No supera el máximo configurado | Si crece sin límite |
| `test_audit_tab_in_ui` | Pestaña de audit visible en el dashboard | `id="tab-audit"` en HTML | Si no aparece |
| `test_audit_entry_has_required_fields` | Estructura de cada entrada | Campos `event`, `user`, `ts` presentes | Si falta alguno |
| `test_admin_password_reset_audited` | Reset de contraseña por admin genera evento | `"password_reset"` en audit | Si no aparece |
| `test_password_reset_separate_from_update` | Reset genera evento distinto al de edición | No aparece `"user_updated"` | Si los mezcla |
| `test_config_save_records_old_and_new` | El evento de config incluye diff old/new | Campos `old` y `new` en el evento | Si no hay diff |
| `test_sensitive_fields_masked_in_audit` | Campos sensibles enmascarados en el diff | `"***"` en lugar del valor real | Si aparece en claro |
| `test_no_update_audit_when_no_changes` | Guardar sin cambios no genera evento | Lista de audit sin `"user_updated"` | Si genera evento vacío |
| `test_diff_dicts_helper` | Helper `_diff_dicts` calcula el diff correcto | Sólo claves modificadas en el resultado | Si incluye todas |
| `test_clear_all_entries` | `DELETE /api/audit` vacía la lista | `200`, lista vacía tras la petición | Si quedan entradas |
| `test_clear_all_persisted_to_db` | Vaciar audit persiste en la BD | Tabla `audit` vacía tras borrar | Si sólo en memoria |
| `test_delete_single_entry` | `DELETE /api/audit/<idx>` elimina entrada puntual | `200`, entrada ya no en lista | Si permanece |
| `test_delete_single_entry_oob` | Índice fuera de rango | `404` | Si borra o lanza |
| `test_delete_single_entry_negative` | Índice negativo | `404` | Si borra o lanza |
| `test_delete_single_entry_viewer_forbidden` | Viewer no puede borrar entradas | `403` | Si borra |
| `test_delete_single_entry_persisted` | Borrado puntual persiste en la BD | Tabla `audit` actualizada sin la entrada | Si sólo en memoria |

### `TestSecurityInjection`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_xss_in_username_create` | XSS en nombre de usuario al crear | Almacenado literal, `200`/`201` | Si se evalúa como HTML |
| `test_xss_in_display_name` | XSS en display name | Almacenado literal | Si se ejecuta |
| `test_xss_in_login_form_username` | XSS en campo username del login | No redirige al dashboard | Si lo ejecuta |
| `test_sql_injection_in_username` | Payload SQL como nombre de usuario | Almacenado literal | Si causa error DB |
| `test_sql_injection_in_user_lookup` | Payload SQL en operación de lectura | Almacenado literal | Si causa error DB |
| `test_path_traversal_lang_endpoint` | Path traversal en `/lang/` | `200` o ignorado, sin acceso a ficheros | Si devuelve ficheros |
| `test_path_traversal_theme_endpoint` | Path traversal en `/theme/` | `200` o ignorado | Si devuelve ficheros |
| `test_path_traversal_session_revoke` | Path traversal en revocación de sesión | `404` o `400` | Si accede a rutas internas |
| `test_non_json_content_type` | Content-Type incorrecto en endpoints JSON | `400` o `415` | Si acepta datos malformados |
| `test_empty_body_json_endpoints` | Body vacío en endpoints que requieren JSON | `400` | Si lanza excepción no controlada |
| `test_deeply_nested_json` | JSON muy anidado | No lanza excepción, respuesta controlada | Si causa stack overflow |
| `test_very_large_json_payload` | JSON de gran tamaño | No lanza excepción | Si cuelga el servidor |
| `test_null_bytes_in_json_fields` | Bytes nulos en campos de texto | Almacenados literal o rechazados | Si causan error |
| `test_unicode_abuse_in_fields` | Caracteres Unicode extremos en campos | Almacenados literal | Si causan error |
| `test_viewer_cannot_create_user` | Escalada de privilegios (crear usuario) | `403` | Si crea el usuario |
| `test_viewer_cannot_delete_user` | Escalada de privilegios (eliminar usuario) | `403` | Si elimina |
| `test_editor_cannot_create_or_delete_user` | Editor no puede gestionar usuarios | `403` | Si lo permite |
| `test_editor_cannot_access_sessions` | Editor no puede ver sesiones | `403` | Si las muestra |
| `test_viewer_cannot_write_modules` | Viewer no puede editar módulos | `403` | Si guarda datos |
| `test_viewer_cannot_write_config` | Viewer no puede editar config | `403` | Si guarda datos |
| `test_viewer_can_access_audit` | Viewer sí puede leer audit | `200` | Si es `403` |
| `test_self_promotion_via_update` | Usuario se intenta promover a admin | `403` | Si lo permite |
| `test_unauthenticated_api_access` | Acceso sin autenticar a todas las rutas `/api/*` | `401` JSON en todos | Si alguno devuelve `200` o `302` |
| `test_login_wrong_password` | Credenciales incorrectas | `302` + mensaje flash | Si entra |
| `test_login_nonexistent_user` | Usuario inexistente | `302` + sesión sin `logged_in` | Si entra |
| `test_login_empty_credentials` | Credenciales vacías | `302` + sesión sin `logged_in` | Si entra |
| `test_forged_session_token_rejected` | Token de sesión falsificado | `401` en `/api/me` | Si acepta la sesión |
| `test_reused_session_token_after_logout` | Token antiguo tras logout | `401` en `/api/me` | Si acepta la sesión |
| `test_reused_session_token_after_logout` | Token de sesión reutilizado tras logout | Redirección a login | Si reutiliza la sesión |
| `test_wrong_http_methods_rejected` | Métodos HTTP incorrectos en endpoints | `405` o `302` | Si devuelve `200` |
| `test_ssti_in_display_name` | SSTI `{{7*7}}` en display name | Almacenado como literal `"{{7*7}}"` | Si se evalúa como `49` |
| `test_invalid_role_rejected` | Rol inexistente al crear usuario | `400` | Si acepta el rol |
| `test_update_to_invalid_role_rejected` | Cambiar usuario a rol inexistente | `400` | Si acepta el rol |
| `test_special_chars_in_module_keys` | Caracteres especiales en claves de módulo | Guardados literal | Si causan error |
| `test_audit_log_not_injectable` | Payloads XSS en entradas de audit | Almacenados literales | Si se ejecutan |

---

## 15b. Panel Web — Política de contraseñas

**Archivo:** `tests/test_wa_password_policy.py`

Cubre la función `_validate_password` (unidad) y la aplicación de la política vía la API HTTP.

### `TestValidatePasswordUnit`

| Test | Qué comprueba | OK | Error |
|------|-------------|-----|------|
| `test_accepts_valid_password_no_policy` | Contraseña válida sin política estricta | `None` (sin error) | Si devuelve error |
| `test_too_short` | Contraseña más corta que `pw_min_len` | Código `password_too_short` con el límite | Si acepta o devuelve otro código |
| `test_too_long` | Contraseña más larga que `pw_max_len` | Código `password_too_long` | Si acepta |
| `test_exactly_min_len_accepted` | Longitud exactamente igual a `pw_min_len` | `None` | Si rechaza |
| `test_exactly_max_len_accepted` | Longitud exactamente igual a `pw_max_len` | `None` | Si rechaza |
| `test_require_upper_rejects_all_lower` | `pw_require_upper=True` con solo minúsculas | `password_need_upper` | Si acepta |
| `test_require_upper_rejects_all_upper` | `pw_require_upper=True` con solo mayúsculas (sin minúscula) | `password_need_upper` | Si acepta |
| `test_require_upper_accepts_mixed_case` | `pw_require_upper=True` con mayúsculas y minúsculas | `None` | Si rechaza |
| `test_no_require_upper_accepts_all_lower` | `pw_require_upper=False` | `None` | Si rechaza |
| `test_require_digit_rejects_no_digit` | `pw_require_digit=True` sin dígitos | `password_need_digit` | Si acepta |
| `test_require_digit_accepts_with_digit` | `pw_require_digit=True` con dígito | `None` | Si rechaza |
| `test_no_require_digit_accepts_no_digit` | `pw_require_digit=False` | `None` | Si rechaza |
| `test_require_symbol_rejects_no_symbol` | `pw_require_symbol=True` sin símbolos | `password_need_symbol` | Si acepta |
| `test_require_symbol_accepts_with_symbol` | `pw_require_symbol=True` con símbolo | `None` | Si rechaza |
| `test_no_require_symbol_accepts_no_symbol` | `pw_require_symbol=False` | `None` | Si rechaza |
| `test_all_rules_enabled_accepts_strong_password` | Todas las reglas activas + contraseña fuerte | `None` | Si rechaza |
| `test_all_rules_enabled_rejects_missing_digit` | Todas las reglas activas, falta dígito | `password_need_digit` | Si acepta |
| `test_all_rules_enabled_rejects_missing_symbol` | Todas las reglas activas, falta símbolo | `password_need_symbol` | Si acepta |
| `test_priority_length_before_complexity` | Longitud se valida antes que complejidad | `password_too_short` | Si devuelve otro error |
| `test_returns_none_means_no_error` | Sin política → `None` | `None` | Si devuelve error |

### `TestPasswordPolicyApi`

| Test | Qué comprueba | OK | Error |
|------|-------------|-----|------|
| `test_create_user_rejects_short_password` | `POST /api/users` contraseña corta | `400` con "password" en error | Si crea el usuario |
| `test_create_user_rejects_no_digit` | `POST /api/users` sin dígito | `400` | Si acepta |
| `test_create_user_rejects_no_upper` | `POST /api/users` sin mayúscula | `400` | Si acepta |
| `test_create_user_rejects_no_symbol` | `POST /api/users` sin símbolo | `400` | Si acepta |
| `test_create_user_accepts_compliant_password` | `POST /api/users` contraseña fuerte | `201` | Si rechaza |
| `test_update_password_rejects_policy_violation` | `PUT /api/users/<u>` contraseña inválida | `400` | Si actualiza |
| `test_update_password_accepts_compliant_password` | `PUT /api/users/<u>` contraseña válida | `200` | Si rechaza |
| `test_change_own_password_rejects_policy_violation` | `PUT /api/users/me/password` inválida | `400` | Si cambia |
| `test_change_own_password_accepts_compliant_password` | `PUT /api/users/me/password` válida | `200` | Si rechaza |

---

## 15c. Panel Web — Página de estado pública

**Archivo:** `tests/test_wa_status.py` — clases `TestPublicStatusPage` y `TestStatusPageLanguage`

Verifica el comportamiento de la ruta `/status` (acceso público vs. autenticado, contenido de la página, configuración e idioma).

### `TestPublicStatusPage`

| Test | Qué comprueba | OK | Error |
|------|-------------|-----|------|
| `test_status_no_login_required` | `/status` accesible sin login | `200` | Si es `302` o `404` |
| `test_status_accessible_when_enabled` | `/status` con `public_status=True` | `200` | Si es `404` o `500` |
| `test_status_shows_all_systems_ok_banner` | Banner verde cuando todo está OK | Texto "All systems operational" en HTML | Si no aparece |
| `test_status_shows_degraded_banner_on_failure` | Banner rojo con algún check fallido | Texto de degradación en HTML | Si no cambia |
| `test_status_shows_module_name` | Nombre de módulo visible | Aparece el label del módulo | Si no aparece |
| `test_status_has_login_link` | Enlace al login en el footer | `/login` en el HTML | Si no aparece |
| `test_status_has_auto_refresh_meta` | Contador de refresco visible | Elemento `countdown` en HTML | Si no aparece |
| `test_status_custom_refresh_secs` | `status_refresh_secs=30` | El valor `30` aparece en el HTML | Si usa otro valor |
| `test_status_config_updates_refresh_secs` | Cambio en runtime de `status_refresh_secs` | Nuevo valor reflejado en el HTML | Si sigue el anterior |
| `test_status_empty_when_no_status_file` | Sin estado previo (tabla `check_state` vacía) | `200` sin tarjetas de módulo | Si falla o muestra módulos |
| `test_status_hidden_from_anonymous_when_disabled` | `public_status=False` + usuario anónimo | `404` | Si devuelve `200` |
| `test_status_visible_to_logged_in_when_disabled` | `public_status=False` + usuario logueado | `200` | Si devuelve `404` |
| `test_status_shows_check_names` | Nombres de checks visibles | Nombre del check en HTML | Si no aparece |
| `test_status_shows_check_status_ok` | Check OK muestra badge correcto | Badge OK en HTML | Si muestra error |
| `test_status_overall_pct_100_when_all_ok` | Porcentaje global 100% cuando todo OK | `100%` en HTML | Si muestra otro valor |

### `TestStatusPageLanguage`

Valida la prioridad de 3 niveles para el idioma de `/status`: sesión de usuario > `status_lang` > `default_lang`.

| Test | Qué comprueba | OK | Error |
|------|-------------|-----|------|
| `test_lang_falls_back_to_default_lang` | Sin `status_lang` ni sesión → usa `default_lang` | `lang=` igual a `default_lang` | Si usa otro idioma |
| `test_lang_default_lang_en_when_all_empty` | Todo vacío → idioma por defecto es `en_EN` | `lang="en_EN"` en `<html>` | Si es otro valor |
| `test_lang_status_lang_overrides_default` | `status_lang=es_ES` > `default_lang=en_EN` | `lang="es_ES"` en `<html>` | Si usa en_EN |
| `test_lang_status_lang_set_en` | `status_lang=en_EN` explícito | `lang="en_EN"` en `<html>` | Si difiere |
| `test_lang_runtime_config_update_applies_to_status` | Cambio de `_STATUS_LANG` en runtime | Nuevo idioma aplicado | Si sigue el anterior |
| `test_lang_user_session_overrides_status_lang` | Sesión de usuario (es_ES) > `status_lang` (en_EN) | `lang="es_ES"` en `<html>` | Si usa status_lang |
| `test_lang_user_session_es_overrides_status_lang_en` | Sesión es_ES con status_lang en_EN | `lang="es_ES"` en `<html>` | Si no es es_ES |
| `test_lang_user_session_overrides_default_lang` | Sesión de usuario > `default_lang` | Idioma de sesión aplicado | Si usa default_lang |
| `test_lang_anonymous_uses_status_lang_not_session` | Usuario anónimo → usa `status_lang`, no sesión de otro usuario | `lang` igual a `status_lang` | Si mezcla sesiones |
| `test_pretty_name_from_lang_file` | Lee `pretty_name` del archivo `lang/{lang}.json` del watchful | Label legible en HTML | Si muestra nombre raw |
| `test_pretty_name_no_modules_dir_falls_back_to_title` | Sin `modules_dir` → title-case del nombre raw | Nombre en title-case | Si muestra nombre raw sin formato |
| `test_pretty_name_unknown_module_title_case_fallback` | Módulo sin archivo lang → title-case del nombre | Nombre en title-case | Si falla o muestra nombre sin formato |

---

## 15d. Panel Web — Páginas de error HTTP

**Archivo:** `tests/test_wa_errors.py` — clase `TestErrorPages`

Verifica que los errores HTTP devuelven la plantilla `error.html` (o JSON para `/api/*`) con el código, título y descripción correctos.

| Test | Qué comprueba | OK | Error |
|------|-------------|-----|------|
| `test_404_returns_html` | Ruta inexistente → 404 HTML | `404`, `text/html` en Content-Type | Si devuelve JSON o 200 |
| `test_404_contains_title` | Página 404 contiene el título traducido | "Page Not Found" en HTML | Si no aparece |
| `test_404_has_error_code_displayed` | Página 404 muestra el código "404" | "404" en el cuerpo HTML | Si no aparece |
| `test_404_api_returns_json` | `Accept: application/json` → JSON | `{"error": ..., "code": 404}` | Si devuelve HTML |
| `test_404_api_path_returns_json` | `/api/ruta-inexistente` → JSON | `{"error": ..., "code": 404}` | Si devuelve HTML |
| `test_500_returns_html` | Ruta que lanza excepción → 500 HTML | `500`, `text/html` | Si propaga la excepción sin capturar |
| `test_405_on_wrong_method` | Método no permitido → 405 HTML | `405` | Si devuelve 404 o 200 |
| `test_error_page_respects_dark_mode` | Página de error hereda tema dark | Atributo `data-bs-theme="dark"` | Si usa tema light siempre |
| `test_error_page_has_description` | Página de error muestra descripción | Texto de descripción en HTML | Si no aparece |
| `test_error_page_404_no_session` | 404 sin sesión activa | `404` y HTML válido | Si falla o redirige |

---

## 16. Panel Web — Permisos granulares y roles personalizados


**Archivos:** `tests/test_wa_roles.py` — `TestPermissionsConstants`, `TestCustomRoles`, `TestGranularPermissions` · `tests/test_wa_groups.py` — grupos de usuarios


### `TestPermissionsConstants`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_permissions_tuple_has_15_flags` | `len(PERMISSIONS) == 15` | 15 elementos | Otro número |
| `test_permissions_are_unique` | Sin duplicados en `PERMISSIONS` | `set` sin colisiones | Si hay repetidos |
| `test_permissions_expected_flags` | El conjunto exacto de 15 flags | Coincide con el set esperado | Si falta o sobra alguno |
| `test_permission_groups_structure` | `PERMISSION_GROUPS` es lista de 2-tuplas | Lista con pares `(key, [perms])` | Si la estructura difiere |
| `test_permission_groups_cover_all_permissions` | Todos los 15 flags están en algún grupo | Unión de grupos == PERMISSIONS | Si alguno no está cubierto |
| `test_permission_groups_no_duplicates` | Ningún flag aparece en más de un grupo | Sin duplicados entre grupos | Si hay solapamiento |
| `test_permission_groups_keys` | Los 7 group keys están presentes | `perm_group_users` … `perm_group_checks` | Si falta alguna clave |
| `test_admin_has_all_permissions` | Role `admin` tiene los 15 permisos | `frozenset == set(PERMISSIONS)` | Si falta alguno |
| `test_editor_permissions` | Role `editor` tiene solo sus 4 permisos | `modules_edit`, `config_edit`, `checks_run`, `audit_view` | Si tiene de más o de menos |
| `test_viewer_has_no_permissions` | Role `viewer` sin permisos | `frozenset()` vacío | Si tiene alguno |
| `test_builtin_roles_are_frozensets` | Los 3 roles integrados son `frozenset` | Tipo correcto | Si son otro tipo |
| `test_get_role_permissions_admin` | `_get_role_permissions('admin')` | Devuelve todos los permisos | Si falta alguno |
| `test_get_role_permissions_viewer` | `_get_role_permissions('viewer')` | Devuelve `frozenset()` | Si devuelve algo |
| `test_get_role_permissions_unknown_role` | Rol inexistente | `frozenset()` vacío | Si lanza o devuelve algo |
| `test_get_role_permissions_custom_role` | Rol personalizado con permisos válidos | Devuelve los permisos asignados | Si difieren |
| `test_get_role_permissions_custom_role_filters_invalid` | Rol personalizado con flags inválidos | Los inválidos son ignorados | Si los incluye |
| `test_api_me_includes_permissions_list` | `GET /api/me` devuelve clave `permissions` | Lista presente en JSON | Si no está |
| `test_api_me_admin_has_all_permissions` | `/api/me` con sesión admin | Lista contiene los 15 flags | Si falta alguno |
| `test_api_me_viewer_has_no_permissions` | `/api/me` con sesión viewer | Lista vacía | Si contiene algo |
| `test_api_me_editor_permissions` | `/api/me` con sesión editor | Lista con 4 permisos de editor | Si difieren |
| `test_dashboard_exposes_permissions_list_js` | Dashboard renderiza `PERMISSIONS` como JS | Variable JS presente en HTML | Si no aparece |
| `test_dashboard_exposes_permission_groups` | Dashboard renderiza `PERMISSION_GROUPS` | Groups JS presente en HTML | Si no aparece |

### `TestCustomRoles`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_get_roles_requires_auth` | `GET /api/roles` sin autenticar | `302` | Si devuelve datos |
| `test_get_roles_returns_builtin_roles` | `GET /api/roles` devuelve `admin`, `editor`, `viewer` | Los 3 en la lista | Si falta alguno |
| `test_builtin_roles_are_marked` | Los roles integrados tienen `builtin: true` | Flag presente | Si no está marcado |
| `test_builtin_roles_have_permissions` | Los roles integrados tienen su `permissions` en la respuesta | Lista no vacía para admin/editor | Si falta |
| `test_create_custom_role` | `POST /api/roles` crea un rol | `201`, role en respuesta | Si es otro código |
| `test_create_role_appears_in_list` | Rol recién creado aparece en `GET /api/roles` | Presente en lista | Si no aparece |
| `test_create_role_invalid_permissions_filtered` | Permisos inválidos ignorados al crear | Solo flags válidos guardados | Si guarda inválidos |
| `test_create_role_missing_name` | `POST /api/roles` sin campo `name` | `400` | Si crea o devuelve 201 |
| `test_create_role_duplicate_name` | Crear rol con nombre ya existente | `409` | Si lo sobreescribe |
| `test_create_role_name_clashes_with_builtin` | Nombre coincide con `admin`/`editor`/`viewer` | `409` | Si lo crea |
| `test_create_role_name_normalised` | Nombre con mayúsculas y espacios | Se normaliza a lowercase + guiones | Si lo guarda tal cual |
| `test_update_custom_role_label` | `PUT /api/roles/<name>` cambia la etiqueta | `200`, etiqueta actualizada | Si es otro código |
| `test_update_custom_role_permissions` | `PUT /api/roles/<name>` cambia permisos | `200`, permisos actualizados | Si no cambian |
| `test_cannot_update_builtin_role` | Intentar editar rol integrado | `403` | Si lo modifica |
| `test_update_nonexistent_role` | `PUT /api/roles/fantasma` | `404` | Si devuelve otro código |
| `test_delete_custom_role` | `DELETE /api/roles/<name>` elimina el rol | `200`, no aparece en lista | Si persiste |
| `test_cannot_delete_builtin_role` | Eliminar rol integrado | `403` | Si lo elimina |
| `test_cannot_delete_role_in_use` | Eliminar rol asignado a un usuario | `409` | Si lo elimina |
| `test_delete_nonexistent_role` | `DELETE /api/roles/fantasma` | `404` | Si devuelve otro código |
| `test_roles_persisted_to_db` | Rol creado se guarda en la BD (`_roles_store`) | La BD contiene el nuevo rol | Si no persiste |
| `test_custom_role_accepted_for_user_creation` | Crear usuario con rol personalizado | `201`, rol asignado | Si rechaza el rol |
| `test_custom_role_audited_on_create` | Crear rol genera evento de auditoría | Evento `role_created` en log | Si no se audita |
| `test_custom_role_audited_on_update` | Editar rol genera evento de auditoría | Evento `role_updated` en log | Si no se audita |
| `test_custom_role_audited_on_delete` | Eliminar rol genera evento de auditoría | Evento `role_deleted` en log | Si no se audita |

### `TestGranularPermissions`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_users_view_allows_get_users` | `users_view` → `GET /api/users` | `200` | Si es `403` |
| `test_without_users_view_get_users_403` | Sin `users_view` → `GET /api/users` | `403` | Si devuelve datos |
| `test_users_add_allows_create_user` | `users_add` → `POST /api/users` | `201` | Si es `403` |
| `test_without_users_add_create_user_403` | Sin `users_add` → `POST /api/users` | `403` | Si crea usuario |
| `test_users_edit_allows_update_user` | `users_edit` → `PUT /api/users/<n>` | `200` | Si es `403` |
| `test_without_users_edit_update_user_403` | Sin `users_edit` → `PUT /api/users/<n>` | `403` | Si actualiza |
| `test_users_delete_allows_delete_user` | `users_delete` → `DELETE /api/users/<n>` | `200` | Si es `403` |
| `test_without_users_delete_delete_user_403` | Sin `users_delete` → `DELETE /api/users/<n>` | `403` | Si elimina |
| `test_roles_add_allows_create_role` | `roles_add` → `POST /api/roles` | `201` | Si es `403` |
| `test_without_roles_add_create_role_403` | Sin `roles_add` → `POST /api/roles` | `403` | Si crea rol |
| `test_roles_edit_allows_update_role` | `roles_edit` → `PUT /api/roles/<n>` | `200` | Si es `403` |
| `test_without_roles_edit_update_role_403` | Sin `roles_edit` → `PUT /api/roles/<n>` | `403` | Si actualiza |
| `test_roles_delete_allows_delete_role` | `roles_delete` → `DELETE /api/roles/<n>` | `200` | Si es `403` |
| `test_without_roles_delete_delete_role_403` | Sin `roles_delete` → `DELETE /api/roles/<n>` | `403` | Si elimina |
| `test_audit_view_allows_get_audit` | `audit_view` → `GET /api/audit` | `200` | Si es `403` |
| `test_without_audit_view_get_audit_403` | Sin `audit_view` → `GET /api/audit` | `403` | Si devuelve datos |
| `test_audit_delete_allows_clear` | `audit_delete` → `DELETE /api/audit` | `200` | Si es `403` |
| `test_without_audit_delete_clear_403` | Sin `audit_delete` → `DELETE /api/audit` | `403` | Si borra |
| `test_audit_delete_allows_delete_entry` | `audit_delete` → `DELETE /api/audit/<idx>` | `200/404` | Si es `403` |
| `test_without_audit_delete_delete_entry_403` | Sin `audit_delete` → `DELETE /api/audit/<idx>` | `403` | Si borra |
| `test_sessions_view_allows_get_sessions` | `sessions_view` → `GET /api/sessions` | `200` | Si es `403` |
| `test_without_sessions_view_get_sessions_403` | Sin `sessions_view` → `GET /api/sessions` | `403` | Si devuelve datos |
| `test_sessions_revoke_allows_invalidate` | `sessions_revoke` → `POST /api/sessions/invalidate` | `200` | Si es `403` |
| `test_without_sessions_revoke_invalidate_403` | Sin `sessions_revoke` → `POST /api/sessions/invalidate` | `403` | Si revoca |
| `test_sessions_revoke_allows_revoke_user` | `sessions_revoke` → `POST /api/sessions/revoke-user/<u>` | `200` | Si es `403` |
| `test_modules_edit_allows_put` | `modules_edit` → `PUT /api/modules` | `200` | Si es `403` |
| `test_without_modules_edit_put_403` | Sin `modules_edit` → `PUT /api/modules` | `403` | Si guarda |
| `test_config_edit_allows_put` | `config_edit` → `PUT /api/config` | `200` | Si es `403` |
| `test_without_config_edit_put_403` | Sin `config_edit` → `PUT /api/config` | `403` | Si guarda |
| `test_config_edit_allows_telegram_test` | `config_edit` → `POST /api/telegram/test` | `200/5xx` (no `403`) | Si devuelve `403` |
| `test_without_config_edit_telegram_test_403` | Sin `config_edit` → `POST /api/telegram/test` | `403` | Si ejecuta |
| `test_checks_run_allows_post` | `checks_run` → `POST /api/checks/run` | `200` | Si es `403` |
| `test_without_checks_run_post_403` | Sin `checks_run` → `POST /api/checks/run` | `403` | Si ejecuta |
| `test_custom_role_user_gets_correct_perms` | Usuario con rol personalizado recibe sus permisos en `/api/me` | Lista correcta | Si difiere |
| `test_custom_role_user_respects_allowed_endpoint` | Usuario con `modules_edit` puede hacer `PUT /api/modules` | `200` | Si es `403` |
| `test_custom_role_user_respects_denied_endpoint` | Usuario con `modules_edit` no puede `GET /api/users` (falta `users_view`) | `403` | Si devuelve `200` |

---

## 16b. Panel Web — Helpers JSON y validación de payloads

**Archivo:** `tests/test_wa_json_helpers.py`

Verifica que todos los endpoints JSON del web admin se comportan correctamente ante payloads malformados o extremos. Complementa las pruebas de seguridad de `test_wa_security.py`.

| Test | Qué verifica |
|------|-------------|
| `test_non_json_content_type` | 5 endpoints rechazan `text/plain` con 400 |
| `test_empty_body_json_endpoints` | 4 endpoints rechazan cuerpo vacío con 400 |
| `test_deeply_nested_json` | JSON 50 niveles → no crash (200 o 400) |
| `test_very_large_json_payload` | ~500 KB de JSON → no crash (200, 400 o 413) |
| `test_null_bytes_in_values` | Bytes nulos (`\x00`) en valores → 201 o 400 |
| `test_unicode_abuse` | RTL override, emoji, cadenas largas → 201, 400 o 409 |

> **`conftest.py` (tests/):** La fixture `admin` crea una instancia `WebAdmin` con credenciales `admin`/`secret` (los usuarios se guardan en la BD), siembra la configuración de módulos de ejemplo (`_SAMPLE_MODULES`) en el store de BD vía `_save_modules()`, y siembra en la tabla `check_state` el estado de ejemplo que esperan los tests (`ping/192.168.1.1` OK). La fixture `config_dir` escribe solo un `config.json` de prueba en un directorio temporal.

---

## 16c. Panel Web — Endpoint de acciones de watchfuls

**Archivo:** `tests/test_wa_watchfuls.py`

Verifica el endpoint `GET|POST /api/v1/modules/watchfuls/<module>/<action>` — autenticación, validación de entrada, despacho a classmethods y seguridad de importación.

### `TestApiWatchfulActionAuth`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_get_requires_auth` | GET sin sesión | Redirección 302 | Si devuelve 200 |
| `test_post_requires_auth` | POST sin sesión | Redirección 302 | Si devuelve 200 |

### `TestApiWatchfulActionValidation`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_invalid_module_name_uppercase` | Nombre de módulo en mayúsculas | 400 con `error` en JSON | Si pasa la validación |
| `test_invalid_module_name_with_dash` | Nombre de módulo con guión | 400 | Si pasa |
| `test_invalid_action_name_uppercase` | Nombre de acción en mayúsculas | 400 | Si pasa |
| `test_invalid_action_name_with_dash` | Nombre de acción con guión | 400 | Si pasa |
| `test_no_modules_dir_returns_404` | Sin `modules_dir` configurado | 404 antes de importar | Si importa |

### `TestApiWatchfulActionDispatch`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_unknown_module_returns_404` | Módulo inexistente | 404 | Si lanza ImportError |
| `test_action_not_in_watchful_actions_returns_404` | Acción real pero fuera de `WATCHFUL_ACTIONS` | 404 con `"Action not supported"` | Si ejecuta la acción |
| `test_get_discover_filesystemusage` | GET `discover` en `filesystemusage` | 200 con lista de particiones | Si falla el despacho |
| `test_post_test_connection_datastore` | POST `test_connection` en `datastore` | 200 con `ok=True` | Si falla el despacho |
| `test_post_list_databases_datastore` | POST `list_databases` devuelve `items` (no `databases`) | 200 con clave `items` | Si devuelve clave incorrecta |
| `test_action_exception_returns_500` | Acción lanza `RuntimeError` | 500 con `ok=False` y mensaje de error | Si propaga la excepción |
| `test_post_empty_body_passes_empty_dict` | POST sin cuerpo llama a la acción con `{}` | Config capturado = `{}` | Si pasa `None` |
| `test_get_discover_service_status` | GET `discover` en `service_status` | 200 con lista de servicios | Si falla el despacho |

### `TestApiWatchfulActionSecurity`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_stdlib_module_names_return_404` | Nombres stdlib (`os`, `sys`, `re`, …) → 404 sin importar el módulo stdlib | 404 para cada nombre | Si importa o devuelve otro código |
| `test_third_party_package_names_return_404` | Paquetes de terceros (`flask`, `psutil`, …) → 404 | 404 para cada nombre | Si importa el paquete real |
| `test_private_and_base_methods_blocked_by_whitelist` | Métodos reales del base class (`check`, `get_conf`, …) → bloqueados por whitelist | 404 para cada método | Si se ejecuta el método |
| `test_dunder_method_names_blocked_by_validation` | Nombres `__init__`, `_private`, `__class__` → rechazados por regex | 400 | Si pasan la validación |
| `test_numeric_leading_module_name_rejected` | Nombre comenzando con dígito (`1ping`) | 400 | Si pasa |
| `test_long_action_name_not_in_whitelist_returns_404` | Acción de 200 chars válida según regex pero no en whitelist | 404 | Si ejecuta |
| `test_enc_prefix_in_post_body_does_not_crash` | Valor `enc:attacker-payload` en POST body | 200, valor pasado tal cual al classmethod | Si lanza o descifra |
| `test_unauthenticated_user_cannot_call_any_action` | GET y POST sin sesión en múltiples rutas | 302 en todas | Si alguna responde sin login |

### `TestMergeHostConn`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_fills_address_and_ssh` | La dirección del host rellena `host`+`ssh_host`; user/password SSH copiados | Campos rellenados desde el host | Si no fusiona |
| `test_explicit_check_value_wins` | Un `host` explícito del check gana sobre la dirección del host | Valor del check conservado | Si lo pisa |

### `TestResolveHostCtxCred`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_ssh_cred_uid_is_resolved` | `cred_uid` resuelve `ssh_user`/`password` | user='svc', password='secret', `ssh_port` preservado | Si no resuelve |
| `test_no_cred_uid_left_unchanged` | Sin `cred_uid`, valores inline intactos | `ssh_user='root'` preservado | Si lo altera |

### `TestApiWatchfulActionAuthorization`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_viewer_cannot_run_write_action` | Viewer ejecuta acción de escritura (`delete_mib`) | 403 | Si ejecuta |
| `test_viewer_can_run_read_only_action` | Viewer ejecuta acción de solo lectura (`list_mibs`) | 200 | Si es 403 |
| `test_admin_can_run_write_action` | Admin ejecuta acción de escritura | ≠ 403 | Si es 403 |

### `TestWatchfulSecretFieldsProtected`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_core_does_not_hardcode_module_secrets` | Los secretos de módulo no están hardcodeados en `ENCRYPT_KEYS` | Campos snmpv3/auth ausentes de `ENCRYPT_KEYS` | Si están hardcodeados |
| `test_secrets_discovered_from_module_schemas` | `discover_secret_fields` descubre los secretos desde los schemas | Encuentra los tres campos secretos | Si falta alguno |
| `test_discovered_secrets_masked` | `mask_sensitive` enmascara los secretos descubiertos | Los tres campos a `None` | Si los deja en claro |
| `test_wa_secret_keys_includes_module_secrets` | `GET /modules` enmascara los secretos de módulo | `snmpv3_auth_key` enmascarado (`None`/`''`) | Si aparece en claro |

### `TestSsrfGuard`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_file_scheme_blocked` | Esquema `file://` bloqueado | Rechazado (no `None`) | Si lo permite |
| `test_metadata_ip_blocked` | IP de metadatos `169.254.169.254` bloqueada | Rechazada (no `None`) | Si la permite |
| `test_normal_http_allowed` | `example.com` permitido | `None` (permitido) | Si lo bloquea |
| `test_private_host_allowed_for_monitoring` | Host privado `192.168.x` permitido para monitorización | `None` (permitido) | Si lo bloquea |

### `TestHostAwareDiscovery`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_process_discover_remote_draft` | `discover` remoto de `process` | 200; nombres incluyen nginx/sshd; ejecuta `ps -A -o comm=` | Si falla |
| `test_service_discover_remote_draft` | `discover` remoto de `service_status` | 200; un servicio "nginx" presente | Si falla |

---

## 16d. Panel Web — Matriz de permisos por endpoint

**Archivo:** `tests/test_wa_permissions.py`

Cobertura de la matriz de acceso completa: para cada endpoint protegido por permiso se comprueba el acceso de los 4 roles integrados (`admin` / `editor` / `viewer` / `none`). Las expectativas se derivan de `BUILTIN_ROLE_PERMISSIONS`/`BUILTIN_ROLE_UIDS` (`lib/web_admin/constants`), con semántica *any-of* sobre el/los permiso(s) requerido(s) por endpoint. La tabla recorre rutas `/api/v1/*` de usuarios, roles, grupos, checks/estado, overview, config, sesiones, audit, history y hosts (servidores).

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_unauthenticated_is_blocked[<ep>]` | Llamada sin autenticar a cada endpoint protegido | `401` o `403` (nunca 2xx) | Si responde con éxito |
| `test_permission_matrix[<role>-<ep>]` | Un rol accede si y solo si tiene uno de los permisos requeridos | Rol con permiso → ≠ `403`; rol sin permiso → `403` | Si la puerta no se abre/cierra como debe |
| `test_matrix_covers_all_crud_actions` | La tabla ejercita view/add/edit/delete (`GET`/`POST`/`PUT`/`DELETE`) | Los 4 métodos presentes | Si falta alguno |

> Las fixtures crean los usuarios `editor`/`viewer`/`none` en `admin._users` y los persisten en la BD vía `admin._persist_users()`; el host de prueba se crea con `admin._hosts_store.create(...)` (registro de hosts en BD).

---

## 17. Watchful: filesystemusage

**Archivo:** `watchfuls/filesystemusage/tests/test_filesystemusage.py`

### `TestParsers` — Parseo de salida de disco

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_df_by_mount` | `_parse_df` calcula el % de uso por montaje y por dispositivo | Uso correcto; `None` si no aparece | Si el parseo falla |
| `test_wmic` | `_parse_wmic` calcula el % de uso desde `FreeSpace`/`Size` (Windows) | Uso correcto para `C:`/`D:` | Si difiere |

### `TestCheck` — Ejecución del check

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_ok_below_threshold` | Uso por debajo del umbral | `status = True`, `other_data.used == 75`, mount `/` | Si es `False` |
| `test_alert_above_threshold` | Uso por encima del umbral (90 > 85) | `status = False`, mensaje con "Warning" | Si es `True` |
| `test_windows_host_uses_wmic` | Host Windows usa `wmic` | Comando incluye `wmic`; `status = True`, `used == 75` | Si usa otro comando |
| `test_message_uses_label_to_identify_server` | El label identifica el servidor en el mensaje | "NS1 - /" aparece en el mensaje | Si no aparece |
| `test_same_mount_distinct_items_do_not_collide` | Mismo mount en dos ítems distintos | Claves distintas (uid-a, uid-b), sin colisión | Si colisionan |
| `test_partition_not_found_is_error` | Partición inexistente | `status = False`, mensaje con "Error" | Si es `True` |
| `test_disabled_and_maintenance_skipped` | Ítem deshabilitado + host en mantenimiento | Sin ítems, `host_exec` no invocado | Si procesa |

### `TestDiscover` — Descubrimiento de particiones

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_discover_remote_df` | Descubrimiento remoto ejecuta `df -P -k` | Nombres incluyen `/` y `/data` | Si falla el descubrimiento |
| `test_discover_local` | Descubrimiento local vía psutil | Devuelve el nombre `/` | Si no aparece |

---

## 18. Watchful: hddtemp

**Archivo:** `watchfuls/hddtemp/tests/test_hddtemp.py`

### `TestHddtempInfo`, `TestHddtempWatchfulInit`, `TestHddtempCheck`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_parse_hddtemp_output` | Parseo de la salida del comando `hddtemp` | Discos y temperaturas correctas | Si el parseo falla |
| `test_parse_empty_output` | Salida vacía | Dict vacío sin excepción | Si lanza |
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_check_ok` | Temperatura por debajo del umbral | `status = True` | Si es `False` |
| `test_check_alert` | Temperatura igual o superior al umbral | `status = False` | Si es `True` |
| `test_check_excluded_disk` | Disco en lista `exclude` | No aparece en el resultado | Si aparece |
| `test_check_disabled` | Módulo deshabilitado en config | No procesa ningún disco | Si procesa |

---

## 19. Watchful: datastore

**Archivo:** `watchfuls/datastore/tests/test_datastore.py`

### `TestDatastoreSchema`

| Test | Qué comprueba | OK | Error |
| ---- | ------------- | -- | ----- |
| `test_item_schema_loaded` | Esquema cargado correctamente | `ITEM_SCHEMA` no nulo, contiene `list` | Si no carga |
| `test_defaults_from_schema` | Defaults extraídos del esquema | `db_type` = `mysql` | Si difiere |
| `test_all_schema_fields_have_type_and_default` | Todos los campos tienen `type` y `default` | Sin excepción | Si falta alguno |

### `TestDatastoreInit`, `TestDatastoreCheck`

| Test | Qué comprueba | OK | Error |
| ---- | ------------- | -- | ----- |
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_empty_list` | Lista vacía | Resultado vacío | Si lanza |
| `test_disabled_item_skipped` | Ítem con `enabled: false` | Omitido del resultado | Si aparece |
| `test_check_ok` | `_ds_check` llamado para ítem habilitado | Mock invocado una vez | Si no se llama |
| `test_check_exception_sets_error` | Excepción en `_ds_check` | `status = False` | Si propaga |

### `TestBackendDispatch`

| Test | Qué comprueba | OK | Error |
| ---- | ------------- | -- | ----- |
| `test_unknown_db_type` | `db_type` desconocido | `ok = False`, mensaje con el nombre | Si devuelve `True` |
| `test_ssh_unavailable_returns_error` | `paramiko` no instalado | `ok = False`, menciona `paramiko` | Si no lo menciona |

### `TestMysqlBackend`, `TestPostgresBackend`, `TestMssqlBackend`, `TestMongoBackend`, `TestRedisBackend`, `TestMemcachedBackend`

| Test | Qué comprueba | OK | Error |
| ---- | ------------- | -- | ----- |
| `test_success` (MySQL) | Conexión MySQL simulada OK | `ok = True` | Si es `False` |
| `test_access_denied` (MySQL) | Error 1045 (credenciales) | `ok = False`, `Access denied` | Si no coincide |
| `test_socket_missing_path` (MySQL) | Socket inexistente | `ok = False`, `Socket` en msg | Si no |
| `test_driver_missing` (PostgreSQL) | `psycopg2` no instalado | `ok = False`, `psycopg2` en msg | Si no |
| `test_mssql_msg_tuple_arg` | Excepción pymssql como `Error((code, bytes))` | Mensaje limpio | Si devuelve raw |
| `test_mssql_msg_two_args` | Excepción pymssql como `Error(code, bytes)` | Mensaje limpio | Si devuelve raw |
| `test_mssql_msg_conn_refused` | Código 20002 = sin conexión | `Connection failed…` | Si no coincide |
| `test_driver_missing` (MSSQL) | `pymssql` no instalado | `ok = False`, `pymssql` en msg | Si no |
| `test_driver_missing` (MongoDB) | `pymongo` no instalado | `ok = False`, `pymongo` en msg | Si no |
| `test_driver_missing` (Redis) | `redis` no instalado | `ok = False`, `redis` en msg | Si no |
| `test_driver_missing` (Memcached) | `pymemcache` no instalado | `ok = False`, `pymemcache` en msg | Si no |

### `TestElasticsearchBackend`, `TestInfluxdbBackend`

| Test | Qué comprueba | OK | Error |
| ---- | ------------- | -- | ----- |
| `test_cluster_status_red` | Estado del clúster `red` | `ok = False`, `RED` en msg | Si no |
| `test_cluster_status_green` | Estado del clúster `green` | `ok = True` | Si es `False` |
| `test_health_pass` | `/health` devuelve `status: pass` | `ok = True` | Si es `False` |
| `test_health_fail` | `/health` devuelve `status: fail` | `ok = False`, `fail` en msg | Si no |

### `TestTestConnection`, `TestListDatabases`

| Test | Qué comprueba | OK | Error |
| ---- | ------------- | -- | ----- |
| `test_routes_to_mysql` | `db_type: mysql` llama `_test_mysql` | Mock invocado | Si no |
| `test_routes_to_postgres` | `db_type: postgres` llama `_test_postgres` | Mock invocado | Si no |
| `test_default_port_applied` | `port: 0` aplica el puerto por defecto del motor | Puerto correcto | Si usa 0 |
| `test_ssh_only_mode` | `_test_mode: ssh` llama `_test_ssh_only` | Mock invocado | Si no |
| `test_mysql_returns_databases` | Lista de BBs MySQL simulada | `databases = [a, b]` | Si difiere |
| `test_unsupported_type_returns_error` | Motor sin soporte de listado (Redis) | `ok = False`, `databases = []` | Si devuelve lista |
| `test_memcached_not_supported` | Memcached sin listado | `ok = False` | Si devuelve datos |

### `TestSshKeyString`, `TestSshVerifyHostBool`

| Test | Qué comprueba | OK | Error |
| ---- | ------------- | -- | ----- |
| `test_pkey_from_string_invalid_raises` | `_pkey_from_string` con texto inválido | Lanza `ValueError` (skip sin paramiko) | Si no lanza |
| `test_pkey_from_string_parses_generated_key` | Clave RSA generada round-trip | Fingerprint coincide (skip sin paramiko) | Si difiere |
| `test_build_cfg_includes_key_string` | `_build_cfg` incluye la clave | `ssh_key_string` empieza con `-----BEGIN` | Si falta |
| `test_absent_is_false` | `ssh_verify_host` ausente | `_build_cfg` devuelve `False` | Si difiere |
| `test_explicit_false_stays_false` | `ssh_verify_host` explícito `False` | `False` | Si difiere |
| `test_explicit_true_stays_true` | `ssh_verify_host` explícito `True` | `True` | Si difiere |

---

## 20. Watchful: ping

**Archivo:** `watchfuls/ping/tests/test_ping.py`

### `TestPingInit`, `TestPingCheck`, `TestPingConfigOptions`, `TestIcmpNative`, `TestDefaults`, `TestAlertThreshold`, `TestEmojiMessages`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_check_empty_list` | Lista vacía | Resultado vacío | Si lanza |
| `test_check_disabled_host` | Host con `enabled: false` | Omitido | Si aparece |
| `test_check_host_ok` | Ping exitoso simulado | `status = True` | Si es `False` |
| `test_check_host_ko` | Ping fallido simulado | `status = False` | Si es `True` |
| `test_check_multiple_hosts` | Múltiples hosts | Resultado con todos los hosts | Si falta alguno |
| `test_icmp_checksum_zero_bytes` | Checksum de bytes vacíos | `0` | Si difiere |
| `test_icmp_checksum_known_value` | Checksum de bytes conocidos | Valor esperado | Si difiere |
| `test_build_icmp_packet_length` | Paquete ICMP tiene longitud correcta | 64 bytes | Si difiere |
| `test_build_icmp_packet_checksum_valid` | Checksum del paquete es válido | Verificación positiva | Si es inválido |
| `test_icmp_ping_unresolvable_host` | Hostname no resolvible | Devuelve `False` sin excepción | Si lanza |
| `test_defaults_extracted_from_schema` | Defaults tomados de `ITEM_SCHEMA` | Valores correctos | Si usan valores hardcodeados |
| `test_no_legacy_default_attributes` | No hay atributos de default legacy en la clase | No existen | Si existen |
| `test_alert_default_is_1` | Alert threshold por defecto es 1 | `1` | Si difiere |
| `test_alert_2_needs_two_failures` | Con threshold 2, primer fallo no alerta | `status = True` (no alerta aún) | Si alerta en el primero |
| `test_alert_resets_on_success` | Contador de fallos se resetea al recuperarse | Después de éxito, vuelve a requerir `threshold` fallos | Si no resetea |
| `test_success_message_contains_up_emoji` | Mensaje de éxito contiene emoji ✅ | Emoji presente | Si no está |
| `test_failure_message_contains_down_emoji` | Mensaje de fallo contiene emoji de caída | Emoji presente | Si no está |

### `TestPingGetConf`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_get_conf_none_raises_value_error` | `_get_conf(None, ...)` | `ValueError` "can not be None" | Si no lanza |
| `test_get_conf_invalid_option_raises_type_error` | Opción IntEnum desconocida | `TypeError` "is not valid option" | Si no lanza |

---

## 21. Watchful: raid

**Archivo:** `watchfuls/raid/tests/test_raid.py` y `test_raid_mdstat.py`

### `TestParseLines` (`test_raid.py`) — Parseo de `/proc/mdstat`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_ok` | Array activo | `md0` con `UpdateStatus.ok` | Si difiere |
| `test_degraded` | Array degradado | `md0` con `UpdateStatus.error` | Si difiere |
| `test_recovery` | Array en reconstrucción | `update = recovery`, porcentaje 12.6 | Si difiere |
| `test_empty` | Salida vacía | Devuelve `{}` | Si lanza |
| `test_accepts_list_of_lines` | Acepta lista de líneas (`splitlines`) | `md0` presente | Si falla |

### `TestRaidDefaults` (`test_raid.py`) — Defaults y schema

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_module_defaults` | Defaults del módulo | `threads=5`, `timeout=30`, `mdstat_path=/proc/mdstat` | Si difieren |
| `test_schema_is_host_centric` | Schema host-céntrico | `__host_profile__` con clave `ssh`; sin `local`/`host` inline | Si difiere |

### `TestRaidCheck` (`test_raid.py`) — Ejecución del check

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_raid_ok` | RAID en buen estado | `1_md0` `status = True`, mensaje "good status" | Si es `False` |
| `test_raid_degraded` | RAID degradado | `1_md0` `status = False`, mensaje "degraded" | Si es `True` |
| `test_raid_recovery` | RAID en reconstrucción | `status = False`, mensaje "recovery", porcentaje 12.6 | Si es `True` |
| `test_no_raids` | Sin arrays RAID | `1` `status = True`, mensaje "No RAID" | Si es `False` |
| `test_disabled_item_skipped` | Ítem deshabilitado | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_non_linux_host_reports_unsupported` | Host no-Linux | `host_exec` no invocado; `status = False`, mensaje "Linux" | Si ejecuta |
| `test_maintenance_host_skipped` | Host en mantenimiento | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_command_failure_is_error` | Fallo del comando | `status = False`, mensaje "Error" | Si es `True` |
| `test_module_disabled` | Módulo deshabilitado | Sin ítems, `host_exec` no invocado | Si procesa |

### `TestRaidLabel` (`test_raid.py`) — Etiqueta del array

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_label_from_item` | `_label('1')` con label configurado | Devuelve "MyServer" | Si difiere |
| `test_label_falls_back_to_key` | `_label` sin label | Devuelve la clave | Si difiere |

### `TestRaidMdstatInit`, `TestRaidMdstatValidateRemote`, `TestRaidMdstatIsExistLocal`, `TestRaidMdstatIsExistRemote` (`test_raid_mdstat.py`)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_default_init` | Init por defecto | `is_remote=False`, path `/proc/mdstat` | Si difiere |
| `test_custom_path` | Path de mdstat personalizado | Path almacenado | Si difiere |
| `test_remote_init` | Init remoto con host/port/user/password | `is_remote=True` | Si difiere |
| `test_not_remote_without_host` | Sin host | `is_remote=False` | Si es `True` |
| `test_remote_with_key_file` | Remoto con `key_file` | `is_remote=True`, `_key_file` fijado | Si difiere |
| `test_key_file_default_none` | `_key_file` por defecto | `None` | Si difiere |
| `test_valid_remote` | `validate_remote` con config completa | `True` | Si es `False` |
| `test_invalid_port_zero` | Puerto 0 | `validate_remote = False` | Si es `True` |
| `test_invalid_no_user` | Usuario vacío | `validate_remote = False` | Si es `True` |
| `test_invalid_empty_host` | Host en blanco | `validate_remote = False` | Si es `True` |
| `test_exist_local` | `is_exist` local | `True`; `isfile` llamado con el path | Si difiere |
| `test_not_exist_local` | Archivo local ausente | `is_exist = False` | Si es `True` |
| `test_exist_remote` | `is_exist` remoto (salida "exists") | `True` | Si es `False` |
| `test_not_exist_remote` | Salida remota vacía | `is_exist = False` | Si es `True` |
| `test_remote_stderr_returns_false` | Remoto con stderr | `is_exist = False` | Si es `True` |
| `test_remote_invalid_config_returns_false` | Config remota inválida | `is_exist = False` | Si es `True` |

### `TestRaidMdstatReadStatusLocal`, `TestRaidMdstatReadStatusRemote`, `TestUpdateStatusEnum` (`test_raid_mdstat.py`)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_read_ok` | Lectura local OK | `md0` presente, `update = ok` | Si difiere |
| `test_read_degraded` | Lectura local degradado | `md0` `update = error` | Si difiere |
| `test_read_recovery` | Lectura local en recuperación | `md0` recovery, porcentaje 5.2 | Si difiere |
| `test_read_not_exist` | Archivo ausente | `read_status` devuelve `{}` | Si lanza |
| `test_read_empty` | mdstat vacío | `read_status` devuelve `{}` | Si difiere |
| `test_read_multiple_raids` | Varios arrays | `md0` y `md1` ambos ok | Si falta alguno |
| `test_read_remote_ok` | Lectura remota (2 llamadas SSH) | `md0` `update = ok` | Si difiere |
| `test_read_remote_stderr_raises` | Remoto con stderr | Lanza excepción con "ERROR" | Si no lanza |
| `test_values` | Valores del enum `UpdateStatus` | `unknown=0, ok=1, error=2, recovery=3` | Si difieren |
| `test_is_intenum` | `UpdateStatus` es `IntEnum` | Comparaciones de orden válidas | Si falla |

### `TestRaidMdstatReadLines`, `TestRaidMdstatIsExistRemoteStdexcept`, `TestRaidMdstatRemoteStderrRaises`, `TestRaidMdstatRecoveryParsing` (`test_raid_mdstat.py`)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_read_lines_local` | `_read_lines` local | Línea con "md0" | Si falla |
| `test_read_lines_remote_ok` | `_read_lines` remoto OK | Línea con "md0" | Si falla |
| `test_read_lines_remote_stderr_raises_oserror` | stderr remoto | Lanza `OSError` "REMOTE ERROR" | Si no lanza |
| `test_read_lines_remote_stdexcept_raises_runtime` | Excepción remota | Lanza `RuntimeError` "REMOTE EXCEPTION" | Si no lanza |
| `test_read_lines_remote_invalid_config_raises_valueerror` | Config remota inválida | Lanza `ValueError` "Remote config not valid" | Si no lanza |
| `test_remote_stdexcept_returns_false` | `is_exist` con excepción | `False` | Si es `True` |
| `test_read_remote_stdexcept_raises` | `read_status` con excepción en 2ª llamada | Lanza `RuntimeError` "REMOTE EXCEPTION" | Si no lanza |
| `test_recovery_details` | Parseo de línea de recuperación | Porcentaje 5.2, finish "200.5min", speed "150000K/sec", blocks es lista | Si el parseo falla |
| `test_recovery_malformed_falls_back_empty` | Línea de recuperación malformada | `update = recovery` pero dict `{}` | Si lanza |

---

## 22. Watchful: ram\_swap

**Archivo:** `watchfuls/ram_swap/tests/test_ram_swap.py`

### `TestParsers` — Parseo por SO

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_linux` | `_parse_linux` | RAM 75.0, swap 25.0 | Si difiere |
| `test_linux_no_swap` | Linux sin swap | RAM 75.0, swap 0.0 | Si difiere |
| `test_windows` | `_parse_windows` | RAM 75.0, swap `None` | Si difiere |
| `test_darwin` | `_parse_darwin` (macOS) | RAM entre 70-80, swap 25.0 | Si difiere |
| `test_commands_are_allowlist_friendly` | Comandos sin encadenado de shell | Sin tokens de chaining en `_MEM_CMDS` | Si los hay |

### `TestCheck` — Ejecución del check

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_normal_usage` | Uso normal | `srv_ram`/`srv_swap` `status = True`, used 75.0, nombres "srv - RAM"/"srv - SWAP" | Si difiere |
| `test_high_ram_triggers_alert` | RAM sobre el umbral (75 ≥ 60) | `srv_ram` `status = False`, mensaje "Excessive" | Si es `True` |
| `test_windows_reports_ram_only` | Windows | Comando con `wmic`; `srv_ram` presente, `srv_swap` ausente | Si difiere |
| `test_unsupported_os` | SO no soportado | `host_exec` no invocado; `status = False`, mensaje "unsupported" | Si ejecuta |
| `test_disabled_item_skipped` | Ítem deshabilitado | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_maintenance_host_skipped` | Host en mantenimiento | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_command_failure_is_error` | Fallo del comando | `status = False`, mensaje "Error" | Si es `True` |
| `test_invalid_threshold_uses_default` | Umbral inválido/fuera de rango | `_alert` cae al default, parsea "80" | Si no aplica el default |

---

## 23. Watchful: service\_status

**Archivo:** `watchfuls/service_status/tests/test_service_status.py`

### `TestParseState` — Parseo de estado por SO

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_linux_active` | systemd activo | `(True, False, 'running')` | Si difiere |
| `test_linux_inactive` | systemd inactivo | running `False`, error `False` | Si difiere |
| `test_linux_failed` | systemd fallido | running `False`, error `False`, detalle "failed" | Si difiere |
| `test_linux_missing_is_error` | Unidad inexistente (exit 127) | running `False`, error `True` | Si difiere |
| `test_windows_running` | `SC RUNNING` | running `True` | Si es `False` |
| `test_windows_stopped` | Servicio Windows detenido | running `False`, error `False`, detalle "stopped" | Si difiere |
| `test_windows_missing_is_error` | Servicio Windows ausente (1060) | running `False`, error `True` | Si difiere |
| `test_darwin_running` | `launchctl` con PID | running `True` | Si es `False` |
| `test_freebsd_running` | FreeBSD "is running" | running `True` | Si es `False` |
| `test_freebsd_stopped` | FreeBSD "is not running" | running `False` | Si es `True` |

### `TestCheck` — Ejecución del check

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_running_ok` | Servicio corriendo | `status = True`, mensaje "Running" | Si es `False` |
| `test_expected_stopped_ok` | Esperado detenido y detenido | `status = True`, mensaje "Stopped" | Si es `False` |
| `test_running_but_expected_stopped` | Corriendo pero esperado detenido | `status = False`, mensaje "expected: Stopped" | Si es `True` |
| `test_windows_host_uses_sc` | Host Windows | Comando empieza "sc query"; `status = True` | Si difiere |
| `test_remediation_recovers` | Remediación (incluye "start") | 3 llamadas `host_exec`; `status = True`, remediación `True` | Si no recupera |
| `test_unsupported_os` | SO no soportado | `host_exec` no invocado; `status = False`, mensaje "unsupported" | Si ejecuta |
| `test_disabled_item_skipped` | Ítem deshabilitado | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_maintenance_host_skipped` | Host en mantenimiento | Sin ítems, `host_exec` no invocado | Si procesa |

### `TestDiscover` — Descubrimiento de servicios

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_parse_systemd_list` | Parseo de `systemctl list-units` | Nombres "nginx" y "cron" | Si falla |
| `test_parse_sc_query` | Parseo de `sc query` (Windows) | `{nginx: running, spooler: stopped}` | Si difiere |
| `test_remote_discovery_uses_ssh` | Descubrimiento remoto vía SSH | Ejecuta "systemctl list-units..."; "nginx" descubierto | Si falla |
| `test_clear_str` | `clear_str()` limpia paréntesis; `None`→`''` | Texto limpio | Si lanza |

---

## 24. Watchful: temperature

**Archivo:** `watchfuls/temperature/tests/test_temperature.py`

### `TestParser` — Parseo de sensores

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_parse_and_dedup` | Parseo y deduplicación de sensores | x86_pkg_temp 45.0, acpitz 39.5, duplicado → acpitz_1 41.0 | Si difiere |
| `test_command_is_allowlist_friendly` | `_THERMAL_CMD` empieza "grep " sin encadenado | Sin tokens de chaining | Si los hay |

### `TestCheck` — Ejecución del check

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_ok_below_threshold` | Temperatura bajo el umbral | `status = True`, temp 45.0 | Si es `False` |
| `test_over_threshold_warns` | Temperatura sobre el umbral | `status = False`, mensaje "Warning" | Si es `True` |
| `test_non_linux_unsupported` | Host no-Linux | `host_exec` no invocado; `status = False`, mensaje "Linux" | Si ejecuta |
| `test_sensor_not_found_is_error` | Sensor no encontrado | `status = False`, mensaje "Error" | Si es `True` |
| `test_disabled_and_maintenance_skipped` | Ítem deshabilitado + mantenimiento | Sin ítems, `host_exec` no invocado | Si procesa |

### `TestDiscover` — Descubrimiento de sensores

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_discover_remote` | Descubrimiento remoto | Nombres incluyen x86_pkg_temp, acpitz, acpitz_1 | Si falta alguno |

---

## 25. Watchful: web

**Archivo:** `watchfuls/web/tests/test_web.py`

### `TestWebInit`, `TestWebCheck`, `TestWebRequest`, `TestWebScheme`, `TestWebUrl`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_schema_has_server_and_port` | `ITEM_SCHEMA['list']` declara `server`/`port` (ya no `url`) | Campos presentes, `address_field='server'` | Si falta alguno |
| `test_check_empty_list` | Lista vacía | Resultado vacío | Si lanza |
| `test_check_disabled_url` | URL con `enabled: false` | Omitida del resultado | Si aparece |
| `test_check_url_ok` | HTTP 200 simulado | `status = True` | Si es `False` |
| `test_check_url_500` | HTTP 500 simulado | `status = False` | Si es `True` |
| `test_check_url_custom_code` | Código esperado personalizado (ej. 301) | `True` si coincide el código | Si no coincide |
| `test_check_url_404` | HTTP 404 sin código personalizado | `status = False` | Si es `True` |
| `test_check_multiple_urls` | Varias URLs | Cada una con su estado | Si se mezclan |
| `test_check_url_enabled_dict` | URL habilitada con config dict completa | Procesada correctamente | Si se salta |
| `test_check_url_string_value_uses_default_enabled` | URL con valor string (formato legacy) | Procesada con `enabled=True` por defecto | Si se omite |
| `test_successful_request` | Respuesta HTTP exitosa simulada | `code == 200`, sin excepción | Si difiere |
| `test_http_error_returns_code` | HTTP error code | Código de error devuelto | Si devuelve 0 |
| `test_url_error_returns_zero` | Fallo de red total | `code == 0` | Si lanza |
| `test_url_without_scheme_gets_https` | URL sin esquema → se añade `https://` | URL con `https://` | Si no se añade |
| `test_url_field_used_for_request` | Campo `url` del schema se usa para la petición | Petición a la URL del campo `url` | Si usa la clave |
| `test_backward_compat_key_as_url` | Sin campo `url` → se usa la clave como URL | Petición a la clave | Si lanza |
| `test_empty_url_falls_back_to_key` | Campo `url` vacío → se usa la clave | Petición a la clave | Si lanza |
| `test_label_used_in_message` | El label (no la URL) aparece en el mensaje | Label "Blog" en el mensaje de estado | Si aparece la URL |

---

## 26. Seguridad: secret\_manager

**Archivo:** `tests/test_secret_manager.py`

### `TestFernetFromSecretFile` — Generación de clave Fernet

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_returns_fernet_for_valid_file` | Archivo hex válido devuelve instancia Fernet | Objeto Fernet no nulo | Si devuelve `None` |
| `test_can_encrypt_and_decrypt_with_returned_fernet` | Cifrar y descifrar con la misma instancia | Texto descifrado igual al original | Si difiere |
| `test_returns_none_for_missing_file` | Archivo inexistente | Devuelve `None` sin lanzar | Si lanza |
| `test_returns_none_for_invalid_hex` | Contenido no es hex válido | Devuelve `None` | Si lanza o devuelve Fernet |
| `test_returns_none_for_empty_file` | Archivo vacío | Devuelve `None` | Si lanza |
| `test_two_instances_from_same_file_are_compatible` | Dos instancias del mismo archivo descifran mutuamente | Descifrado correcto | Si son incompatibles |

### `TestDecryptAll` — Descifrado de configuración

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_decrypts_valid_token` | Token `enc:` válido se descifra | Valor en texto claro | Si queda cifrado |
| `test_plain_string_unchanged` | Valor sin `enc:` no se altera | String intacto | Si se modifica |
| `test_malformed_enc_token_kept_as_is` | Token `enc:` inválido no rompe | String original preservado | Si lanza o devuelve vacío |
| `test_nested_dict_decrypted` | Dict anidado con token cifrado | Valor descifrado en la ruta anidada | Si no llega a la profundidad |
| `test_nested_list_decrypted` | Lista anidada con dicts cifrados | Todos los valores descifrados | Si se omite alguno |
| `test_none_fernet_does_not_crash` | `fernet=None` no lanza | Sin excepción, valores intactos | Si lanza |
| `test_non_string_values_unchanged` | Bool, int, float, None no se tocan | Tipos y valores idénticos | Si se alteran |
| `test_modifies_dict_in_place_and_returns_it` | Modifica el dict original y lo devuelve | `returned is data` y valor descifrado | Si devuelve copia |

### `TestEncryptSensitive` — Cifrado de campos sensibles

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_sensitive_key_encrypted` | Clave sensible se cifra | Valor empieza con `enc:` | Si queda en claro |
| `test_non_sensitive_key_unchanged` | Clave no sensible no se cifra | Valor intacto | Si se cifra |
| `test_all_encrypt_keys_are_encrypted` | Todas las claves de `ENCRYPT_KEYS` se cifran | Cada una comienza con `enc:` | Si alguna queda en claro |
| `test_already_encrypted_value_not_re_encrypted` | Valor ya con `enc:` no se vuelve a cifrar | Valor idéntico | Si se doble-cifra |
| `test_empty_string_not_encrypted` | String vacío no se cifra | `""` intacto | Si se cifra |
| `test_nested_dict_sensitive_fields_encrypted` | Dict anidado — campos sensibles cifrados, otros intactos | Solo `password` con `enc:` | Si se cifran campos no sensibles |
| `test_returns_new_dict_does_not_mutate_input` | No muta el dict de entrada | Original sin `enc:`, copia con `enc:` | Si muta el original |
| `test_none_fernet_returns_data_unchanged` | `fernet=None` devuelve datos sin cifrar | Valores intactos | Si lanza |
| `test_roundtrip_encrypt_then_decrypt` | Cifrar y descifrar da el valor original | Texto claro recuperado | Si difiere |
| `test_roundtrip_all_encrypt_keys` | Roundtrip completo sobre todas las claves de `ENCRYPT_KEYS` | Todos los valores recuperados | Si alguno difiere |

### `TestEncPrefixInjection` — Ataques de inyección con prefijo `enc:`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_injected_bad_enc_token_not_decrypted_to_garbage` | Token `enc:AAAA...` inválido no se decodifica a basura | String original preservado | Si devuelve valor incorrecto |
| `test_injected_enc_value_not_re_encrypted` | `enc:fake` en campo sensible pasa sin re-cifrar | Valor idéntico | Si se doble-cifra |
| `test_fake_enc_sibling_does_not_affect_legitimate_encryption` | Valor falso en un campo no corrompe el cifrado real de otro | Campo real cifrado y descifrado correctamente | Si el vecino falso interfiere |
| `test_enc_prefix_in_non_sensitive_key_never_decrypted` | `enc:` en clave no sensible no se descifra | Valor `enc:...` intacto en `decrypt_all` | Si se intenta descifrar |

---

## 27. Watchful: cpu

**Archivo:** `watchfuls/cpu/tests/test_cpu.py`

### `TestParsers` — Parseo por SO

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_proc_stat` | `_parse_proc_stat` (Linux) | `75.0` | Si difiere |
| `test_cp_time` | `_parse_cp_time` (BSD) | `75.0` | Si difiere |
| `test_windows` | `_parse_windows` | `42` | Si difiere |
| `test_darwin_uses_last_sample` | `_parse_darwin` usa la última muestra | `75.0` | Si difiere |
| `test_single_sample_is_none` | Muestra única | Devuelve `None` | Si difiere |
| `test_commands_are_allowlist_friendly` | `_cpu_cmd` sin encadenado por SO | Sin tokens de chaining | Si los hay |

### `TestCheck` — Ejecución del check

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_below_threshold_ok` | Uso bajo el umbral | `status = True`, used 75.0 | Si es `False` |
| `test_above_threshold_alert` | Uso sobre el umbral (75 ≥ 60) | `status = False`, mensaje "Excessive" | Si es `True` |
| `test_windows_host_uses_wmic` | Host Windows | Comando `wmic`; `status = True`, used 42.0 | Si difiere |
| `test_disabled_item_skipped` | Ítem deshabilitado | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_maintenance_host_skipped` | Host en mantenimiento | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_command_failure_is_error` | Fallo del comando | `status = False`, mensaje "Error" | Si es `True` |
| `test_module_disabled` | Módulo deshabilitado | Sin ítems, `host_exec` no invocado | Si procesa |

### `TestThresholdInheritance` — Herencia del umbral

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_blank_item_inherits_module_threshold` | Ítem en blanco hereda umbral del módulo | alert 85 heredado; `status = True` | Si no hereda |
| `test_null_item_inherits_module_threshold` | Ítem `null` hereda | alert 90 heredado; `status = True` | Si no hereda |
| `test_blank_item_no_module_uses_schema_default` | Sin módulo, usa default del schema | alert 85 (schema); `status = True` | Si difiere |
| `test_explicit_item_value_wins` | Valor explícito del ítem gana | alert 60 override; `status = False` | Si no prevalece |
| `test_item_zero_inherits_module` | alert 0 en ítem hereda | alert 85 heredado; `status = True` | Si usa 0 |

### `TestSchema` — Schema host-céntrico

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_host_centric` | Schema host-céntrico | `__host_profile__` clave `ssh`; `list` con `alert` y `label` | Si difiere |

---

## 28. Watchful: ssl\_cert

**Archivo:** `watchfuls/ssl_cert/tests/test_ssl_cert.py`

### `TestSslCertCheck` — Ejecución del check

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_disabled_module_empty` | Módulo deshabilitado | Resultado vacío | Si procesa |
| `test_disabled_item_skipped` | Ítem con `enabled: false` | Omitido del resultado | Si aparece |
| `test_valid_ok` | Certificado con caducidad +60 días | `status = True` | Si es `False` |
| `test_within_warning_window` | Caducidad +10 días (ventana de aviso) | `status = False`, "warning threshold" | Si es `True` |
| `test_expired` | Certificado expirado (-5 días) | `status = False`, mensaje "EXPIRED" | Si es `True` |
| `test_connection_error_handled` | Error de conexión SSL (rechazo) | `status = False`, "Error" sin lanzar | Si lanza al caller |
| `test_per_item_warning_days_overrides_module` | `warning_days` por ítem anula el del módulo | +20 días con ventana 10 → `status = True` | Si usa el global |
| `test_sni_uses_server_name_not_address` | Conecta a la dirección pero SNI = FQDN | `other_data` con `server_name`/`verify` | Si usa la dirección como SNI |
| `test_sni_defaults_to_address` | Sin `server_name`, SNI cae a la dirección | `server_hostname` = dirección del host | Si difiere |
| `test_verify_off_uses_insecure_context` | `verify_ssl=false` | `check_hostname=False`, `CERT_NONE`, `status = True`, verify `False` | Si verifica |
| `test_verify_on_uses_default_context` | `verify_ssl=true` | `verify_mode != CERT_NONE` | Si no verifica |

### `TestCertExpiry` — Extracción de caducidad

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_parses_generated_cert` | `_cert_expiry` sobre un cert generado | Timestamp correcto (≈`not_after`) y fecha "2031-06-01" | Si difiere |

---

## 29. Watchful: process

**Archivo:** `watchfuls/process/tests/test_process.py`

### `TestCountMatches` — Conteo de coincidencias

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_unix_counts_by_comm` | Conteo por `comm` (Unix) | nginx==2, sshd==1, ausente==0 | Si difiere |
| `test_windows_counts_with_or_without_exe` | Conteo con o sin sufijo `.exe` | nginx/nginx.exe==2, explorer==1 | Si difiere |

### `TestProcessCheck` — Ejecución del check

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_disabled_module_empty` | Módulo deshabilitado | Sin ítems, `host_exec` no invocado | Si procesa |
| `test_disabled_item_skipped` | Ítem con `enabled: false` | Sin ítems, `host_exec` no invocado | Si aparece |
| `test_running_ok` | Proceso con instancias suficientes | `status = True`, count 2 | Si es `False` |
| `test_min_count_not_met` | Instancias < `min_count` | `status = False`, mensaje "2/3" | Si es `True` |
| `test_windows_host_uses_tasklist` | Host Windows | Comando `tasklist`; `status = True`, count 2 | Si difiere |
| `test_empty_process_uses_key` | Campo `process` vacío → usa la clave | Búsqueda con la clave; `status = True` | Si usa string vacío |
| `test_command_failure_is_error` | Fallo del comando | `status = False`, mensaje "Error" | Si es `True` |
| `test_maintenance_host_skipped` | Host en mantenimiento | Sin ítems, `host_exec` no invocado | Si procesa |

### `TestProcessDiscover` — Descubrimiento de procesos

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_discover_counts_and_sorts` | Cuenta y ordena procesos | Orden alfabético; "aaa" primero, bash `status = '×2'` | Si difiere |
| `test_discover_exception_returns_empty` | Excepción en psutil durante discover | `[]` devuelto | Si lanza al caller |
| `test_discover_remote_over_ssh` | Descubrimiento remoto vía SSH | Ejecuta `ps -A -o comm=`; nginx '×2', sshd '×1' | Si falla |
| `test_discover_remote_windows_tasklist` | Descubrimiento remoto Windows | Comando `tasklist`; nginx.exe '×2' | Si difiere |

---

## 30. Watchful: dns

**Archivo:** `watchfuls/dns/tests/test_dns.py`

### `TestDnsInit`, `TestDnsCheck`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_init` | Instanciación del módulo | Sin excepción | Si lanza |
| `test_check_disabled_returns_empty` | Módulo deshabilitado | Resultado vacío | Si procesa |
| `test_check_empty_list_returns_empty` | Lista vacía | Resultado vacío | Si lanza |
| `test_check_disabled_item_skipped` | Ítem con `enabled: false` | Omitido del resultado | Si aparece |
| `test_check_resolution_ok` | Registro A resuelve a al menos una IP | `status = True` | Si es `False` |
| `test_check_resolution_fails` | Hostname no resuelve | `status = False` | Si es `True` |
| `test_check_expected_match` | Valor resuelto contiene `expected` (subcadena) | `status = True` | Si es `False` |
| `test_check_expected_mismatch` | Valor resuelto no contiene `expected` | `status = False` con mensaje | Si es `True` |
| `test_check_other_data_populated` | `other_data` contiene `host`, `record_type`, `resolved`, `expected` | Todos los campos presentes | Si faltan |
| `test_check_deduplicates_ips` | IPs duplicadas en la resolución se deducan | Lista sin duplicados | Si hay duplicados |
| `test_check_empty_host_uses_key` | Campo `host` vacío → usa la clave del ítem | Resolución con la clave | Si usa string vacío |
| `test_check_record_type_aaaa` | Registro AAAA usa `AF_INET6` en `getaddrinfo` | `AF_INET6` pasado como familia | Si usa `AF_INET` |
| `test_check_mx_record_via_dnspython` | Registro MX usa `_resolve_dns` (dnspython) | `_resolve_dns` llamado con `('host', 'MX', timeout)` | Si usa socket |
| `test_check_txt_expected_match` | Registro TXT con `expected` → subcadena encontrada | `status = True` | Si es `False` |
| `test_check_non_a_without_dnspython_returns_false` | Tipo no-A/AAAA sin dnspython instalado | `status = False` con mensaje `dnspython` | Si lanza o da `True` |
| `test_check_dns_no_results_is_false` | Consulta no-A que devuelve lista vacía | `status = False` | Si es `True` |

### `TestDnsHardening`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_a_expected_requires_exact_match` | `expected` en A exige coincidencia exacta (no subcadena) | `'1.2.3.4'` no casa `'11.2.3.40'` → `status = False` | Si casa por subcadena |
| `test_other_data_has_response_time` | `other_data.response_time` presente | Es `int`/`float` | Si falta |
| `test_non_numeric_timeout_does_not_crash` | Timeout no numérico ('abc') | No aborta; `status = True` | Si lanza |
| `test_socket_network_error_is_reported` | `OSError` de red aflora en el mensaje | Mensaje con "network down"; `status = False` | Si se silencia |
| `test_socket_gaierror_is_no_results` | `gaierror` → sin resultados | Mensaje "no results", `status = False` | Si difiere |

### `TestDnsDiscovery`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_actions_declared_and_read_only` | `discover` en `WATCHFUL_ACTIONS` y `READ_ONLY_ACTIONS` | Presente en ambos | Si falta |
| `test_empty_domain_returns_empty` | Discover sin dominio | `[]` | Si devuelve algo |
| `test_probe_returns_existing_types` | Una entrada por tipo que resuelve (A, MX) | `name`/`category='address'`/`value`/`fill_value='1.2.3.4'` | Si difiere |
| `test_axfr_flag_selects_mode` | Flag `axfr` selecciona modo | `False`→probe, `True`/`'true'`→axfr | Si difiere |
| `test_axfr_failure_returns_empty` | AXFR que lanza excepción | Discover devuelve `[]` | Si propaga |

### `TestDnsRemote`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_remote_a_via_dig_targets_nameserver` | A remoto vía `dig` apuntando al nameserver | Comando con `dig` y `@192.168.110.253`; `status = True`, resuelto `['192.168.110.10']` | Si difiere |
| `test_local_host_also_uses_dig` | Host local también usa `dig` vía `host_exec` | `status = True` | Si no usa dig |
| `test_remote_failure_reports_error` | `host_exec` rc=9 "connection timed out" | `status = False`, mensaje con "timed out" | Si difiere |
| `test_parse_dig_short` | `_parse_dig_short` parsea A/MX/TXT/NS | Quita puntos finales y comillas | Si el parseo falla |
| `test_discover_probe_remote_parses_combined` | Parseo de salida `##TYPE##` combinada | A y MX presentes, AAAA ausente; A `fill_value='1.2.3.4'` | Si difiere |
| `test_discover_uses_host_via_ssh_when_remote` | `__host__` remoto vía `lib.core.hosts.runner.run` | Registro A con `fill_value='9.9.9.9'` | Si no usa SSH |

### `TestDnsWindowsResolver`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_parse_resolve_dnsname` | `_parse_resolve_dnsname` para MX/A/TXT/NS/SOA | Parseo correcto (MX '10 mx1.x.lan', SOA 'ns1.x.lan serial=7') | Si difiere |
| `test_resolve_win_invokes_resolve_dnsname` | `_resolve_win` invoca `Resolve-DnsName` | Devuelve `['10 mx1.x.lan']`; comando con `-Server '192.168.1.1'` | Si difiere |
| `test_check_on_windows_uses_resolve_dnsname` | En Windows usa `_resolve_win` | Llamado una vez; `status = True`, resuelto `['10 mx1.x.lan']` | Si no lo usa |

---

## 31. Watchful: ntp

**Archivo:** `watchfuls/ntp/tests/test_ntp.py`

### `TestNtpQuery`, `TestNtpInit`, `TestNtpCheck`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_ntp_query_returns_offset_and_delay` | Respuesta NTP válida devuelve offset y delay | Tupla `(float, float)` correcta | Si lanza o devuelve valores inválidos |
| `test_ntp_query_short_response_raises` | Respuesta < 48 bytes lanza `ValueError` | `ValueError` lanzado | Si no lanza |
| `test_ntp_query_socket_error_propagates` | Error de socket se propaga al caller | Excepción propagada | Si se silencia |
| `test_init` | Instanciación del módulo | Sin excepción | Si lanza |
| `test_check_disabled_returns_empty` | Módulo deshabilitado | Resultado vacío | Si procesa |
| `test_check_empty_list_returns_empty` | Lista vacía | Resultado vacío | Si lanza |
| `test_check_disabled_item_skipped` | Ítem con `enabled: false` | Omitido del resultado | Si aparece |
| `test_check_offset_within_threshold` | Offset < `max_offset` | `status = True` | Si es `False` |
| `test_check_offset_exceeds_threshold` | Offset ≥ `max_offset` | `status = False` | Si es `True` |
| `test_check_socket_error_handled` | Error de red | `status = False` sin lanzar | Si lanza al caller |
| `test_check_other_data_populated` | `other_data` contiene `offset_seconds`, `delay_seconds`, `server`, `max_offset` | Todos los campos presentes | Si faltan |
| `test_check_per_item_max_offset_overrides_module` | `max_offset` por ítem anula el del módulo | Umbral correcto del ítem | Si usa el global |

---

## 32. Watchful: ups

**Archivo:** `watchfuls/ups/tests/test_ups.py`

### `TestNutQuery`, `TestUpsInit`, `TestUpsCheck`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_nut_query_ol_status` | Respuesta NUT con `OL` parsea variables correctamente | Dict con `ups.status = "OL"` | Si falla el parsing |
| `test_nut_query_err_raises` | Respuesta `ERR` del demonio lanza `ConnectionError` | Excepción lanzada | Si no lanza |
| `test_nut_query_connection_error` | Fallo de conexión TCP se propaga | Excepción propagada | Si se silencia |
| `test_init` | Instanciación del módulo | Sin excepción | Si lanza |
| `test_check_disabled_returns_empty` | Módulo deshabilitado | Resultado vacío | Si procesa |
| `test_check_empty_list_returns_empty` | Lista vacía | Resultado vacío | Si lanza |
| `test_check_item_without_host_skipped` | Ítem sin `host` | Omitido silenciosamente | Si lanza o aparece |
| `test_check_disabled_item_skipped` | Ítem con `enabled: false` | Omitido del resultado | Si aparece |
| `test_check_ol_status_ok` | UPS en línea (`OL`) | `status = True` | Si es `False` |
| `test_check_ob_status_warning` | UPS en batería (`OB`) | `status = False` | Si es `True` |
| `test_check_lb_status_critical` | Batería baja (`LB`) | `status = False` | Si es `True` |
| `test_check_connection_error_handled` | Error de conexión al demonio NUT | `status = False` sin lanzar | Si lanza al caller |
| `test_check_other_data_populated` | `other_data` contiene `status`, `battery_charge`, `runtime`, `load` | Todos los campos presentes | Si faltan |
| `test_check_ol_lb_combination_is_not_ok` | Estado `OL LB` (en línea pero batería baja) | `status = False` | Si es `True` |

### `TestUpsThresholds`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_low_battery_charge_triggers` | Carga 15 con `alert_battery` 20 | `status = False`, mensaje "battery" | Si es `True` |
| `test_charge_above_threshold_ok` | Carga 80 con umbral 20 | `status = True` | Si es `False` |
| `test_low_runtime_triggers` | Runtime 300 s (5 min) con `alert_runtime` 10 | `status = False`, mensaje "runtime" | Si es `True` |
| `test_on_battery_alerts_by_default` | `OB` sin overrides | `status = False` (alerta por defecto) | Si es `True` |
| `test_on_battery_alert_can_be_disabled` | `OB` + `alert_on_battery=False`, carga/runtime sanos | `status = True` | Si es `False` |
| `test_load_threshold_triggers` | Carga 95 con `alert_load` 80 | `status = False`, mensaje "load" | Si es `True` |
| `test_load_threshold_disabled_by_default` | Carga 99 con `alert_load` 0 (por defecto) | `status = True` | Si es `False` |

### `TestTestConnection`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_ok` | `test_connection` con `OL` | `ok = True`; mensaje con "host:port" y "OL"; info con estado/carga | Si falla |
| `test_failure_returns_message` | Conexión rechazada | `ok = False`, mensaje con "refused" | Si difiere |
| `test_no_host` | Host vacío | `ok = False` | Si acepta |
| `test_host_from_bound_host_ctx` | Host vacío cae al `__host__` (172.16.0.5) | `ok = True`; usa esa dirección | Si no la usa |

---

## 33. Core — CLI y variables de entorno

**Archivo:** `tests/test_cli_env.py` — 6 tests

| Test | Qué comprueba |
|---|---|
| `test_defaults_without_env` | Defaults without env |
| `test_env_maps_to_args` | Env maps to args |
| `test_nocolor_env` | Nocolor env |
| `test_no_color_standard_env` | The de-facto NO_COLOR standard: present (non-empty) disables colour |
| `test_bool_falsey_values` | Bool falsey values |
| `test_cli_flag_overrides_absent_env` | Cli flag overrides absent env |

## 34. Core — Resolución de configuración

**Archivo:** `tests/test_config_resolve.py` — 13 tests

| Test | Qué comprueba |
|---|---|
| `test_flattens_two_levels` | Flattens two levels |
| `test_ignores_non_dict_sections` | Ignores non dict sections |
| `test_db_value_is_editable` | Db value is editable |
| `test_file_overrides_db_and_locks` | File overrides db and locks |
| `test_env_overrides_file_and_db` | Env overrides file and db |
| `test_default_when_unset` | Default when unset |
| `test_database_section_never_from_db` | Database section never from db |
| `test_database_default_when_only_db` | Database default when only db |
| `test_locked_set_is_union_of_env_and_file` | Locked set is union of env and file |
| `test_opaque_leaf_values_preserved` | Opaque leaf values preserved |
| `test_env_overlays_file_section` | Env overlays file section |
| `test_no_env_returns_file_section` | No env returns file section |
| `test_bad_port_is_ignored` | Bad port is ignored |

## 35. Core — Registro central de config (spec)

**Archivo:** `tests/test_config_spec.py` — 44 tests

| Test | Qué comprueba |
|---|---|
| `test_no_duplicate_paths` | No duplicate paths |
| `test_cfg_by_path_complete` | Cfg by path complete |
| `test_every_path_has_section_and_field` | Every path has section and field |
| `test_known_defaults` | Known defaults |
| `test_notifications_default_false` | Notifications default false |
| `test_missing_uses_default_coerced` | Missing uses default coerced |
| `test_present_value` | Present value |
| `test_bool_coercion` | Bool coercion |
| `test_falsy_false_keeps_empty` | Falsy false keeps empty |
| `test_falsy_true_replaces_empty` | Falsy true replaces empty |
| `test_int_ok` | Int ok |
| `test_int_out_of_range` | Int out of range |
| `test_int_wrong_type` | Int wrong type |
| `test_int_rejects_bool` | Int rejects bool |
| `test_json_dict_ok_string` | Json dict ok string |
| `test_json_dict_ok_dict` | Json dict ok dict |
| `test_json_dict_bad` | Json dict bad |
| `test_json_dict_empty_ok` | Json dict empty ok |
| `test_unconstrained_passes` | Unconstrained passes |
| `test_store_form` | Store form |
| `test_bool_field` | Bool field |
| `test_int_field_has_range` | Int field has range |
| `test_excludes_non_attr_fields` | Excludes non attr fields |
| `test_int_rules` | Int rules |
| `test_bool_rules` | Bool rules |
| `test_json_dict_fields` | Json dict fields |
| `test_env_field_specs` | Env field specs |
| `test_admin_only_fields` | Admin only fields |
| `test_valid_kept` | Valid kept |
| `test_invalid_falls_back` | Invalid falls back |
| `test_records_and_applies_change` | Records and applies change |
| `test_no_change_no_record` | No change no record |
| `test_old_default` | Old default |

## 36. Core — Almacén de config en BD

**Archivo:** `tests/test_config_store.py` — 9 tests

| Test | Qué comprueba |
|---|---|
| `test_is_empty` | Is empty |
| `test_type_preservation_roundtrip` | Type preservation roundtrip |
| `test_get_and_has` | Get and has |
| `test_stored_null_vs_absent` | Stored null vs absent |
| `test_set_many_upsert` | Set many upsert |
| `test_delete` | Delete |
| `test_value_agnostic_stores_ciphertext_asis` | Value agnostic stores ciphertext asis |
| `test_audit_columns_populated` | Audit columns populated |
| `test_version_increments` | Version increments |

## 37. BD — Tablas declaradas por módulos

**Archivo:** `tests/test_db_module_tables.py` — 15 tests

| Test | Qué comprueba |
|---|---|
| `test_prefixes_table_and_indexes` | Prefixes table and indexes |
| `test_prefix_is_idempotent` | Prefix is idempotent |
| `test_carries_pk_and_unique` | Carries pk and unique |
| `test_valid_namespaced_table` | Valid namespaced table |
| `test_wrong_prefix_skipped` | Wrong prefix skipped |
| `test_raw_unprefixed_tablespec_skipped` | Raw unprefixed tablespec skipped |
| `test_non_tablespec_skipped` | Non tablespec skipped |
| `test_missing_function` | Missing function |
| `test_non_callable_attribute` | Non callable attribute |
| `test_raising_function_is_contained` | Raising function is contained |
| `test_empty_return` | Empty return |
| `test_reconcile_creates_usable_table` | Reconcile creates usable table |
| `test_reconcile_module_tables_real_dir_is_safe` | Reconcile module tables real dir is safe |
| `test_collect_module_tables_real_dir` | Collect module tables real dir |
| `test_reconcile_failure_is_isolated` | Reconcile failure is isolated |

## 38. BD — ModulesStore

**Archivo:** `tests/test_modules_store.py` — 17 tests

| Test | Qué comprueba |
|---|---|
| `test_is_empty` | Is empty |
| `test_roundtrip_exact` | Roundtrip exact |
| `test_promoted_columns_not_duplicated_in_data` | Promoted columns not duplicated in data |
| `test_host_uid_omitted_when_empty` | Host uid omitted when empty |
| `test_enabled_false_preserved` | Enabled false preserved |
| `test_meta_key_is_module_field_not_collection` | Meta key is module field not collection |
| `test_scalar_legacy_items_preserved` | Scalar legacy items preserved |
| `test_multiple_collection_keys` | Multiple collection keys |
| `test_sync_removes_item` | Sync removes item |
| `test_sync_removes_module` | Sync removes module |
| `test_module_uid_stable_across_saves` | Module uid stable across saves |
| `test_version_increments_on_write` | Version increments on write |
| `test_save_read_roundtrip` | Save read roundtrip |
| `test_get_conf_parity_with_configcontrol` | Get conf parity with configcontrol |
| `test_set_conf_then_save_persists` | Set conf then save persists |
| `test_secrets_encrypted_at_rest_decrypted_on_read` | Secrets encrypted at rest decrypted on read |
| `test_reload_if_changed` | Reload if changed |

## 39. BD — HostsStore

**Archivo:** `tests/test_hosts_store.py` — 20 tests

| Test | Qué comprueba |
|---|---|
| `test_create_and_get_roundtrip` | Create and get roundtrip |
| `test_create_requires_name` | Create requires name |
| `test_duplicate_name_rejected` | Duplicate name rejected |
| `test_list_ordered_by_name` | List ordered by name |
| `test_get_by_name` | Get by name |
| `test_count` | Count |
| `test_update_replaces_fields` | Update replaces fields |
| `test_update_rejects_name_clash` | Update rejects name clash |
| `test_update_unknown_uid` | Update unknown uid |
| `test_delete` | Delete |
| `test_kind_defaults_to_local` | Kind defaults to local |
| `test_create_remote_and_maintenance` | Create remote and maintenance |
| `test_invalid_kind_normalised_to_local` | Invalid kind normalised to local |
| `test_os_defaults_to_auto_and_persists` | Os defaults to auto and persists |
| `test_invalid_os_normalised_to_auto` | Invalid os normalised to auto |
| `test_modules_list_persists` | Modules list persists |
| `test_update_toggles_kind_and_maintenance` | Update toggles kind and maintenance |
| `test_secrets_encrypted_at_rest` | Secrets encrypted at rest |
| `test_no_fernet_stores_plaintext` | No fernet stores plaintext |
| `test_persists_across_store_instances` | Persists across store instances |

## 40. BD — CredentialsStore

**Archivo:** `tests/test_credentials.py` — 37 tests

| Test | Qué comprueba |
|---|---|
| `test_create_get_roundtrip` | Create get roundtrip |
| `test_secret_encrypted_at_rest` | Secret encrypted at rest |
| `test_duplicate_name_rejected` | Duplicate name rejected |
| `test_update_and_list` | Update and list |
| `test_delete` | Delete |
| `test_enabled_default_and_toggle` | Enabled default and toggle |
| `test_overlay_wins_for_identity` | Overlay wins for identity |
| `test_empty_cred_fields_do_not_clobber` | Empty cred fields do not clobber |
| `test_none_cred_returns_copy` | None cred returns copy |
| `test_disabled_credential_ignored` | Disabled credential ignored |
| `test_inline_check_uses_credential` | Inline check uses credential |
| `test_host_ssh_profile_cred_uid` | Host ssh profile cred uid |
| `test_dangling_cred_uid_is_ignored` | Dangling cred uid is ignored |
| `test_inline_check_uses_non_ssh_credential` | Inline check uses non ssh credential |
| `test_builtin_ssh_present` | Builtin ssh present |
| `test_module_declared_type_discovered` | Module declared type discovered |
| `test_secret_fields_union` | Secret fields union |
| `test_requires_auth` | Requires auth |
| `test_create_list_and_mask` | Create list and mask |
| `test_update_keeps_masked_secret` | Update keeps masked secret |
| `test_delete` | Delete |
| `test_duplicate_name_rejected` | Duplicate name rejected |
| `test_clone_preserves_secret_and_renames` | Clone preserves secret and renames |
| `test_host_test_ssh_uses_credential_not_stored` | Host test ssh uses credential not stored |
| `test_action_config_applies_credential` | Action config applies credential |
| `test_check_test_applies_credential` | Check test applies credential |
| `test_modules_save_strips_inline_cred_fields` | Modules save strips inline cred fields |
| `test_usage_lists_referencing_host` | Usage lists referencing host |
| `test_test_endpoint_uses_stored_secret` | Test endpoint uses stored secret |
| `TestFindAllCredentialUsage::test_it_buckets_every_reference_by_credential` | Una sola pasada contesta por todas: el escaneo recorre los perfiles de host y los checks de todos los módulos igual pregunte por una credencial o por el catálogo entero |
| `TestFindAllCredentialUsage::test_an_unreferenced_credential_has_no_entry` | Ausente **es** la respuesta «no la usa nadie»; inventar una entrada vacía rompería la lectura sobre la que se construye la vista |
| `TestFindAllCredentialUsage::test_module_metadata_is_not_a_check` | Las claves `__…` son config del módulo, no ítems que definiera un usuario: contarlas mantendría viva una credencial cuyo último check real se borró |
| `TestFindAllCredentialUsage::test_the_module_name_loses_its_package_prefix` | `watchfuls.web` es cómo se guarda; `web` es cómo lo llama el usuario |
| `TestFindAllCredentialUsage::test_the_single_credential_answer_is_the_same_slice` | La ruta por credencial delega en la de bloque: no pueden discrepar |
| `test_bulk_usage_answers_for_the_whole_catalogue` | El endpoint nuevo, extremo a extremo |
| `test_bulk_usage_matches_the_per_credential_answer` | Dos rutas, un escaneo |
| `test_bulk_usage_needs_a_credential_permission` | Misma puerta que la ruta por credencial —que es exactamente lo que abre la sección—, así que no concede nada que la vista no alcanzara ya |

## 41. Core — Cliente SSH

**Archivo:** `tests/test_ssh_client.py` — 15 tests

| Test | Qué comprueba |
|---|---|
| `test_parses_generated_key` | Parses generated key |
| `test_invalid_key_raises` | Invalid key raises |
| `test_empty_address_reported` | Empty address reported |
| `test_success` | Success |
| `test_failure_is_caught` | Failure is caught |
| `test_build_connect_kwargs_auth_precedence` | Build connect kwargs auth precedence |
| `test_build_connect_kwargs_password_only` | Build connect kwargs password only |
| `test_no_paramiko_degrades_gracefully` | No paramiko degrades gracefully |
| `test_uname_linux` | Uname linux |
| `test_uname_darwin` | Uname darwin |
| `test_uname_freebsd` | Uname freebsd |
| `test_windows_via_ver` | Windows via ver |
| `test_unknown_is_other` | Unknown is other |
| `test_test_connection_detect_returns_os` | Test connection detect returns os |
| `test_local_os_is_canonical` | Local os is canonical |

## 42. Hosts — Ejecución local/SSH

**Archivo:** `tests/test_hosts_exec.py` — 11 tests

| Test | Qué comprueba |
|---|---|
| `test_picks_by_os` | Picks by os |
| `test_falls_back_to_default_os` | Falls back to default os |
| `test_empty_cmds` | Empty cmds |
| `test_local_inline_runs_locally` | Local inline runs locally |
| `test_no_command_is_error` | No command is error |
| `test_remote_runs_over_ssh` | Remote runs over ssh |
| `test_remote_without_address_errors` | Remote without address errors |
| `test_remote_without_paramiko` | Remote without paramiko |
| `test_remote_ssh_failure_caught` | Remote ssh failure caught |
| `test_run_command_decodes_and_exit_code` | Run command decodes and exit code |
| `test_run_command_transport_error` | Run command transport error |

## 43. Hosts — Perfiles de protocolo

**Archivo:** `tests/test_hosts_profiles.py` — 12 tests

| Test | Qué comprueba |
|---|---|
| `test_protocols_discovered` | Protocols discovered |
| `test_snmp_profile_is_address_only` | Snmp profile is address only |
| `test_ssh_is_core_builtin` | Ssh is core builtin |
| `test_datastore_db_endpoint_is_not_a_profile` | Datastore db endpoint is not a profile |
| `test_module_host_specs_preserves_datastore_ssh` | Module host specs preserves datastore ssh |
| `test_module_host_fields` | Module host fields |
| `test_module_host_multiple` | Module host multiple |
| `test_module_host_collections` | Module host collections |
| `test_missing_dir_is_empty` | Missing dir is empty |

## 44. Hosts — Resolución host→check

**Archivo:** `tests/test_hosts_config_resolution.py` — 26 tests

| Test | Qué comprueba |
|---|---|
| `test_inline_item_unchanged` | Inline item unchanged |
| `test_no_store_returns_item` | No store returns item |
| `test_unknown_host_returns_item` | Unknown host returns item |
| `test_address_injected_and_host_wins` | Address injected and host wins |
| `test_snmp_inherits_only_address` | Snmp inherits only address |
| `test_ssl_cert_host_address_port_stays_on_check` | Ssl cert host address port stays on check |
| `test_ntp_host_address_port_stays_on_check` | Ntp host address port stays on check |
| `test_datastore_address_and_ssh_from_host_db_creds_from_check` | Datastore address and ssh from host db creds from check |
| `test_web_inherits_only_address` | Web inherits only address |
| `test_local_host_skips_ssh_profile` | Local host skips ssh profile |
| `test_remote_host_injects_ssh_profile` | Remote host injects ssh profile |
| `test_maintenance_disables_check` | Maintenance disables check |
| `test_no_maintenance_keeps_enabled` | No maintenance keeps enabled |
| `test_host_os_explicit_injected` | Host os explicit injected |
| `test_host_os_auto_local_resolves_to_platform` | Host os auto local resolves to platform |
| `test_host_os_auto_remote_stays_auto` | Host os auto remote stays auto |
| `test_dns_has_ssh_host_profile` | Dns has ssh host profile |
| `test_dns_in_module_host_fields` | Dns in module host fields |
| `test_resolved_item_inherits_host` | Resolved item inherits host |
| `test_resolved_item_inline_unchanged` | Resolved item inline unchanged |

## 45. Hosts — Sonda de check único

**Archivo:** `tests/test_hosts_probe.py` — 4 tests

| Test | Qué comprueba |
|---|---|
| `test_is_a_monitor` | Is a monitor |
| `test_runs_process_check_remote` | Runs process check remote |
| `test_runs_process_check_failure` | Runs process check failure |
| `test_returns_draft_for_its_uid` | Returns draft for its uid |

## 46. Hosts — Asistente de migración

**Archivo:** `tests/test_hosts_migrate.py` — 7 tests

| Test | Qué comprueba |
|---|---|
| `test_merges_duplicates_and_cross_module` | Merges duplicates and cross module |
| `test_same_address_merges_regardless_of_settings` | Same address merges regardless of settings |
| `test_different_address_separate` | Different address separate |
| `test_skips_already_bound_and_empty_address` | Skips already bound and empty address |
| `test_datastore_ssh_profile_db_creds_stay_on_check` | Datastore ssh profile db creds stay on check |
| `test_strips_connection_and_sets_host_uid` | Strips connection and sets host uid |
| `test_apply_ignores_unknown_members` | Apply ignores unknown members |

## 47. Seguridad — Regresión

**Archivo:** `tests/test_security_regression.py` — 30 tests

| Test | Qué comprueba |
|---|---|
| `test_safe_filename_rejects_path_separator` | Safe filename rejects path separator |
| `test_safe_filename_rejects_dot_prefix` | Safe filename rejects dot prefix |
| `test_safe_filename_rejects_shell_metacharacters` | Safe filename rejects shell metacharacters |
| `test_safe_filename_accepts_valid_names` | Safe filename accepts valid names |
| `test_safe_filename_rejects_wrong_extension_for_compiled` | Safe filename rejects wrong extension for compiled |
| `test_confined_path_blocks_traversal` | Confined path blocks traversal |
| `test_confined_path_allows_valid_subpath` | Confined path allows valid subpath |
| `test_non_admin_cannot_delete_admin` | Non admin cannot delete admin |
| `test_admin_can_delete_non_admin` | Admin can delete non admin |
| `test_non_admin_cannot_create_role_with_admin_permissions` | User with roles_add cannot create a role that has permissions |
| `test_non_admin_can_create_role_with_own_permissions_only` | User with roles_add CAN create a role that only uses their own permissions |
| `test_non_admin_cannot_edit_role_to_add_permissions_they_lack` | User with roles_edit cannot add permissions to a role that they don't hold |
| `test_admin_can_create_role_with_any_permissions` | Admin is not restricted — can create roles with any permissions |
| `test_non_admin_cannot_create_group_with_admin_role` | Non admin cannot create group with admin role |
| `test_non_admin_cannot_assign_admin_role_to_existing_group` | Non admin cannot assign admin role to existing group |
| `test_non_admin_cannot_edit_group_that_already_has_admin_role` | Even modifying name/members of an admin-role group requires admin |
| `test_admin_can_create_group_with_admin_role` | Admin can create group with admin role |
| `test_non_admin_cannot_modify_ldap_section` | Non admin cannot modify ldap section |
| `test_non_admin_cannot_modify_oidc_section` | Non admin cannot modify oidc section |
| `test_non_admin_cannot_modify_email_section` | Non admin cannot modify email section |
| `test_non_admin_cannot_modify_telegram_section` | Non admin cannot modify telegram section |
| `test_non_admin_can_modify_non_sensitive_section` | config_edit users CAN modify non-sensitive sections (e.g. daemon) |
| `test_admin_can_modify_ldap_section` | Admin has no restriction on config sections |
| `test_versioned_format_also_blocked_for_non_admin` | The new versioned PUT format is also blocked for sensitive sections |
| `test_non_admin_cannot_disable_lockout` | Non admin cannot disable lockout |
| `test_non_admin_cannot_disable_secure_cookies` | Non admin cannot disable secure cookies |
| `test_non_admin_cannot_weaken_password_policy` | Non admin cannot weaken password policy |
| `test_non_admin_cannot_change_proxy_count` | Non admin cannot change proxy count |
| `test_admin_can_modify_web_admin_security_fields` | Admin can modify web admin security fields |
| `test_empty_password_rejected` | Empty password rejected |

## 48. Syslog — Parser RFC 3164/5424

**Archivo:** `tests/test_syslog_parser.py` — 14 tests

| Test | Qué comprueba |
|---|---|
| `test_facility_severity_split` | Facility severity split |
| `test_local0_info` | Local0 info |
| `test_invalid_pri_ignored` | Invalid pri ignored |
| `test_classic` | Classic |
| `test_tag_with_pid` | Tag with pid |
| `test_no_timestamp` | No timestamp |
| `test_full` | Full |
| `test_structured_data_stripped` | Structured data stripped |
| `test_nil_fields` | Nil fields |
| `test_no_pri_keeps_raw` | No pri keeps raw |
| `test_bytes_input_and_source` | Bytes input and source |
| `test_trailing_newline_stripped` | Trailing newline stripped |
| `test_empty` | Empty |
| `test_names_tables` | Names tables |

## 49. Syslog — Listener UDP/TCP/TLS

**Archivo:** `tests/test_syslog_server.py` — 13 tests

| Test | Qué comprueba |
|---|---|
| `test_blank_defaults_to_all_ipv4_and_ipv6` | Bind vacío → escucha en todas las IPv4 e IPv6 |
| `test_detects_family_and_multiple` | Detecta familia (v4/v6) y múltiples binds |
| `test_dedup` | Deduplica binds repetidos |
| `test_receive_udp` | Recibe y parsea un datagrama UDP |
| `test_allowlist_blocks` | Origen fuera del allowlist se descarta (y se cuenta) |
| `test_drop_logging_counts_and_rate_limits` | Los descartes se cuentan y el log se rate-limita por origen |
| `test_newline_framing` | Framing TCP por salto de línea (2 mensajes en 1 conexión) |
| `test_octet_counted_framing` | Framing TCP octet-counted (RFC 6587) |
| `test_bind_failure_reported` | Un bind imposible se reporta en `start()` |
| `test_no_ports_no_threads` | Sin puertos configurados no arranca hebras |

### `TestLoad` — Carga / concurrencia (sin pérdida)

> Un colector syslog recibe *fan-in* de muchos hosts a la vez. En **TCP** (stream fiable) no puede perderse **ninguna**: cada mensaje enmarcado llega al sink exactamente una vez. En **UDP** (best-effort) la pérdida bajo ráfaga es legítima, así que su aserción es tolerante.

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_many_concurrent_connections_no_loss_tcp` | **1000 conexiones simultáneas** (fase 1 abre y mantiene las 1000 → el servidor tiene 1000 hebras vivas a la vez; fase 2 transmite en todas), 5 mensajes cada una = **5000** | Se reciben exactamente los 5000 mensajes, sin pérdida ni duplicados | Si falta o se duplica alguno |
| `test_high_volume_single_connection_octet_counted_no_loss` | 1 conexión con **3000** frames octet-counted seguidos (framing bajo volumen) | Los 3000 frames se reciben exactos | Si el framing pierde/parte alguno |
| `test_udp_burst_is_best_effort` | Ráfaga de **500** datagramas UDP | El listener sobrevive y entrega el grueso (≥50%); UDP no garantiza entrega | Si se cae o pierde casi todo |

**Consumo medido** (escenario de 1000 conexiones, máquina dev de 24 núcleos, Python 3.14; media de 2 corridas, cero pérdida 5000/5000):

| Métrica | Valor |
|---|---|
| Hebras del proceso | ~4 en reposo → **~1000-1070 en pico** (una por conexión viva, es *thread-per-connection*) |
| RSS | ~41 MB base → **~88 MB pico** → **+≈46 MB** por las 1000 conexiones (**≈47 KB/conexión**: stack de hebra + buffers) |
| CPU | **~3 s** de CPU total (user+sys); picos instantáneos de **5-6 núcleos** durante el *connect/stream* concurrente; media ≈0,8 núcleos sobre la corrida |
| Tiempo | ~1,7 s el test en la suite (~4 s el arnés de medición aparte, con el muestreo cada 20 ms) |

> Regla aproximada: **~47 KB de RAM por conexión TCP concurrente**. 1000 conexiones simultáneas ⇒ ~46 MB extra y ~1000 hebras; escala lineal, así que un colector con muchísimas conexiones persistentes debe dimensionar RAM/hebras en consecuencia (el diseño *thread-per-connection* prioriza simplicidad y aislamiento por conexión frente a densidad extrema).

## 50. Syslog — SyslogStore

**Archivo:** `tests/test_syslog_store.py` — 18 tests

| Test | Qué comprueba |
|---|---|
| `test_add_and_query` | Add and query |
| `test_add_many` | Add many |
| `test_filter_severity_max` | Filter severity max |
| `test_filter_host_app_facility_text` | Filter host app facility text |
| `test_filter_time_range` | Filter time range |
| `test_distinct` | Distinct |
| `test_prune_by_age` | Prune by age |
| `test_prune_by_max_rows` | Prune by max rows |
| `test_prune_disabled` | Prune disabled |
| `test_delete_all` | Delete all |
| `test_breakdowns_and_total` | Breakdowns and total |
| `test_stats_honour_filters` | Stats honour filters |
| `test_stats_empty` | Stats empty |
| `test_stats_faceting_keeps_own_dimension_options` | Stats faceting keeps own dimension options |
| `test_effective_host_falls_back_to_source` | Effective host falls back to source |
| `test_stats_multi_value` | Stats multi value |

## 51. Syslog — Servicio independiente

**Archivo:** `tests/test_syslog_service.py` — 26 tests

| Test | Qué comprueba |
|---|---|
| `test_reads_shared_config` | Reads shared config |
| `test_load_webhooks_returns_list` | Load webhooks returns list |
| `test_read_config_file_is_effective` | Read config file is effective |
| `test_udp_message_is_stored` | Udp message is stored |
| `test_disabled_does_not_bind` | Disabled does not bind |
| `test_enable_only_still_has_default_ports` | Enable only still has default ports |
| `test_listener_does_not_dispatch` | El listener solo almacena mensajes; nunca despacha (lo evalúa el worker de eventos) |
| `test_cooldown_suppresses_second` | Cooldown suppresses second |
| `test_no_rule_no_dispatch` | No rule no dispatch |
| `test_disabled_shares_system_db` | Disabled shares system db |
| `test_enabled_uses_separate_db` | Enabled uses separate db |
| `test_env_enables_dedicated_db` | Env enables dedicated db |
| `test_run_stays_alive_when_disabled_then_stops` | Run stays alive when disabled then stops |
| `test_watch_reloads_on_enable` | Watch reloads on enable |
| `test_init_is_logged` | Init is logged |
| `test_init_respects_log_off` | Init respects log off |
| `test_start_and_stop_are_logged` | Start and stop are logged |
| `test_disabled_is_logged` | Disabled is logged |
| `test_event_rule_match_is_logged` | Event rule match is logged |

## 52. Panel Web — Comprobación de rol admin

**Archivo:** `tests/test_wa_admin_check.py` — 4 tests

| Test | Qué comprueba |
|---|---|
| `test_direct_admin` | Direct admin |
| `test_admin_via_enabled_group` | Admin via enabled group |
| `test_not_admin_via_disabled_group` | Not admin via disabled group |
| `test_plain_non_admin` | Plain non admin |

## 53. Panel Web — LDAP

**Archivo:** `tests/test_providers_ldap.py` — 22 tests

| Test | Qué comprueba |
|---|---|
| `test_is_available_returns_bool` | Is available returns bool |
| `test_admin_group_maps_to_admin` | Admin group maps to admin |
| `test_no_match_returns_empty_string` | No match returns empty string |
| `test_editor_maps_correctly` | Editor maps correctly |
| `test_highest_priority_wins` | Highest priority wins |
| `test_disabled_returns_ldap_disabled` | Disabled returns ldap disabled |
| `test_unavailable_returns_ldap_unavailable` | Unavailable returns ldap unavailable |
| `test_connection_error_returns_connection_error` | Connection error returns connection error |
| `test_user_not_found_returns_not_found` | User not found returns not found |
| `test_invalid_password_returns_invalid_credentials` | Invalid password returns invalid credentials |
| `test_successful_auth_returns_attrs` | Successful auth returns attrs |
| `test_posix_group_memberuid_maps_role` | posixGroup membership via memberUid on the group object maps the role |
| `test_new_user_is_created` | New user is created |
| `test_existing_user_role_is_resynced` | Existing user role is resynced |
| `test_new_user_uid_is_generated` | New user uid is generated |
| `test_ldap_user_logged_in_successfully` | Ldap user logged in successfully |
| `test_local_user_bypasses_ldap` | A user with auth_source='local' always uses local auth |
| `test_connection_error_fallback_to_local` | On LDAP connection error with fallback_to_local=True, local auth is tried |
| `test_connection_error_no_fallback_returns_error` | On LDAP connection error with fallback_to_local=False, login fails |
| `test_connection_test_creates_audit_entry` | Connection test creates audit entry |
| `test_connection_error_message_differs_from_credential_error` | Connection errors and credential errors return different messages |

## 54. Panel Web — OIDC/SSO

**Archivo:** `tests/test_providers_oidc.py` — 22 tests

| Test | Qué comprueba |
|---|---|
| `test_is_available_returns_bool` | Is available returns bool |
| `test_admin_group_maps_to_admin` | Admin group maps to admin |
| `test_no_match_returns_empty_string` | No match returns empty string |
| `test_editor_maps_correctly` | Editor maps correctly |
| `test_highest_priority_wins` | Highest priority wins |
| `test_case_insensitive_match` | Case insensitive match |
| `test_new_user_is_created` | New user is created |
| `test_existing_user_role_is_resynced` | Existing user role is resynced |
| `test_auto_create_false_blocks_new_user` | Auto create false blocks new user |
| `test_auto_create_false_allows_existing_user` | Auto create false allows existing user |
| `test_new_user_uid_is_generated` | New user uid is generated |
| `test_empty_userinfo_returns_none` | Empty userinfo returns none |
| `test_sub_stored_as_auth_source_id` | Sub stored as auth source id |
| `test_login_page_shows_sso_button` | SSO button appears on /login when OIDC is enabled |
| `test_oidc_login_triggers_redirect` | GET /auth/oidc/login redirects via the OAuth client |
| `test_callback_creates_user_and_session` | Successful OIDC callback creates user and establishes a session |
| `test_callback_group_maps_to_admin_role` | OIDC group claim is mapped to the correct role on callback |
| `test_callback_token_error_returns_to_login` | Token exchange failure redirects to /login with an error flash |
| `test_auto_create_false_blocks_unknown_user` | auto_create_users=False rejects unknown users in the OIDC callback |
| `test_disabled_account_blocked_at_callback` | A disabled OIDC user is blocked at the callback |

## 55. Panel Web — SAML2

**Archivo:** `tests/test_providers_saml.py` — 24 tests

| Test | Qué comprueba |
|---|---|
| `test_is_available_returns_bool` | Is available returns bool |
| `test_admin_group_maps_to_admin` | Admin group maps to admin |
| `test_no_match_returns_empty_string` | No match returns empty string |
| `test_editor_maps_correctly` | Editor maps correctly |
| `test_highest_priority_wins` | Highest priority wins |
| `test_case_insensitive_match` | Case insensitive match |
| `test_new_user_is_created` | New user is created |
| `test_name_id_used_when_no_username_attr` | Name id used when no username attr |
| `test_existing_user_role_is_resynced` | Existing user role is resynced |
| `test_auto_create_false_blocks_new_user` | Auto create false blocks new user |
| `test_auto_create_false_allows_existing_user` | Auto create false allows existing user |
| `test_new_user_uid_is_generated` | New user uid is generated |
| `test_name_id_stored_as_auth_source_id` | Name id stored as auth source id |
| `test_empty_name_id_and_no_attrs_returns_none` | Empty name id and no attrs returns none |
| `test_login_page_shows_saml2_button` | SAML2 button appears on /login when SAML2 is enabled |
| `test_saml2_login_redirects_to_idp` | GET /auth/saml2/login redirects to IdP SSO URL |
| `test_acs_creates_user_and_session` | Successful SAMLResponse creates user and establishes a session |
| `test_acs_group_maps_to_admin_role` | SAML2 groups claim is mapped to the correct role on ACS |
| `test_acs_saml_errors_redirect_to_login` | SAML2 assertion errors redirect back to /login |
| `test_acs_not_authenticated_redirects_to_login` | ACS returning is_authenticated=False redirects to /login |
| `test_acs_auto_create_false_blocks_unknown_user` | auto_create_users=False rejects unknown users in ACS |
| `test_acs_disabled_account_blocked` | A disabled SAML2 user is blocked at the ACS endpoint |

## 55b. Capa Microsoft compartida (Entra ID + ARM)

**Archivo:** `tests/test_providers_graph_api.py` — 26 tests

Esta capa transporta **a la vez** los watchfuls `m365` y `azure`, así que un fallo aquí es un fallo
en dos módulos. Y como los tests de ambos módulos la mockean, sin estos tests no la cubriría nadie.

| Test | Qué comprueba |
|---|---|
| `TestApiError::test_the_graph_shape` | `{"error": {"message": …}}` → el mensaje |
| `TestApiError::test_the_arm_shape_falls_back_to_the_code` | ARM manda a veces solo `code`, y `AuthorizationFailed` (la app no tiene rol RBAC) es la respuesta entera |
| `TestApiError::test_the_token_endpoint_shape` | `error_description` con el `AADSTS…` real, no un "Bad Request" pelado |
| `TestApiError::test_a_bare_error_code_is_better_than_nothing` | `{"error": "invalid_request"}` → el código |
| `TestApiError::test_a_non_json_body_gives_nothing_rather_than_html` | Devolver el cuerpo pegaría el HTML de error de un proxy dentro de una alerta |
| `TestApiError::test_the_message_is_bounded` | Truncado a 200 caracteres |
| `TestEncoding::test_a_space_survives_as_an_escape` | Un espacio sin escapar hace que urllib **rechace la URL** (`URL can't contain control characters`) |
| `TestEncoding::test_a_path_segment_is_fully_escaped` | Ids de suscripción y regiones en el path |
| `TestParseDt::*` | ISO-8601 → datetime *aware*; un valor naive se asume UTC (restarlo de un `now` aware lanzaría `TypeError`); lo imparseable da `None`, no excepción |
| `TestToken::test_the_scope_defaults_to_graph` | Scope y `grant_type` del client-credentials |
| `TestToken::test_an_answer_with_no_token_is_an_error_carrying_the_reason` | El `AADSTS…` llega al `EntraApiError` |
| `TestToken::test_the_tenant_is_escaped_into_the_path` | El tenant va escapado |
| `TestPaging::test_graph_next_links_are_followed` | Graph pagina de 100 en 100 |
| `TestPaging::test_arm_uses_its_own_next_key` | ARM dice `nextLink` donde Graph dice `@odata.nextLink`: usar la clave de Graph contra ARM **para en silencio tras la primera página** |
| `TestPaging::test_a_runaway_next_link_cannot_spin_forever` | Tope de páginas |
| `TestPaging::test_non_dict_entries_are_skipped` | Entradas basura en `value` |
| `TestArm::test_arm_is_a_different_audience_from_graph` | El fallo clásico de Azure: todos los permisos de Graph concedidos y ARM sigue dando 403 |
| `TestArm::test_an_arm_read_goes_to_the_arm_base` | Base correcta |
| `TestArm::test_the_bearer_token_is_sent` | Cabecera `Authorization` |
| `TestArm::test_an_empty_body_is_an_empty_dict_not_a_crash` | Cuerpo vacío |

> **Ojo con los mocks:** un `_get_token` mockeado devuelve token *pidas el scope que pidas*, así que
> ningún test de módulo detecta un scope equivocado. Eso lo cubre
> `TestTokenAudience` en `watchfuls/azure/tests/test_azure.py` (§ módulo azure), que afirma que el
> monitor y el picker de regiones piden **ARM** y que el check de secretos pide **Graph**.

## 56. Panel Web — Servidores (hosts)

**Archivo:** `tests/test_wa_hosts.py` — 52 tests

| Test | Qué comprueba |
|---|---|
| `test_requires_auth` | Requires auth |
| `test_create_list_and_mask` | Create list and mask |
| `test_overview_servers_widget_returns_hosts` | El widget de servidores del Overview lista el host creado |
| `test_virtual_flag_roundtrip_and_widget_split` | El flag `virtual` persiste; el widget separa físicos/virtuales |
| `test_clone_duplicates_with_secrets` | Clonar copia perfiles y secreto, sobreescribe nombre/dirección; origen intacto |
| `test_clone_only_selected_checks` | Clonar con lista de checks clona solo esos |
| `test_clone_empty_checks_clones_none` | Clonar con lista de checks vacía no clona ninguno |
| `test_clone_defaults_name_when_blank` | Nombre de clon en blanco cae a "(copia)" |
| `test_clone_missing_source_returns_404` | Clonar un origen inexistente devuelve 404 |
| `test_delete_host_with_checks` | `delete?with_checks` elimina single-bind y desvincula checks de clúster |
| `test_delete_host_without_checks_keeps_them` | Delete sin `with_checks` conserva los checks |
| `test_clone_label_uses_module_template` | El label del clon usa la plantilla de discovery con el nuevo nombre |
| `test_clone_blanks_cluster_node` | Clonar limpia la identidad de nodo proxmox, conserva el resto |
| `test_clone_resets_os_to_auto` | Clonar resetea el campo `os` a `auto` |
| `test_clone_duplicates_bound_module_checks` | Clonar duplica los checks vinculados, copiando campos+label |
| `test_clone_joins_cluster_membership` | Clonar un miembro de clúster lo une al clúster, sin duplicar |
| `test_kind_and_maintenance_persist` | Kind and maintenance persist |
| `test_status_derived_from_checks` | The listing carries a per-host monitoring status built from the |
| `test_module_counts_in_listing` | The listing reports modules added vs active per host: total = the |
| `test_create_requires_name` | Create requires name |
| `test_duplicate_name_rejected` | Duplicate name rejected |
| `test_update_restores_masked_secret` | Update restores masked secret |
| `test_update_unknown_uid` | Update unknown uid |
| `test_delete` | Delete |
| `test_probe_uses_submitted_fields` | Probe uses submitted fields |
| `test_probe_restores_masked_secret_from_stored_host` | Probe restores masked secret from stored host |
| `test_probe_requires_edit_permission` | Probe requires edit permission |
| `test_preview_and_apply` | Preview and apply |
| `test_preview_masks_secrets` | Preview masks secrets |
| `test_apply_requires_edit_permission` | Apply requires edit permission |
| `test_update_audits_field_diff_with_masked_secret` | Update audits field diff with masked secret |
| `test_added_ssh_profile_secret_masked_in_audit` | Regression: adding a whole SSH profile must NOT log the password / |
| `test_create_and_delete_audit_details` | Create and delete audit details |
| `test_migrate_audits_created_hosts` | Migrate audits created hosts |
| `test_history_delete_audited` | History delete audited |
| `test_history_delete_all_audited` | History delete all audited |
| `test_returns_bound_check_status` | Returns bound check status |
| `test_matches_derived_keys` | ram_swap derived keys (<uid>_ram) match their base bound item |
| `test_restores_masked_password_from_stored_item` | Restores masked password from stored item |
| `test_explicit_new_password_is_kept` | Explicit new password is kept |
| `test_test_check_individual` | Test check individual |
| `test_full_test_ssh_and_checks` | Full test ssh and checks |
| `test_module_test_no_ssh_skips_ssh` | A module-scoped test (no_ssh) runs the checks but not the SSH probe |
| `test_test_requires_edit_permission` | Test requires edit permission |
| `test_view_scoped_to_granted_server` | View scoped to granted server |
| `test_no_server_perm_forbidden` | No server perm forbidden |
| `test_view_only_cannot_edit_or_delete` | View only cannot edit or delete |
| `test_edit_and_delete_when_granted` | Edit and delete when granted |
| `test_server_add_can_add_host_bound_check` | Server add can add host bound check |
| `test_server_view_only_cannot_add_check` | Server view only cannot add check |
| `test_server_add_cannot_edit_existing_check` | Server add cannot edit existing check |
| `test_server_add_host_modules_growth_allowed_not_field_edit` | Server add host modules growth allowed not field edit |

## 57. Panel Web — Historial

**Archivo:** `tests/test_wa_history.py` — 2 tests

| Test | Qué comprueba |
|---|---|
| `test_index_label_from_item_label` | A series whose key matches a configured item shows that item's label |
| `test_index_label_falls_back_to_record_name` | ram_swap emits derived keys ("<uid>_ram") that are not real item keys, so |

## 58. Panel Web — Webhooks

**Archivo:** `tests/test_wa_webhook.py` — 35 tests

| Test | Qué comprueba |
|---|---|
| `test_disabled_returns_error` | Disabled returns error |
| `test_no_url_returns_error` | No url returns error |
| `test_no_requests_package` | No requests package |
| `test_post_success` | Post success |
| `test_put_method` | Put method |
| `test_get_method` | Get method |
| `test_http_error_returns_failure` | Http error returns failure |
| `test_network_exception` | Network exception |
| `test_placeholder_substitution` | Placeholder substitution |
| `test_default_body_template_used_when_empty` | Default body template used when empty |
| `test_hmac_signature_added` | Hmac signature added |
| `test_custom_headers_merged` | Custom headers merged |
| `test_invalid_headers_json_returns_error` | Invalid headers json returns error |
| `test_requires_auth` | Requires auth |
| `test_viewer_denied` | Viewer denied |
| `test_success_returns_ok` | Success returns ok |
| `test_disabled_returns_ok_false` | Disabled returns ok false |
| `test_stored_secret_kept_on_null` | Sending id + secret=null merges the stored secret from the webhooks store |
| `test_audit_ok_on_success` | Audit ok on success |
| `test_audit_fail_on_error` | Audit fail on error |
| `test_create_requires_auth` | Create requires auth |
| `test_list_requires_auth` | List requires auth |
| `test_create_and_list` | Create and list |
| `test_create_missing_url_fails` | Create missing url fails |
| `test_update` | Update |
| `test_delete` | Delete |
| `test_delete_not_found` | Delete not found |
| `test_test_by_id` | Test by id |
| `test_test_by_id_not_found` | Test by id not found |
| `test_secret_masked_in_list` | Secret masked in list |
| `test_audit_on_create` | Audit on create |
| `test_audit_on_delete` | Audit on delete |

## 59. Panel Web — Plantillas de notificación

**Archivo:** `tests/test_wa_notif_templates.py` — 47 tests

| Test | Qué comprueba |
|---|---|
| `test_default_returns_english` | Default returns english |
| `test_unknown_lang_falls_back_to_english` | Unknown lang falls back to english |
| `test_overrides_take_precedence` | Overrides take precedence |
| `test_overrides_ignore_unknown_keys` | Overrides ignore unknown keys |
| `test_overrides_ignore_empty_string_values` | Overrides ignore empty string values |
| `test_overrides_with_known_lang` | Overrides stack on top of language-specific built-in overlay |
| `test_none_overrides_same_as_no_overrides` | None overrides same as no overrides |
| `test_render_test_uses_custom_strings` | Render test uses custom strings |
| `test_render_alert_uses_custom_strings` | Render alert uses custom strings |
| `test_render_summary_uses_custom_strings` | Render summary uses custom strings |
| `test_render_test_without_strings_uses_lang` | Render test without strings uses lang |
| `test_get_requires_auth` | Get requires auth |
| `test_get_returns_defaults_and_overrides` | Get returns defaults and overrides |
| `test_put_requires_auth` | Put requires auth |
| `test_put_saves_overrides` | Put saves overrides |
| `test_put_get_round_trip` | Put get round trip |
| `test_put_ignores_unknown_keys` | Put ignores unknown keys |
| `test_put_empty_values_not_stored` | Put empty values not stored |
| `test_put_unknown_lang_returns_400` | Put unknown lang returns 400 |
| `test_delete_requires_auth` | Delete requires auth |
| `test_delete_resets_overrides` | Delete resets overrides |
| `test_delete_nonexistent_lang_is_ok` | Delete nonexistent lang is ok |
| `test_put_all_empty_clears_lang_entry` | Put all empty clears lang entry |
| `test_get_html_requires_auth` | Get html requires auth |
| `test_get_html_returns_structure` | Get html returns structure |
| `test_builtin_uses_placeholder_keys` | 'Load built-in' should return {test_title} not the real title text |
| `test_builtin_with_lang_uses_placeholder_keys` | Built-in with a language still returns {key} placeholders |
| `test_builtin_string_overrides_reflected` | String overrides saved for a lang are applied to built-in preview |
| `test_put_html_requires_auth` | Put html requires auth |
| `test_put_html_saves` | Put html saves |
| `test_put_html_round_trip` | Put html round trip |
| `test_delete_html_requires_auth` | Delete html requires auth |
| `test_delete_html_removes_entry` | Delete html removes entry |
| `test_put_html_unknown_type_returns_400` | Put html unknown type returns 400 |
| `test_apply_html_override_substitutes_strings` | apply_html_override replaces {key} with string values and runtime vars |
| `test_apply_html_override_two_pass` | String values containing {vars} are pre-interpolated with runtime kwargs |
| `test_apply_html_override_unknown_keys_unchanged` | Unknown {variables} are left as-is (not raised as errors) |
| `test_render_test_with_html_override` | render_test uses html_override when provided |
| `test_render_alert_with_html_override` | render_alert uses html_override; {item} substituted |
| `test_preview_requires_auth` | Preview requires auth |
| `test_preview_unknown_type_returns_400` | Preview unknown type returns 400 |
| `test_preview_alert_with_custom_html` | Preview alert with custom html |
| `test_preview_test_with_custom_html` | Preview test with custom html |
| `test_preview_summary_with_custom_html` | Preview summary with custom html |
| `test_preview_empty_html_uses_builtin` | Preview empty html uses builtin |
| `test_preview_respects_string_overrides` | Preview respects string overrides |
| `test_test_email_applies_html_and_string_overrides` | Test email applies html and string overrides |

## 60. Panel Web — Syslog

**Archivo:** `tests/test_wa_syslog.py` — 18 tests

| Test | Qué comprueba |
|---|---|
| `test_requires_auth` | Requires auth |
| `test_list_empty` | List empty |
| `test_list_and_filter` | List and filter |
| `test_sort_by_column` | Sort by column |
| `test_host_filter_matches_hostname_or_source` | Host filter matches hostname or source |
| `test_multi_value_filter` | Multi value filter |
| `test_exact_severity_filter` | Exact severity filter |
| `test_pagination_offset_limit` | Pagination offset limit |
| `test_date_range_filter` | Date range filter |
| `test_facets` | Facets |
| `test_status` | Status |
| `test_stats` | Stats |
| `test_stats_requires_auth` | Stats requires auth |
| `test_clear` | Clear |
| `test_null_field_uses_registry_default` | Null field uses registry default |
| `test_drops_requires_auth` | Drops requires auth |
| `test_drops_endpoint` | Drops endpoint |
| `test_worker_evaluates_stored_messages` | The event worker drains stored syslog rows by cursor and evaluates them (listener no longer evaluates inline) |

## 61. Panel Web — Gestor de eventos

**Archivo:** `tests/test_wa_events.py` — 27 tests

| Test | Qué comprueba |
|---|---|
| `test_requires_auth` | Requires auth |
| `test_crud` | Crud |
| `test_promoted_columns` | name/enabled/description are first-class columns, not buried in data |
| `test_validation` | Validation |
| `test_audit_event_fires_rule` | Audit event fires rule |
| `test_non_matching_audit_event_does_not_fire` | Non matching audit event does not fire |
| `test_disabled_rule_does_not_fire` | Disabled rule does not fire |
| `test_syslog_rule_matches_by_severity` | Syslog rule matches by severity |
| `test_cooldown_suppresses_second` | Cooldown suppresses second |
| `test_blank_cooldown_inherits_global` | Blank cooldown inherits global |
| `test_explicit_zero_overrides_global` | Explicit zero overrides global |
| `test_syslog_text_match` | Syslog text match |
| `test_log_records_test_send_and_last_fired` | Log records test send and last fired |
| `test_log_records_failure` | Log records failure |
| `test_channels_override_targets_only_those` | Channels override targets only those |
| `test_webhook_ids_restrict_destinations` | Webhook ids restrict destinations |
| `test_empty_webhook_ids_targets_all` | Empty webhook ids targets all |

## 62. Panel Web — Servicios

**Archivo:** `tests/test_wa_services.py` — 23 tests

### `TestServicesStatus`

| Test | Qué comprueba |
|---|---|
| `test_requires_auth` | `GET /services` sin autenticar devuelve 401 |
| `test_status_lists_all_services` | Lista los servicios core con flags state/controllable/embedded |
| `test_database_reports_driver_and_connectivity` | La tarjeta de BD reporta driver y conectividad, no controlable |
| `test_worker_reflects_history_activity` | El estado del worker refleja la actividad del historial |
| `test_external_runtime_overlaid_from_leader` | La tarjeta external superpone next/last-run desde el heartbeat del líder |
| `test_external_running_for_active_active_without_leader` | Active-active corriendo si cualquier instancia está viva |
| `test_external_not_running_when_all_stopped` | No corriendo cuando todas las instancias están paradas |

### `TestPoke`

| Test | Qué comprueba |
|---|---|
| `test_poke_reaches_stopped_instance` | Hace poke a la instancia parada-alcanzable, salta la caída |

### `TestDebugAccessor`

| Test | Qué comprueba |
|---|---|
| `test_debug_property_applies_log_level` | La propiedad `debug` (`set_from_config`) conmuta `enabled` |

### `TestExternalControl`

| Test | Qué comprueba |
|---|---|
| `test_external_monitoring_is_controllable` | El monitoring external es controlable, no embebido |
| `test_external_start_stop_writes_enabled` | Start/stop escribe el estado deseado `enabled` de monitoring |
| `test_external_control_preserves_other_config` | El control external preserva otras secciones de config |
| `test_external_events_stop_sets_enabled_false` | Parar events pone `enabled=false`, el worker queda ocioso |

### `TestMonitoringControl`

| Test | Qué comprueba |
|---|---|
| `test_start_then_stop` | Monitoring embebido: start y luego stop conmuta running |
| `test_unknown_service_404` | Start de servicio desconocido devuelve 404 |
| `test_bad_action_400` | Acción inválida devuelve 400 |

### `TestSyslogControl`

| Test | Qué comprueba |
|---|---|
| `test_start_disabled_is_409` | Arrancar syslog deshabilitado devuelve 409 (razón "disabled") |
| `test_start_stop_when_enabled` | Syslog habilitado: start/stop conmuta running |

### `TestIpbanService`

| Test | Qué comprueba |
|---|---|
| `test_ipban_service_registered` | ipban registrado embebido+controlable, expone contadores |
| `test_ipban_start_stop_toggles_enabled` | Start/stop conmuta `ipban_enabled` y estado |
| `test_ipban_control_preserves_other_config` | Conmutar preserva otras secciones de config |
| `test_ipban_heartbeat_detail_carries_counts` | El detalle del heartbeat lleva counts banned/watchlist/whitelist |

### `TestPermissions`

| Test | Qué comprueba |
|---|---|
| `test_control_requires_services_control` | El control requiere `services_control`; ver sigue permitido |


---

## 63. Watchful: keepalived

**Archivo:** `watchfuls/keepalived/tests/test_keepalived.py` — 13 tests

### `TestKeepalivedBasics`, `TestVipRollup`, `TestPriority`, `TestVipConfig`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | El módulo se inicializa con el nombre correcto | `name_module == 'watchfuls.keepalived'` | nombre distinto |
| `test_schema_is_cluster` | El esquema declara binding multi-host de cluster (columnas VIP, campo miembro `priority`) | flags de cluster presentes | flags ausentes |
| `test_declares_vip_provision_host` | El VIP se auto-aprovisiona como host vía `__provision_host__` (vip → vip_host_uid) | declaración con `address_field`/`link_field`/`name_template` | declaración incorrecta |
| `test_healthy_single_master` | Cluster sano con un único MASTER que sostiene el VIP | VIP OK, nodo master con `holds_vip=True`, resto `False` | roll-up incorrecto |
| `test_vip_down_no_holder` | Ningún nodo sostiene el VIP | VIP en fallo con severidad dura (no warning) | VIP marcado OK o warning |
| `test_split_brain_is_warning` | Dos nodos sostienen el VIP a la vez (split-brain) | VIP en fallo, severidad `warning`, `holders==2` | no detecta split-brain |
| `test_service_down_node_fails` | Un nodo con servicio inactivo | nodo en fallo pero VIP OK (otro lo sostiene) | VIP afectado erróneamente |
| `test_unreachable_node` | Un miembro inalcanzable por host_exec | nodo en fallo | nodo marcado OK |
| `test_maintenance_member_skipped` | Miembro en mantenimiento | nodo omitido (no en resultados) y VIP OK | nodo evaluado/fallado |
| `test_priority_ok_on_highest` | El VIP lo sostiene el nodo de mayor prioridad | check priority OK | fallo |
| `test_priority_warns_when_lower_holds_vip` | Un nodo de menor prioridad sostiene el VIP | priority en fallo, `warning`, `top_priority==150` | no avisa |
| `test_missing_vip_warns` | Item sin VIP configurado | VIP en fallo con `warning` | error duro o OK |
| `test_no_members_warns` | Item sin miembros vinculados | item en fallo con `warning` | error duro o OK |

---

## 64. Watchful: m365

**Archivo:** `watchfuls/m365/tests/test_m365.py` — 69 tests

**Postura del tenant** (14 tests, `TestExtendedChecks`): cinco comprobaciones que contestan
preguntas que el panel puede y un administrador normalmente no, porque cada una vive en un
informe que nadie abre dos veces al año — cobertura de MFA registrada, licencias asignadas a
cuentas que no entran —**nombrando qué SKU** se están desperdiciando, porque «10 de 11
inactivas» es una cifra sin respuesta—, cuántos administradores globales hay, dominios sin
verificar y avisos
de Microsoft con fecha límite de acción. Tres decisiones que los tests fijan porque son
fáciles de equivocar: **no haber entrado nunca cuenta** como licencia sin usar (es el caso más
claro de desperdicio), **una fecha ya pasada no es próxima** (está hecha o perdida), y un
**directorio vacío no incumple** el mínimo de MFA (0% de nadie es un número sin sujeto). Graph
aún llama *Company Administrator* al rol en algunos sitios, así que ambas grafías cuentan: sin
eso, un tenant lleno de admins se reportaría con cero.

Las licencias pasan a **una fila por SKU**, como salud de servicio ya hacía por servicio. Los
números detrás del veredicto —cuántas unidades hay y cuántas están tomadas— se calculaban y se
tiraban, dejando una fila que decía «4 SKU» y no podía contestar cuál se está llenando.

### `TestHelpers`, `TestSite`, `TestTenant`, `TestModule`, `TestListSites`, `TestCredentialAndProvision`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_fmt_bytes` | Formateo humano de bytes (`_fmt_bytes`) | `0 B`, `1.0 GB`, `1.5 GB` | formato distinto |
| `test_to_bytes` | Conversión unidad→bytes (`_to_bytes`), vacío = 0 | valores correctos GB/TB | conversión errónea |
| `test_csv_max` | Máximo de una columna de un CSV (`_csv_max`), vacío = 0 | devuelve 3000 | valor incorrecto |
| `test_ok_under_thresholds` | Uso bajo umbrales de % y espacio libre | site OK, `used=50.0`, `alert=90` publicado | fallo indebido |
| `test_over_percentage_warns` | Uso por encima del % configurado | site en fallo, `warning`, `used=95.0` | no avisa |
| `test_low_free_warns` | Espacio libre por debajo del mínimo (regla de free-space) | site en fallo con `warning` | no avisa |
| `test_percentage_off_when_module_default_zero` | Umbral % en 0 a nivel item y módulo | site OK, sin `alert` en other_data (barra neutra) | umbral falso publicado |
| `test_usage_pct_inherits_module_default` | Item con `usage_pct` en blanco hereda default de módulo (80) | site en fallo, `alert=80` heredado | no hereda |
| `test_free_min_inherits_module_default` | Item con `free_min` en blanco hereda default (10 GB) | site en fallo con `warning` | no hereda |
| `test_item_value_overrides_module_default` | `usage_pct` explícito de item gana sobre default de módulo | site OK con `alert=95` | usa default |
| `test_missing_credentials_warns` | Faltan credenciales (client_secret vacío) | item en fallo con `warning` | error duro o OK |
| `test_auth_failure_smoothed_then_alerts` | Fallo de auth con `alert=1` (sin ventana de suavizado) | item en fallo, mensaje con 'auth' | no alerta |
| `test_auth_failure_first_is_smoothed` | Fallo de auth con `alert=3`: primer fallo se suaviza | item reportado OK | alerta prematura |
| `test_tenant_usage_ok` | Uso de tenant bajo el máximo | tenant OK | fallo |
| `test_tenant_usage_over_warns` | Uso de tenant sobre el máximo | tenant en fallo con `warning` | no avisa |
| `test_init` | Inicialización del módulo | `name_module == 'watchfuls.m365'` | nombre distinto |
| `test_schema` | Esquema: secret sensible, unidades, `__status_render__` | flags correctos | esquema incorrecto |
| `test_test_connection` | Acción test_connection con token/site/drive mockeados | `ok=True`, mensaje con `25.0%` | fallo |
| `test_test_connection_missing_creds` | test_connection sin credenciales completas | `ok=False` | `ok=True` |
| `test_lists_sites_stripped_and_sorted` | Listado de sites (URL sin esquema, ordenado por display_name) | nombres ordenados, `kind='SharePoint'` | orden/formato erróneo |
| `test_list_sites_missing_creds_is_empty` | list_sites sin credenciales | lista vacía | no vacía |
| `test_list_sites_auth_error_is_empty` | list_sites con error de auth | lista vacía | excepción propagada |
| `test_list_sites_declared_in_actions` | list_sites en acciones y read-only; campo de descubrimiento con opción vacía | declaraciones presentes | ausentes |
| `test_declares_credential_type` | Credencial `m365_app` con campos tenant/client/secret (secret secreto) | declaración correcta | incorrecta |
| `test_credential_action_is_device_code` | Acción `provision_app` = wizard device-code (perfil m365), fuera de WATCHFUL_ACTIONS | declaración correcta | incorrecta |
| `test_declares_entraid_provision_roles` | Roles Entra ID declarados (`Sites.Read.All`, `Reports.Read.All`) | roles correctos | roles distintos |

---

## 65. Watchful: proxmox

**Archivo:** `watchfuls/proxmox/tests/test_proxmox.py` — 46 tests

### `TestProxmoxInit`, `TestProxmoxCheck`, `TestProxmoxAction`, `TestProxmoxProvision`, `TestProxmoxCredentialManager`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Inicialización del módulo | `name_module == 'watchfuls.proxmox'` | nombre distinto |
| `test_schema` | Esquema: host, auth_method (token/password), puerto 8006, verify_ssl | defaults correctos | esquema incorrecto |
| `test_empty_list` | Lista vacía no produce items | 0 items | items generados |
| `test_disabled_item` | Item deshabilitado | 0 resultados | evaluado |
| `test_cluster_quorate_ok` | Cluster con quórum y nodos online | cluster OK, `nodes_online==2` | fallo |
| `test_cluster_quorum_lost` | Cluster sin quórum | cluster en fallo | OK |
| `test_cluster_standalone` | Nodo único sin cluster | cluster OK, `standalone=True` | fallo |
| `test_cluster_caches_node_ips` | Cachea las IPs de los nodos del cluster | `node_ips` con ambas IPs | no cacheadas |
| `test_connection_failover_between_nodes` | Failover al siguiente nodo si el primero está caído | cluster OK vía 2º nodo | fallo total |
| `test_nodes_online_offline_maintenance` | Estados de nodo: online/offline/maintenance | n1 OK, n2 fallo (offline), n3 OK (maintenance) | clasificación errónea |
| `test_nodes_without_ha` | Nodos sin HA configurado (error al leer HA) | nodo OK, no marcado maintenance | fallo por error HA |
| `test_ceph_ok` | Ceph HEALTH_OK | ceph OK | fallo |
| `test_ceph_warn` | Ceph HEALTH_WARN | ceph en fallo | OK |
| `test_ceph_not_configured` | Ceph no instalado (rados_connect falla) | ceph OK/info | fallo |
| `test_network_iface_down` | Interfaz con autostart pero sin `active` | net en fallo, `eth1` en `down` | no detecta |
| `test_network_all_up` | Todas las interfaces activas | net OK | fallo |
| `test_updates_security_alerts` | Actualizaciones de seguridad presentes | updates en fallo, `security==1` | no alerta |
| `test_updates_count_informational` | Actualizaciones sin seguridad | updates OK, `total==2` (informativo) | fallo |
| `test_updates_up_to_date` | Sistema al día | updates OK, `total==0` | fallo |
| `test_storage_inactive_alerts` | Storage habilitado pero inactivo (deshabilitado ignorado) | storage en fallo, `down==['nfs1']` | no detecta |
| `test_storage_usage_over_threshold` | Uso de storage sobre umbral (used/total) | storage en fallo, `full==['local 95%']` | no avisa |
| `test_storage_all_ok` | Storage activo y bajo umbral | storage OK | fallo |
| `test_storage_threshold_zero_ignores_usage` | Umbral 0 → solo alerta por inactivo, nunca por uso | storage OK con uso 99% | fallo por uso |
| `test_maintenance_skips_per_node_checks` | Nodo cuyo host mapeado está en mantenimiento omite checks per-node | `pve/net/pve02` ausente, pve01 OK | evaluado/fallado |
| `test_member_host_maintenance_skips_node` | Nodo offline con host en mantenimiento se reporta como maintenance | nodo OK, `maintenance=True`, `host_name='srv-2'` | offline-error |
| `test_member_host_name_annotates_node` | Nodo online mapeado a host muestra el nombre del host | nodo OK, `host_name='srv-1'` en mensaje | sin anotación |
| `test_vip_used_when_no_host` | Solo VIP configurado (sin host miembro) conecta y ejecuta | cluster OK | no conecta |
| `test_list_nodes_returns_member_names` | list_nodes devuelve nombres de nodos ordenados/dedup | `ok=True`, `['pve01','pve02']` | lista incorrecta |
| `test_connection_error_threshold` | Fallo de conexión con `alert=2`: primer fallo aún efectivo | item presente, `error='timeout'` | alerta prematura |
| `test_test_connection_token` | test_connection con token (versión+cluster+ceph) | `ok=True`, mensaje con 'quórum OK' | fallo |
| `test_test_connection_password_ticket` | test_connection con password: login POST + GET con cookie | `ok=True`, mensaje 'standalone' | flujo de ticket erróneo |
| `test_provision_creates_token` | Provisión least-privilege: rol custom + usuario + ACL + token | `ok=True`, campos token, comandos pveum correctos | comandos ausentes |
| `test_provision_renew_rotates_secret_only` | mode=renew solo rota el secret (sin user/ACL) | token nuevo, remove+add token, sin role/user/acl | recrea todo |
| `test_provision_uses_bound_host_ssh_profile` | Provisión reutiliza el perfil SSH del host vinculado (`__host__`) | conn con address/port/user/password del host | ignora perfil |
| `test_provision_explicit_overrides_host_profile` | Valor explícito del modal gana sobre el perfil SSH del host | conn con datos explícitos | usa perfil host |
| `test_provision_verify_host_default_autoadd` | verify_host por defecto False salvo `ssh_verify_host` del perfil | False por defecto, True si activado | valor incorrecto |
| `test_provision_requires_ssh_credentials` | Provisión sin credenciales SSH | `ok=False`, mensaje con 'ssh' | continúa |
| `test_provision_ssh_error` | Error de conexión SSH | `ok=False`, mensaje 'auth failed' | excepción propagada |
| `test_provision_no_token_in_output` | Comando falla sin producir token | `ok=False`, mensaje 'permission denied' | falso éxito |
| `test_credential_overlays_token` | Credencial reutilizable (proxmox_auth) se superpone al item | resolved con token de la credencial | no aplicado |
| `test_schema_declares_credential` | Esquema declara credencial `proxmox_auth` | tipo y campos token/password presentes | ausentes |
| `test_catalog_exposes_provision_action` | credential_schemas expone acción provision_token con picker SSH y selector mode | inputs y opciones create/renew con labels i18n | declaración incompleta |
| `test_secondary_ssh_cred_overlay` | La ruta de acción superpone un `ssh_cred_uid` guardado sobre la config | `ssh_user`/`ssh_password` aplicados | no aplicado |

---

## 66. Watchful: snmp

**Archivo:** `watchfuls/snmp/tests/test_snmp.py` — 70 tests

### `TestEvaluate`, `TestActions`, `TestCheckFlow`, `TestAlertDebounce`, `TestCompileResultClassification`, `TestGetCategory`, `TestHttpFetchTimeout`, `TestGithubFolderParse`, `TestLooksLikeMib`, `TestLoadMibSources`, `TestKnownRepos`, `TestRepoTemplates`, `TestImportFromGithub`, `TestImportFromGithubAsync`, `TestMibCatalog`, `TestCompilePhase`, `TestCompileCancel`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_operators` | Operadores de evaluación de valor (any/contains/regex/eq/ne/gt/lt/gte/lte, fallback string, no-numérico, desconocido) — parametrizado | cada caso devuelve el booleano esperado | evaluación errónea |
| `test_actions_declared` | `discover` declarada; read-only ⊆ todas las acciones | subconjunto válido | inconsistente |
| `test_disabled_module_returns_empty` | Módulo deshabilitado | 0 items | items generados |
| `test_disabled_server_skipped` | Servidor deshabilitado | 0 items | evaluado |
| `test_disabled_check_skipped` | Check deshabilitado | 0 items | evaluado |
| `test_no_host_fails_gracefully` | Check sin host | item en fallo | excepción |
| `test_value_evaluated_on_success` | Se evalúa el valor obtenido (gt 42>10 OK, 5>10 fallo) | status correcto según valor | evaluación errónea |
| `test_threshold_requires_consecutive_failures` | Umbral `alert=3` requiere 3 ciclos consecutivos de fallo | OK 1/3, 2/3; DOWN en 3/3 y sigue DOWN | flip prematuro |
| `test_alert_one_fails_immediately` | `alert=1` falla al primer ciclo | item en fallo inmediato | suavizado |
| `test_success_resets_counter` | Un éxito resetea el contador de fallos | contador 2 → 0 tras recuperación | no resetea |
| `test_streak_survives_new_process` | La racha persiste entre procesos (mismo status.json) | fail 1/2 y luego 2/2 tras nuevo monitor | reinicia racha |
| `test_counter_change_marks_status_dirty` | Incremento de racha sin flip marca status dirty | `_status_counts_dirty=True` | no guarda |
| `test_all_compiled` | Clasificación pysmi: todo compilado | `ok=True`, `compiled=True`, `partial=False` | clasificación errónea |
| `test_failed_status_is_reported` | Regresión: un MIB 'failed' se reporta como fallo | `ok=False`, `failed==['A']` | reportado éxito |
| `test_missing_and_unprocessed_are_failures` | Estados missing/unprocessed son fallos | `ok=False` | `ok=True` |
| `test_partial_success` | Éxito parcial (uno compila, otro falla) | `ok=True`, `partial=True`, mensaje '1 compiled' | no marca parcial |
| `test_untouched_is_up_to_date` | Estado untouched = al día | `ok=True`, `compiled=False` | fallo |
| `test_borrowed_not_a_failure` | Estado borrowed no es fallo | `ok=True`, sin `failed` | reportado fallo |
| `test_category` | Mapeo tipo SNMP → categoría (numeric/string/ip/oid/unknown) — parametrizado | categoría correcta | mapeo erróneo |
| `test_http_reader_injects_timeout` | El lector HTTP pysmi inyecta timeout | `timeout==7` capturado | timeout ausente |
| `test_parse_ok` | Parseo de URL de carpeta GitHub (owner/repo/branch/subpath) — parametrizado | tupla esperada | parseo erróneo |
| `test_parse_rejects_non_github` | Rechaza URLs no-GitHub / inválidas — parametrizado | `None` | acepta |
| `test_looks_like` | Detección de nombre de fichero MIB — parametrizado | booleano esperado | detección errónea |
| `test_loads_and_orders` | Carga fuentes MIB de *.json ordenadas por `order` (clave interna eliminada) | `['Alpha','Beta']`, sin `order` | orden/limpieza erróneos |
| `test_scalar_dep_template_coerced_to_list` | `dep_templates` escalar se coacciona a lista | lista de un elemento | no coacciona |
| `test_skips_malformed_and_invalid` | Salta JSON roto / sin folder / URL no-GitHub | solo carga 'Good' | rompe import |
| `test_missing_directory_is_empty` | Directorio inexistente | lista vacía | error |
| `test_real_sources_dir_loads` | mib_sources/ enviado carga los repos conocidos | count == `_KNOWN_MIB_REPOS` ≥ 1 | discrepancia |
| `test_structure` | Cada repo conocido: folder parseable y dep_templates con `@mib@` | estructura válida | inválida |
| `test_extensions_covered` | Cada repo ofrece variante plana y sufijada de plantilla | ambas presentes | falta una |
| `test_splits_newline_and_comma` | `_repo_templates` divide por newline y coma | 3 plantillas | división errónea |
| `test_empty` | `_repo_templates` con vacío/espacios | lista vacía | no vacía |
| `test_recursive_import` | Import recursivo BFS (salta README/notes.md, recurre en sub/) | `ok=True`, `['BAR-MIB','FOO-MIB.txt']`, `count=2` | import erróneo |
| `test_non_recursive_skips_subfolders` | Import no recursivo omite subcarpetas | solo `['FOO-MIB.txt']`, `total=1` | recurre |
| `test_progress_reports_total_then_xy` | El callback aprende el total por adelantado y avanza X/total | primera llamada (0,2), última (2,2), total constante | reporta sin total |
| `test_missing_var_dir` | Import sin `__var_dir__` | `ok=False` | continúa |
| `test_bad_url` | Import con URL no-GitHub | `ok=False` | continúa |
| `test_concurrent_download_aggregates_counts` | Descargas concurrentes agregan bien (un fallo no corrompe) | `total=12`, `count=11`, un failed = 'MIB-3.txt' | agregación errónea |
| `test_import_action_requires_edit` | Acciones de import son escrituras (no read-only) | en WATCHFUL_ACTIONS y no en READ_ONLY | mal clasificadas |
| `test_start_poll_done` | Job async: start → poll → done con conteo | `imported=2`, `total=2`, `failed=0`, `result_ok=True`; job recolectado | flujo async roto |
| `test_start_rejects_bad_url` | start con URL no-GitHub | `ok=False` | continúa |
| `test_start_missing_var_dir` | start sin var_dir | `ok=False` | continúa |
| `test_status_unknown_job` | status de job desconocido | `ok=False` | `ok=True` |
| `test_status_poll_suppressed_in_audit` | Poll de job en curso no audita; poll final sí | None en curso, no-None al terminar | auditoría errónea |
| `test_start_audit_suppressed` | El arranque no se audita | `None` | audita |
| `test_audit_reports_counts_and_failed_names` | La auditoría reporta conteos y nombres fallidos | imported/failed/failed_names y nombres en `name` | datos ausentes |
| `test_start_run_keeps_failed_names` | El job retiene qué ficheros fallaron | `imported=2`, `failed=1`, `failed_names==['BAD-MIB.txt']` | pierde nombres |
| `test_write_read_roundtrip` | Roundtrip escribir/leer catálogo SQLite | escribe 2, lee idéntico | discrepancia |
| `test_read_caches_by_mtime` | Lectura cacheada por mtime | mismo objeto en 2ª lectura | recarga |
| `test_write_replaces_not_appends` | Escribir reemplaza, no añade | queda 1 símbolo (sysDescr) | acumula |
| `test_missing_catalog_reads_empty` | Catálogo inexistente | lista vacía | error |
| `test_needs_rebuild_when_missing` | Necesita rebuild si falta; no si nada más nuevo | True sin catálogo, False tras escribir | lógica errónea |
| `test_needs_rebuild_when_compiled_newer` | Rebuild si un compilado es más nuevo que la DB | `True` | `False` |
| `test_get_all_symbols_reads_catalog` | get_all_symbols sirve del catálogo cacheado | `ok=True`, símbolos sysDescr/ifOperStatus | recarga pysnmp |
| `test_get_all_symbols_no_var_dir` | get_all_symbols sin var_dir | `symbols==[]` | error |
| `test_delete_compiled_discards_without_rebuild` | Borrar MIB compilado descarta el catálogo sin reconstruir inline | catálogo eliminado, sin rebuild | reconstruye |
| `test_initial_phase_is_compiling` | El job de compilación arranca en fase 'compiling' | `phase=='compiling'` | fase distinta |
| `test_phase_transitions_to_indexing` | Transición de fase a 'indexing' | fase 'indexing' observable | no transiciona |
| `test_action_registered_and_not_read_only` | `compile_mibs_cancel` registrada y no read-only | presente y no read-only | mal clasificada |
| `test_cancel_sets_job_event` | Cancelar activa el evento del job | `ok=True`, `cancelling=True`, event set | no cancela |
| `test_cancel_unknown_job` | Cancelar job desconocido | `ok=True`, `cancelling=False` | error |
| `test_status_omits_cancel_event` | El `threading.Event` no llega al JSON de status | `_cancel` ausente, `phase` presente | fuga del event |
| `test_should_cancel_stops_resolver_loop` | should_cancel True corta el bucle antes de compilar | `cancelled=True`, `compiled=False` | compila igual |

---

## 67. Watchful: ping — get_conf_in_list (tipos de clave)

**Archivo:** `watchfuls/ping/tests/test_get_conf_in_list.py` — 12 tests

### `TestGetConfInListTypes`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_opt_find_enum` | IntEnum usa `.name` como clave de búsqueda | devuelve `'MyDevice'` | valor incorrecto |
| `test_opt_find_str` | str se usa directamente como clave | devuelve `'MyDevice'` | valor incorrecto |
| `test_opt_find_list` | list se usa como ruta de claves | devuelve `'MyDevice'` | valor incorrecto |
| `test_opt_find_int` | int se convierte a str | devuelve `'found_it'` | valor incorrecto |
| `test_opt_find_float` | float se convierte a str | devuelve `'pi_value'` | valor incorrecto |
| `test_opt_find_tuple` | tuple se convierte a list | devuelve `'MyDevice'` | valor incorrecto |
| `test_opt_find_invalid_type_raises_type_error` | Tipo no soportado (set) lanza TypeError | `TypeError` con 'opt_find is not valid type' | no lanza |
| `test_opt_find_none_raises_type_error` | None lanza TypeError | `TypeError` | no lanza |
| `test_opt_find_bytes_raises_type_error` | bytes lanza TypeError | `TypeError` | no lanza |
| `test_opt_find_enum_not_found_returns_default` | Enum inexistente en config retorna default | devuelve `'fallback'` | otro valor |
| `test_opt_find_str_not_found_returns_default` | str inexistente en config retorna default | devuelve `'fallback'` | otro valor |
| `test_opt_find_bool_matches_int_branch` | bool (subclase de int) cae en la rama int → str | devuelve `'bool_as_key'` | rama incorrecta |

---

## 68. Servicios — Cola de comandos (ServiceCommandsStore)

**Archivo:** `tests/test_service_commands_store.py` — 6 tests

### `TestServiceCommandsStore`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_enqueue_and_list` | Encolar un comando y recuperarlo con `list_recent` | Devuelve id > 0 y la fila con action/args/created_by correctos y claimed_at/done_at a None | Id inválido o campos no persistidos |
| `test_claim_is_exclusive` | La reclamación de un comando es exclusiva entre instancias | El primer `claim_next` obtiene la fila; el segundo devuelve None | Dos reclamadores obtienen la misma fila |
| `test_claim_filters_by_service` | `claim_next` solo devuelve comandos de su propio servicio | Reclamar 'monitoring' da None y 'syslog' sí obtiene la fila | Reclama comando de otro servicio |
| `test_complete_records_outcome` | `complete` registra resultado y marca de fin | ok=True, result guardado y done_at no nulo | Resultado o done_at no persistidos |
| `test_fifo_order` | Los comandos se reclaman en orden FIFO | Se obtiene 'reload' antes que 'run_now' | Orden alterado |
| `test_prune_drops_finished` | `prune` elimina comandos finalizados antiguos y conserva los recientes/pendientes | Elimina 1 (el antiguo) y mantiene 'run_now' | Poda pendientes o recientes |

---

## 69. Servicios — Registro de heartbeat / estado (ServiceInstancesStore)

**Archivo:** `tests/test_service_instances_store.py` — 6 tests

### `TestServiceInstancesStore`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_empty` | Registro vacío inicialmente | `list_instances` y `list_for` devuelven listas vacías | Devuelve filas inexistentes |
| `test_heartbeat_insert_then_update` | Primer heartbeat inserta y el segundo hace upsert de la misma fila | Campos persistidos; segundo heartbeat actualiza running/detail y mantiene started_at estable | started_at cambia o se duplica la fila |
| `test_list_for_filters_by_service` | `list_for` filtra instancias por service_key | Devuelve solo las instancias del servicio pedido | Incluye instancias de otro servicio |
| `test_mark_down` | `mark_down` marca una instancia como caída | La instancia queda con running=False | Sigue marcada como activa |
| `test_clear_others_removes_same_host_restarts` | `clear_others` elimina reinicios previos del mismo proceso embebido en el host | Elimina 2 (PIDs viejos) y conserva la actual, la réplica de otro host y otro servicio | Borra réplicas ajenas o la instancia vigente |
| `test_prune_drops_stale_rows` | `prune` elimina instancias con last_seen caducado | Elimina 1 (la antigua) y conserva 'new' | Poda la reciente o conserva la obsoleta |

---

## 70. Servicios — Lease de líder único HA (ServiceLeaderStore)

**Archivo:** `tests/test_service_leader_store.py` — 8 tests

### `TestServiceLeaderStore`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_empty_has_no_leader` | Sin lease no hay líder | `current_leader` es None y `list_leaders` vacío | Devuelve líder inexistente |
| `test_acquire_then_others_blocked` | Adquirido el lease, otros contendientes quedan bloqueados | A adquiere; B recibe False y A sigue siendo líder | B roba un lease vivo |
| `test_holder_can_renew` | El poseedor puede renovar su propio lease | Reintento de A devuelve True (renovación idempotente) | La renovación falla |
| `test_failover_after_expiry` | Tras expirar el lease, otro puede tomar el relevo | Sin líder vivo; B adquiere y pasa a ser líder | El lease caducado sigue bloqueando |
| `test_only_one_wins_an_expired_lease` | Solo uno gana un lease expirado en competencia | B obtiene True y C False; B queda de líder | Ambos ganan o gana el equivocado |
| `test_release_enables_immediate_failover` | `release` libera y permite relevo inmediato | Tras liberar A no hay líder y B adquiere | El lease sigue retenido |
| `test_release_by_non_holder_is_noop` | Liberar sin ser poseedor no tiene efecto | A sigue siendo líder tras el release de B | B libera un lease ajeno |
| `test_keys_are_independent` | Los leases por service_key son independientes | A adquiere 'monitoring' y 'events' por separado | Un lease interfiere con otro |

---

## 71. Panel Web — API de comandos de servicio

**Archivo:** `tests/test_wa_service_commands.py` — 6 tests

### `TestServiceCommands`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_requires_auth` | El endpoint exige autenticación | Responde 401 sin sesión | Permite acceso anónimo |
| `test_bad_action_400` | Rechaza acciones no válidas | 400 con reason 'bad_action' | Acepta acción desconocida |
| `test_unknown_service_404` | Rechaza servicios inexistentes | 404 con reason 'unknown_service' | Acepta servicio inexistente |
| `test_read_only_service_rejected` | Un servicio de solo lectura no admite comandos | 409 con reason 'not_controllable' | Encola comando sobre servicio no controlable |
| `test_reload_enqueues_and_runs_when_embedded` | Con el monitor embebido el comando se ejecuta sincrónicamente | 200, ok=True, command_id; fila reclamada y completada (done_at, ok) | Comando no drenado en el proceso local |
| `test_enqueued_only_when_external` | Con worker externo el comando solo se encola | 200, ok=True; fila con claimed_at y done_at a None | El proceso web ejecuta un comando ajeno |

---

## 72. Servicios — Listener HTTP de control (ControlServer)

**Archivo:** `tests/test_control_server.py` — 9 tests

### `TestControlServer`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_health_no_auth` | `/control/health` responde sin token | 200 con ok/key correctos y version desde lib.__version__ | Exige token o versión errónea |
| `test_reconcile_requires_token` | `/control/reconcile` exige token | 401 sin Authorization | Ejecuta sin token |
| `test_reconcile_wrong_token` | Rechaza token incorrecto en reconcile | 401 y no se ejecuta la reconciliación | Acepta token inválido |
| `test_reconcile_runs_with_token` | Reconcile válido dispara la reconciliación | 200, running=True y contador reconciled=1 | No reconcilia con token correcto |
| `test_unknown_path_404` | Ruta desconocida devuelve 404 | 404 en `/control/nope` | Responde otra cosa |
| `test_info_requires_token` | `/control/info` exige token | 401 sin Authorization | Devuelve snapshot sin token |
| `test_info_returns_snapshot_with_token` | Info válida devuelve snapshot del servicio | 200 con key, version '1.2.3' y datos de db | Snapshot incompleto o sin auth |

### `TestStartControlServer`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_no_token_means_disabled` | Sin SS_CONTROL_TOKEN el servidor no arranca | `start_control_server` devuelve None | Arranca sin token |
| `test_started_when_token_set` | Con token definido el servidor arranca y publica su URL | Devuelve instancia y fija `_control_url` para el heartbeat | No arranca o no anuncia la URL |

---

## 73. Servicios — Helpers de heartbeat (db_summary / app_version)

**Archivo:** `tests/test_heartbeat_helpers.py` — 6 tests

### `TestDbSummary`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_sqlite_uses_basename` | SQLite resume la ruta a su basename | Devuelve driver sqlite, host None y name 'data.db' | Conserva ruta completa |
| `test_sqlite_default_name` | Nombre por defecto cuando falta config | name 'data.db' con None y respeta el fallback pasado ('syslog.db') | No aplica el nombre por defecto |
| `test_mysql_keeps_host_and_name` | MySQL conserva host y name | Devuelve driver/host/name intactos | Altera host o name |
| `test_engine_and_type_aliases` | Acepta alias 'engine' y 'type' para el driver | driver resuelto a 'postgresql' y 'mariadb' | Ignora los alias |

### `TestAppVersion`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_uses_lib_version` | La versión proviene de lib.__version__ | `app_version` coincide con __version__ | Devuelve otra versión |
| `test_not_overridable_by_env` | La versión no es sobreescribible por entorno | Ignora SS_VERSION y refleja el código en ejecución | El env sobrescribe la versión |

---

## 74. Panel Web — Layout de la config UI (registry-driven)

**Archivo:** `tests/test_config_layout.py` — 9 tests

### `TestLayoutCoherence` — Coherencia layout ↔ registro

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_tabs_and_cards_present` | `config_layout()` devuelve tabs y cards, cada tab con `id`/`label_key`/`icon` | Ambas listas no vacías y tabs completos | Si falta alguna lista o clave |
| `test_every_card_targets_a_real_tab` | Cada card apunta a un `tab` existente en `TABS` | Todos los `card['tab']` están en los ids de tabs | Si una card referencia un tab desconocido |
| `test_card_is_generic_xor_bespoke` | Cada card tiene exactamente uno de `fields` (genérica) o `renderer` (a medida) | XOR se cumple en todas las cards | Si una card tiene ambos o ninguno |
| `test_generic_cards_have_fields` | Las cards genéricas declaran al menos un campo en `fields` | Toda card genérica tiene `fields` no vacío | Si una card genérica no tiene campos |
| `test_generic_fields_exist_in_registry` | Los `fields` de cada card existen en `registry_defaults()` | Todo campo está registrado | Si un campo no está en el registro |
| `test_no_field_placed_in_two_cards` | Ningún campo aparece en dos cards | Cada campo en una sola card | Si un campo se repite entre cards |
| `test_card_ids_unique` | Los `id` de card no se repiten | Todos únicos | Si hay ids duplicados |

### `TestLayoutEndpoint` — Endpoint `/api/v1/config/layout` (skip si no hay Flask)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_requires_auth` | El endpoint exige autenticación | Sin sesión responde 401 | Si devuelve otro código |
| `test_returns_layout` | Autenticado devuelve el layout | 200 con tabs `general`/`monitoring`/`auth` y alguna card con `renderer='database'` | Si falta algún tab o la card database |

---

## 75. Providers — Provisioning de apps Entra ID (Graph)

**Archivo:** `tests/test_entraid_provision.py` — 26 tests

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_provisions_app_with_requested_roles` | `provision_module_app` crea app app-only con solo los roles Graph pedidos y consentimiento admin | Devuelve tenant/client_id/secret; app declara `r-sites`+`r-reports` y `appRoleAssignments` para ambos sobre `graph-sp` | Si incluye roles no pedidos o falta consentimiento |
| `test_reused_for_a_different_app_and_roles` | El mismo helper genérico reutilizado con otro nombre y otro set de roles (estilo Intune) sin tocar código | App creada con el `displayName` dado y exactamente `r-device`+`r-user`, consentidos | Si el nombre o los roles no coinciden |
| `test_provision_entra_app_multi_resource_roles_and_scopes` | `provision_entra_app` con varias APIs, mezclando roles de aplicación y scopes delegados | `requiredResourceAccess` declara ambos recursos con tipos Role/Scope; `appRoleAssignments` por SP correcto; `oauth2PermissionGrant` del scope sobre `graph-sp` | Si falta un recurso, tipo, assignment o grant |
| `test_provision_entra_app_sso_style_options` | Opciones SSO-OIDC declarativas: redirect URIs web, claim de grupos y `require_assignment` | App declara `redirectUris`, `groupMembershipClaims='SecurityGroup'` y claim `groups`; PATCH de `appRoleAssignmentRequired=True` en el SP nuevo | Si falta alguna opción o el PATCH |
| `test_app_only_stays_minimal_without_sso_options` | Omitir opciones SSO deja una app app-only mínima | Sin `web`/`groupMembershipClaims` y sin PATCH | Si añade web/claims o hace PATCH |
| `test_provision_endpoint_accepts_inline_spec` | El endpoint device-code acepta un spec inline (sin `profile` de módulo) e inicia el flujo | 200 con `flow_token` y sin `error` | Si rechaza o no arranca el flujo |
| `test_provision_endpoint_rejects_empty_spec` | Endpoint sin profile ni permisos | 400 con `error` | Si arranca un flujo igualmente |
| `test_module_entraid_provision_discovers_declarations` | `module_entraid_provision()` descubre declaraciones de app de los módulos | `m365` declara `app_roles` esperados; `ping` no aparece | Si falta m365 o aparece un módulo sin provisioning |
| `test_missing_role_raises` | Rol inexistente en el SP de Graph | Lanza `RuntimeError` mencionando el rol (`Nope.Read`) | Si no lanza o el mensaje no lo cita |

---

## 76. Hosts — Primitivas de resolución (lib/hosts/resolve.py)

**Archivo:** `tests/test_hosts_resolve.py` — 7 tests

### `TestHostProfileSpecs` — Normalización de specs de perfil

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_dict_becomes_single_element_list` | Un dict se envuelve en lista de un elemento | Devuelve `[spec]` | Si no lo envuelve |
| `test_list_is_kept_dropping_non_dicts` | Una lista se conserva descartando los no-dict | Solo quedan los dicts (`a`, `b`) | Si mantiene `'nope'`/`None` o descarta dicts |
| `test_none_and_other_types_give_empty` | `None` y tipos no soportados | Devuelven `[]` | Si devuelven algo distinto de lista vacía |

### `TestResolveOs` — Resolución del SO

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_concrete_value_is_lowercased` | Un valor concreto de SO se pasa a minúsculas | `'Linux'`→`linux`, `'WINDOWS'`→`windows` | Si no normaliza |
| `test_auto_local_resolves_to_platform` | `auto`/vacío/`None` en local resuelven al SO de la plataforma | Devuelve `local_os()` | Si no resuelve al SO local |
| `test_auto_remote_keeps_auto_by_default` | `auto` remoto se mantiene para resolver luego por SSH | Devuelve `'auto'` | Si lo resuelve antes de tiempo |
| `test_auto_remote_honours_remote_default` | `auto` remoto con `remote_auto` dado (flujo de descubrimiento web) | Devuelve el default (`'linux'`) | Si ignora `remote_auto` |

---

## 77. Hosts — Hook de hosts aprovisionados

**Archivo:** `tests/test_provisioned_hosts.py` — 7 tests

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_creates_and_links_host` | El hook crea un host desde el `address_field` y estampa su uid en el `link_field` | Host con `address` correcto, `name` según `name_template` y `kind='local'` (sin perfil ssh) | Si no crea/vincula o usa nombre/kind erróneos |
| `test_idempotent` | Re-ejecutar con los mismos datos no duplica | Mismo uid y un solo host | Si crea un host duplicado |
| `test_syncs_address_on_change` | Cambiar el address del item sincroniza el host vinculado | El host actualiza su `address`, sin duplicar | Si no sincroniza o duplica |
| `test_no_address_no_host` | Item sin address | No crea host ni añade `link_field` | Si crea host o estampa uid |
| `test_module_without_declaration_is_noop` | Módulo cuyo schema no declara `__provision_host__` | Se salta, no crea hosts | Si crea algún host |
| `test_adopts_existing_host_by_name` | Item sin link adopta un host existente con el nombre determinista (anti-duplicación) | Reutiliza el uid existente, un solo host, address sincronizado | Si crea un duplicado |
| `test_returns_assignments_for_roundtrip` | El hook devuelve los links establecidos para round-trip; re-run no repite | Devuelve una asignación (`field`/`item`/`uid`); segunda ejecución devuelve `[]` | Si no devuelve la asignación o repite en la segunda pasada |

---

## 78. Panel Web — Política de bind del servidor web

**Archivo:** `tests/test_wa_server.py` — 7 tests

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_bind_all_ok` | Una interfaz alcanzable bindea sin fallos | `servers=['127.0.0.1']`, `failed=[]` | Si reporta fallos o no bindea |
| `test_bind_skips_unbindable_and_keeps_good` | Fallo parcial: la interfaz mala se reporta, la buena sigue bindeando | Buena en `servers`, mala en `failed` con un `OSError` | Si tumba el bind bueno o no reporta el malo |
| `test_run_aborts_when_no_interface_binds` | Fallo total: `run()` hace hard-exit (`os._exit`) en vez de fingir servir | `SystemExit` con código 1 | Si no aborta o el código no es 1 |
| `test_parse_excluded_ranges_reads_data_rows_only` | `parse_excluded_ranges` sobre salida `netsh` ignora cabeceras/guiones/`*` | Devuelve solo los pares de enteros | Si incluye ruido o pierde rangos |
| `test_port_excluded_matches_range` | `port_excluded` detecta si un puerto cae en un rango reservado | 8080→`(8054,8153)`; 18080→`None` | Si no detecta o falsea el rango |
| `test_run_abort_hints_windows_reserved_range` | Un bind fallido en puerto reservado explica la causa Windows | stderr contiene `Windows`, `winnat` y `config.json` | Si falta la pista en el mensaje |
| `test_default_port_windows_reserved_state_is_visible` | (Solo Windows, informativo) si el puerto web por defecto cae en un rango reservado vivo | Skip con diagnóstico si está reservado; sigue si no | Es no-fatal: nunca falla, solo salta |

---

## 79. Panel Web — SCIM 2.0 (aprovisionamiento)

**Archivo:** `tests/test_wa_scim.py` — 18 tests

> Las pruebas unitarias del servicio SCIM (autenticación Bearer, parseo de filtros, mapeo de campos de usuario) están en `tests/test_scim_service.py`, documentadas aparte en §85.

### `TestScimAuth`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_disabled_rejected` | SCIM desactivado | 401 aun con token válido | Responde el recurso |
| `test_no_token_rejected` | Petición sin Authorization | 401 | Deja pasar |
| `test_wrong_token_rejected` | Bearer token incorrecto | 401 | Acepta el token |
| `test_spconfig_ok` | ServiceProviderConfig con token válido | 200, `patch.supported=true` | Otro código/capacidad |

### `TestScimUsers`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_create_user` | POST /Users crea usuario | 201; usuario con `auth_source='scim'`, email/externalId/enabled | No crea o campos erróneos |
| `test_duplicate_conflicts` | userName ya existente | 409 en el segundo POST | Duplica |
| `test_filter_by_username` | `filter=userName eq "x"` (probe del IdP) | ListResponse con 1; desconocido → totalResults 0 (no 404) | Filtro incorrecto |
| `test_get_and_patch_deactivate` | GET/{id} y PATCH `active:false` | 200; usuario `enabled=False` | No desactiva |
| `test_delete_user` | DELETE /Users/{id} | 204; usuario eliminado del store | No borra |
| `test_missing_username_400` | POST sin userName | 400 | Crea igualmente |
| `test_update_audits_before_after` | PATCH `active:false` y luego un no-op | Audita `scim_user_updated` con `before/after` **solo del campo cambiado** (`{enabled:true}`→`{enabled:false}`); el no-op no genera otra entrada | No audita, incluye campos sin cambio, o audita el no-op |

### `TestScimGroups`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_create_group_with_members` | POST /Groups con miembros | 201; grupo con `source='scim'` (persiste tras recarga) y uid en `user.groups`; miembros en el GET | No crea, no vincula o no marca `source` |
| `test_patch_remove_member` | PATCH `remove` de un miembro | 200; grupo fuera de `user.groups` | No lo quita |
| `test_delete_group_unlinks_members` | DELETE /Groups/{id} | 204; grupo borrado y desvinculado de los miembros | No desvincula |

## 80. Panel Web — Utilidades genéricas (`/api/v1/util/*`)

**Archivo:** `tests/test_wa_util.py` — 8 tests

### `TestUtilToken` — `GET /api/v1/util/token`

| Test | Qué prueba | Espera | Falla si |
|------|-----------|--------|----------|
| `test_requires_auth` | Sin sesión | 401 | Deja pasar |
| `test_returns_hex_token` | Token por defecto | 200; 64 chars hex (32 bytes) | Longitud/formato erróneo |
| `test_respects_bytes_and_is_random` | `?bytes=16` dos veces | 32 chars cada uno y distintos | No respeta tamaño o repite |
| `test_bytes_clamped` | `bytes=1` y `bytes=9999` | Clamp a 16 (32 chars) y 128 (256 chars) | No aplica el clamp |

### `TestPublicBaseUrl` — `WebAdmin.public_base_url()`

| Test | Qué prueba | Espera | Falla si |
|------|-----------|--------|----------|
| `test_config_override_wins` | `public_url` fijado (proxy) | `https://ss.dominio.com` aunque se sirva por IP | Usa el host de la petición |
| `test_config_override_respects_force_https` | Override con `force_https=false` | `http://…` | Fuerza https |
| `test_autodetect_from_request` | Sin override, con petición | Deriva de `request.host_url` (proxy-aware) | No auto-detecta |
| `test_fallback_outside_request` | Sin override ni contexto | `http://localhost:<port>` | Otro fallback |

---

## 81. Seguridad (regresiones) y Portabilidad multi-motor

**Archivos:** `tests/test_security_regressions.py`, `tests/test_db_portability.py`, `tests/test_db_portability_live.py`

### `test_security_regressions.py` — regresiones de la auditoría de seguridad
Cada test blinda un arreglo para que no vuelva a colarse: lectura anónima del endpoint de widgets del Overview (exige sesión), escalada de privilegios por rol/grupo (`_role_grantable`/`_groups_grantable` — un no-admin no puede asignar admin ni por rol, ni por rol *custom* superior, ni por pertenencia al grupo Administrators), cifrado de `graph_secret`, mapeo grupo→rol LDAP exacto (no por subcadena; casa DN completo o CN), toma de cuenta SSO (no convierte cuenta local), y `parse_manual_ban` con duración negativa.

### `test_db_portability.py` — portabilidad SQL (offline)
Un conector-stub que **graba el SQL** con `KIND='mysql'` verifica que el SQL crudo de los stores **cita los identificadores reservados** (`key`/`virtual`/tabla `groups`/`user`) con `quote_ident`, y que `quote_ident` es dialect-aware (backticks MySQL / comillas SQLite+PG). Caza cualquier futura reservada sin comillas sin necesidad de un motor real.

### `test_db_portability_live.py` — verificación contra MySQL/PostgreSQL reales (opt-in)
Corre los stores contra **MySQL/MariaDB** y/o **PostgreSQL** reales (los motores de producción), cubriendo lo que SQLite no detecta: reservadas, `CAST`, `json_extract`/concat por dialecto, upsert por rowcount (`FOUND_ROWS`), rebuild de migración que preserva datos, introspección de esquema y elección de líder. **Opt-in por variables de entorno** (si no están, se salta entero):

Variables (una por conexión; si falta el `*_HOST`, ese motor se salta):

| MySQL/MariaDB | PostgreSQL |
|---|---|
| `SS_TEST_MYSQL_HOST` (+ `_PORT`=3306) | `SS_TEST_PG_HOST` (+ `_PORT`=5432) |
| `SS_TEST_MYSQL_USER` / `_PASSWORD` / `_DB` | `SS_TEST_PG_USER` / `_PASSWORD` / `_DB` |

Lo más cómodo es un fichero **`src/tests/.env.test`** (está en `.gitignore` — **no se versiona**, contiene credenciales) con esas variables. `src/conftest.py` lo **carga automáticamente** para toda la suite (no hace falta `source`): basta con que el fichero exista. Las variables ya presentes en el entorno real tienen prioridad (CI / export inline mandan sobre el fichero).

```bash
# desde src/ — el .env.test se auto-carga; solo hay que ejecutarlo en serie:
.venv/Scripts/python -m pytest -n0 -q tests/test_db_portability_live.py
```

> Ejecútalo con **`-n0`** (serie): usan nombres de tabla fijos, así que en paralelo colisionarían. Por eso, bajo `-n auto` (suite completa) estos tests se **saltan** automáticamente (aunque el `.env.test` esté cargado) con el aviso *"live DB tests must run serially - use -n0"*.

> Usa una **BD scratch** y ejecútalo con `-n0`: crea y borra tablas con nombres fijos, así que en paralelo colisionaría. La CI debería inyectar esas variables (secretas) apuntando a un MySQL y un PostgreSQL de test para cubrir la portabilidad de motor de forma continua.

---

## 82. Servicios — IP-ban (jail, store, integración)

**Archivo:** `tests/test_wa_ipban.py`

### `TestIpBanShared` — Estado compartido entre procesos

| Test | Qué comprueba |
|---|---|
| `test_counters_survive_restart` | Un manager nuevo sobre el mismo store conserva las 4 ofensas; la 5ª banea |
| `test_counter_shared_across_processes` | Dos managers sobre un store comparten el contador; la 4ª ofensa banea y el otro lo ve |
| `test_unban_shared_across_processes` | Un baneo de un manager es visible en el otro; el desbaneo se propaga |

### `TestIpBanManager` — Lógica de baneo

| Test | Qué comprueba |
|---|---|
| `test_auth_track_bans_at_threshold` | No banea por debajo de 3 `login_failed`; banea exactamente en el 3º |
| `test_authz_track_more_tolerant` | No banea a 4 `forbidden`; banea en el 5º (umbral authz 5) |
| `test_escalation_to_permanent` | Cuatro baneos sucesivos → flags `[False, False, False, True]` |
| `test_whitelist_never_bans` | IP en whitelist nunca baneada tras 10 ofensas; baneo explícito devuelve `None` |
| `test_loopback_always_whitelisted` | `127.0.0.1` nunca baneada tras 10 ofensas |
| `test_manual_ban_and_unban` | Baneo manual con duración 0 es permanente (`until` `None`); unban `True` y luego `False` |
| `test_watchlist_lists_pending_offenders` | Ofensores con total/remaining correctos; el más cercano al baneo primero |
| `test_banned_ip_leaves_watchlist` | Una IP baneada en el umbral desaparece de la lista de ofensores |
| `test_whitelisted_never_in_watchlist` | IP en whitelist con ofensas → lista de ofensores vacía |
| `test_disabled_never_blocks` | Deshabilitado, un baneo registrado no bloquea (`is_banned` `False`) |
| `test_expired_ban_stops_blocking` | Tras expirar la duración, `is_banned` devuelve `False` |

### `TestIpBanStore` — Persistencia

| Test | Qué comprueba |
|---|---|
| `test_upsert_load_delete` | Upsert carga con level/until correctos; delete devuelve `True` y elimina |
| `test_permanent_survives_load` | Baneo permanente (`until` `None`) recarga con `until` aún `None` |

### `TestIpBanIntegration` — Endpoints y efecto HTTP

| Test | Qué comprueba |
|---|---|
| `test_granular_permissions` | Rol viewer: endpoints de vista 200; mutaciones POST/DELETE 403 |
| `test_manual_ban_blocks_ip` | Baneo manual → 403 para la IP atacante; admin en whitelist sin afectar (200) |
| `test_manual_ban_validates_ip_and_caps_reason` | No-IP rechazado 400; razón demasiado larga recortada a ≤200 chars |
| `test_unban_via_api` | IP baneada 403; tras DELETE de unban ya no es 403 |
| `test_offenses_auto_ban` | Tres 401 alcanzan el umbral; la siguiente petición es 403 |
| `test_whitelisted_ip_rejected_by_api` | Banear loopback vía API devuelve 400 |
| `test_watchlist_via_api` | 3 ofensas bajo umbral → total 3, remaining 2, sin baneos |
| `test_clear_watchlist_via_api` | Ofensor presente; tras clear devuelve cleared y vacía ofensores |
| `test_history_via_api` | Dos hits → 2 filas de historial, categoría "unauthorized" con `ts` |
| `test_whitelist_crud_and_effect` | Whitelist registra creador/hora, aplica, valida, lista y el delete lo levanta |
| `test_block_actions` | El cuerpo del 403 difiere por acción web (page/minimal/reject) |
| `test_per_ban_action_override` | Override "reject" por-baneo gana sobre "page" global; visible en el listado |
| `test_set_action_unknown_ip` | Fijar acción por-baneo a IP desconocida devuelve 404 |
| `test_static_served_when_banned` | Un asset CSS estático no es 403 para una IP baneada (assets exentos) |
| `test_layout_exposes_ipban_config_tab` | El layout tiene pestaña ipban con cards settings+services; sin cards operacionales |
| `test_banlist_active_only_history_keeps_all` | Baneos activos excluyen la IP expirada; el historial conserva ambos |
| `test_banlog_records_escalation_and_unban` | Eventos del banlog, más reciente primero: `["unbanned", "escalated", "banned"]` |
| `test_unban_reason_recorded` | DELETE con `reason` registra esa razón en el evento "unbanned" |

### `TestIpBanServiceRegistry` — Registro de servicios

| Test | Qué comprueba |
|---|---|
| `test_web_service_registered` | El servicio "web" soporta {page, minimal, reject, json}; primer endpoint proto "tcp" |
| `test_set_service_action_drives_gate` | Fijar acción web "reject" → cuerpo 403 vacío para IP baneada |
| `test_unsupported_action_refused` | syslog solo soporta "drop": `set_action("page")` devuelve `True` pero queda "drop" |
| `test_service_action_persists` | La acción se guarda; un registry nuevo recarga "minimal" para web |
| `test_unknown_service_action_404` | Fijar acción en servicio desconocido devuelve 404 |

---

## 83. CLI — Servicios de usuarios/grupos y comandos

**Archivo:** `tests/test_cli.py`

### `TestUsersService`

| Test | Qué comprueba |
|---|---|
| `test_create_user_defaults_and_role` | Usuario creado: rol editor, `enabled=True`, hash fijado, `updated_by="cli"` |
| `test_create_disabled_and_groups` | `enabled=False` respetado; grupos `['g1']` |
| `test_duplicate_raises` | Usuario duplicado lanza `AdminOpError` `user_already_exists` |
| `test_bad_role_and_group` | Rol desconocido → `invalid_role`; grupo desconocido → `invalid_groups` |
| `test_password_policy` | (param.) `'a'`→`password_too_short`; `'abcd'`→`None` (válida) |
| `test_last_admin_guards` | Degradar último admin → `must_have_admin`; deshabilitarlo → `cannot_disable_last_admin` |
| `test_set_role_and_enabled_ok` | `set_role` devuelve uid editor; `set_enabled` `True` luego `False` sin cambio |
| `test_group_membership` | `add_group` `True` luego `False` (idempotente); `remove_group` `True`; grupo desconocido lanza |

### `TestGroupsService`

| Test | Qué comprueba |
|---|---|
| `test_create_and_delete` | Crea grupo con nombre/roles; dup case-insensitive lanza `group_already_exists`; delete limpia membresías |

### `TestCliCommands`

| Test | Qué comprueba |
|---|---|
| `test_user_lifecycle` | add/role/disable/enable devuelven 0; usuario final viewer, `enabled=True` |
| `test_passwd_and_group_membership` | passwd, group add, group-add/del, group del devuelven 0; membresía verificada |
| `test_invalid_inputs_fail` | Rol desconocido, usuario ausente, grupo desconocido devuelven código 1 |
| `test_status_and_reload` | Los comandos `status` y `reload` devuelven 0 |

---

## 84. Monitor — Notificador multi-canal (routing y formato)

**Archivo:** `tests/test_monitor_notifier.py`

### `TestRouting`

| Test | Qué comprueba |
|---|---|
| `test_matrix_selects_channels_per_kind` | La matriz enruta: 1 telegram agrupado, 1 email digest, 1 webhook |
| `test_nothing_enabled_sends_nothing` | Todos los canales deshabilitados: flush devuelve `{}`, no envía nada |
| `test_flush_clears_the_buffer` | Tras flush no hay pendientes; el segundo flush no envía nada |

### `TestTelegramGrouping`

| Test | Qué comprueba |
|---|---|
| `test_grouped_message_has_sections_lines_and_summary` | Un mensaje con iconos down/recovery, secciones Issues/Recovered ordenadas, resumen y URL |
| `test_ungrouped_sends_one_message_per_line_plus_summary` | Sin agrupar: 2 mensajes de alerta + 1 resumen = 3 mensajes telegram |

### `TestEmailDigest`

| Test | Qué comprueba |
|---|---|
| `test_single_digest_lists_every_routed_alert` | Un email; asunto menciona alertas; cuerpo lista ping/pve/disk |

### `TestWebhookPerEvent`

| Test | Qué comprueba |
|---|---|
| `test_one_call_per_alert` | Tres llamadas webhook con kinds ordenados `['down', 'recovery', 'warn']` |

### `TestEmailGrouping`

| Test | Qué comprueba |
|---|---|
| `test_digest_splits_issues_and_recovered` | El cuerpo del email pone Issues antes de Recovered |
| `test_digest_groups_rows_by_item` | Dos filas de recovery del mismo ítem muestran la celda del ítem una vez |

### `TestPlainText`

| Test | Qué comprueba |
|---|---|
| `test_plain_strips_telegram_markdown` | `_plain` quita `*` y des-escapa `\[` → texto limpio |
| `test_email_body_has_no_markdown` | El cuerpo del email no tiene markdown `*NS1*` pero conserva `NS1` |

---

## 85. Servicios — SCIM (helpers unitarios)

**Archivo:** `tests/test_scim_service.py`

### `TestBearerTokenOk`

| Test | Qué comprueba |
|---|---|
| `test_valid` | Bearer token correcto (len ≥16) aceptado |
| `test_wrong_token` | Token distinto rechazado |
| `test_missing_prefix` | Token sin prefijo "Bearer " rechazado |
| `test_token_below_min_len_denied` | Token coincidente pero demasiado corto (min 16) rechazado |
| `test_empty` | Cabecera/token vacío rechazado |

### `TestParseFilterEq`

| Test | Qué comprueba |
|---|---|
| `test_quoted` | `userName eq "bob"` → `'bob'` |
| `test_single_quoted` | `userName eq 'bob'` → `'bob'` |
| `test_case_insensitive_attr` | `USERNAME eq "x"` casa el atributo `userName` → `'x'` |
| `test_no_match` | Atributo no coincidente, string vacío y `None` → `None` |

### `TestScimUserFields`

| Test | Qué comprueba |
|---|---|
| `test_primary_email_and_name` | Elige email primario `p@x.com`, nombre "Jane", `active=True` |
| `test_name_formatted_fallback_and_inactive` | Sin emails → `''`; nombre de `name.formatted`; `active=False` |
| `test_active_defaults_true` | `active` ausente por defecto `True` |

---

## 86. Panel Web — Protección CSRF

**Archivo:** `tests/test_wa_csrf.py`

### `TestCsrf`

| Test | Qué comprueba |
|---|---|
| `test_login_requires_token` | POST login sin token: no queda logueado |
| `test_login_with_token_succeeds` | POST login con token sembrado: logueado |
| `test_api_mutation_without_token_rejected` | `PUT /api/v1/config` sin token → 403 |
| `test_api_mutation_with_token_allowed` | PUT con cabecera `X-CSRF-Token` → ≠ 403 |
| `test_get_never_blocked` | `GET /api/v1/config` → 200 |
| `test_scim_exempt_from_csrf` | POST SCIM autenticado por Bearer sin CSRF → ≠ 403 |

---

## 87. Panel Web — Cabeceras de seguridad y módulo CSRF

**Archivo:** `tests/test_wa_headers.py`

### `TestSecurityHeaders`

| Test | Qué comprueba |
|---|---|
| `test_headers_present_on_response` | Respuesta con nosniff, `X-Frame-Options DENY`, Referrer-Policy, Permissions-Policy y CSP (`frame-ancestors 'none'` + `default-src 'self'`) |
| `test_setdefault_does_not_override_proxy` | Preserva `X-Frame-Options SAMEORIGIN` del upstream; sigue añadiendo nosniff |

### `TestCsrfModule`

| Test | Qué comprueba |
|---|---|
| `test_issue_and_validate` | `issue_token` almacena/devuelve token estable; valida por cabecera o form; rechaza token erróneo/ausente y sesión vacía |
| `test_needs_check` | `POST /api/v1/config` requiere check; GET y rutas exentas (`/scim/`, saml acs) no |

---

## 88. Core — Estampado de entidades (audit)

**Archivo:** `tests/test_entity_audit.py`

### `TestTouchEntity`

| Test | Qué comprueba |
|---|---|
| `test_stamps_updated_fields` | `touch_entity` fija `updated_by="admin"` y un `updated_at` con formato ISO |

---

## 88b. Watchfuls — Patrones de publicación de resultados

**Archivo:** `tests/test_watchful_emit_patterns.py` — 5 tests

Un watchful publica cada resultado por una de dos vías (ver `docs/ref-watchful-emit.md`): la
**automática** (`dict_return.set` y notifica el monitor) o la **manual** (`ModuleBase._emit`).
Este guard nació de tres fallos reales encontrados a la vez.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (2) | Que el propio recorrido encuentra los módulos y las llamadas; si fallan, lo roto es el guard |
| `test_automatic_results_carry_an_explicit_name` | **11 sitios** omitían `name=`, así que el monitor etiquetaba la alerta con el **host enlazado** en vez de con el check — la misma comprobación salía con dos nombres según cómo fallara |
| `test_other_data_name_is_not_mistaken_for_the_real_one` | `other_data={'name': …}` NO alimenta la notificación (`get_name()` lee el campo de nivel superior); dos módulos llevaban esa confusión y parecían correctos |
| `test_manual_emit_is_the_exception_not_the_rule` | Deriva silenciosa hacia el emparejamiento a mano. Cazó `proxmox`, que suprimía la notificación **y** no enviaba ninguna: una excepción ponía el check en rojo sin avisar a nadie |

---

## 88c. Meta — Versión y CHANGELOG

**Archivo:** `tests/test_version_changelog.py` — 9 tests

Cada commit publica un build (`0.0.1+build.N`) cuya sección del CHANGELOG contiene **solo** lo
que cambió en ese commit. Ese número vive en **dos** sitios —`lib.__version__` (lo que imprime
`main.py --version` y lo que un operador cita en un informe de fallo) y la cabecera más reciente
de `CHANGELOG.md`— así que pueden divergir. Y una versión que miente sobre lo que está corriendo
es peor que no tener versión.

Es el mismo razonamiento que el resto de esta tanda: **un dato que viaja dos veces se
desincroniza si nadie lo comprueba**.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (2) | Que el CHANGELOG existe y que el formato `## [x.y.z+build.N] - fecha` sigue casando; si cambia, este guard pasaría sin comprobar nada |
| `TestTheyAgree::test_the_version_matches_the_newest_build_section` | `__version__` y la sección más reciente nombran el mismo build |
| `TestTheyAgree::test_the_version_is_a_build_of_the_semantic_version` | El contador es metadato de build, no puede convertirse en la versión |
| `TestBuildsAreOrdered::*` (2) | Orden descendente (Keep a Changelog) y sin builds duplicados — una sección añadida al final parsearía igual, y la lectura "el más nuevo primero" elegiría el equivocado |
| `TestTheSectionIsUsable::test_the_newest_build_carries_a_date` | Fecha presente |
| `TestTheSectionIsUsable::test_the_newest_build_has_content` | Una sección vacía significa un commit que cambió algo y no lo contó |
| `TestTheSectionIsUsable::test_the_historical_block_is_kept_out_of_the_build_sections` | Lo anterior al versionado por build se queda en un bloque intacto: numerarlo a posteriori sería atribuir cambios a ojo |

---

## 88c-bis. Meta — Secciones publicadas del CHANGELOG

**Archivo:** `tests/test_changelog_frozen.py` — 6 tests

Cada commit publica un build cuya sección contiene **solo lo que ese commit cambió**. Nada
vigilaba la segunda mitad de esa regla: tras commitear `build.2` es fácil —y pasó— seguir
añadiendo entradas ahí, con lo que la sección acaba describiendo trabajo que no está en el commit
que nombra.

El guard de versión de al lado **no lo caza**: el número sigue coincidiendo, el orden sigue bien y
la sección sigue sin estar vacía. Lo único que miente es el contenido.

La regla es exacta: toda sección presente en el CHANGELOG de `HEAD` debe ser **byte a byte
idéntica** en el árbol de trabajo. Un commit nuevo añade su sección encima y no toca las demás.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (2) | Que el fichero existe y que se parsean ≥2 secciones de `HEAD`; si cambia el formato de cabecera, falla en vez de pasar sin comprobar nada |
| `test_no_committed_section_was_edited` | El fallo para el que existe: escribir en un build ya publicado |
| `test_no_committed_section_disappeared` | Renombrar o borrar un build publicado reescribe la historia igual que editarlo, y es más fácil de hacer sin querer con una edición por script |
| `test_the_working_copy_only_ever_adds_sections` | El invariante entero: las secciones de `HEAD` son un subconjunto intacto de las del árbol |
| `TestOneBuildPerCommit::test_at_most_one_section_is_unpublished` | La otra mitad de la regla, que no vigilaba nadie: un build lo publica un commit, así que **como mucho una** sección puede estar sin commitear. Pasó al revés — se abrió un build encima de otro sin commitear y la versión saltó de la 4 a la 6 con cero commits. El guard de versión no lo ve: `__version__` y la cabecera se mueven juntos, así que siguen coincidiendo; lo que falla es que el contador avanzó sin lo que cuenta |

> **Dos consecuencias antes de que te falle:**
>
> - **Rechaza el `--amend`** que edite las entradas de ese build. Es deliberado y encaja con la
>   preferencia ya existente del proyecto por un commit nuevo antes que enmendar; si de verdad hay
>   que reescribir historia, se enmienda también el CHANGELOG, no se afloja el test.
> - **Se salta (skip) en vez de fallar cuando no puede ejecutarse** — sin git, o en una exportación
>   del fuente sin historia. Un guard que no ve la referencia no debe inventarse un veredicto.

---

## 88d. Meta — Enlaces con número de línea

**Archivo:** `tests/test_docs_line_links.py` — 6 tests

Los documentos enlazan al código con ancla de línea — la forma `[fichero:N](ruta#LN)`. Son los
enlaces más útiles de la referencia y lo más frágil que hay en ella: **cualquier edición por
encima del destino los desplaza en silencio**, y nada lo notaba.

En su primera ejecución encontró tres rotos, uno de ellos recién provocado por un arreglo de
seguridad en `secret_manager.py` — romper una referencia de documentación arreglando un bug, sin
enterarse, es justo el caso que motiva el guard.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (2) | Que existe `docs/` y que se encuentran >20 enlaces; si cambia el formato, falla en vez de pasar sin comprobar nada |
| `test_the_target_file_exists` | Rutas obsoletas — cazó `lib/modules/monitor.py`, movido a `lib/services/monitoring/` (la línea seguía siendo correcta, solo la ruta había podrido) |
| `test_the_line_is_inside_the_file` | Anclas más allá del final del fichero |
| `test_the_line_is_not_blank` | Un ancla que cae en un hueco ha podrido con seguridad: la sentencia que nombraba se movió y el número se quedó |
| `test_a_link_whose_text_names_a_line_names_the_same_one` | El número está escrito **dos veces a mano** (texto y ancla) y ya se había desincronizado |

> **Lo que NO puede hacer:** juzgar si la línea 28 es la línea *correcta*. Solo comprueba que el
> ancla es internamente coherente y aterriza en algo real. Y no prohíbe las anclas de línea:
> valen lo que cuestan, solo necesitaban algo que las vigilara.

---

## 89. Meta — Este documento

**Archivo:** `tests/test_docs_tests_inventory.py` — 9 tests

Este documento es el mapa de la suite, y hasta ahora **no lo vigilaba nadie** — a diferencia del
índice de rutas, que sí tiene `test_routes_documented.py` rompiendo el build. Resultado: cuando se
escribió este guard había **25 ficheros de test ausentes**, 11 de los 49 contadores declarados
estaban mal (uno por más del doble) y el ejemplo de `bytes2human` era falso.

Las comprobaciones son mecánicas a propósito: un fichero está nombrado en el documento o no lo está.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (3) | Que el propio guard funciona: el documento existe, el recorrido encuentra ficheros y el formato `**Archivo:** …` sigue casando. Si fallan estos, lo roto es el guard, no la documentación |
| `TestFileCoverage::test_every_test_file_is_documented` | **Un fichero de test nuevo debe entrar en el inventario.** Es la razón de ser del guard |
| `TestFileCoverage::test_the_pending_list_only_shrinks` | Documentar un fichero obliga a borrar su línea de `PENDING_DOCUMENTATION`. Sin esto la lista se volvería permanente, y una lista de exenciones permanente es un test desactivado con pasos extra |
| `TestFileCoverage::test_the_pending_list_has_no_ghosts` | Un fichero renombrado o borrado no puede quedarse como exención |
| `TestDocumentAccuracy::test_every_path_the_document_names_exists` | La dirección contraria: un renombrado deja al documento apuntando a la nada, que es como un inventario se vuelve ficción |
| `TestDocumentAccuracy::test_declared_counts_are_not_rotten` | Los "— N tests" declarados, con tolerancia del 30% |
| `TestDocumentAccuracy::test_the_headline_total_is_in_the_right_ballpark` | La cabecera `**Total: ~N tests**`, escrita a mano, llegó a estar 500 tests desfasada |

> **Por qué los contadores llevan tolerancia y no igualdad exacta:** casar el número exacto exigiría
> reimplementar la recolección de pytest — solo `parametrize` ya hace que el conteo estático difiera
> (`test_providers_graph_api.py` declara 26 y tiene 23 `def`). Un guard que debe replicar un
> recolector es un problema en sí mismo. La tolerancia sigue cazando la podredumbre real: la entrada
> de m365 declaraba 26 contra 53 tests reales.

> **Deuda pendiente:** `PENDING_DOCUMENTATION` lista los ficheros que faltan por documentar. Es
> **solo-decreciente**: nunca se añade nada, y documentar uno obliga a quitarlo de ahí.

---

## 90. Core — Salud, escaneos programados y HA

Vigilancias que corren en el propio ServiceSentry, no sobre lo monitorizado: certificados y secretos
que caducan, salud de los servicios internos, y quién manda cuando hay varias réplicas.

**Archivo:** `tests/test_cert_scan.py` — 11 tests

| Test | Qué comprueba |
|---|---|
| `TestEnumerate::*` (4) | De dónde salen los objetivos: config inline, `host_uid` resuelto por el store, deshabilitados omitidos, y ausencia de config `ssl_cert` |
| `TestScanner::test_disabled_never_emits` / `test_not_leader_never_emits` | Ni apagado ni desde una réplica no líder: evita avisos duplicados en HA |
| `TestScanner::test_healthy_cert_not_alerted` | Un certificado sano no genera ruido |
| `TestScanner::test_expiring_alerts_once` | Avisa **una vez** por severidad, no en cada ciclo |
| `TestScanner::test_escalates_expiring_to_expired` | La escalada sí vuelve a avisar: es información nueva |
| `TestScanner::test_recovery_rearms` | Renovar el certificado rearma el aviso para la próxima vez |
| `TestScanner::test_unreachable_leaves_state` | Un host inalcanzable **no** borra el estado: perder visibilidad no es lo mismo que estar sano |

**Archivo:** `tests/test_secret_scan.py` — 15 tests

El secreto de la app Entra caduca, y cuando lo hace el SSO deja de funcionar sin avisar.

| Test | Qué comprueba |
|---|---|
| `TestExpiryHelpers::*` (3) | `parse_expiry` con sufijo `Z`, valor vacío/basura → `None`, y la cuenta atrás en días |
| `TestWarning::test_no_alert_while_outside_the_window` | Silencio fuera de la ventana |
| `TestWarning::test_warns_once_inside_the_window` | Un aviso por severidad, no uno por ciclo |
| `TestWarning::test_escalates_from_expiring_to_expired` | *Por caducar* → *caducado* es un aviso nuevo |
| `TestWarning::test_rearms_after_renewal` | Renovar rearma |
| `TestWarning::test_unknown_expiry_does_nothing` | Sin fecha fiable no se inventa una alarma |
| `TestWarning::test_disabled_oidc_or_both_toggles_off_does_nothing` | Respeta los interruptores |
| `TestWarning::test_non_leader_never_alerts` | Solo el líder avisa |
| `TestRotation::test_rotates_inside_the_margin_and_does_not_warn` | Rotación desatendida dentro del margen, **y sin avisar**: una rotación correcta no es un incidente |
| `TestRotation::test_does_not_rotate_outside_the_margin` | No rota antes de tiempo |
| `TestRotation::test_failed_rotation_still_warns` | Si la rotación falla, el aviso sigue saliendo — alguien tiene que actuar |
| `TestRotation::test_empty_secret_from_graph_is_treated_as_failure` | Un secreto vacío devuelto por Graph es un fallo, no un éxito |
| `TestRotation::test_rotation_works_with_notify_off` | Rotar y avisar son independientes |

**Archivo:** `tests/test_service_health.py` — 9 tests

| Test | Qué comprueba |
|---|---|
| `TestClassify::test_up_down_idle` | Clasificación de vivacidad a partir de las instancias registradas |
| `TestClassify::test_any_fresh_running_instance_makes_service_up` | Basta **una** instancia fresca: un servicio replicado no está caído porque una réplica lo esté |
| `TestClassify::test_ignores_blank_service_key` | Filas sin clave de servicio no ensucian el cálculo |
| `TestTransitions::test_disabled_never_emits` | Respeta el interruptor |
| `TestTransitions::test_first_observation_seeds_without_alert` | La primera observación siembra el estado **sin** alertar: arrancar no es una caída |
| `TestTransitions::test_up_to_down_emits_service_down` / `test_down_to_up_emits_service_up` | Las dos transiciones reales |
| `TestTransitions::test_idle_clears_state_and_never_alerts` | *Idle* limpia estado y calla |
| `TestTransitions::test_non_leader_updates_state_but_does_not_emit` | Una réplica no líder **sí** actualiza el estado (para que la UI esté al día) pero no notifica |

**Archivo:** `tests/test_scheduler_lifecycle.py` — 6 tests

| Test | Qué comprueba |
|---|---|
| `TestAuditAutoDedup::test_background_writes_a_single_system_row` | Un arranque en segundo plano deja **una** fila de auditoría, no una por hilo |
| `TestAuditAutoDedup::test_request_context_attributes_to_the_actor` | Si lo arranca un usuario desde el panel, la auditoría lo atribuye a él |
| `TestAuditAutoDedup::test_request_context_without_login_falls_back_to_system` | Sin sesión, `system` |
| `TestSchedulerNotify::test_start_stop_are_discovered_matrix_events` | Arranque/parada son eventos descubiertos, no claves cableadas |
| `TestSchedulerNotify::test_lifecycle_dispatches_a_translated_body` | El cuerpo sale traducido |

**Archivo:** `tests/test_ha_failover.py` — 5 tests

Failover end-to-end con varias réplicas compartiendo el store de liderazgo.

| Test | Qué comprueba |
|---|---|
| `test_only_one_replica_is_leader` | Exclusión mutua real |
| `test_failover_when_holder_stops_renewing` | Si el líder deja de renovar, otro toma el relevo |
| `test_clean_release_is_instant_failover` | Una liberación limpia no espera al vencimiento del lease |
| `test_active_active_service_runs_on_every_replica` | Los servicios activo-activo **no** se gatean por líder |
| `test_gated_without_store_defaults_to_sole_owner` | Sin store (despliegue de una sola réplica) el servicio corre: la HA no debe romper el caso simple |

---

## 91. Notificaciones — registro de eventos, idioma, destinatarios y overrides

**Archivo:** `tests/test_notify_events.py` — 9 tests

El registro de eventos notificables es la **única** fuente de verdad de la matriz de enrutado.

| Test | Qué comprueba |
|---|---|
| `TestDiscovery::test_discovers_builtin_domain_events` | Cada dominio publica sus kinds |
| `TestDiscovery::test_events_are_ordered_and_deduped` | Orden estable y sin duplicados |
| `TestDiscovery::test_descriptors_carry_source_and_label` | Cada descriptor sabe de dónde viene y cómo se llama |
| `TestDiscovery::test_matrix_subset_excludes_rule_driven_event` | Los eventos dirigidos por regla no entran en la matriz general |
| `TestDiscovery::test_ui_matrix_hides_compat_only_kinds` | Los kinds de compatibilidad no se enseñan |
| `TestManualRegistration::*` (2) | Registro/override manual, y descriptor inválido ignorado |
| `TestMatrixIsFullyDynamic::test_no_static_matrix_keys_in_spec` | **Ninguna clave de matriz escrita a mano en `spec.py`** — si aparece una, hay dos fuentes de verdad |
| `TestMatrixIsFullyDynamic::test_builtin_kinds_come_from_the_registry` | Los kinds vienen del registro |

**Archivo:** `tests/test_notify_i18n.py` — 10 tests

| Test | Qué comprueba |
|---|---|
| `TestEventTitle::*` (4) | Traducción del título, idioma por defecto si va vacío, kind desconocido → clave "embellecida" (nunca la clave cruda), y `format_title` localizado |
| `TestNotifyLang::*` (3) | Precedencia: idioma de **notificaciones** sobre el del panel; si no hay, el del panel; vacío si ninguno |
| `TestBodyTemplates::*` (3) | Cuerpos de auth/login, scheduler/ipban y servicio/certificado, rellenados posicionalmente |

**Archivo:** `tests/test_notify_recipients.py` — 10 tests

Los destinatarios se escriben como tokens (`email` | `user:<uid>` | `group:<uid>`).

| Test | Qué comprueba |
|---|---|
| `TestRecipientResolver::test_group_expands_to_member_emails_deduped` | Un grupo se expande a correos, sin repetir |
| `TestRecipientResolver::test_user_token_resolves_to_email` | Token de usuario → su correo |
| `TestRecipientResolver::test_user_without_email_is_skipped` | Sin correo no hay a dónde enviar |
| `TestRecipientResolver::test_disabled_group_does_not_send` / `test_disabled_user_token_skipped_with_name` | Deshabilitados fuera, y el motivo se reporta con nombre |
| `TestRecipientResolver::test_empty_group_reported_not_fatal` | Un grupo vacío se reporta, no revienta el envío |
| `TestRecipientResolver::test_unknown_token_reported` | Un token desconocido se dice, no se traga |
| `TestSuggestEndpoint::*` (2) | El endpoint de sugerencias lista usuarios y grupos, y exige permiso de edición de config |
| `TestDispatchNoFallback::test_empty_explicit_list_does_not_fall_back_to_raw_tokens` | **Una lista resuelta vacía NO cae a los tokens crudos** — el fallback podría mandar correo a una dirección que el resolutor descartó a propósito |

**Archivo:** `tests/test_notify_router.py` — 7 tests

| Test | Qué comprueba |
|---|---|
| `test_is_channel_agnostic` | El router no conoce canales concretos |
| `test_channels_own_their_stores_via_the_router_cache` / `test_store_factory_is_called_once` | Cada canal gestiona su store por la caché del router, y la factoría se llama una sola vez |
| `test_config_section_reads_from_context` | La config llega por `NotifyContext`, no por Flask |
| `test_dispatch_routes_by_matrix` | Enrutado por matriz |
| `test_dispatch_channels_override_ignores_matrix` | Una regla con canales explícitos manda sobre la matriz |
| `test_run_dispatch_accepts_the_router_as_surface` | El router sirve de superficie: **independiente de web_admin/Flask**, que es lo que permite usarlo desde los workers standalone |

**Archivo:** `tests/test_notify_text_overrides.py` — 9 tests

| Test | Qué comprueba |
|---|---|
| `TestResolution::*` (4) | El texto personalizado gana sobre el i18n; sin override, el i18n; el título del evento lo honra; vacío cuando no hay nada |
| `TestDiscovery::*` (5) | Grupos core y módulos presentes, cada entrada lleva su valor por defecto y el personalizado, los placeholders con nombre se declaran, un mensaje sin placeholders no declara variables, y el paquete de email usa su propio store de plantillas |

---

## 92. Panel Web — páginas de sección, cuenta y convenciones de partials

**Archivo:** `tests/test_module_pages.py` — 35 tests

Un watchful puede reclamar una sección propia de primer nivel declarando `__page__`.

| Test | Qué comprueba |
|---|---|
| `TestNormalize::test_defaults_are_applied` / `test_explicit_values_win` | Normalización de la declaración |
| `TestNormalize::test_an_unusable_id_is_dropped` | El id se convierte en URL, id de elemento y destino de pestaña: si no vale, se descarta |
| `TestNormalize::test_a_blank_id_falls_back_to_the_module_name` | En blanco = "llámalo como yo" |
| `TestNormalize::test_core_ids_cannot_be_shadowed` | **Un módulo no puede reclamar `/admin` u `/overview`** y secuestrar una ruta del core |
| `TestNormalize::test_a_non_dict_declaration_is_dropped` | Una declaración malformada no rompe el panel |
| `TestDiscovery::test_a_real_module_contributes_a_page` | m365 lo hace: prueba el pipeline sobre un módulo real, no un mock |
| `TestDiscovery::test_a_declared_refresh_reaches_the_client_spec` | `refresh` es lo que le dice al renderizador genérico que el módulo puede traer datos en vivo — se perdía por el camino |
| `TestDiscovery::test_the_label_is_the_module_s_own_pretty_name` | **El core no contiene ninguna cadena que nombre a un módulo** |
| `TestDiscovery::*` (resto) | Cada página lleva lo que el core necesita, orden estable y único, y un `watchfuls/` ausente no es un error |
| `TestRegistryMerge::*` (2) | La página entra en el registro de landing sin tocar las del core |
| `TestServed::*` (6) | Ruta enrutada, exige sesión, el shell trae su pane y su entrada de sidebar, el fragmento `web/_ui.html` se inyecta, el endpoint de datos responde, y **un módulo sin página da 404** — eso es lo que impide que sea un "ejecuta cualquier hook" |
| `TestLiveRefreshWithoutAForm::*` (5) | El refresco en vivo conoce solo la CLAVE del ítem: basta con ella, lo que envía el llamante manda, una clave sin prefijo también se encuentra, y un fallo de lectura de config no es fatal |

**Archivo:** `tests/test_wa_standalone_pages.py` — 37 tests

Overview, History y Syslog viven fuera del panel, pero **todas las URL sirven el mismo shell SPA**.

| Test | Qué comprueba |
|---|---|
| `TestRegistry::*` (2) | Cada página declara lo que necesita y es una landing válida |
| `TestRoutes::*` (3) | Exige sesión, renderiza para admin, y History acepta deep link `?module=&key=` |
| `TestNotTabsAnymore::*` (2) | History y Syslog ya no son pestañas del panel, pero sus panes siguen existiendo como contenedor |
| `TestEveryUrlIsTheSameShell::*` (3) | Shell completo en toda URL — nunca una página recortada |
| `TestNoUnguardedPanelElementAccess::test_panel_only_elements_are_accessed_defensively` | Los elementos exclusivos del panel no están en el DOM de una página standalone: leerlos sin guarda rompería el JS |
| `TestUnsavedChangesGuard::*` (3) | Las insignias de "sin guardar" están en el shell, un elemento ausente **nunca** se lee como sucio, y salir ofrece el modal propio en vez del diálogo del navegador |
| `TestSidebarSections::*` (3) | Secciones gateadas por permiso, botones de pestaña SPA en toda URL, y el cliente abre el pane que toca según la URL (recarga, deep link, atrás/adelante) |
| `TestFrontendWiring::*` (3) | La página declara su punto de entrada de render, el panel conserva los placeholders, y el panel no es una standalone |

**Archivo:** `tests/test_wa_account_page.py` — 9 tests

| Test | Qué comprueba |
|---|---|
| `TestRoute::*` (2) | `/account` exige sesión y renderiza |
| `TestTheForm::*` (2) | La página standalone trae el pane y el formulario; el panel también, para que el menú de usuario lo abra como SPA sin recarga |
| `TestItIsAPageNotAModal::*` (2) | Es una página, y el modal antiguo **no queda en ningún sitio** |
| `TestOpensLikeTheOtherPages::test_user_menu_opens_it_spa_on_every_url` | Se abre igual desde cualquier URL |
| `TestDarkModeMovedToUserMenu::*` (2) | El control de modo oscuro ya no está ni en la página ni en el panel |

**Archivo:** `tests/test_wa_partials_convention.py` — 15 tests

| Test | Qué comprueba |
|---|---|
| `TestNaming::test_every_partial_is_underscore_prefixed` | El `_` inicial marca un fragmento que nunca se enruta solo |
| `TestNaming::test_names_are_lowercase_words` | Nomenclatura uniforme |
| `TestNaming::test_no_ambiguous_table_partial` | `_table` significaba dos cosas distintas (la lista entera vs el estado de columnas) |
| `TestNaming::test_one_render_shell_per_section_folder` | Un `_render.html` por carpeta: el único punto de entrada de la sección |
| `TestWiring::test_no_orphan_partials` | Todo partial lo incluye alguien. Un huérfano es código muerto que parece vivo |
| `TestWiring::test_script_partials_are_included_once` | El bundle JS es **un** `<script>`: incluir dos veces redeclararía sus constantes |
| `TestSize::test_render_shells_stay_thin` | Un `_render.html` que engorda es una sección escondiendo subsecciones dentro |

---

## 93. Panel Web — Microsoft Teams

**Archivo:** `tests/test_wa_msteams.py` — 21 tests

| Test | Qué comprueba |
|---|---|
| `TestCards::*` (2) | Forma y color de la MessageCard, y la variante compacta de texto plano |
| `TestChannelSender::*` (5) | Sin canales no hace nada, fan-out a los habilitados, fallo HTTP reportado, helper de prueba, y credenciales ausentes en el envío a usuario |
| `TestBotInbound::*` (2) | Extracción de la referencia de conversación, y **degradación limpia sin PyJWT** (dependencia opcional) |
| `TestChannelRoutes::*` (4) | Exige auth, CRUD completo, alta sin URL rechazada, endpoint de prueba |
| `TestUserAndInboundRoutes::*` (2) | Prueba de usuario sin credenciales, y 404 del endpoint de bot cuando está deshabilitado |
| `TestAppPackage::*` (4) | El ZIP del paquete Teams con sus iconos, la ruta de descarga, y que exige `client_id` y sesión |
| `TestMatrixConfig::test_msteams_matrix_key_saves` | La clave de matriz se guarda |
| `test_msteams_bot_csrf_exempt_declared` | El endpoint del bot declara su exención de CSRF **explícitamente** (lo llama Microsoft, no un navegador) |

**Archivo:** `tests/test_wa_msteams_sso.py` — 13 tests

| Test | Qué comprueba |
|---|---|
| `TestTabPage::*` (2) | La página de pestaña carga el SDK con la CSP de *framing* correcta, y es pública (aún no hay sesión) |
| `TestResolveUser::*` (3) | Correspondencia por usuario, por correo, y sin correspondencia |
| `TestSsoEndpoint::test_no_token_400` / `test_unavailable_501_when_no_pyjwt` | Sin token, 400; sin PyJWT, 501 (no un 500) |
| `TestSsoEndpoint::test_invalid_token_401` / `test_unknown_user_403` | Token inválido y usuario desconocido |
| `TestSsoEndpoint::test_local_account_rejected` | **Una cuenta local no se puede tomar por SSO**: sería escalada de privilegios |
| `TestSsoEndpoint::test_disabled_user_rejected` | Un usuario deshabilitado no entra |
| `TestSsoEndpoint::test_success_establishes_session` | El camino feliz establece sesión |
| `test_msteams_sso_csrf_and_embed_declared` | CSRF y *embedding* declarados explícitamente |

---

## 94. Panel Web — orígenes de grupos, acciones de configuración y rate limit

**Archivo:** `tests/test_wa_group_sources.py` — 13 tests

Cada sección de autenticación que sabe leer grupos del directorio declara sus hooks; el panel **no**
ramifica por proveedor.

| Test | Qué comprueba |
|---|---|
| `TestGroupSourceWiring::test_ldap_source_is_wired` / `test_entra_source_is_wired` | Ambas fuentes cableadas |
| `TestGroupSourceWiring::test_both_lookup_endpoints_are_referenced` | Resolver un id/DN a nombre es lo que rellena las etiquetas del mapeo |
| `TestGroupSourceWiring::test_pickers_are_declared_for_every_section` | Cada fuente declara su contenedor de picker |
| `TestGroupSourceWiring::test_panel_has_no_provider_branching_left` | **Regresión: nada de `sec === 'ldap'`** — el widget se dirige por descriptor |
| `TestGroupSourceDescriptors::*` (4) | Toda sección con directorio declara descriptor, lleva lo que el renderizador necesita, el layout lo entrega al panel, y una sección sin directorio no declara ninguno |
| `TestGroupSourceEndpointsGuarded::test_requires_authentication` | Los endpoints detrás de los botones nunca son alcanzables sin sesión |

**Archivo:** `tests/test_config_actions.py` — 18 tests

Un paquete puede aportar acciones a una sección de configuración describiéndose a sí mismo.

| Test | Qué comprueba |
|---|---|
| `TestNormalize::*` (3) | Entradas sin claves obligatorias fuera, claves conocidas con sus defaults, y variante/orden explícitos ganan |
| `TestDiscovery::*` (4) | El proveedor entraid aporta acciones OIDC, salen ordenadas, cada una nombra una función JS y una clave i18n, y una sección desconocida no tiene ninguna |
| `TestLayoutExposure::*` (2) | Las acciones se enganchan a la tarjeta que toca; una tarjeta sin aportaciones no lleva la clave |
| `TestMaintenanceCard::test_it_is_assembled_from_contributions_only` | Los borrados destructivos viven en Config → General → Mantenimiento, y la tarjeta se ensambla **solo** con aportaciones |
| `TestMaintenanceCard::test_every_wipe_is_permission_gated` | Sin permiso de borrado no se ve **ni el botón** |
| `TestMaintenanceCard::test_the_panel_can_render_an_actions_only_card` | Una tarjeta sin campos se saltaba antes |
| `TestMaintenanceCard::test_the_buttons_left_the_section_toolbars` | El objetivo del movimiento: ya no están en History, Syslog ni Audit |
| `TestGroupLabel::*` (3) | La fila de acciones se titula por paquete cuando todas vienen del mismo, y esa clave es traducible y sobrevive a la normalización |
| `TestI18nKeysExist::test_declared_label_keys_are_translatable` | Ninguna etiqueta declarada se queda sin traducir |

**Archivo:** `tests/test_ratelimit.py` — 9 tests

Limitador de ventana deslizante en proceso (`lib.security.ratelimit`), con reloj inyectado.

| Test | Qué comprueba |
|---|---|
| `test_under_limit_allowed` / `test_exceeding_limit_blocked_with_retry` | Por debajo pasa; por encima bloquea e informa del reintento |
| `test_zero_max_disables_limit` | 0 = desactivado |
| `test_window_slides` | La ventana desliza de verdad, no es un cubo fijo |
| `test_keys_are_independent` | Una IP no consume la cuota de otra |
| `test_peek_does_not_record` / `test_peek_reports_over_after_hits` | `peek` consulta sin contar |
| `test_reset_forgets_history` | El reset olvida |
| `test_gc_drops_stale_buckets` | El GC suelta cubos viejos: sin eso el limitador es una fuga de memoria |

---

## 95. Overview — recuento de checks y filtros de severidad

**Archivo:** `tests/test_overview_checks_widget.py` — 28 tests

Los avisos se cuentan **aparte** de los errores duros: mezclarlos convierte un umbral rozado en una
caída.

| Test | Qué comprueba |
|---|---|
| `TestSeverityFilterParsing::*` (2) | Parseo del filtro, y que `ge` cubre niveles superiores mientras `eq` no |
| `TestModChecksCounts::*` (3) | Separa aviso de error, todo-avisos sin errores, y módulo ausente → vacío |
| `TestChecksStat::*` (3) | Insignias separadas para errores y avisos, solo-avisos en ámbar, y todo OK |
| `TestSeverityFilter::*` (5) | `warning` exacto excluye error, `ge warning` lo incluye, nivel error, valores heredados siguen funcionando, y **ambos widgets declaran sus niveles** |
| `TestServerMatcher::*` (5) | El mismo criterio aplicado a servidores, incluida la unión con mantenimiento y que lo virtual lo excluye |

---

## 96. Guards de documentación e i18n

Tests que no comprueban conducta sino que **la documentación y las traducciones no se queden atrás**.
Ver también §88b y §89.

**Archivo:** `tests/test_routes_documented.py` — 3 tests

| Test | Qué comprueba |
|---|---|
| `TestPerModuleHeaders::test_every_route_is_listed_in_its_module_header` | Las rutas viven repartidas en ~30 módulos: cada una debe estar en la cabecera de la suya |
| `TestPerModuleHeaders::test_headers_use_the_real_parameter_names` | Una cabecera con `<ip>` para una ruta declarada `<path:ip>` se lee bien pero deja de casar — así empezó la deriva |
| `TestSurfaceIndex::test_every_route_falls_under_an_indexed_prefix` | El índice lista **prefijos**: un dominio nuevo tiene que aparecer, un endpoint dentro de uno conocido no |

**Archivo:** `tests/test_i18n_keys_exist.py` — 8 tests

| Test | Qué comprueba |
|---|---|
| `test_no_referenced_key_is_missing` | Una clave usada por el código pero ausente del idioma se renderizaría **cruda en pantalla** |
| `test_language_files_are_in_parity` | `en_EN` y `es_ES` definen exactamente las mismas claves |
| `test_the_regression_that_motivated_this` | `insufficient_permissions` la devuelven 6 módulos de rutas en sus 403 |
| `test_audit_actually_finds_keys` | **Guard del guard**: si las expresiones regulares dejaran de casar, el test pasaría sin comprobar nada |

---

## 97. Watchfuls — severidad de avisos y RAID mdstat

**Archivo:** `tests/test_warning_severity.py` — 21 tests

Un sensor que roza un umbral enruta como `warn`, no como `down`. Ver `docs/ref-watchful-emit.md`.

| Test | Qué comprueba |
|---|---|
| `TestSeverityNormalization::*` (3) | `warning` se conserva en un resultado no-OK, un no-OK sin severidad es `error`, y un resultado OK no lleva severidad |
| `TestAlertKindMapping::test_kind` | El mapa (estado, severidad) → kind: `warn` / `down` / `recovery` |
| `TestSendMessageBridgeCarriesSeverity::*` (2) | El puente `send_message` enruta el aviso como `warn`, y sin severidad se queda en `down` |
| `TestModuleBaseEmitCarriesSeverity::*` (4) | **El bug que costó cuatro módulos**: `_emit` pasaba la severidad al resultado pero no a la notificación, así que la fila salía ámbar y la alerta como caída dura. Incluye que un fallo duro siga sin severidad (el arreglo no podía volver todo ámbar) y que módulo y enrutado no puedan divergir |
| `TestEmitChangeMsgGate::*` (4) | `change_msg` cambia el gate a `check_status_custom` para re-avisar cuando cambia la **razón**; que puede seguir callando si nada cambió; y que `''` es una razón legítima mientras solo `None` elige el gate simple |

**Archivo:** `watchfuls/raid/tests/test_raid_mdstat.py` — 35 tests

Lector de `/proc/mdstat`, local y por SSH.

| Test | Qué comprueba |
|---|---|
| `TestRaidMdstatInit::*` (6) | Construcción local/remota, ruta personalizada, y que sin host no es remoto |
| `TestRaidMdstatValidateRemote::*` (4) | Validación de la config SSH: puerto 0, sin usuario, host vacío |
| `TestRaidMdstatIsExistLocal/Remote::*` (6) | Existencia del fichero en ambos modos, incluidas salidas por *stderr* y config inválida → `False` en vez de excepción |
| `TestRaidMdstatReadStatusLocal::*` (6) | Lectura OK, degradado, en recuperación, inexistente, vacío y con varios arrays |
| `TestRaidMdstatReadStatusRemote::*` (2) | Lectura remota y que *stderr* sí levanta |
| `TestUpdateStatusEnum::*` (2) | El enum es `IntEnum` y admite comparación directa |
| `TestRaidMdstatReadLines::*` (5) | Las excepciones se traducen al tipo correcto: `OSError`, `RuntimeError`, `ValueError` |
| `TestRaidMdstatRecoveryParsing::*` (2) | Detalles de recuperación, y que una línea malformada devuelve un dict vacío en vez de romper |

---

## 98. Entra ID — paso de RBAC de Azure del asistente

**Archivo:** `tests/test_entraid_azure_rbac.py` — 47 tests

Acceder a Azure **no** es un permiso de aplicación de Entra: hace falta una asignación de rol RBAC
sobre la suscripción, contra otra audiencia. Por eso es un paso propio del asistente.
Ver `lib/providers/azure/rbac.py`.

| Test | Qué comprueba |
|---|---|
| `TestDeclaration::test_the_rbac_step_is_optional` | Un perfil sin él queda intacto — todos los módulos existentes carecen de este paso |
| `TestDeclaration::test_it_normalises_with_defaults` / `test_explicit_values_win` / `test_a_bogus_declaration_is_dropped` | Normalización |
| `TestDeclaration::test_the_field_reaches_the_client` | El cliente debe saber **a qué campo** de credencial apuntar como destino del RBAC |
| `TestDeclaration::test_azure_module_declares_it` | El módulo azure lo declara de verdad |
| `TestRoleAssignment::test_a_successful_assignment` | Camino feliz |
| `TestRoleAssignment::test_an_existing_assignment_counts_as_success` | Re-ejecutar el asistente no puede fallar por un rol ya concedido |
| `TestRoleAssignment::test_a_denied_assignment_reports_the_reason` | El fallo habitual: un admin de Entra que **no** es Owner ni User Access Administrator |
| `TestRoleAssignment::test_an_unknown_role_is_refused_without_calling_azure` | Se rechaza antes de gastar una llamada |
| `TestRoleAssignment::test_missing_target_is_refused` / `test_a_transport_error_is_reported_not_raised` | Destino ausente y error de transporte reportados, no lanzados |
| `TestSubscriptionListing::*` (5) | El picker: id/nombre/estado ordenados, una suscripción deshabilitada **se lista con su estado** en vez de ocultarse, sin nombre cae al id, entradas basura fuera, y un fallo es lista vacía — el camino de teclear el id a mano sigue disponible |
| `TestTokenExchange::*` (3) | El consentimiento se canjea en la otra audiencia, sin refresh token se explica por qué (sin `offline_access` no hay nada que canjear), y un error del proveedor se propaga |
| `TestServicePrincipalId::test_provision_returns_it` | La asignación necesita el **object id** del SP, que la creación ahora devuelve |
| `TestPickerFlow::test_offline_access_is_requested_even_without_a_target` | Listar suscripciones también necesita el token ARM |
| `TestPickerFlow::test_no_target_offers_the_subscriptions_instead_of_failing` | Sin destino, ofrece elegir en vez de fallar |
| `TestPickerFlow::test_a_supplied_target_still_assigns_in_one_go` | El picker no estorba cuando el campo ya está relleno |
| `TestPickerFlow::test_the_choice_completes_the_assignment` | La elección cierra el ciclo |
| `TestPickerFlow::test_the_pending_flow_is_single_use` | Guarda un token ARM: no puede quedarse vivo una vez gastado |
| `TestPickerFlow::test_an_unknown_flow_is_expired_not_an_error` | Un flujo desconocido está caducado, no roto |
| `TestPickerFlow::test_no_subscription_is_refused_without_spending_the_flow` | **Un clic en falso no puede quemar el token ARM** — se puede volver a elegir |
| `TestPickerFlow::test_a_token_exchange_failure_reports_and_skips_the_picker` | Sin token ARM no hay lista ni asignación, pero la app sí vuelve |

---

## 99. Panel Web — sección Permisos (Acceso › Permisos)

**Archivo:** `tests/test_wa_permissions_section.py` — 28 tests

Asignar permisos a roles en una página entera, en vez de un rol cada vez dentro del modal. Dos
maquetas sobre los mismos datos —matriz permisos × roles y dos paneles (lista de roles | permisos
de ese rol)— conviviendo para poder compararlas con datos reales. Los roles integrados son
**columnas de solo lectura**: son el patrón contra el que se lee un rol propio.

Se comprueban dos cosas de naturaleza distinta.

**El contrato con la API en el que se apoya la pantalla.** La sección envía
`{"permissions": [...]}` y nada más, así que el endpoint tiene que aplicar exactamente el campo que
recibe: si un PUT parcial empezara a rellenar por defecto lo que no recibe, guardar un permiso desde
aquí borraría el nombre del rol o lo dejaría deshabilitado. Estos tests atacan el endpoint de verdad.

**El cableado de la propia sección.** Es JS dentro de partials Jinja y aquí no hay runtime de JS, así
que se comprueba lo que un trozo ausente rompería de verdad — y en silencio: la sub-pestaña existe en
el shell, las dos maquetas se cargan y las etiquetas resuelven en los dos idiomas. Un partial que no
se incluye da un panel vacío sin error en ninguna parte.

| Test | Qué comprueba |
|---|---|
| `TestPartialUpdateLeavesTheRestAlone::test_saving_permissions_keeps_name_and_description` | Guardar permisos no toca lo que la pantalla nunca mostró |
| `TestPartialUpdateLeavesTheRestAlone::test_saving_permissions_does_not_disable_the_role` | `enabled` tampoco viaja: un rol no puede apagarse desde una pantalla sin interruptor |
| `TestPartialUpdateLeavesTheRestAlone::test_granular_keys_survive_a_save` | **El fallo que más caro sale:** un rol puede tener claves granulares (`module.<name>.view`) que esta pantalla no dibuja. El borrador parte de la lista COMPLETA del rol, así que sobreviven; sembrarlo con las 64 casillas renderizadas las borraría al primer guardado sin que nada se viera en pantalla |
| `TestPartialUpdateLeavesTheRestAlone::test_builtin_permissions_are_refused` | Por qué las columnas integradas son de solo lectura y no "desaconsejadas" |
| `TestTheSectionReachesThePage::test_the_shell_carries_the_subtab_and_its_pane` | Entrada de nav, botón de pestaña y contenedor |
| `TestTheSectionReachesThePage::test_both_layouts_are_loaded` | Un `include` que falta = panel vacío y ningún error |
| `TestTheSectionReachesThePage::test_the_sidebar_offers_it_under_access` | La barra lateral la ofrece bajo Acceso |
| `TestTheWiringItself::test_the_save_sends_permissions_and_nothing_else` | El contrato anterior desde este lado: añadir `name` o `enabled` al cuerpo convertiría la pantalla en algo que sobrescribe campos que no enseña |
| `TestTheWiringItself::test_the_draft_is_seeded_from_the_full_permission_list` | Todo sitio que cree un borrador debe sembrarlo igual — es lo único que salva las claves granulares |
| `TestTheWiringItself::test_the_access_poll_only_redraws_on_a_real_change` | `refreshAccessData` reemplaza `rolesData` cada 30 s. Redibujar igualmente reconstruye el DOM debajo de quien está leyendo —te devolvía arriba del todo dos veces por minuto—, así que el sondeo compara lo que pintaría; y una edición en curso se salta entera (un borrador no está obsoleto: es lo que ha escrito el usuario) |
| `TestTheWiringItself::test_hiding_a_role_hides_it_everywhere` | El filtro actúa sobre la **lista de roles**, no sobre las columnas: así los contadores y lo que compara «Solo diferencias» le siguen. Filtrando solo columnas, la pantalla llamaría idénticos a dos roles porque el que discrepaba está oculto |
| `TestTheWiringItself::test_hide_builtin_is_a_preset_not_a_second_state` | Salió como interruptor propio en el toolbar y el selector lo dejó de sobra; ahora escribe en el mismo conjunto de ocultos y su estado se **deriva** de él — dos controles sobre un conjunto son dos oportunidades de contradecirse |
| `TestTheWiringItself::test_copying_stages_the_change_instead_of_sending_it` | Copiar permisos de un rol a otros aterriza en el **borrador**: las celdas copiadas quedan pendientes, Guardar las manda y Descartar las tira. Llamar a la API desde ahí sería una segunda forma de cambiar permisos, y una que se salta la pantalla que te enseña qué cambió |
| `TestTheWiringItself::test_copying_only_targets_roles_you_may_edit` | Los integrados los rechaza la API, y un rol no editable parecería copiado hasta que fallara el guardado |
| `TestTheWiringItself::test_a_role_with_unsaved_changes_cannot_be_hidden` | Perder de vista una edición sin guardar es como se descarta sin querer, y el selector es el único sitio donde se podría hacer de un clic |
| `TestTheWiringItself::test_hiding_them_all_says_so` | «No hay roles» y «los que hay están ocultos» no son lo mismo; lo segundo es un filtro que puedes deshacer |
| `TestTheWiringItself::test_a_redraw_keeps_where_you_were` | Reemplazar `innerHTML` resetea todos los contenedores con scroll de dentro — y eso pasa también en cada pulsación del filtro, no solo en el sondeo |
| `TestTheWiringItself::test_it_uses_the_same_chrome_as_every_other_list_section` | Salió con un `.ss-toolbar`, que dentro de un panel full-bleed conserva borde, esquinas redondeadas y hueco: la sección se leía como una tarjeta flotando en un panel sin márgenes, al lado de un Users que va de borde a borde. La tarjeta compartida sí se aplana sola |
| `TestTheWiringItself::test_the_two_panes_are_a_row` | `.ss-vfill` **es** el helper de relleno vertical, o sea una columna; `d-flex` fija `display`, no la dirección. Sin `flex-row` los dos paneles se apilan — así salió la primera vez |
| `TestTheWiringItself::test_the_per_instance_permissions_are_shown` | **Se perdieron en el primer corte:** un rol puede acotar un flag global a un módulo, host o cluster (`module.ping.view`) y la sección solo pintaba los 64 del catálogo. Guardar sí los conservaba — eran invisibles, que es peor que perderlos: la pantalla afirma que el rol tiene menos de lo que tiene |
| `TestTheWiringItself::test_the_resource_table_has_one_builder` | Las dos maquetas dibujan la tabla ítems × acciones desde **una** función (`_resources.html`) |
| `TestTheWiringItself::test_the_resources_come_from_the_shared_registry` | De dónde salen módulos/servidores/clusters es `_PERM_RES_SPECS`; declararlos otra vez haría que un recurso acotado nuevo saliera en una maqueta y en la otra no |
| `TestTheWiringItself::test_the_override_blocks_fold` | Los bloques por instancia arrancan cerrados (N módulos × 4 acciones desplegados entierran el catálogo) y una búsqueda los abre: una coincidencia escondida tras una cabecera plegada hace parecer que la búsqueda no encontró nada |
| `TestTheWiringItself::test_the_role_modal_no_longer_edits_permissions` | **Un solo editor.** Dos pantallas sobre el mismo campo es como una deshace en silencio lo que guardó la otra — y el modal hacía PUT de todas las casillas que tenía, incluidas las no refrescadas |
| `TestTheWiringItself::test_the_modal_still_carries_permissions_when_cloning` | El único caso en que sí debe mandarlos: un clon es un rol NUEVO y el POST decide su conjunto entero. Sin esto, «clonar» pasaría a ser «crear vacío» |
| `TestItSpeaksBothLanguages::test_every_new_key_is_translated` (×2) | Una etiqueta que resuelve a su propia clave solo se ve en la página |
| `TestItSpeaksBothLanguages::test_the_placeholders_match_across_languages` | `tf()` sustituye un `{}` por argumento: un recuento distinto deja un `{}` literal en pantalla |

---

## 100. Meta — Cada dominio del core guarda su propio código

**Archivo:** `tests/test_core_domain_layout.py` — 28 tests (+9 skips)

`lib/core/__init__.py` enuncia la regla: un paquete de dominio agrupa su `store`, su `mixin`,
sus `routes` y su `manifest` *«instead of spreading those across lib/stores,
lib/web_admin/mixins and lib/web_admin/routes»*. La reorganización se había quedado a un dominio
del final: permisos seguía con sus 210 líneas de resolución en `lib/web_admin/mixins/`, justo
donde el docstring dice que no debe estar. Un docstring no puede darse cuenta; estos tests sí.

Además fijan los dos invariantes que hacen que la distribución **funcione**, no solo que parezca
ordenada:

- El catálogo tiene que seguir importándose **sin Flask**: el descubrimiento de permisos corre al
  importar `lib.web_admin.constants`, así que traerse el glue web desde el catálogo cerraría un
  ciclo de imports.
- «Qué cuenta como permiso» debe tener **una sola** definición. Tenía dos, escritas idénticas: una
  clase nueva de clave por-instancia habría que recordarla en ambas, y la mitad que se olvidara
  **descartaría** esas claves en silencio en vez de fallar.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_domains_are_found` | Si el escaneo mira donde no es, falla en vez de pasar sin comprobar nada |
| `TestDomainCodeLivesWithItsDomain::test_no_domain_mixin_is_left_in_web_admin` | **El fallo para el que existe**: un mixin de dominio olvidado en `lib/web_admin/mixins/`. Solo `auth` y `services` (que no son dominios) viven ahí |
| `TestDomainCodeLivesWithItsDomain::test_every_domain_mixin_is_in_its_package` | La misma regla al revés, para los dominios que se añadan luego |
| `TestDomainCodeLivesWithItsDomain::test_permissions_is_a_domain_package` | Era un módulo plano cuando todos los demás eran paquetes; y el `.py` viejo no puede convivir con el paquete |
| `TestTheImportCycleStaysOpen::test_a_domain_init_does_not_import_its_mixin` (×N) | El `__init__` ligero que pide `lib/core/__init__.py`, por el motivo concreto que da |
| `TestTheImportCycleStaysOpen::test_the_probe_detects_flask` | Control positivo: sin él, el test siguiente pasaría para cualquier módulo |
| `TestTheImportCycleStaysOpen::test_the_catalog_imports_without_flask` | El ciclo de imports sigue abierto (subproceso limpio; código de salida 2 = «vino Flask», distinto del 1 de un import roto) |
| `TestTheImportCycleStaysOpen::test_the_catalog_is_still_imported_the_same_way` | El movimiento es invisible para los ~25 módulos que importan del catálogo |
| `TestOneDefinitionOfAValidPermission::test_the_rule_is_written_once` | Nadie vuelve a deletrear la regla: barre `lib/` buscando la expresión repetida |
| `TestOneDefinitionOfAValidPermission::test_both_directions_use_it` | Guardar un rol y resolver un rol usan **el mismo objeto** |
| `TestOneDefinitionOfAValidPermission::test_what_the_rule_says` (×7) | Qué acepta y qué no: flags, claves por-instancia, acciones inventadas |
| `TestBuiltInIdentitiesHaveOneHome::test_the_uuids_are_written_in_exactly_one_place` | Los UUID estables estaban pegados a mano en dos ficheros de test: una copia pasa su propio test tan contenta mientras el producto usa otro valor |
| `TestBuiltInIdentitiesHaveOneHome::test_the_catalog_does_not_hold_them` | No vuelven al catálogo, y tampoco se re-exportan desde ahí: eso sería el segundo nombre que este movimiento quita |
| `TestBuiltInIdentitiesHaveOneHome::test_the_role_names_are_enumerated_once` | `ROLES` y las claves de `BUILTIN_ROLE_UIDS` eran dos literales de los mismos cuatro nombres; ahora una deriva de la otra |
| `TestBuiltInIdentitiesHaveOneHome::test_the_grants_cover_exactly_those_roles` | La tercera enumeración (qué concede cada rol) no se puede derivar, así que se comprueba: un rol con UID pero sin grants resuelve a cero permisos en silencio |
| `TestBuiltInIdentitiesHaveOneHome::test_the_group_uid_set_is_derived` | El frozenset de grupos integrados sale del dict, no de otra lista |
| `TestOneEscalationGuard::test_the_guard_is_defined_once` | «Un no-admin solo puede conceder permisos que él tiene» también estaba escrito dos veces: como closure en las rutas de roles y como última línea de `_role_grantable`. Ahora hay un `_perms_grantable` y ambos lo llaman |

---

## 101. Permisos — poda de claves por instancia

**Archivo:** `tests/test_scoped_permission_pruning.py` — 12 tests

`server.<uid>.edit`, `module.<name>.view` y `cluster.<uid>.delete` acotan un flag global a
**una** cosa. Esa cosa vive en otra tabla (o en la configuración de módulos) y nada unía las dos:
borrar un host dejaba sus claves en la lista de permisos de cada rol para siempre.

No concedían nada —un UUID no se reutiliza—, pero se acumulaban sin que nadie las viera, y la
sección Permisos **las cuenta**: un rol declaraba más permisos acotados de los que tenía.

Los nombres de módulo son el caso que merece fijarse: un nombre **sí** puede volver. Un
`module.ping.edit` obsoleto se aplicaría en silencio a lo que se llame `ping` después, así que
quitar un módulo purga sus claves en vez de guardarlas por si vuelve. Esa dirección —una concesión
que nadie recuerda haber dado— es la que importa.

| Test | Qué comprueba |
|---|---|
| `TestTheRuleItself::test_a_resource_owns_four_keys` | Un recurso posee sus cuatro acciones |
| `TestTheRuleItself::test_only_the_named_resource_is_stripped` | Se va el recurso nombrado y solo ese |
| `TestTheRuleItself::test_a_role_that_did_not_hold_them_is_not_reported_changed` | Solo se persiste y audita si algo cambió de verdad; decir «cambiado» de todos reescribiría la tabla de roles en cada borrado de host |
| `TestTheRuleItself::test_nothing_to_strip_is_not_an_error` | Lista vacía, uid vacío o `None` no son un fallo |
| `TestTheRuleItself::test_cluster_items_are_the_ones_bound_to_many_hosts` | Un cluster es un ítem con `host_uids`; uno de un solo host es cosa de `server.*` y no puede confundirse |
| `TestTheRuleItself::test_a_malformed_config_yields_nothing` | Una config rota no puede provocar un borrado |
| `TestDeletingTheResourcePrunesIt::test_deleting_a_host_drops_its_keys` | Por el endpoint real: el cableado es la mitad que se olvida |
| `TestDeletingTheResourcePrunesIt::test_the_other_hosts_keep_theirs` | La poda no se lleva por delante lo de al lado |
| `TestDeletingTheResourcePrunesIt::test_removing_a_module_drops_its_keys` | El caso del nombre reutilizable |
| `TestDeletingTheResourcePrunesIt::test_a_module_that_stays_keeps_its_keys` | Guardar la config de módulos no es una poda general |
| `TestDeletingTheResourcePrunesIt::test_it_is_audited` | Edita permisos sin que nadie lo pida en esa pantalla, así que tiene que verse en algún sitio |
| `TestDeletingTheResourcePrunesIt::test_nothing_is_written_when_no_role_referenced_it` | El caso común —un host que no está en la lista acotada de nadie— no reescribe nada ni miente en la auditoría |

---

## 102. Cachés compartidas — frescura entre procesos

**Archivo:** `tests/test_cache_freshness.py` — 18 tests

Roles, usuarios y grupos se leen de la BD **una vez**, al arrancar, y cada petición responde
desde esos diccionarios. Eso asume un único escritor, y era falso por partida doble: el **CLI**
escribe usuarios y grupos contra la misma BD (`ssentry user role bob viewer` era invisible hasta
reiniciar) y una **segunda réplica** del web escribe los tres. El proceso que no hizo el cambio
seguía sirviendo lo que cargó, incluidos permisos ya revocados.

Recargar en cada petición lo arreglaría releyendo y reparseando todas las filas para descubrir que
no cambió nada, que es el caso normal. En su lugar se pregunta algo barato —un **contador de versión** que cada escritor
incrementa dentro de su misma transacción, más recuento de filas y `updated_at` como red— y solo
se relee cuando la respuesta se mueve.

| Test | Qué comprueba |
|---|---|
| `TestTheProbe::test_it_reports_version_count_and_newest_timestamp` | La sonda dice lo que promete |
| `TestTheProbe::test_every_write_moves_the_version` | Altas, ediciones y borrados mueven el contador |
| `TestTheProbe::test_a_writer_whose_clock_runs_behind_is_still_noticed` | **Por qué es un contador y no un timestamp**: una réplica con el reloj atrasado escribe una fila por debajo del máximo actual — ni `MAX(updated_at)` ni el recuento se mueven — y con una sonda basada en tiempo su cambio sería invisible para todos los demás |
| `TestTheProbe::test_an_unreadable_table_answers_nothing_rather_than_zero` | `None` es «no hay respuesta»; devolver `(0, '')` sería idéntico a «la tabla se vació» |
| `TestReloadingOnChange::test_a_role_written_elsewhere_is_picked_up` | El escenario de dos procesos, con un segundo store sobre la misma BD |
| `TestReloadingOnChange::test_a_revoked_permission_stops_being_served` | **La razón de existir**: la copia obsoleta seguía concediendo lo que se había quitado |
| `TestReloadingOnChange::test_an_unchanged_table_is_not_reloaded` | El caso normal cuesta una consulta agregada, no una relectura completa |
| `TestReloadingOnChange::test_our_own_write_does_not_trigger_a_reload` | Persistir mueve el sello; sin registrarlo, la siguiente petición releería lo recién escrito **encima** de quien aún esté editando |
| `TestReloadingOnChange::test_the_ttl_bounds_how_often_it_asks` | Una ráfaga de peticiones cuesta una sonda, no una por petición |
| `TestReloadingOnChange::test_an_unreadable_database_keeps_the_cache` | Un corte no puede vaciar los roles contra los que un proceso está autorizando |
| `TestUsersAndGroups::test_a_user_written_elsewhere_is_picked_up` | Con el CLI esto no era hipotético |
| `TestUsersAndGroups::test_an_empty_users_table_is_refused` | «Sin usuarios» no es un estado posible del producto: aplicarlo dejaría a todos fuera |
| `TestUsersAndGroups::test_a_group_written_elsewhere_is_picked_up` | Los roles de un grupo son parte de los permisos efectivos de sus miembros |
| `TestUsersAndGroups::test_a_role_added_to_a_group_elsewhere_is_picked_up` | Los roles viven en una tabla de unión y solo se sondea `groups`; funciona porque ambas las escribe el mismo `save_all`, en una transacción, sellando el grupo |
| `TestUsersAndGroups::test_each_table_is_tracked_apart` | Un mecanismo compartido, una entrada por tabla: un cambio en roles no puede leerse como «usuarios también» |
| `TestItRunsBeforeTheHandler::test_the_request_hook_is_wired` | Un mecanismo que nadie llama es el modo de fallo aquí — todo lo demás seguiría pasando |
| `TestItRunsBeforeTheHandler::test_static_files_do_not_pay_for_it` | Con la recomprobación a 0 convertirían una carga de página en treinta consultas |
| `TestItRunsBeforeTheHandler::test_the_reload_is_not_wired_into_the_permission_check` | `_get_session_permissions` se llama desde dentro de handlers, algunos ya tras mutar el dict: recargar ahí tiraría la edición en curso |

---

## 103. Escrituras diferenciales — dos escritores sobre una BD

**Archivo:** `tests/test_entity_sync.py` — 10 tests

Roles, usuarios y grupos se guardaban con `DELETE FROM <tabla>` + reinsertar todo lo que había
en memoria. Correcto mientras un proceso sea dueño de la BD, y destructivo en cuanto son dos:
dos admins en dos réplicas editando roles **distintos** no perdían un campo cada uno — el
segundo en guardar **borraba el rol del otro** y dejaba la tabla como estaba en su memoria. Sin
error y sin log.

La regla que lo arregla va de **borrados**, no de actualizaciones: solo puede borrarse una fila
que este proceso **tenía** y ya no tiene. Una fila que apareció mientras editábamos es de otro.

| Test | Qué comprueba |
|---|---|
| `TestTheDiff::test_an_unchanged_row_is_not_written` | Lo que no cambió no se escribe |
| `TestTheDiff::test_a_changed_row_is_written` / `test_a_new_row_is_written` | Cambios y altas sí |
| `TestTheDiff::test_a_row_we_had_and_dropped_is_deleted` | Un borrado intencionado sigue ocurriendo |
| `TestTheDiff::test_the_first_save_of_all_writes_nothing_away` | Sin snapshot (primer arranque) = «no conozco nada», así que no se borra nada |
| `TestTheDiff::test_the_snapshot_does_not_share_its_lists` | El snapshot es **profundo**: uno superficial compartiría la lista de permisos que se edita en sitio, cambiaría con el dato vivo y todos los diffs dirían «nada cambió» — el bug que convertiría el mecanismo entero en un no-op |
| `TestTwoWriters::test_saving_one_role_does_not_delete_another_writer_s` | **El fallo para el que existe**, con dos stores sobre una BD |
| `TestTwoWriters::test_a_role_this_writer_deleted_is_deleted` | La otra mitad: borrar de verdad sigue funcionando |
| `TestTwoWriters::test_an_update_that_changes_nothing_writes_nothing` | MySQL informa de 0 filas afectadas cuando el UPDATE deja los mismos valores, por eso el upsert pregunta si la fila existe en vez de fiarse del `rowcount`: «0 = insertar» acabaría en clave duplicada |
| `TestTwoWriters::test_the_panel_saving_does_not_wipe_a_cli_user` | La misma historia con el escritor que ya existía: el CLI |

---

## 104. Stores — la base compartida y el formato de fecha único

**Archivo:** `tests/test_store_base.py` — 32 tests

Cada dominio es dueño de su store —columnas, joins, payloads JSON, cómo una fila se
convierte en dict— y nada de eso se comparte. Lo que **sí** se compartía y aun así estaba
copiado era lo de los bordes: nueve `close()` idénticos, siete `count()` idénticos, tres
rellenos de columnas de auditoría iguales, siete copias de «qué hora es, en el formato que
guarda este proyecto» y un par de helpers de cifrado byte a byte iguales.

El número de líneas no es el argumento. Cada una de esas es una **decisión** —«cerrar es un
no-op porque el dueño del ciclo de vida es el conector»— y una decisión escrita nueve veces
es una decisión que nadie puede cambiar.

Dos de estos tests existen por fallos reales, no por pulcritud:

- la sonda de frescura recibía el nombre **crudo** de una tabla cuyo nombre es palabra
  reservada (`groups` en MySQL 8): así no lanza error, devuelve «no sé», y una sonda que no
  puede contestar no recarga nunca;
- convivían **dos formatos de fecha** (`…Z` en los stores, `…+00:00` en `touch_entity`) y para
  el mismo segundo el segundo ordena **por debajo** del primero, así que ordenar por la cadena
  guardada dejaba de ser ordenar por tiempo justo cuando se cruzaban dos escritores.

| Test | Qué comprueba |
|---|---|
| `TestOneTimestampFormat::test_it_is_utc_second_resolution_and_sortable` | Un solo formato: UTC, segundos, `…Z` |
| `TestOneTimestampFormat::test_touch_entity_uses_it` | El que producía la otra grafía ahora usa la única |
| `TestOneTimestampFormat::test_lexicographic_order_is_chronological` | La propiedad de la que depende todo lo que compara esas cadenas |
| `TestOneTimestampFormat::test_no_store_spells_it_out_again` (×8) | Ningún store vuelve a escribir el formato a mano |
| `TestTheSharedBase::test_the_store_uses_it` (×8) | Los ocho stores del core heredan la base |
| `TestTheSharedBase::test_it_does_not_reimplement_what_it_inherits` (×8) | Ninguno se reescribe `close()` ni un `count()` que ya hereda |
| `TestTheSharedBase::test_encryption_is_defined_once` | Credenciales y perfiles de host compartían helpers idénticos |
| `TestTheSharedBase::test_close_is_a_no_op_callers_can_rely_on` | Cerrar no lanza ni necesita conector |
| `TestTheSharedBase::test_the_mixin_passes_the_payload_through_without_a_key` | Sin Fernet, «déjalo como está» y nunca «tíralo»: son credenciales y perfiles de host |
| `TestTheProbeUsesTheRightIdentifier::test_a_reserved_table_name_is_quoted` | **El fallo silencioso**: la sonda debe pasar por el mismo identificador que el resto del SQL del store |
| `TestTheProbeUsesTheRightIdentifier::test_the_logical_name_stays_unquoted` | La fila del contador se indexa por el nombre plano; citarlo ahí crearía una segunda fila que nadie incrementa |

---

## 105. Config — un mapeo Grupo→Rol nuevo tiene que sobrevivir al Guardar

**Archivo:** `tests/test_cfg_group_role_map.py` — 20 tests

El síntoma reportado era un guardado que **mentía**: añadir una fila en Configuration ›
Authentication › SSO (OIDC), pulsar Guardar y recargar dejaba el mapeo nuevo sin rastro,
mientras el toast decía que se había guardado. Cambiar el Role de un mapeo **ya existente**
funcionaba siempre.

Esa asimetría es todo el diagnóstico. Las dos mitades pasan por handlers distintos: el
`<select>` de Role llama a `_grmUpdate` directamente —síncrono, el valor queda en
`_dirtyFields` antes de que el clic llegue a Guardar—, mientras que el `<input>` del id de
grupo llamaba a `_grmRowIdChanged`, que en una sección con fuente de grupos (oidc, saml2 y
ldap declaran una) **esperaba antes una búsqueda de nombre**. El handler corre en `change`,
que dispara cuando el botón Guardar toma el foco: el clic caía con la búsqueda en vuelo,
`saveConfig` enviaba todos los campos sucios menos ése, informaba de éxito con toda la razón,
y el mapeo se apuntaba un instante después sin nadie que lo guardara.

| Test | Qué comprueba |
|---|---|
| `TestTheValueIsStagedBeforeAnythingIsAwaited::test_the_mapping_is_staged_unconditionally_before_any_branch` | **La invariante**, y el primer error de este propio guard: «antes del primer await» no basta —la versión con el bug también apuntaba pronto, pero dentro de un `if` que retorna—, así que se exige antes de **cualquier** bifurcación |
| `TestTheValueIsStagedBeforeAnythingIsAwaited::test_the_lookup_only_decorates_the_name` | Por qué apuntar pronto es correcto y no un parche a la carrera: lo que se espera rellena la columna de nombre, que es otro campo |
| `TestWhatIsPendingMatchesWhatIsOnScreen::test_typing_stages_the_value_not_just_the_dirty_flag` | `markDirty` encendía el botón dejando el campo fuera del payload: el botón decía «hay cambios» y el guardado no estaba de acuerdo |
| `TestWhatIsPendingMatchesWhatIsOnScreen::test_every_row_source_agrees` | Las filas se construyen en dos sitios (render inicial y «Add»); arreglar uno solo es cómo vuelve esto |
| `TestTheOtherHalfStillWorks::test_the_role_select_stages_synchronously` | La mitad que siempre funcionó, fijada para que un refactor no vuelva asíncronas las dos |
| `TestTheOtherHalfStillWorks::test_removing_a_row_stages_too` | Quitar una fila también tiene que llegar al payload |
| `test_the_sections_this_affects_declare_a_group_source` (×3) | El bug solo muerde donde hay búsqueda de nombre: si un proveedor deja de declararla el camino async es código muerto, y si uno nuevo la declara hereda el arreglo |

**La segunda mitad de la misma historia.** Con el mapeo ya guardándose, el botón *Save
Configuration* volvía a ponerse en «cambios pendientes» justo después de anunciar el éxito;
F5 demostraba que el valor estaba guardado y pulsar Guardar otra vez era lo que lo callaba.
Mismo widget, dirección opuesta: `markDirty` decide el botón comparando `configData` con
`_serverConfigData` —la foto de lo que tiene el servidor— y este widget guarda un campo
**por su cuenta** (`group_display_names`: nombres que resuelve él solo y que el usuario nunca
tecleó, así que no debería tener que guardarlos). Esa escritura fuera de banda quitaba la
ruta de `_dirtyFields` pero no movía la foto, así que las dos discrepaban para siempre.

| Test | Qué comprueba |
|---|---|
| `TestASaveThatSucceedsLeavesTheButtonAtRest::test_the_reconciliation_is_defined_once` | Token de versión, conjunto sucio y foto describen el mismo hecho y se mueven juntos (`applySavedField`) |
| `TestASaveThatSucceedsLeavesTheButtonAtRest::test_the_main_save_uses_it` | Estaba embebido en `saveConfig`, que es justo por qué el guardado del widget pudo hacerlo mal: no había definición que reutilizar |
| `TestASaveThatSucceedsLeavesTheButtonAtRest::test_the_widgets_own_save_uses_it_too` | **El fallo reportado**: guardar sin mover la foto deja el botón mintiendo |
| `TestASaveThatSucceedsLeavesTheButtonAtRest::test_the_dirty_set_is_not_edited_behind_the_helpers_back` | |
| `TestResolvingANameDoesNotDirtyTheMapping::test_the_mapping_is_staged_exactly_once` | Una vez, arriba y sin condiciones; los caminos de después solo rellenan la columna de nombre |
| `TestResolvingANameDoesNotDirtyTheMapping::test_the_later_paths_stage_names_only` | Volver a apuntar el mapeo tras la búsqueda lo devolvía a `_dirtyFields` después de que un guardado ya se lo hubiera llevado |
| `TestResolvingANameDoesNotDirtyTheMapping::test_the_bulk_resolver_agrees` | `_grmAutoResolveNames` sigue la misma regla tras un fetch del directorio |

---

## 106. Entra ID — comprobar permisos de las secciones SSO

**Archivo:** `tests/test_entraid_sso_check_perms.py` — 17 tests

El editor de credenciales ya sabía preguntar si la app de un módulo tiene los permisos de
Graph que necesita. Las apps de SSO no, y son donde más duele: **el consentimiento es la
mitad que falla en silencio.** Registrar la app va bien, el admin nunca pulsa «Grant admin
consent», y nada se queja hasta que alguien llama de verdad a Graph — el selector de grupos
vuelve vacío, o un login no mapea ningún grupo, sin nada que apunte a la causa.

La comprobación lee el claim `roles` de un token app-only: un permiso pedido pero no
consentido nunca llega a ese claim, que es justo la distinción que se quiere hacer.

| Test | Qué comprueba |
|---|---|
| `TestWhatTheAppIsRegisteredWith::test_the_name_and_the_id_live_together` | El id es con lo que se concede, el nombre lo único que lleva el claim; separarlos es cómo se acaba verificando un permiso que el registro nunca pidió |
| `TestWhatTheAppIsRegisteredWith::test_the_saml2_registration_grants_exactly_that` | El asistente de SAML2 escribe el id directamente |
| `TestTheRoute::test_it_needs_config_edit` | Lee un secreto guardado y habla con el tenant |
| `TestTheRoute::test_a_section_with_no_provider_url_says_so` | Sin tenant no hay dónde iniciar sesión: contesta en vez de reventar |
| `TestTheRoute::test_it_reports_missing_credentials_instead_of_failing` | El estado justo después de teclear la URL a mano |
| `TestTheRoute::test_a_granted_permission_reports_all_ok` | El camino feliz, con la lista construida desde la respuesta |
| `TestTheRoute::test_a_requested_but_unconsented_permission_reports_missing` | **El caso por el que existe**: pedido pero sin consentir |
| `TestTheRoute::test_a_failed_sign_in_is_reported_not_raised` | Un fallo de autenticación se cuenta, no se lanza |
| `TestTheRoute::test_saml2_uses_its_own_app_never_oidc_s` | Tomar prestadas las credenciales de OIDC comprobaría una app que nadie usa para SAML |
| `TestTheButtons::test_the_section_offers_the_button` (×2) | Ambas secciones declaran la acción |
| `TestTheButtons::test_it_only_shows_once_there_is_an_app` (×2) | Y se apoya en el campo que rellena **su propio** registro |
| `TestTheButtons::test_one_handler_serves_both_sections` | El panel pasa el id de sección a la acción, así que un paquete escribe una función y no un wrapper por sección |
| `TestTheModalIsShared::test_there_is_one_renderer` | Un solo `showPermissionCheck` |
| `TestTheModalIsShared::test_the_credentials_editor_uses_it` | El editor de credenciales dejó de tener su copia |
| `TestTheModalIsShared::test_a_caller_without_the_list_still_gets_a_checklist` | Las secciones de auth no tienen la lista (es del servidor), así que las filas se construyen desde la respuesta |

---

## 107. Entra ID — rotar el secreto de la app de una credencial

**Archivo:** `tests/test_entraid_cred_secret_rotate.py` — 23 tests

La sección SSO OIDC ya sabía hacerlo; una credencial de módulo no, y la única forma de
sustituir un secreto a punto de caducar era **volver a registrar la app** — lo que acuña un
id nuevo y deja permisos y consentimiento a cero, rompiendo a todo el que ya confiaba en la
anterior. Rotar toca el secreto y nada más.

Dos propiedades cargan con el peso: el secreto nuevo se **guarda en la credencial** (una
rotación que solo rellenara el formulario dejaría la app con un secreto que nadie conservó
si se cierra el editor sin guardar) y la respuesta dice `rotated`, para que el asistente no
anuncie «app creada y credencial rellenada» en la única operación cuyo sentido es que la app
**no** cambió.

`AADSTS7000215` merece su propio bloque: Entra devuelve ese mismo código para un secreto
equivocado y para uno recién creado que aún no ha replicado. Reintentar distingue los casos
que se pueden distinguir; el mensaje explica el que no.

| Test | Qué comprueba |
|---|---|
| `TestTheModulesOfferIt::test_the_credential_type_has_the_action` (×2) | m365 y azure declaran la acción en su `schema.json` |
| `TestTheModulesOfferIt::test_it_names_its_own_poll_endpoint` (×2) | La acción trae su endpoint de sondeo |
| `TestTheModulesOfferIt::test_it_does_not_ask_for_an_application_name` (×2) | **El fallo reportado**: salía el modal de «Create Application» pidiendo nombre, cuando no se crea nada |
| `TestTheModulesOfferIt::test_the_editor_passes_those_through` | El asistente reenvía `client_id`/`cred_uid`: sin eso el servidor no sabe qué app rotar |
| `TestTheModulesOfferIt::test_the_app_id_reaches_the_server` | El otro fallo reportado: «Fill in the client_id first» con el id delante |
| `TestTheModulesOfferIt::test_it_is_labelled_in_both_languages` (×2) | Sin traducción el botón sale con la clave cruda |
| `TestTheFlow::test_it_needs_the_credential_permissions` | Acuña un secreto en el tenant: no es una ruta abierta |
| `TestTheFlow::test_it_refuses_without_an_app` | |
| `TestTheFlow::test_it_finds_the_app_on_the_stored_credential` | El id puede no estar en el formulario |
| `TestTheFlow::test_the_new_secret_is_stored_on_the_credential` | **La propiedad principal**, y la que destapó que `update()` reemplaza la credencial entera |
| `TestTheFlow::test_it_reports_a_rotation_not_a_creation` | |
| `TestTheFlow::test_an_unsaved_credential_still_gets_its_field` | Rotar desde un editor sin guardar sigue devolviendo el secreto |
| `TestTheFlow::test_a_failed_sign_in_is_reported_and_audited` | |
| `TestTheFlow::test_a_flow_of_another_kind_is_not_accepted` | Un token de otro asistente no avanza por aquí |
| `TestAFreshSecretIsNotUsableYet::test_a_secret_that_needs_a_moment_is_retried` | |
| `TestAFreshSecretIsNotUsableYet::test_any_other_error_fails_at_once` | Reintentar cualquier fallo de autenticación sería esconder el caso común |
| `TestAFreshSecretIsNotUsableYet::test_it_gives_up_after_its_attempts` | |
| `TestTheMessageSaysWhichItIs::test_a_stubborn_fresh_secret_is_explained` | Los dos significados del mismo código, dichos |
| `TestTheMessageSaysWhichItIs::test_another_failure_is_not_dressed_up_as_that_one` | |

---

## 108. Entra ID — la conversación device-code, escrita una vez

**Archivo:** `tests/test_entraid_device_flow.py` — 43 tests

Seis botones registran o reparan una app de Entra —SAML2, SCIM, el secreto de OIDC, el de
una credencial, el asistente genérico de módulos— y todos mantienen **el mismo intercambio**:
pedir un código a Entra, aparcar lo que la operación va a necesitar, y sondear hasta que el
admin haya iniciado sesión en otro sitio. Ese intercambio estaba escrito seis veces dentro de
`routes.py`, y con él seis copias de sus reglas: cuánto vive un flujo aparcado, que
`slow_down` sube el intervalo, que una respuesta terminal lo consume.

Seis copias de una regla es una regla que nadie puede cambiar. Y además dejó que **divergiera**:
el sondeo de SAML2 comprobaba que hubiera *un* flujo aparcado bajo el token, pero no que
estuviera aparcado *para él*, así que un flujo de cualquier otro tipo podía avanzar por ahí y
leerse luego con el stash equivocado.

Las dos últimas clases cubren lo que el mismo movimiento hizo alcanzable: la regla de **qué
app usa cada sección de auth** y la escritura del secreto rotado eran closures dentro de una
ruta Flask, solo comprobables por HTTP. Como funciones planas, sus trampas se pueden enunciar
directamente.

| Test | Qué comprueba |
|---|---|
| `TestItIsWrittenOnce::test_no_route_spells_the_ceremony_out_again` (×4) | Ni `authorization_pending`, ni `slow_down`, ni acuñar tokens, ni sondear: una copia de vuelta es una regla que deja de serlo |
| `TestItIsWrittenOnce::test_the_flow_registry_is_still_the_hosts` | El registro sigue siendo del host (un código que solo puede terminar quien lo emitió), no un global del módulo |
| `TestStarting::test_it_parks_the_flow_under_its_kind` | |
| `TestStarting::test_the_token_is_not_guessable` | Es lo único entre un sondeo y la sesión de otro |
| `TestStarting::test_the_payload_carries_the_code_and_the_direct_link` | `verification_uri_complete` lleva el código dentro; uno de los seis no lo devolvía |
| `TestStarting::test_the_deadline_comes_from_entra` | |
| `TestStarting::test_a_response_without_a_deadline_still_gets_one` | |
| `TestStarting::test_a_non_default_client_is_remembered` | SCIM usa otro cliente, y el sondeo **debe** canjear con el mismo que emitió el código |
| `TestStarting::test_the_default_client_is_not_stashed` | Copiar el defecto lo congelaría en cada flujo aparcado |
| `TestStarting::test_a_failure_to_start_is_the_callers_to_report` | «El asistente no pudo arrancar» se dice distinto en cada sección |
| `TestPolling::test_pending_keeps_the_flow_parked` | |
| `TestPolling::test_slow_down_raises_the_interval_and_keeps_the_flow` | |
| `TestPolling::test_the_interval_is_capped` | Sin tope, un tenant que insista estira el sondeo más allá de la vida del código: parece un cuelgue, no una caducidad |
| `TestPolling::test_an_error_consumes_the_flow_and_is_audited` | Un fallo que solo es un toast es un fallo que nadie puede consultar después |
| `TestPolling::test_an_expired_flow_is_consumed_and_audited` | Y no se manda a Entra un código ya caducado |
| `TestPolling::test_a_flow_of_another_kind_is_refused` | **La divergencia que cierra este movimiento** |
| `TestPolling::test_an_unknown_token_is_expired_not_described` | Caducado o falsificado: ninguno merece explicación |
| `TestPolling::test_completion_hands_back_the_stash_and_the_token` | |
| `TestPolling::test_a_completed_flow_cannot_be_polled_twice` | Se suelta **antes** de la parte lenta: si no, un segundo sondeo canjea el mismo código y ejecuta la operación dos veces |
| `TestPolling::test_it_redeems_with_the_client_that_issued_the_code` | |
| `TestPolling::test_the_default_client_is_left_to_auth` | |
| `TestTheFollowUpFlow::test_park_and_take_round_trip` | El paso de RBAC de Azure: elegir suscripción no puede costar un segundo inicio de sesión |
| `TestTheFollowUpFlow::test_take_does_not_consume` | Una petición mal formada se puede reintentar sin quemar el token |
| `TestTheFollowUpFlow::test_it_refuses_a_flow_of_another_kind` | |
| `TestTheFollowUpFlow::test_an_abandoned_picker_does_not_hold_the_token` | |
| `TestTheFollowUpFlow::test_the_default_ttl_is_shorter_than_an_arm_token` | |
| `TestWhichAppASectionUses::test_oidc_uses_its_own` | |
| `TestWhichAppASectionUses::test_saml2_never_borrows_oidcs` | La respuesta parecería correcta y no significaría nada |
| `TestWhichAppASectionUses::test_an_unknown_section_is_not_a_third_set_of_rules` | |
| `TestWhichAppASectionUses::test_a_full_pair_from_the_request_wins` | El estado justo después del asistente |
| `TestWhichAppASectionUses::test_a_lone_client_id_must_not_override` | Se emparejaría con el secreto **guardado** de otra app, y el fallo se leería como un problema de permisos |
| `TestWhichAppASectionUses::test_a_lone_secret_must_not_override_either` | |
| `TestWhichAppASectionUses::test_the_provider_url_may_travel_alone` | Nombra al tenant, no a una identidad |
| `TestWritingARotatedSecretBack::test_the_id_on_screen_wins` | |
| `TestWritingARotatedSecretBack::test_the_stored_credential_fills_in_for_a_field_the_editor_never_got` | |
| `TestWritingARotatedSecretBack::test_no_store_is_not_a_crash` | |
| `TestWritingARotatedSecretBack::test_the_rotation_changes_the_secret_and_nothing_else` | **La trampa**: `update()` reemplaza la credencial entera, así que mandar solo `data` borraba el nombre y reseteaba el tipo |
| `TestWritingARotatedSecretBack::test_nothing_to_write_is_not_an_error` | |
| `TestWritingARotatedSecretBack::test_an_unknown_credential_is_not_created` | |
| `TestWritingARotatedSecretBack::test_the_identity_to_check_prefers_what_was_typed` | Los campos enmascarados siguen viniendo del store |

---

## 109. Config — la cabecera tiene que quedarse arriba toda la sección

**Archivo:** `tests/test_wa_config_pane_layout.py` — 21 tests

La barra (título, Reload, Save con su chincheta de cambios sin guardar) y el buscador son los
controles que buscas **porque** has hecho scroll: encuentras un campo, lo cambias y le das a
Guardar. Estaban fijados con `position: sticky`, y eso los fijaba durante **una pantalla**;
después la cabecera se iba hacia arriba y desaparecía, justo donde la lista de configuración
se hace larga y hace falta.

`sticky` no podía funcionar ahí, y el motivo es una regla que el panel impone a propósito en
otro sitio: **una tab-pane activa es una columna flex acotada por el viewport**
(`.container-fluid > .tab-content > .tab-pane.active` con `flex: 1 1 auto; min-height: 0`
dentro de una `.ss-main` que es `height: 100vh`). Un elemento sticky solo viaja hasta donde
llega su bloque contenedor, y ese bloque mide una pantalla por muy largo que sea el contenido:
el contenido se desborda y la cabecera se va con el bloque.

El mecanismo que sí funciona es el que ya usa el resto del panel: la cabecera conserva su
altura natural y el cuerpo de debajo pasa a ser el scroller (`.ss-vscroll`). Así la cabecera no
puede irse — no hay scroll debajo de ella que se la lleve.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_the_pane_is_found` | |
| `TestTheScanItself::test_the_fill_helpers_exist` | |
| `TestTheBodyScrolls::test_the_config_body_is_the_scroller` | Si no scrollea él, scrollea la página y se lleva la cabecera |
| `TestTheBodyScrolls::test_the_scroller_has_a_gutter` | Cards en flujo, no una tabla: sin canal la barra de scroll se come el borde derecho |
| `TestTheBodyScrolls::test_the_gutter_is_not_baked_into_the_scroll_helper` | `.ss-vscroll` lo usan cuerpos de tabla que no quieren ese padding; un helper genérico con el gusto de una sección deja de ser genérico |
| `TestTheSeamBetweenHeaderAndBody::test_the_header_card_has_no_bottom_margin` | La franja de 1rem de fondo de página entre el card y el cuerpo: las filas que pasaban por debajo **asomaban ahí**, un trozo de input flotando que parecía un fallo de pintado |
| `TestTheSeamBetweenHeaderAndBody::test_the_header_sits_on_the_edge_not_inside_the_padding` | Es el borde superior de la sección, no un card flotando dentro: ancho completo, a ras del marco y cuadrado arriba |
| `TestTheSeamBetweenHeaderAndBody::test_the_bottom_stays_rounded` | La curva de abajo es lo que dice «el cuerpo se mete por aquí» |
| `TestTheSeamBetweenHeaderAndBody::test_the_bleed_cancels_exactly_the_padding_above_it` | El margen negativo es aritmética contra dos paddings del shell; si cambia alguno, la barra deja de estar a ras y nada más lo diría |
| `TestTheSeamBetweenHeaderAndBody::test_the_cut_is_faded_not_sliced` | `overflow` corta a cuchillo; un input partido por la mitad se lee como error, no como «hay más arriba» |
| `TestTheSeamBetweenHeaderAndBody::test_the_fade_is_not_baked_into_the_scroll_helper` | `.ss-vscroll` lo comparten cuerpos de tabla con su propia fila de cabecera, que no deben enmascararse |
| `TestTheSeamBetweenHeaderAndBody::test_the_fade_is_short` | Suficiente para suavizar el borde, nunca tanto como para tapar una fila que estás leyendo |
| `TestTheHeaderDoesNotGoBackToSticky::test_the_header_is_not_positioned` | **La regresión**: volver a `position:sticky` dentro de una pane acotada |
| `TestTheHeaderDoesNotGoBackToSticky::test_the_pane_is_still_a_flex_column` | Todo el montaje se apoya en ella: sin columna, el cuerpo no tiene altura donde scrollear |
| `TestTheHeaderDoesNotGoBackToSticky::test_the_shell_is_the_bounded_one` | `.ss-main` a `100vh` es justo la razón por la que sticky no podía funcionar |
| `TestTheSearchBoxIsCollapsed::test_it_starts_closed` | El filtro sirve para encontrar un ajuste entre muchos, no para estar a la vista el resto del tiempo |
| `TestTheSearchBoxIsCollapsed::test_the_toggle_targets_it` | Incluido el estado cerrado anunciado a accesibilidad |
| `TestTheSearchBoxIsCollapsed::test_an_active_filter_is_visible_with_the_box_closed` | **La trampa** de esconder el buscador: un filtro activo con la caja cerrada deja media configuración oculta y parece pérdida de datos |
| `TestTheSearchBoxIsCollapsed::test_the_toolbar_closes_the_card_when_the_box_is_hidden` | Sin nada debajo, la barra **es** el fondo del card y tiene que tener su forma; un borde inferior recto sin nada después parece un panel que no llegó a pintarse |
| `TestTheSearchBoxIsCollapsed::test_opening_it_puts_the_cursor_in_it` | Pulsas la lupa porque vas a escribir; abrir sin foco pide un segundo clic |
| `TestTheControlsAreStillThere::test_the_header_holds_them_all` | Un cambio de layout no puede dejarse un control por el camino |

---

## 110. Un ajuste no puede dejarte fuera del panel

**Archivo:** `tests/test_wa_cookie_lockout.py` — 13 tests

Dos ajustes podían hacerlo, y los dos fallaban igual: un rebote infinito entre `/login` y `/`.
El login **funcionaba** —credenciales correctas, sesión creada— y el navegador llegaba a la
página siguiente sin sesión ninguna, porque la cookie que la llevaba se tiraba al llegar. Nada
en pantalla lo decía; el panel simplemente dejaba de ser alcanzable, incluida la página donde
se apaga el ajuste que lo causó.

**Cookies Secure sobre HTTP plano.** Un navegador descarta una cookie `Secure` en `http://`.
La configuración de sesión es cuidadosa con esto para `public_url` —una URL externa canónica
no afirma que todo el tráfico sea HTTPS—, pero la política de *embed* marcaba `Secure` sin
condiciones en cuanto se permitía cualquier origen en frame-ancestors (activar el embed de
Teams bastaba). Ese trato nunca compensó: un iframe cross-site necesita `SameSite=None`, los
navegadores rechazan `SameSite=None` sin `Secure`, y rechazan `Secure` sobre HTTP — así que en
un despliegue http:// la política tampoco habilitaba el embed. Solo rompía el login.

**Una redirección a sí misma.** `force_fqdn` comparaba `request.host` (que lleva el puerto)
contra una URL pública que puede no llevarlo, así que `192.168.0.1:8080` se leía como host
distinto de `192.168.0.1` y mandaba al navegador al puerto 80. El ajuste va del *hostname* por
el que entras, y una redirección que aterriza donde empezó gira para siempre.

La forma de las dos reglas es la misma, y es el sentido del fichero: **un ajuste de seguridad
que no puede aplicarse no debe aplicarse a medias.** No redirigir, o dejar la cookie usable, es
siempre mejor que un bloqueo — el peor caso es que el endurecimiento no se aplique, que es
justo donde ya estabas.

| Test | Qué comprueba |
|---|---|
| `TestTheSessionCookieStaysUsableOverPlainHttp::test_no_embed_no_https_keeps_the_cookie_usable` | |
| `TestTheSessionCookieStaysUsableOverPlainHttp::test_allowing_an_iframe_origin_does_not_break_plain_http_login` | **El bloqueo**: activar el embed de Teams marcaba la cookie Secure y el login rebotaba en bucle |
| `TestTheSessionCookieStaysUsableOverPlainHttp::test_with_https_the_embed_policy_applies` | No se desactiva: se condiciona a lo único que la hace funcionar |
| `TestTheSessionCookieStaysUsableOverPlainHttp::test_an_https_intent_alone_still_marks_it_secure` | |
| `TestTheSessionCookieStaysUsableOverPlainHttp::test_the_impossible_combination_is_reported` | Un embed que no puede funcionar no puede fallar en silencio |
| `TestForcingTheDomainCannotLoop::test_a_different_hostname_is_redirected` | Lo que el ajuste sí debe hacer |
| `TestForcingTheDomainCannotLoop::test_the_query_string_survives` | |
| `TestForcingTheDomainCannotLoop::test_a_public_url_without_a_port_accepts_any_port` | **El bucle**: `request.host` lleva puerto y la URL pública puede no llevarlo |
| `TestForcingTheDomainCannotLoop::test_a_named_port_is_still_honoured` | Nombrar un puerto significa que importa |
| `TestForcingTheDomainCannotLoop::test_the_comparison_ignores_case` | |
| `TestForcingTheDomainCannotLoop::test_it_never_redirects_to_the_request_it_is_answering` | Cinturón y tirantes: un destino idéntico a la petición actual es un bucle que el navegador seguirá siempre |
| `TestForcingTheDomainCannotLoop::test_it_does_nothing_while_switched_off` | |
| `TestForcingTheDomainCannotLoop::test_it_does_nothing_without_a_public_url` | Activarlo a solas es un no-op |

---

## 111. El icono del sitio existe y pedirlo no da 404

**Archivo:** `tests/test_wa_favicon.py` — 11 tests

No había favicon, así que cada visita dejaba un `GET /favicon.ico 404` — inofensivo en sí, y
ruido en el log de acceso de todos los despliegues para siempre. Los navegadores piden ese
fichero **por su cuenta y desde la raíz**, haya o no etiquetas `<link rel="icon">` en la
página: en una página de error, en un endpoint JSON abierto en una pestaña, antes de parsear
ningún HTML. Por eso las etiquetas no bastan y la ruta tiene que contestar.

Dos propiedades merecen fijarse más allá de «el fichero está»:

- **es público.** Exigir sesión redirigiría al login y le daría al navegador un documento HTML
  donde va un icono — un 200 que no es una imagen es peor que un 404;
- **el binario tiene fuente.** `tools/make_favicon.py` lo dibuja a partir de la geometría (sin
  dependencias: un PNG son unas cuantas scanlines comprimidas con zlib y un `.ico` es un
  directorio de PNGs), así que el `.ico` commiteado es reproducible en vez de un artefacto que
  nadie puede regenerar. El test vuelve a ejecutar el generador y compara bytes.

Cada tamaño se renderiza desde la forma en lugar de reescalar un bitmap: a 16px —el tamaño que
enseña de verdad una pestaña— un check reescalado se convierte en una mancha.

| Test | Qué comprueba |
|---|---|
| `TestTheFilesExist::test_the_ico_is_there` | |
| `TestTheFilesExist::test_the_svg_is_there` | Lo que prefiere un navegador moderno: un fichero, nítido a cualquier densidad |
| `TestTheFilesExist::test_the_ico_is_a_real_ico` | Cabecera válida y payloads PNG |
| `TestTheFilesExist::test_it_carries_the_sizes_a_browser_asks_for` | 16 y 32; el de 16 es el de la pestaña |
| `TestTheBinaryIsReproducible::test_the_committed_ico_matches_its_generator` | Un binario sin fuente es un callejón sin salida: nadie puede cambiarle el color ni la forma |
| `TestThePageDeclaresIt::test_both_forms_are_offered` | SVG + bitmap alternativo |
| `TestThePageDeclaresIt::test_they_are_cache_busted_like_the_stylesheet` | Un icono que el navegador fijó para siempre es lo único que nadie piensa en recargar a la fuerza |
| `TestTheRootPathAnswers::test_it_is_served_without_a_session` | **El sentido de la ruta**: se pide antes de haber sesión y en páginas que no son nuestras |
| `TestTheRootPathAnswers::test_it_returns_the_committed_file` | |
| `TestTheRootPathAnswers::test_it_is_cacheable` | Refrescarlo en cada carga es justo el ruido que esta ruta viene a quitar |

---

## 112. El breadcrumb nombra el camino completo hasta la sección

**Archivo:** `tests/test_wa_breadcrumb.py` — 10 tests

Leía el ítem activo del sidebar y su sub-ítem y ahí paraba, así que una sección anidada dos
niveles se anunciaba como «Infrastructure / Servers» y una anidada un nivel como «Services» a
secas — el mismo título que recibe una sección de primer nivel. Las dos perdían el grupo en el
que viven, que es justo la parte que dice *dónde estás*: a Servers se llega abriendo System y
luego Infrastructure. Un camino al que le falta el primer paso no es un camino.

La regla tiene dos mitades y la segunda importa igual:

- una sección dentro de un grupo se nombra con su cadena entera — «System / Services»,
  «System / Infrastructure / Servers»;
- una sección de primer nivel (Overview, History, Syslog…) no pertenece a ningún grupo y es
  solo ella misma. Prefijarla nombraría un sitio en el que no vive.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_the_builder_is_found` | |
| `TestTheScanItself::test_the_sidebar_has_groups` | Todo el arreglo se apoya en que el grupo sea un elemento real con etiqueta |
| `TestThePathStartsAtTheGroup::test_the_group_is_part_of_the_crumb` | **La regresión** |
| `TestThePathStartsAtTheGroup::test_it_is_the_group_containing_the_active_item` | Se resuelve hacia arriba desde el ítem activo, no «el primer grupo del sidebar» — que acertaría por suerte mientras solo haya uno |
| `TestThePathStartsAtTheGroup::test_it_takes_that_groups_own_header` | `:scope >`: un grupo anidado aportaría la cabecera de su hijo |
| `TestThePathStartsAtTheGroup::test_the_group_comes_first` | El orden **es** el camino |
| `TestAFirstLevelSectionIsJustItself::test_the_standalone_sections_are_outside_every_group` | Si alguna se moviera dentro de un grupo heredaría prefijo en silencio |
| `TestAFirstLevelSectionIsJustItself::test_missing_parts_are_dropped_not_rendered_empty` | Sin `filter(Boolean)` una sección sin grupo empezaría por un separador |
| `TestTheGroupHeaderIsNeverTheSection::test_the_parent_link_is_excluded_from_the_item_lookup` | La cabecera del grupo también lleva `.ss-sb-item`; sin excluirla el crumb la repetiría |
| `TestTheGroupHeaderIsNeverTheSection::test_the_separator_is_still_escaped_markup` | Las etiquetas se escapan; solo el separador es marcado |

---

## 113. «Conexión perdida» tiene que significar que se perdió la conexión

**Archivo:** `tests/test_wa_conn_overlay.py` — 11 tests

El overlay tapa el panel entero, así que uno falso no es un fallo cosmético: interrumpe lo que
estuvieras haciendo para decirte algo que no es cierto, y se queda hasta que la siguiente
sonda acierte. Y saltaba con **un solo** fallo.

El mecanismo se leía como si fuera cuidadoso —el comentario decía «con antirrebote (~1,2 s de
fallo continuado) para que un parpadeo no lo enseñe»— pero durante esa espera **no se
recomprobaba nada**: el temporizador solo retrasaba el anuncio, nunca lo cuestionaba. Bastaba
una respuesta lenta: una petición que se pasa de los 4 s del latido porque un worker está
ocupado, un parpadeo mientras un portátil cambia de red.

Dos cambios, y el primero es el que importa:

- **un primer fallo vuelve a preguntar en vez de anunciar.** Dispara una re-sonda inmediata y
  solo un segundo fallo consecutivo levanta el overlay. Una caída real tarda apenas más en
  verse, porque la confirmación no espera al siguiente latido;
- **la confirmación espera más.** El timeout corto de la primera sonda está pensado para
  detectar un backend **colgado**; uno simplemente ocupado también se lo pasa, y «lento una vez»
  no es «no está».

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_the_pieces_are_found` | |
| `TestOneFailureIsNotAnAnswer::test_a_failure_is_counted_not_announced` | **La regresión**: sin contador, lo único entre un parpadeo y un cartel a pantalla completa es un temporizador que no comprueba nada |
| `TestOneFailureIsNotAnAnswer::test_the_first_failure_triggers_a_re_probe` | Preguntar otra vez es lo que hace que el segundo fallo signifique algo |
| `TestOneFailureIsNotAnAnswer::test_the_probe_is_reachable_from_there` | Era una const dentro del closure de arranque, así que nada de fuera podía relanzarla — de ahí que la confirmación se inventara como temporizador a secas |
| `TestOneFailureIsNotAnAnswer::test_the_confirmation_is_given_more_time` | Un servidor ocupado también se pasa del presupuesto de la primera sonda |
| `TestSuccessClearsEverything::test_a_success_resets_the_counter` | Si no, dos fallos sin relación con minutos de diferencia sumarían una caída |
| `TestSuccessClearsEverything::test_it_cancels_both_pending_timers` | Una confirmación o un pintado en cola dispararían después de que el servidor ya hubiera contestado |
| `TestSuccessClearsEverything::test_hiding_is_immediate` | Solo se protege el mostrar: un panel que funciona nunca debe parecer roto |
| `TestTheAuthoritativeSignalsStillBypassIt::test_the_browser_going_offline_shows_it_at_once` | El navegador sabe que no hay enlace; no hay nada que confirmar |
| `TestTheAuthoritativeSignalsStillBypassIt::test_a_gateway_error_still_counts_as_unreachable` | Un proxy vivo delante de un backend muerto contesta 502/503/504 |
| `TestTheAuthoritativeSignalsStillBypassIt::test_an_abort_is_still_not_a_network_error` | Una petición cancelada al navegar no es el servidor yéndose |

---

## 114. El menú de órdenes por servicio: qué ofrece, qué destruye y que se parezca al resto

**Archivo:** `tests/test_wa_services_commands.py` — 18 tests

Tres cosas, y la tercera es la que importa de verdad.

**Los ítems llevan icono.** Start y Stop están a un centímetro con el suyo, así que un
desplegable solo-texto al lado se lee como algo sin terminar. El icono se elige **por orden**,
no por servicio: «Reload» significa lo mismo dondequiera que aparezca y no puede ser un glifo
bajo Monitor y otro bajo Syslog. `run_now` evita a propósito el icono de play que usa Start —
ejecuta un ciclo ya, no arranca el servicio, y dos controles tan juntos no deben reclamar la
misma acción.

**fail2ban tenía Start/Stop y nada más.** No por diseño: era el único servicio controlable sin
`_apply_command`. Ahora ofrece `reload` (empujar la config a la jaula viva — umbrales,
ventanas, duraciones y **whitelist**; una IP añadida a la whitelist no surtía efecto hasta
guardar config) y `prune` (barrer contadores rancios y recortar log e histórico). El hook vive
en `embedded.py`, no en `manager.py`, porque este servicio **no tiene bucle de trabajo**: la
jaula se aplica en línea en cada petición. El `prune` manual no llama al `_gc` interno de la
jaula a propósito: ese está limitado a una vez cada 5 minutos, así que pulsar el botón dentro
de esa ventana habría dicho «hecho» sin barrer nada.

**Lo destructivo pregunta antes.** `prune` y `clear_status` borran cosas que no vuelven y
están en el mismo desplegable que Reload — una fila más abajo, mismo color, sin separación. Lo
único entre un clic mal puesto y datos perdidos es que te pregunten. El mensaje **nombra el
servicio**, porque la misma orden destruye cosas distintas según dónde se pulse: Prune bajo
Syslog tira mensajes guardados, bajo fail2ban contadores de ofensa y el log de baneos. Un
diálogo que no dice qué vas a perder es un badén, no una salvaguarda.

**Y una deuda que quedó anotada, no arreglada.** El mapa de órdenes del frontend y los
`_apply_command` del backend son dos declaraciones del mismo hecho, y ya han divergido (syslog
acepta `clear_status` como alias de `prune` y el panel nunca lo ofrece). Peor: la ruta valida
el nombre de la acción contra **un conjunto global**, así que `run_now` sobre ipban se acepta,
se encola y solo lo rechaza el servicio — el `unknown_action` acaba en la fila de la tabla,
fuera de la vista, mientras el HTTP contestó `ok`. Los tests fijan eso **como está**, con el
motivo escrito: hacer honesta la respuesta requiere que cada servicio DECLARE sus órdenes, que
es el mismo cambio que quitaría el mapa hardcodeado.

| Test | Qué comprueba |
|---|---|
| `TestEveryEntryHasAnIcon::test_the_menu_renders_one` | **La regresión** de los iconos |
| `TestEveryEntryHasAnIcon::test_every_offered_command_has_one` | Una orden nueva sin icono no pasa desapercibida |
| `TestEveryEntryHasAnIcon::test_the_icon_belongs_to_the_command_not_the_service` | Un mapa por servicio dejaría que la misma orden tuviera dos caras |
| `TestEveryEntryHasAnIcon::test_run_now_does_not_borrow_the_start_glyph` | Pulsar uno queriendo el otro es justo el riesgo |
| `TestTheMenuOnlyOffersWhatTheServiceAccepts::test_no_menu_entry_is_rejected_by_its_service` | Un ítem que el backend no implementa falla siempre que se pulsa |
| `TestTheMenuOnlyOffersWhatTheServiceAccepts::test_the_services_that_offer_commands_implement_the_hook` | Un menú sin nada detrás |
| `TestTheMenuOnlyOffersWhatTheServiceAccepts::test_the_command_is_reachable_from_the_queue` | El drenaje busca el hook en el objeto **embebido**; definirlo donde el gemelo no lo hereda encolaría órdenes que nadie ejecuta |
| `TestFail2banActuallyRunsThem::test_prune_sweeps_the_store` | Prueba funcional por la ruta real, no solo acuerdo estático |
| `TestFail2banActuallyRunsThem::test_reload_pushes_config_into_the_live_jail` | |
| `TestFail2banActuallyRunsThem::test_an_action_it_does_not_know_is_recorded_as_failed` | **La deuda**, fijada tal cual: `ok` significa «encolada», no «ejecutada» |
| `TestFail2banActuallyRunsThem::test_it_needs_the_control_permission` | Reconfigura la jaula que mantiene fuera a los atacantes |
| `TestTheDestructiveOnesAskFirst::test_they_are_marked_as_destructive` | Declarado como dato: una orden destructiva nueva está a una entrada de quedar protegida |
| `TestTheDestructiveOnesAskFirst::test_the_handler_confirms_before_sending` | Y **no** manda la petición de camino al modal: se confirmaría con el borrado ya en vuelo |
| `TestTheDestructiveOnesAskFirst::test_it_is_the_in_app_modal_not_the_browser_one` | Un `confirm()` del navegador bloquea la página y no se puede traducir |
| `TestTheDestructiveOnesAskFirst::test_a_harmless_command_is_not_gated` | Preguntar siempre enseña a pulsar sin leer |
| `TestTheDestructiveOnesAskFirst::test_the_message_names_what_is_being_emptied` | |
| `TestTheDestructiveOnesAskFirst::test_every_destructive_command_has_its_wording` | En los dos idiomas, y con hueco para el nombre del servicio |
| `TestTheLabelsExist::test_every_command_is_translated` | Sin etiqueta el menú saldría con la clave cruda |

---

## 115. Modules — cuatro layouts, no cuatro renderizadores

**Archivo:** `tests/test_wa_modules_views.py` — 19 tests

La sección tenía uno: una rejilla de tarjetas, cada una desplegando su configuración dentro de
una celda de 420 px. Ese layout **ya admitía** que la celda se quedaba corta: llevaba un botón
de «pantalla completa» que reabría el mismo cuerpo en un modal, que es un apaño para el
contenedor, no una funcionalidad. Se escribieron tres más para compararlos: lista-y-detalle,
tabla densa, y tarjetas compactas con editor a ancho completo.

**Una vista es chrome y navegación. Nada más.** Cómo se ve la configuración de un módulo es
`renderModuleBody()`, que las cuatro usan tal cual. En cuanto una vista pinte un campo por su
cuenta, un fallo de campo tiene cuatro sitios donde arreglarse y tres se olvidan. Esa es la
regla que sostiene el fichero, y casi todo lo demás es una forma de ella:

- ninguna vista construye el cuerpo de un módulo: llaman al renderizador compartido;
- ninguna decide por su cuenta qué es un «ítem», si un módulo está disponible o quién puede
  editarlo — `_modFacts()` lo contesta una vez;
- el conmutador, el filtro y la selección son estado de la **sección**, no de cada vista, así
  que cambiar de vista conserva lo que tenías escrito y seleccionado.

La otra mitad son las cosas que un cambio de layout rompe en silencio: el permiso de solo
lectura, el deep-link que auto-expande un ítem recién añadido, y un módulo con dependencias
que faltan — al que no se le puede ofrecer un editor cuyos campos no surten efecto.

Escribiendo el guard salió una duplicación que ya existía: el selector de «nuevo módulo» leía
las tres banderas de descubrimiento por su cuenta, a una divergencia de ofrecer un módulo que
la lista luego se negaría a configurar. Ahora ambos preguntan a `_modAvailability()`.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_the_registry_is_found` | |
| `TestTheScanItself::test_every_view_file_exists` | |
| `TestAViewIsChromeOnly::test_no_view_builds_a_module_body_itself` | **La regla**: una cuarta copia del formulario es un fallo con tres escondites |
| `TestAViewIsChromeOnly::test_the_view_only_case_is_applied_in_one_place` | Olvidar `_applyReadonly` es ofrecer un editor que tira lo que escribes |
| `TestAViewIsChromeOnly::test_no_view_counts_items_itself` | «Qué cuenta como ítem» ya estaba escrito dos veces antes de esto |
| `TestAViewIsChromeOnly::test_no_view_decides_availability_itself` | Dos lecturas de las banderas pueden discrepar sobre si un módulo funciona |
| `TestTheSectionOwnsTheState::test_the_switcher_is_driven_by_the_registry` | Añadir una vista es una entrada, no una entrada más un botón más una rama |
| `TestTheSectionOwnsTheState::test_the_chosen_view_survives_a_reload` | |
| `TestTheSectionOwnsTheState::test_the_filter_is_shared_by_every_view` | Si cada vista filtra, el mismo texto significa dos cosas |
| `TestTheSectionOwnsTheState::test_the_filter_matches_id_and_display_name` | La mitad de las veces recuerdas uno y la mitad el otro |
| `TestWhatALayoutChangeBreaksQuietly::test_the_render_entry_point_is_still_one_function` | Una docena de sitios llaman a `renderModules()`; las vistas cuelgan de ella, no la sustituyen |
| `TestWhatALayoutChangeBreaksQuietly::test_an_unknown_stored_view_falls_back` | Un valor rancio en localStorage dejaría la sección en blanco |
| `TestWhatALayoutChangeBreaksQuietly::test_the_expand_modal_is_still_refreshed` | Un ítem añadido con el modal abierto aparecería en la lista de detrás y no en el modal de delante |
| `TestWhatALayoutChangeBreaksQuietly::test_the_auto_expand_deep_link_is_preserved` | La captura tiene que ir antes de generar HTML: generarlo es lo que consume la bandera |
| `TestWhatALayoutChangeBreaksQuietly::test_the_count_badge_keeps_its_id_in_every_view` | `_refreshModuleCount` lo actualiza en sitio; sin el id se congelaría |
| `TestWhatALayoutChangeBreaksQuietly::test_an_unavailable_module_is_not_offered_an_editor` | Un formulario que parece editable es peor que decir por qué no lo hay |
| `TestTheSelectionIsHonest::test_a_selection_that_is_no_longer_shown_falls_back` | Un módulo borrado o filtrado dejaría el detalle sin nada que lo resalte al lado |
| `TestTheSelectionIsHonest::test_the_compact_editor_closes_when_its_module_goes` | |
| `TestTheLabelsExist::test_every_view_is_named_in_both_languages` | |

---

## 116. Status — cuatro layouts que tienen que coincidir en qué está fallando

**Archivo:** `tests/test_wa_status_views.py` — 32 tests

El **Resumen** estuvo a punto de no tener nombre propio: al mover la barra de totales a una
cabecera que dibujan las cuatro vistas, se quedó siendo la rejilla de tarjetas en otro orden —
dos vistas de cuatro diferenciándose por un `sort`. Ahora gasta página en un módulo en
proporción a lo que ese módulo tiene que decir: el que falla se abre en tarjeta, el que está
bien se colapsa a una línea, y esa línea sigue siendo una entrada (un clic la abre).

Status es una superficie de **monitorización**, así que sus layouts se diferencian en una
cosa: cuánto tardan en contestar «¿qué está roto ahora mismo?». La rejilla de tarjetas tarda
mucho — hay que pasar por delante de todo lo verde para encontrar los dos que no lo están —,
así que se le suman tres: un resumen con los totales y los problemas ordenados primero, una
tabla plana de checks, y un mosaico.

**Lo que no puede diferir es qué SIGNIFICA un check.** Si un resultado es ok / aviso / error,
cuál es su nombre visible y la decoración valor-contra-umbral que su módulo declara en
`__status_render__` se deciden una vez y todas las vistas beben de ahí. Una vista que leyera
`status` y `severity` por su cuenta sería libre de discrepar de la tarjeta de al lado sobre el
mismo check — y en una página cuyo trabajo entero es decir qué va mal, dos paneles
contradiciéndose es peor que cualquiera de los dos equivocado por separado.

La distinción que más caro sale perder es **aviso frente a error**. Un rebase blando de umbral
es ámbar, no rojo; pintar los dos de rojo es cómo una página llena de «todo está ardiendo»
deja de leerse, y es justo lo que se re-deriva ligeramente distinto en un cuarto sitio.

Los tres controles (filtro, vista, «solo problemas») viven **con los totales**, no en una
fila propia ni en la barra del Scheduler, que es donde visiblemente sobra sitio: esa barra
solo se dibuja con permiso `checks_run`, y filtrar o cambiar de vista es **leer**, no
ejecutar. Ponerlos ahí se los quitaría justo a quien solo puede mirar.

«Solo problemas» **se recuerda** entre visitas, y lo que lo hace seguro es dónde acabó el
interruptor: junto a los totales, que siempre declaran el conjunto entero. La página puede
estar filtrada, pero no puede mentir sobre cuánto hay. El texto del buscador **no** se
recuerda, y la diferencia es real: los totales no dicen nada de un filtro de texto, así que
una página que abriera con uno aplicado en silencio no tendría cómo admitirlo.

El resto va de lo que un redibujado **no** puede hacer: cambiar de vista, filtrar o marcar
«solo problemas» miran los **mismos** datos, así que ninguno puede volver a pedirlos — en una
página que se auto-refresca, un redibujado que pide datos además compite con su propio timer.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_the_registry_is_found` | |
| `TestTheScanItself::test_every_view_file_exists` | |
| `TestEveryViewAgreesOnWhatACheckIs::test_a_check_state_is_decided_in_one_place` | |
| `TestEveryViewAgreesOnWhatACheckIs::test_no_view_reads_the_raw_result_itself` | `status === true` en una vista es una segunda opinión sobre el mismo check |
| `TestEveryViewAgreesOnWhatACheckIs::test_no_view_re_derives_the_warning_rule` | **La distinción cara**: ámbar no es rojo |
| `TestEveryViewAgreesOnWhatACheckIs::test_the_schema_decoration_is_rendered_once` | Cuatro lectores de `__status_render__` son cuatro números distintos para el mismo valor |
| `TestEveryViewAgreesOnWhatACheckIs::test_the_palette_is_shared` | Dos colores separándose es cómo una página deja de poder ojearse |
| `TestEveryViewAgreesOnWhatACheckIs::test_a_phantom_row_is_excluded_once` | Una entrada sin `status` es contabilidad, no un check |
| `TestTheControlsSitWithWhatTheyControl::test_there_is_one_header_and_every_view_uses_it` | Filtro, vista y «solo problemas» viven **con los totales**, en una sola barra |
| `TestTheControlsSitWithWhatTheyControl::test_no_view_builds_the_totals_bar_itself` | |
| `TestTheControlsSitWithWhatTheyControl::test_the_controls_do_not_depend_on_the_run_permission` | **El sitio donde no pueden ir**: la barra del Scheduler solo existe con `checks_run`, y filtrar es leer, no ejecutar |
| `TestTheControlsSitWithWhatTheyControl::test_a_view_may_add_one_thing_of_its_own` | La leyenda del mosaico es de esa vista, no de la barra: se pasa, no se reconstruye |
| `TestTheSummaryEarnsItsName::test_a_failing_module_gets_a_card` | |
| `TestTheSummaryEarnsItsName::test_a_passing_module_collapses_to_a_line` | Doce módulos que están bien deben costar doce líneas, no doce tarjetas |
| `TestTheSummaryEarnsItsName::test_that_line_is_still_a_way_in` | Querer mirar un módulo que pasa es normal y no debe obligar a cambiar de vista |
| `TestTheSummaryEarnsItsName::test_what_you_opened_is_not_remembered` | Un resumen que se fuera llenando de todo lo abierto alguna vez sería la rejilla con pasos de más |
| `TestTheSummaryEarnsItsName::test_a_module_with_no_items_is_not_called_passing` | No ejecutó nada; decir OK sería la mentira pequeña de la propia página |
| `TestTheSummaryEarnsItsName::test_it_no_longer_merely_reorders_the_grid` | **La regresión**: dos vistas que solo se diferencian en el orden |
| `TestLookingIsNotFetching::test_switching_view_redraws_the_data_it_has` | Es una forma de **mirar** el último resultado, no de pedir otro |
| `TestLookingIsNotFetching::test_filtering_redraws_too` | |
| `TestLookingIsNotFetching::test_the_payload_is_kept_for_that` | |
| `TestLookingIsNotFetching::test_the_draw_step_is_separate_from_the_load` | |
| `TestTheOrderIsPartOfTheAnswer::test_problems_come_first` | Una página con la primera pantalla verde y el fallo tres filas más abajo te ha hecho scrollear para saber algo que ya sabía |
| `TestTheOrderIsPartOfTheAnswer::test_the_baseline_view_is_not_reordered` | Las tarjetas son la referencia contra la que se comparan las otras tres; reordenarlas cambiaría lo comparado |
| `TestTheOrderIsPartOfTheAnswer::test_the_filter_still_applies_to_it` | Filtrar es estado de la sección, no propiedad de un layout |
| `TestOnlyProblemsIsHonest::test_it_hides_the_passing_CHECKS_too` | **El bug**: quedarse solo con los módulos que tienen un problema no basta — un módulo con un error y ocho checks OK seguía listando los nueve |
| `TestOnlyProblemsIsHonest::test_the_counts_still_include_them` | La cabecera sigue diciendo «6/9 OK»: esconder los que pasan no puede esconder que existen |
| `TestOnlyProblemsIsHonest::test_it_survives_a_reload` | Si así es como trabajas, no deberías tener que decirlo en cada visita |
| `TestOnlyProblemsIsHonest::test_the_totals_beside_it_still_report_everything` | Lo que hace **seguro** recordarlo: la línea junto al interruptor sigue declarando el conjunto entero |
| `TestOnlyProblemsIsHonest::test_the_search_term_is_not_remembered` | Los totales no dicen nada de un filtro de texto, así que una página que abriera con uno puesto no podría admitirlo |
| `TestOnlyProblemsIsHonest::test_the_empty_state_says_which_emptiness_it_is` | «No hay checks» y «nada coincide con tu filtro» son noticias distintas |
| `TestTheLabelsExist::test_every_view_is_named_in_both_languages` | |

---

## 117. Marcado que no hace lo que sugiere el nombre de la clase

**Archivo:** `tests/test_wa_css_traps.py` — 9 tests

Tres trampas: dos encontradas la misma tarde mirando la tabla de Status y la tercera reportada desde una captura, las tres invisibles en revisión y evidentes en pantalla.

**Una clase que ignora el tema.** El panel se sirve en claro y oscuro y recuerda cuál elegiste, así que un componente que
decide sus propios colores acierta la mitad de las veces. El que cayó fue una cabecera de
tabla: `.table-light` de Bootstrap pone fondo claro **y** texto oscuro sin mirar
`data-bs-theme`, así que en modo oscuro la tabla de checks llevaba una franja blanca con
letras negras — lo único claro de la página.

Para cuando se vio, estaba en **tres sitios**, y ese es el argumento para un guard y no para
tres arreglos: dos se escribieron la misma semana desde la misma costumbre, y el tercero
llevaba ahí lo bastante como para que ya nadie lo viera.

**Una celda que deja de serlo.** `d-flex` sobre un `<td>` lo saca de `display:table-cell`,
así que ya no participa en la altura de la fila y su borde inferior se dibuja a la altura
de su propio contenido. El separador de filas se parte en esa columna mientras el resto de
tablas del panel mantienen la línea recta.

**Un botón del color de lo que tiene debajo.** `btn-dark` no es ciego al tema: es correcto en
el claro y casi invisible en el oscuro, donde cae a un tono o dos de la superficie de la
tarjeta (#181818 / #212121 / #2a2a2a). Reportado desde una captura del botón de auto-refresco:
con el intervalo apagado el control desaparecía en la cabecera y solo el caret delataba que
había algo. Un botón de refresco que no se ve mientras está apagado es un botón que nadie
encuentra para encenderlo.

La sustituta es `.ss-btn-graphite`, un botón sólido oscuro un escalón por encima de la misma
escala de grises del tema oscuro — discreto, que es lo correcto para un estado apagado, sin
ser la tarjeta sobre la que se apoya. Gris y no un oscuro con tinte a propósito: primero se
probó un slate azulado y se leía como un color venido de otra paleta.

La regla del tema es que un componente pida una **variable** de Bootstrap (`--bs-tertiary-bg` y
compañía) o una de las clases propias del panel construidas sobre ellas, y decida el tema.

Lo que el guard **no** prohíbe importa tanto como lo que prohíbe: `bg-light` se dejó fuera a
propósito. Un `badge bg-light text-dark` dentro de un botón primario es claro contra **el
botón**, no contra la página, y es correcto en ambos temas. Prohibirlo habría señalado cinco
plantillas que están bien y habría enseñado al siguiente a desactivar el test.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_templates_are_found` | |
| `TestNoTemplatePinsALightSurface::test_none_of_the_theme_blind_classes_is_used` | **La regresión**: `class="… table-light …"`, solo en marcado, no en un comentario |
| `TestNoTemplatePinsALightSurface::test_the_replacement_exists_and_is_theme_driven` | Si la clase sustituta fijara un color, el guard solo habría movido el problema detrás de un nombre mejor |
| `TestNoTemplatePinsALightSurface::test_the_tables_that_had_it_use_the_replacement` | Las tres donde apareció, nombradas: volver atrás en cualquiera es la regresión que este fichero vigila |
| `TestNoControlWearsTheSurfaceColour::test_no_button_uses_btn_dark` | **La tercera trampa**, global: ninguna plantilla puede volver a vestir `btn-dark` (ignorando comentarios, que nombran la clase para explicar por qué se abandonó) |
| `TestNoControlWearsTheSurfaceColour::test_the_auto_refresh_off_state_uses_the_graphite_button` | Nombrado explícitamente: el estado apagado es el que una vuelta atrás silenciosa escondería otra vez — nadie se fija en un botón que solo está mal mientras no hace nada |
| `TestNoControlWearsTheSurfaceColour::test_the_graphite_button_is_not_one_of_the_surfaces` | Si se define con una variable de superficie, vuelve a ser invisible sobre esa superficie |
| `TestNoControlWearsTheSurfaceColour::test_it_stays_on_the_neutral_ramp` | Los tres canales del hex, iguales: el tema oscuro es una escala de grises y su único botón oscuro también tiene que serlo |
| `TestATableCellStaysATableCell::test_no_cell_is_turned_into_a_flex_container` | **La segunda trampa**: `d-flex` en un `<td>` lo saca de `display:table-cell`, deja de contar para la altura de la fila y su borde se dibuja a la altura del contenido — el separador se parte justo en esa columna |

---

## 118. Páginas de módulo — cuatro layouts que son del núcleo, no de un módulo

**Archivo:** `tests/test_wa_module_page_views.py` — 36 tests

Un módulo aporta una sección de primer nivel declarando `__page__` y contestando con una
forma fija: secciones de filas, cada fila con estado, mensaje y lo que la comprobación haya
medido. Como la forma es fija, **los layouts son mobiliario del núcleo**: Microsoft 365 y
Azure los reciben del mismo código, y un módulo que aporte una página mañana los hereda sin
escribir nada de front-end.

Eso estuvo a punto de perderse. M365 traía **su propio** renderizador —declarado en su
schema, viviendo en `web/_ui.html`— que empezó siendo una copia del del núcleo y dejó de
seguirle: cuando se miró, el núcleo había ganado la agrupación por métrica y la copia no. No
era un diseño distinto, era uno más viejo. Así que las vistas fueron al renderizador genérico
y la copia se retiró, en lugar de escribir un cuarto renderizador a su lado.

**El anillo de uso** es el mismo trato que `group_by`: el módulo declara **qué dos medidas**
son el par usado/total y el núcleo divide. Ninguna clave de métrica aparece en el núcleo — hay
un guard que lo comprueba, porque es justo el conocimiento que no le toca tener. Dos detalles
que costaron un ida y vuelta cada uno: se dibuja **por fila**, no por sección (sumar los
sitios contesta «cuán lleno está SharePoint entero», que nadie pregunta, y esconde qué sitio
se está llenando); y cuando falta el total **se dibuja un anillo vacío** en vez de nada,
porque una ausencia muda obliga a salir de la página para averiguar por qué.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×2) | El registro y el cableado de los dos ficheros |
| `TestTheLayoutsBelongToTheCore::test_no_shipped_module_declares_its_own_page_renderer` | **La regla**: un segundo renderizador merece una conversación, no aparecer en silencio |
| `TestTheLayoutsBelongToTheCore::test_the_retired_renderer_is_really_gone` | Una copia muerta en el árbol es la que edita el siguiente |
| `TestAViewIsChromeOnly::test_no_view_draws_a_row_itself` | Una vista que montara una fila podría discrepar de la de al lado sobre el mismo check |
| `TestAViewIsChromeOnly::test_the_measurements_are_rendered_once` | |
| `TestAViewIsChromeOnly::test_the_filter_is_applied_in_one_place` | |
| `TestTheRingIsDeclaredNotGuessed::test_the_core_only_draws_what_it_was_told` | Ningún nombre de métrica en el núcleo |
| `TestTheRingIsDeclaredNotGuessed::test_a_missing_total_never_becomes_a_number` | Un 0,0% que se lee como medida y no lo es |
| `TestTheRingIsDeclaredNotGuessed::test_a_missing_total_says_so_instead_of_vanishing` | La ausencia muda costó un ida y vuelta real |
| `TestTheRingIsDeclaredNotGuessed::test_the_placeholder_shows_no_percentage` | Cualquier cifra dentro se leería como dato |
| `TestTheRingIsDeclaredNotGuessed::test_it_is_drawn_per_row_not_per_section` | |
| `TestTheRingIsDeclaredNotGuessed::test_every_view_shows_it` | Una cifra en un layout y no en el siguiente hace que se contradigan |
| `TestTheRingIsDeclaredNotGuessed::test_the_label_is_centred_by_declaration` | El ajuste a ojo solo acierta a un tamaño |
| `TestTheRingIsDeclaredNotGuessed::test_each_declared_pair_is_what_that_check_publishes` | **El error que cazó**: `total_bytes` frente a `limit_bytes`; la declaración equivocada no pintaba nada, en silencio |
| `TestTheRingIsDeclaredNotGuessed::test_it_is_only_offered_when_the_rows_carry_both` | |
| `TestTheRingIsDeclaredNotGuessed::test_the_ring_takes_its_colour_from_the_row` | Una escala «más lleno es peor» vale para un disco y no para lo demás: un anillo rojo junto a una fila ámbar son dos señales discrepando sobre el mismo registro |
| `TestTheRingIsDeclaredNotGuessed::test_it_needs_no_charting_library` | Un anillo no justifica una dependencia, y la CSP prohíbe traerla |
| `TestTheStateBelongsToThePage::*` (×3) | Vista y filtro son **por página**: querer la tabla para Azure y el cuadro para M365 a la vez es normal |
| `TestTheBoardIsASummaryNotAFilteredList::*` (×3) | Las casillas **son** el conjunto; la lista de abajo es lo que necesita atención — y el interruptor tenía que morder también las casillas |
| `TestATileIsBoundedAndReadsAsOne::*` (×3) | Una rejilla de cifras sin bordes es una rejilla de cifras ambiguas: el badge estaba a la derecha del todo, o sea lo más lejos posible de su número y lo más cerca de la etiqueta de al lado |
| `TestTheTwoPanesLineUp::*` (×4) | Una sola clase con altura fija: con contenidos distintos a cada lado, igualar el padding alinea por casualidad |
| `TestOnlyProblemsIsHonest::*` (×3) | Esconde filas, nunca los recuentos |
| `TestTheLabelsExist::test_every_view_is_named_in_both_languages` | |

---

## 119. Ejecutar un check una vez — la proyección es el contrato

**Archivo:** `tests/test_module_check_runner.py` — 11 tests

Dos funciones necesitan exactamente lo mismo: el botón **probar** de Servers y el **refresco
en vivo** de una página de módulo. Las dos quieren el `check()` **real** del módulo —una sonda
que pasara por otro código no probaría nada de lo que corre a las 3 de la mañana—, así que el
módulo recibe un Monitor mínimo y se le llama. Eso es `lib/modules/check_runner.py`, y estuvo
viviendo en `lib/core/hosts/probe.py` porque allí se necesitó primero: la capa genérica
dependiendo de **un** dominio.

La factura llegó como bug. El runner no devuelve el resultado del módulo tal cual: lo
**reconstruye campo a campo**, y esa lista blanca es el único sitio que decide qué sobrevive a
una ejecución bajo demanda. `severity` no estaba en ella, así que un aviso de umbral llegaba
indistinguible de una caída y la página lo pintaba rojo mientras el resultado guardado del
**mismo** check salía ámbar. Nada falló: se perdió información, que es la forma más cara de
romperse. `name` iba detrás, por la misma puerta.

De ahí el guard: `RESULT_FIELDS` se compara con lo que `ReturnModuleCheck.set()` escribe, y un
campo nuevo del contrato tiene que estar proyectado **o** excluido a propósito
(`RESULT_FIELDS_EXCLUDED`, hoy solo `send`, que es la compuerta de notificación y no parte de
la respuesta). Verificado quitando `severity`: falla nombrándolo.

| Test | Qué comprueba |
|---|---|
| `TestTheProjectionMatchesTheContract::test_no_field_of_the_contract_is_lost_by_omission` | **La regla**: ningún campo se cae por olvido |
| `TestTheProjectionMatchesTheContract::test_nothing_is_projected_that_the_contract_does_not_write` | Y al revés: nada inventado |
| `TestTheProjectionMatchesTheContract::test_the_exclusion_is_only_the_notify_gate` | La lista de exclusiones no puede volverse un escondite |
| `TestTheProjectionMatchesTheContract::test_every_projected_field_reaches_the_caller` | |
| `TestTheProjectionMatchesTheContract::test_the_notify_gate_does_not_reach_the_caller` | Una ejecución puntual no notifica a nadie |
| `TestASeveritySurvivesTheRun::test_a_warning_is_not_reported_as_a_failure` | **El bug**: ámbar o rojo según quién lo ejecutara |
| `TestASeveritySurvivesTheRun::test_a_plain_failure_carries_no_severity` | El vacío **es** el dato: significa «esto sí es un error» |
| `TestASeveritySurvivesTheRun::test_a_field_the_module_never_set_reads_as_empty_not_missing` | Quien tenga que preguntar si la clave existe acabará olvidándolo, y la rama que olvide es la ámbar |
| `TestItRunsTheRealCheck::*` (×2) | Un módulo sin `Watchful` no corre en silencio; un resultado no-dict no es fatal |
| `TestTheStandInIsAMonitor::test_is_a_monitor` | La firma tiene que reflejar `Monitor.send_message` o cualquier módulo que avise revienta |

---

## 120. Credentials es una sección, no una sub-pestaña de Infrastructure

**Archivo:** `tests/test_wa_credentials_section.py` — 11 tests

Credentials llegó a Infrastructure cuando el catálogo eran **identidades SSH reutilizables**, y
el comentario que justificaba la mudanza decía exactamente eso. Dejó de ser verdad: la mitad
del catálogo son hoy registros de aplicación de Entra ID —se alcanzan por *tenant*, sin ningún
host detrás— y los flujos construidos alrededor (rotar un secreto, conceder y consentir los
roles que le faltan a una app) no tocan ninguna máquina.

Dos razones estructurales, más allá de la población. Sus vecinas bajo Infrastructure —Servers
y Clusters— son **cosas que monitorizas**; una credencial no se monitoriza, es el secreto con
el que alcanzas otras cosas. Y sus consumidores están repartidos entre hosts, módulos y
proveedores, así que colgarla de cualquiera de los tres afirma una pertenencia que no existe.
Tampoco a Access: ahí viven usuarios, grupos, roles y sesiones —*quién entra al panel*—, y
estas son identidades de máquina que el panel usa hacia fuera.

De paso se cazó un puntero podrido: el widget de Overview declaraba `nav: {tab: '#tab-access',
sub: '#subtab-credentials'}` mucho después de que la pestaña se hubiera ido de Access, así que
al pulsarlo abría el panel equivocado y luego buscaba una sub-pestaña que vivía dentro de un
tercero. **Un destino muerto es peor que uno ausente**: Bootstrap no activa nada y no dice
nada, así que la sección simplemente no se abre y no hay error que seguir.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::test_every_file_is_found` | Las siete superficies que participan |
| `TestItIsATopLevelSection::test_the_sidebar_lists_it_among_the_panel_tabs` | **La regla** |
| `TestItIsATopLevelSection::test_it_declares_no_sub_tabs` | Una sección con sub-pestañas es un contenedor; esta tiene una sola lista |
| `TestItIsATopLevelSection::test_the_pane_exists_and_the_shell_includes_it` | |
| `TestItIsATopLevelSection::test_infrastructure_no_longer_carries_it` | Marcado huérfano es el que edita el siguiente |
| `TestNothingStillPointsAtTheOldSubTab::test_no_file_targets_the_retired_sub_pane` | Un destino muerto no da error, solo no hace nada |
| `TestNothingStillPointsAtTheOldSubTab::test_the_overview_widget_points_at_the_section` | **El puntero podrido** que cazó |
| `TestNothingStillPointsAtTheOldSubTab::test_a_stored_sub_tab_from_before_does_not_strand_infrastructure` | Quien tuviera guardada la sub-pestaña vieja aterriza en una visible, no en ninguna |
| `TestTheGateTravelledWithIt::test_the_section_is_shown_by_its_own_permissions` | |
| `TestTheGateTravelledWithIt::test_infrastructure_is_no_longer_revealed_by_a_credential_permission` | Antes `credentials_view` abría Infrastructure por ella; ahora sería una pestaña vacía |
| `TestTheGateTravelledWithIt::test_it_still_loads_on_access` | Cargar al abrir, no al arrancar: un panel que precargara todo pagaría por todas para enseñar una |

---

## 121. Un widget de módulo, añadido varias veces y configurado por instancia

**Archivo:** `tests/test_overview_module_widget_instances.py` — 20 tests

Una sola tarjeta no puede contestar «cómo va Microsoft 365»: esa pregunta son varias —cuánto
almacenamiento queda, cuánto del directorio registró MFA, cuánto margen hay de licencias— y
querer dos a la vez en pantalla es el caso normal, no el exótico.

Lo llamativo es que **el mecanismo ya estaba construido y nunca se encendió**: los ids de
instancia llevan sufijo `:N`, `mws`/`mwlvl` se guardan por instancia, y la barra de añadir
sigue ofreciendo un widget cuya declaración diga `multi`. Faltaba la declaración. Incluso había
un `_dwIsMulti()` definido y sin usar en ningún sitio.

El **anillo de uso** es el mismo trato que en las páginas de módulo: el módulo dice qué dos
medidas son una fracción y entrega los números **ya divididos**; el núcleo no divide ni conoce
ningún nombre de métrica —hay un guard que falla si aparece uno— y decide solo dónde va y de
qué color, que lo toma del estado de la entrada. Dos sitios donde deliberadamente **no**
aparece: en el scope agregado, porque no se suman porcentajes de almacenamiento con los de un
score; y cuando falta el total, porque un anillo sin total es un 0 % con pinta de dato.

De paso cazó un fallo anterior: `normalize_layout()` se quedaba solo con la geometría, así que
un admin que publicara su Overview como layout por defecto de la organización repartía **las
cajas correctas enseñando lo que no era** — el scope y el filtro se perdían por el camino.

| Test | Qué comprueba |
|---|---|
| `TestTheWidgetCanBeAddedMoreThanOnce::*` (×3) | La declaración `multi`, la regla que la hace valer, y que `mw_x:2` resuelva a su tipo |
| `TestEachInstanceKeepsItsOwnSettings::test_the_three_settings_are_saved_per_instance` | `mws`, `mwlvl` y `mwchart` viajan con el layout |
| `TestEachInstanceKeepsItsOwnSettings::test_a_saved_default_layout_keeps_them` | **El fallo que cazó**: el default de la organización los perdía |
| `TestEachInstanceKeepsItsOwnSettings::test_absent_settings_are_not_invented` | Ausente y vacío se leen igual, pero no en un diff de dos layouts |
| `TestEachInstanceKeepsItsOwnSettings::test_junk_entries_are_still_dropped` | |
| `TestTheModuleSuppliesTheRatio::*` (×6) | Quién mide una fracción, quién no, y que un total ausente no produzca un cero |
| `TestTheModuleSuppliesTheRatio::test_one_incomplete_result_disqualifies_the_whole_kind` | Sumar lo presente e ignorar lo que falta reporta **menos lleno** de lo que está |
| `TestTheCoreOnlyDraws::test_no_metric_name_reaches_the_core` | El día que el núcleo conozca `used_bytes`, añadir un módulo será editar el núcleo |
| `TestTheCoreOnlyDraws::test_the_colour_comes_from_the_state_not_from_the_percentage` | Dos señales discrepando sobre un registro es peor que una sola equivocada |
| `TestTheCoreOnlyDraws::test_the_aggregate_scope_draws_none` | Un anillo ahí sería una cifra sin pregunta detrás |
| `TestTheCoreOnlyDraws::*` (resto ×3) | Opt-in por instancia, sin total no dibuja, y sin librería de gráficos |
| `TestTheLabelExists::test_the_toggle_is_named_in_both_languages` | |

---

## 122. Services — cuatro vistas, y la que pivota sobre la instancia

**Archivo:** `tests/test_wa_services_views.py` — 22 tests

Services es una superficie de **control**, así que sus vistas se diferencian en qué ponen en
posición de sujeto. La rejilla de tarjetas pone el servicio, y eso está bien hasta que hay
instancias: entonces cada una solo se ve dentro de la tarjeta de su servicio, la flota se lee
de una en una y nunca entera. Eso esconde justo los dos fallos que tiene un despliegue
multi-contenedor y no tiene uno de un solo contenedor:

- un **seguidor que dejó de reportar** mientras el líder sigue, así que el servicio sigue
  diciendo RUNNING y la redundancia se ha ido en silencio;
- un **contenedor rezagado en otra versión**, que ninguna tarjeta por servicio puede enseñar
  porque la deriva solo se ve cuando las versiones están una al lado de la otra.

La vista **flota** invierte eso: la instancia es el sujeto y el servicio pasa a ser uno de sus
atributos. Es superficie de **lectura**: no ofrece arrancar/parar, porque esas acciones son
sobre un SERVICIO y esta página no está enseñando servicios — un botón por fila invitaría a
pulsarlo contra la fila que tengas delante.

El guard que no es cosmético es `test_no_view_builds_its_own_action_buttons`: el permiso
`services_control` se comprueba dentro de `_svcActionsHtml` y **en un solo sitio**. Una vista
que se montara sus propios botones sería una vista libre de ofrecer «Parar» a quien no puede
pulsarlo, y eso no es un fallo de estilo.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Registro, ficheros y que el bundle los incluya **después** del registro (si no, la vista cae en silencio al fallback) |
| `TestAViewIsChromeOnly::test_no_view_builds_its_own_action_buttons` | **La regla**: ninguna vista cablea `servicesControl` ni re-comprueba el permiso |
| `TestAViewIsChromeOnly::test_the_permission_is_asked_in_exactly_one_place` | |
| `TestAViewIsChromeOnly::test_no_view_invents_a_state_colour` | `stale` es un color en todas partes |
| `TestAViewIsChromeOnly::test_the_state_badge_comes_from_one_helper` | |
| `TestTheHeaderIsDrawnOnce::*` (×3) | Totales, conmutador y Refresh en el despachador; los totales cuentan **también instancias**, que es lo que se mueve |
| `TestSwitchingViewCostsNothing::*` (×3) | Conmutar redibuja: pedir datos para contestar una pregunta de presentación además correría contra el temporizador de sondeo |
| `TestTheFleetViewIsThePoint::test_it_offers_no_start_or_stop` | La instancia es el sujeto; las acciones no son suyas |
| `TestTheFleetViewIsThePoint::test_a_service_with_no_leader_is_not_called_standby` | Un servicio activo-activo no tiene líder; decir «standby» inventaría una jerarquía |
| `TestTheFleetViewIsThePoint::test_version_drift_is_computed_across_the_fleet` | Es un hecho del conjunto: ninguna fila puede saberlo sola |
| `TestTheFleetViewIsThePoint::test_the_list_does_not_reorder_itself_on_a_timer` | **Reportado**: las filas cambiaban de sitio en cada refresco. Ordenaba por último latido —el campo más volátil de la fila— así que instancias con ritmos parecidos se adelantaban unas a otras en cada sondeo. Una lista que se reordena sola no se puede leer ni pulsar |
| `TestTheFleetViewIsThePoint::test_the_rank_is_not_the_colour_vocabulary` | Para ordenar bastan tres rangos; el badge conserva el vocabulario completo |
| `TestTheFleetViewIsThePoint::test_it_reads_every_instance_across_every_service` | |
| `TestSilenceIsNotFreshness::test_never_reported_is_not_drawn_as_a_time` | «Nunca reportó» y «hace mucho» no pueden parecer lo mismo |
| `TestTheLabelsExist::*` (×2) | Las cuatro vistas y las nueve columnas, en los dos idiomas |

## 123. Credentials — cuatro vistas, y la que pregunta quién las usa

**Archivo:** `tests/test_wa_credentials_views.py` — 30 tests

La tabla contesta «qué tengo» y nada más. Encima de los mismos datos hay dos preguntas que no
puede contestar:

- **qué CLASE de secreto es cada uno.** Una identidad SSH y un registro de aplicación de
  tenant no son el mismo animal —una llega a una máquina, el otro es una aplicación con
  permisos consentidos y ningún host detrás— y ordenar por la columna Tipo solo los
  entremezcla en una lista;
- **quién la REFERENCIA todavía**, que no forma parte de la credencial: sus consumidores viven
  en el store de hosts y dentro de la config de cada módulo. Hasta ahora la única forma de
  verlo era abrir una credencial y pulsar su pestaña Uso — de una en una, que contesta «¿puedo
  borrar ésta?» y nunca «¿de qué está lleno este catálogo?».

Vista entera, la de uso contesta la pregunta que pudre un almacén de credenciales: un secreto
que no referencia nadie es un secreto que no rota nadie, y sigue siendo válido.

Lo que **no** puede diferir entre vistas es qué significa una credencial: el badge de tipo, la
marca de inactiva y sobre todo las **acciones** se deciden una vez y las compone cada vista. El
guard que no es cosmético es `test_no_view_builds_its_own_action_buttons`: los permisos
`credentials_*` se convierten en botones dentro de `_credActionsHtml` y en un solo sitio.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Registro, ficheros y que el bundle los incluya **después** del registro (si no, la vista cae en silencio a un cuerpo vacío) |
| `TestAViewIsChromeOnly::test_no_view_builds_its_own_action_buttons` | **La regla**: ninguna vista cablea `deleteCred`/`cloneCred`/`openEditCredModal` |
| `TestAViewIsChromeOnly::test_the_table_composes_the_same_builder` | También la tabla: en cuanto una de las cuatro se monta sus botones, «qué botones tiene una credencial» tiene dos respuestas |
| `TestAViewIsChromeOnly::test_the_permissions_are_asked_in_one_place` | `canEdit`/`canAdd`/`canDelete` se resuelven en `prepare()` y se vuelven controles en una única función |
| `TestAViewIsChromeOnly::test_no_view_picks_the_type_colour_itself` | El color del tipo sale del mismo hash que usa el widget de Overview, así que un tipo viste un color en todo el panel — incluidos los tipos que este build no ha visto nunca |
| `TestTheFourViewsShareOnePage::test_the_non_table_views_go_through_the_factory` | Filtro, orden y paginación siguen en `createListTable`: ninguna vista puede enseñar un conjunto distinto del que anuncia la banda de paginación |
| `TestTheFourViewsShareOnePage::test_the_grouped_views_are_summaries_not_pages` | Cuentan cosas —cuántas de cada tipo, cuántas huérfanas— y un recuento sobre una página es una afirmación sobre la paginación: tres SSH cuando hay diez, y otras tres en la página siguiente |
| `TestTheFourViewsShareOnePage::test_no_view_fetches_the_catalogue_again` | |
| `TestTheFourViewsShareOnePage::test_the_switcher_is_drawn_by_the_header_not_the_views` | |
| `TestTheFourViewsShareOnePage::test_the_column_chooser_belongs_to_the_table` | Configura columnas; las otras tres no tienen |
| `TestTheFourViewsShareOnePage::test_the_choice_is_remembered_both_ways` | En este navegador y en la config del usuario, para que le siga al siguiente |
| `TestTheFourViewsShareOnePage::test_switching_view_does_not_refetch` | |
| `TestASelectionYouCannotSee::*` (×2) | Las vistas agrupadas no dibujan casillas, así que arrastrar una selección hasta ellas dejaría la barra de acciones masivas armada sobre filas que ya no están en pantalla |
| `TestUsageIsADifferentFact::test_it_is_asked_once_for_the_whole_catalogue` | Una llamada, no una por fila |
| `TestUsageIsADifferentFact::test_never_loaded_is_not_drawn_as_loaded_and_empty` | Una pregunta que nadie ha hecho y la respuesta «no la usa nadie» se parecerían — y la segunda es una llamada a la acción |
| `TestUsageIsADifferentFact::test_a_failed_fetch_does_not_retry_itself` | Se ejecuta desde el render y su fetch redibuja al llegar: reintentar sería petición → redibujo → petición contra un servidor que ya dice que no |
| `TestUsageIsADifferentFact::test_a_refresh_drops_the_cached_map` | Puede quedarse rancio por cosas que el catálogo no ve: un host o un check editados en otra sección |
| `TestUsageIsADifferentFact::test_the_orphan_count_is_catalogue_wide` | Contado sobre la página encogería al pasar de página, que es peor que no contar |
| `TestUsageIsADifferentFact::test_the_rows_keep_the_sort_the_user_chose` | Subir las no usadas arriba se lee bien y pisaría en silencio el orden que eligió el usuario; el badge dice lo mismo sin mover nada |
| `TestGroupingTellsTheTruth::test_the_empty_types_line_is_computed_over_the_catalogue` | «Ningún credencial de este tipo» es una afirmación sobre la instalación: sobre la página sería mentira |
| `TestGroupingTellsTheTruth::test_a_type_no_module_declares_any_more_is_still_shown` | Se quitó un módulo y sus credenciales le sobrevivieron — justo el caso que hay que ver |
| `TestTheLabelsExist::*` (×3) | Las cuatro vistas y el vocabulario de uso en los dos idiomas, y que el aviso de huérfanas lleve los **dos** números: 3 de 4 y 3 de 400 no son la misma noticia |
| `TestTheViewModeRestoreIsRegistryDriven::*` (×3) | El modo de vista lo restaura la propia tabla (`persistExtra`/`applyExtra`). Antes era una línea fija `tc.sessions.view` en la capa de persistencia, así que cada tabla con una preferencia nueva tenía que venir a editar esa función |

## 124. Audit — cuatro vistas, y dos de ellas no son listas

**Archivo:** `tests/test_wa_audit_views.py` — 29 tests

La tabla lee el registro línea a línea: es la forma correcta para «qué pasó a las 14:32» y la
equivocada para cualquier pregunta sobre el registro **entero**. Dos de ésas merecen vista
propia:

- **quién** ha estado activo. La tabla enseña todas las líneas de todos los actores y ningún
  total por actor, así que «una cuenta que no usa nadie hizo cuarenta cosas anoche» era
  invisible salvo que ya lo sospecharas y filtraras por ese usuario — hay que saber la
  respuesta para poder hacer la pregunta;
- **cuándo** pasó. Un inicio de sesión a las 03:00 y otro a las 11:00 se leen igual en una
  lista ordenada por tiempo; en una rejilla día × hora están en sitios distintos, y «¿pasa algo
  aquí fuera del horario?» pasa de ser una consulta que hay que idear a una forma que se ve.

Esas dos son **resúmenes**, y casi todos los guards van de lo que cuesta esa palabra: describen
un conjunto, así que se calculan sobre todo lo que dejaron los filtros y no sobre la página, no
se paginan (la página 2 de un mapa de calor no existe) y eligen su propio eje — por eso Orden y
Agrupar se ocultan mientras una está en pantalla, en vez de quedarse ahí sin hacer nada.

Lo que no puede diferir es qué es una **entrada**, y la parte no cosmética de eso es el botón
de borrar: `audit_delete` se convierte en control en un solo sitio.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Registro, ficheros y que el bundle los incluya **después** del registro |
| `TestOnePlaceDecidesWhoMayDelete::test_the_permission_becomes_a_button_once` | **La regla**: dos sitios preguntando «¿puede borrar?» es un sitio que puede contestar distinto |
| `TestOnePlaceDecidesWhoMayDelete::test_no_view_builds_its_own_delete_button` | Ni las vistas nuevas ni la tabla |
| `TestOnePlaceDecidesWhoMayDelete::test_no_view_reads_the_permission_set` | Se resuelve una vez por render en un `ctx` |
| `TestOnePlaceDecidesWhoMayDelete::test_a_summary_row_offers_no_delete` | No hay una entrada detrás de un recuento; borrar «42 entradas de este usuario» sería otra función |
| `TestASummaryIsNotAPage::test_summaries_are_handed_the_whole_filtered_set` | Sobre la página describirían «las 25 primeras entradas», que es una afirmación sobre la paginación |
| `TestASummaryIsNotAPage::test_only_the_list_views_are_paginated` | Ni bandas ni recorte para un resumen |
| `TestASummaryIsNotAPage::test_the_summary_header_states_the_whole_set` | Doce filas no pueden sugerir que el registro tiene doce entradas |
| `TestASummaryIsNotAPage::test_the_list_only_controls_are_hidden_for_a_summary` | Un control que no hace nada al usarlo es peor que uno que no está |
| `TestASummaryIsNotAPage::test_the_column_chooser_belongs_to_the_table` | Configura columnas que las otras tres no tienen |
| `TestSwitchingViewIsPresentationOnly::test_it_redraws_instead_of_refetching` | El fetch de esta sección devuelve el registro **entero**: volver a pedirlo para cambiar de layout sería la forma más cara posible |
| `TestSwitchingViewIsPresentationOnly::test_it_returns_to_the_first_page` | La página 3 de la tabla no es la página 3 de nada más |
| `TestSwitchingViewIsPresentationOnly::test_the_choice_is_remembered_with_the_rest_of_the_ui_state` | Orden, agrupación, filtros y vista en una sola clave |
| `TestTheTimelineIsTheSameRowsInTheSameOrder::test_it_does_not_re_sort` | Agrupar por día y ordenar los días pisaría en silencio la dirección elegida en el control de orden |
| `TestTheTimelineIsTheSameRowsInTheSameOrder::test_the_day_header_follows_the_entries` | |
| `TestTheTimelineIsTheSameRowsInTheSameOrder::test_a_day_is_the_readers_day` | Con `toISOString()` la clave sería el día **UTC**: una entrada al otro lado de la medianoche local caería bajo una cabecera con otra fecha que la suya, en la cronología y en la rejilla |
| `TestActorsCountsWhatMatters::test_failed_logins_are_counted_apart` | Cien entradas de un admin trabajando no es noticia; seis fallos de una cuenta que no hizo nada más sí, y promediados se parecen |
| `TestActorsCountsWhatMatters::test_the_failure_definition_is_narrow_and_shared` | «Todo lo que no es un éxito» haría que el número no significara nada |
| `TestActorsCountsWhatMatters::test_it_lists_the_addresses_rather_than_only_counting_them` | «3 IPs» es un número; **cuáles** es el hecho sobre el que se actúa |
| `TestActorsCountsWhatMatters::test_an_entry_with_no_user_is_not_called_unknown` | El demonio escribe entradas sin sesión detrás: llamarlo «desconocido» sugeriría que falta algo |
| `TestActivityIsACountNotAVerdict::test_the_ramp_is_one_hue` | El color lleva un recuento y nada más; una rampa rojo-verde inventaría una opinión |
| `TestActivityIsACountNotAVerdict::test_it_is_theme_aware` | Los dos extremos son variables del tema: una escala afinada contra un fondo está mal en el otro |
| `TestActivityIsACountNotAVerdict::test_every_cell_states_its_number` | Un tono es una comparación, no un valor |
| `TestActivityIsACountNotAVerdict::test_the_cap_is_never_silent` | Recortar los días viejos sin decirlo se lee como «esto es todo lo que hay», que es justo lo que una vista de auditoría no puede insinuar |
| `TestTheLabelsExist::*` (×3) | Las cuatro vistas y el vocabulario de resumen en los dos idiomas, y que el aviso de recorte lleve los **dos** números |

## 125. Events — dos cosas distintas, cuatro vistas cada una

**Archivo:** `tests/test_wa_events_views.py` — 30 tests

La sección guarda dos cosas y cada una tiene su registro:

**Las reglas son configuración** — «cuando pase esto, avisa a esta gente». La tabla contesta
«qué hay configurado» y deja dos preguntas fuera:

- **qué reglas llegan a un canal.** Si Telegram se rompe, ¿qué deja de llegar? La columna de
  canales son iconos por fila, así que la respuesta es un barrido; agrupadas por canal es un
  recuento. Y es donde aparece por fin la regla **sin ningún canal**: una que puede casar
  perfectamente y no avisar a nadie, cosa que ninguna otra parte de la página hace evidente.
- **si una regla llega a dispararse alguna vez.** `last_fired` es una columna que se puede
  ordenar; lo que hace falta es el triaje — fallando ahora, nunca ha disparado, entregando.
  «Nunca ha disparado» es el estado interesante y no es un error, así que una vista de dos
  estados tendría que llamarlo éxito.

**El log es historia** — una línea por notificación enviada. Además de leerlo como un log, las
preguntas son por regla («cuál es ruidosa, cuál está fallando») y por canal («¿el email lleva
fallando desde las 10:00?»). Las dos son hechos que la lista plana contiene y nunca dice.

Los resúmenes describen todo lo que dejan los filtros y no se paginan, igual que en Audit. Y lo
que no puede diferir es qué **es** una regla: el vocabulario de canales, el veredicto de
entrega y los botones — `events_*` se vuelve control en un solo sitio.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Los dos registros, los ficheros y el orden de inclusión |
| `TestOnePlaceDecidesWhatAUserMayDo::test_the_permissions_become_buttons_once` | **La regla**: cuatro vistas pintan los mismos botones |
| `TestOnePlaceDecidesWhatAUserMayDo::test_no_view_wires_a_rule_action_itself` | Incluida la tabla (sólo su cuerpo: el «Nueva regla» de la cabecera abre el modal sin regla detrás, que es otra cosa) |
| `TestOnePlaceDecidesWhatAUserMayDo::test_no_view_asks_the_permission_set` | Se resuelve una vez por render |
| `TestOnePlaceDecidesWhatAUserMayDo::test_the_log_views_offer_no_actions_at_all` | Una línea de log es historia: botones ahí invitarían a actuar sobre la regla desde el registro de lo que hizo |
| `TestASummaryIsNotAPage::*` (×4) | Conjunto filtrado entero, sin bandas de paginación, cabecera que dice el conjunto, y el selector de columnas es de la tabla |
| `TestSwitchingViewIsPresentationOnly::test_neither_switch_refetches` | Las dos sub-secciones se piden juntas: refrescar para cambiar de layout recargaría también la que no estás mirando |
| `TestSwitchingViewIsPresentationOnly::test_each_switch_returns_to_the_first_page` | |
| `TestSwitchingViewIsPresentationOnly::test_each_choice_is_remembered_apart` | Elegir tarjetas en reglas no decide cómo se pinta el log |
| `TestOneChannelVocabulary::test_the_icon_map_exists_once` | Eran dos literales —tabla y modal— y al de la tabla ya le faltaba `msteams`, así que una regla de Teams pintaba la campana genérica |
| `TestOneChannelVocabulary::test_every_declared_channel_has_an_icon` | |
| `TestOneChannelVocabulary::test_the_log_splits_the_channel_string_in_one_place` | El backend los guarda como una cadena; una vista que hace su propio split puede discrepar sobre qué cuenta como canal |
| `TestDeliveryHasThreeStates::test_never_fired_is_not_folded_into_ok` | Un booleano tendría que llamar «bien» a una regla que nunca disparó |
| `TestDeliveryHasThreeStates::test_the_buckets_are_ordered_worst_first` | Y «nunca» por encima de «entregando»: una pregunta sin responder enterrada bajo lo que funciona no la lee nadie |
| `TestDeliveryHasThreeStates::test_a_rule_with_no_channel_is_called_out` | Casa, dispara y no llega a nadie |
| `TestDeliveryHasThreeStates::test_the_channel_groups_are_not_claimed_to_partition` | Una regla con dos canales sale bajo los dos; la cabecera dice cuántas reglas hay para que la diferencia no se lea como un descuadre |
| `TestTheLogSummariesCountTheSameThing::test_both_share_the_cells` | «Fallos» significa lo mismo por regla y por canal |
| `TestTheLogSummariesCountTheSameThing::test_the_last_send_carries_its_own_outcome` | 12 fallos de 300 acabando en verde es un transporte que se recuperó; los mismos números acabando en rojo es uno caído ahora |
| `TestTheLogSummariesCountTheSameThing::test_the_shell_is_told_which_columns_to_draw` | Decidir una columna comparando texto traducido la perdería en el idioma que traduzca dos cabeceras igual |
| `TestTheLogSummariesCountTheSameThing::test_the_timeline_does_not_re_sort` | |
| `TestTheLogSummariesCountTheSameThing::test_the_timestamps_are_seconds_and_converted_in_one_place` | `ts` y `last_fired` son segundos unix: una vista que olvide multiplicar pinta enero de 1970 y parece un problema de datos |
| `TestTheSwitcherItselfIsShared::*` (×2) | **Seis secciones** pintaban el mismo grupo de botones con seis copias del marcado; ahora `_viewSwitcher(registro, actual, setter)` y cada una pasa lo que de verdad difiere |
| `TestTheLabelsExist::*` (×2) | Las ocho vistas y el vocabulario, en los dos idiomas |

## 126. Servers — cuatro vistas, y dos que hablan de la flota

**Archivo:** `tests/test_wa_servers_views.py` — 24 tests

Servers es la única lista donde las filas no son el asunto: lo que quieres de ella es un
estado de la flota, y una tabla te lo da de host en host. Tres cosas que deja fuera:

- **cómo está la flota AHORA.** Hay columna de estado y se puede ordenar, lo que contesta
  «cuál es el peor host» y nunca «cuántos están rotos».
- **qué hosts no se están vigilando.** La columna de módulos pinta «0/0» y «0/3» con la misma
  píldora gris: a uno no se le puso nunca una comprobación, al otro se las apagaron todas, y
  los dos significan que la flota es más pequeña de lo que aparenta la lista. Así es como un
  panel se queda verde mientras una máquina está caída.
- **qué es un host** como objeto y no como ocho columnas que enciendes y lees de izquierda a
  derecha.

Las dos vistas agrupadas son **resúmenes**: reciben todas las filas que dejaron los filtros,
no la página, y no pintan paginación. La fábrica aprendió ese modo para esta sección
(`bodyMode: 'summary'`), y Credentials se alineó con él.

Y la parte que no es cosmética: Servers es la sección con permisos **por host**
(`server.<uid>.edit` da exactamente una fila), así que una vista que se montara sus botones
sería una vista que olvidó que el caso granular existe.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Registro, ficheros y orden de inclusión |
| `TestPerHostPermissionsAreAskedOnce::*` (×3) | **La regla**: los botones se construyen en un sitio y siguen decidiéndose por el permiso **por host** |
| `TestASummaryIsNotAPage::test_the_factory_knows_what_a_summary_is` | `'cards'` es otro cuerpo sobre la misma página; `'summary'` describe el conjunto: recibe todas las filas y quita las bandas |
| `TestASummaryIsNotAPage::test_the_grouped_views_declare_it` | |
| `TestASummaryIsNotAPage::test_a_summary_is_handed_every_filtered_row` | |
| `TestASummaryIsNotAPage::test_both_summaries_state_the_whole_fleet` | Tres grupos no pueden sugerir que la flota son tres hosts |
| `TestASummaryIsNotAPage::test_the_column_chooser_belongs_to_the_table` | |
| `TestOneStatusVocabulary::test_no_view_paints_its_own_status` | Mantenimiento es naranja en todas partes: el mismo host no puede parecer dos estados en dos vistas de la misma página |
| `TestOneStatusVocabulary::test_no_checks_is_not_a_fifth_state` | «No sabemos cómo está» no es un matiz de «bien» |
| `TestOneStatusVocabulary::test_the_worst_group_leads` | |
| `TestOneStatusVocabulary::test_an_empty_error_group_is_not_drawn` | Y la cabecera sigue diciendo el total, que es lo que hace legible la ausencia |
| `TestCoverageHasThreeAnswers::test_never_checked_and_all_disabled_are_not_the_same` | 0/0 nunca tuvo comprobación; 0/3 se las apagaron, y eso es peor porque la fila parece configurada |
| `TestCoverageHasThreeAnswers::test_the_gaps_lead` | |
| `TestCoverageHasThreeAnswers::test_the_pill_always_shows_both_numbers` | «3» a secas no dice si las otras dos faltan o están apagadas |
| `TestCoverageHasThreeAnswers::test_the_ratio_names_both_numbers` | |
| `TestSwitchingViewIsPresentationOnly::*` (×3) | Redibuja sin pedir datos, no arrastra una selección a un resumen sin casillas, y recuerda la elección en las dos capas |
| `TestTheLabelsExist::*` (×2) | Las cuatro vistas y el vocabulario de cobertura, en los dos idiomas |

## 127. Syslog — tres vistas sobre la misma página del servidor

**Archivo:** `tests/test_wa_syslog_views.py` — 19 tests

Es la única sección cuyas filas llegan ya filtradas, ordenadas y paginadas **por el
servidor**: lo que hay en pantalla es una página de una consulta, no un trozo de algo que
tenga el navegador. Eso cambia dos cosas. El paginador se queda en todas las vistas —aquí es
el control que **carga** las filas siguientes, no un recorte de presentación— y un recuento
significa otra cosa, porque el almacén puede tener millones de filas y el navegador tiene unas
decenas.

Dos formas que la tabla no puede tener:

- **stream**: leer un log en una rejilla obliga a releer cinco cabeceras por línea para seguir
  la historia de una máquina, y gasta un tercio del ancho en adornos.
- **patrones**: quinientas líneas suelen ser una docena de mensajes distintos repetidos, y el
  que importa es muchas veces el que aparece dos veces.

Los guards van sobre todo del segundo: como cuenta, tiene que decir **sobre qué** contó, y la
agrupación que lo hace posible tiene que ser conservadora — que dos mensajes distintos se
fundan en uno es peor fallo que dos parecidos que no se junten.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Registro, ficheros y orden de inclusión |
| `TestEveryViewShowsTheSamePage::test_no_view_re_queries_the_store` | Estas consultas son las caras del panel, y además correrían contra el auto-refresco |
| `TestEveryViewShowsTheSamePage::test_every_view_is_handed_the_loaded_page` | |
| `TestEveryViewShowsTheSamePage::test_the_pager_survives_every_view` | Quitarlo dejaría al usuario encallado en la página uno |
| `TestEveryViewShowsTheSamePage::test_the_column_chooser_belongs_to_the_table` | Vive en la cabecera, fuera del cuerpo: lo refresca el despachador o seguiría ofreciendo columnas a una vista que no tiene |
| `TestOneSeverityVocabulary::test_no_view_picks_the_severity_colour_itself` | `err` es un color en todas partes |
| `TestOneSeverityVocabulary::test_the_stream_says_the_severity_as_well_as_colours_it` | Solo con color, el stream es ilegible para quien no separa rojos de grises — y es la vista con menos contexto de apoyo |
| `TestOneSeverityVocabulary::test_the_arrival_time_is_read_the_same_way_everywhere` | `received_at` es lo que registró el almacén; `ts` es lo que dijo el emisor, y un reloj mal puesto es lo bastante común como para preferir el primero |
| `TestPatternsCountHonestly::test_it_says_what_it_counted_over` | Un número a secas se leería como «el log» |
| `TestPatternsCountHonestly::test_the_loaded_message_names_the_number` | |
| `TestPatternsCountHonestly::test_the_grouping_never_touches_words` | Es una ayuda de lectura, no un identificador |
| `TestPatternsCountHonestly::test_addresses_are_replaced_before_bare_numbers` | Una IPv4 lleva dígitos: con la regla de números primero se la comería a trozos y el patrón dejaría de casar consigo mismo |
| `TestPatternsCountHonestly::test_severity_is_part_of_the_key` | El mismo texto en `err` y en `info` son dos sucesos; juntarlos dejaría que un aviso se escondiera dentro del ruido |
| `TestPatternsCountHonestly::test_the_hosts_are_listed_not_just_counted` | Un mensaje desde doce máquinas y doce desde una son incidentes distintos |
| `TestPatternsCountHonestly::test_the_rare_line_is_findable` | Colapsar sirve para que la línea que sale dos veces deje de estar enterrada |
| `TestTheLabelsExist::*` (×2) | Las tres vistas y el vocabulario, en los dos idiomas |

## 128. History — la gráfica, y el inventario de series del que nunca habla

**Archivo:** `tests/test_wa_history_views.py` — 21 tests

La sección es una gráfica con una lista de series al lado, y la gráfica es el asunto: una
serie cada vez, o varias superpuestas. La barra lateral es **navegación** —nombres y un punto
de color—, lo cual está bien para elegir y esconde dos hechos que el índice ya trae:

- **qué series han dejado de registrar.** Un check borrado, renombrado o que lleva tiempo sin
  producir muestra deja su historial detrás, y la barra lateral lo dibuja igual que a uno
  sano. Te enteras al pincharlo y ver el borde derecho vacío.
- **qué checks tienen peor disponibilidad.** Está en cada entrada; la barra lo convierte en un
  punto de tres colores, y los puntos no se pueden ordenar.

Así que el inventario es una fila por serie con los números, ordenable, y pinchar una fila
vuelve a la gráfica con esa serie seleccionada — que es lo que ibas a hacer después.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Registro, ficheros y orden de inclusión |
| `TestTheTwoViewsAreOneSection::test_one_filter_drives_both` | Escribir en una y cambiar de vista no puede cambiar en silencio qué series estás mirando |
| `TestTheTwoViewsAreOneSection::test_one_uptime_scale` | La tabla y el punto de la barra no pueden discrepar sobre qué es «sano» |
| `TestTheTwoViewsAreOneSection::test_the_chart_tools_are_hidden_in_the_inventory` | Comparar, rango y auto-refresco actúan sobre una gráfica |
| `TestTheTwoViewsAreOneSection::test_switching_stops_the_auto_refresh` | Existe para redibujar una gráfica que ya no está en pantalla |
| `TestTheTwoViewsAreOneSection::test_the_chart_comes_back_the_way_it_was` | Ir y volver redibuja la serie, no te deja en el placeholder |
| `TestTheTwoViewsAreOneSection::test_the_initial_render_does_not_chart_into_the_inventory` | |
| `TestTheInventoryAnswersWhatTheDotCannot::test_it_is_sortable` | |
| `TestTheInventoryAnswersWhatTheDotCannot::test_its_columns_behave_like_every_other_table` | **Reportado**: las columnas no se ajustaban al contenido ni se podían redimensionar. La tabla era marcado a mano en vez de la maquinaria de columnas del panel, así que no tenía nada de ella: el navegador repartía el ancho a partes iguales y las dos columnas de nombre acababan tan estrechas como el número de al lado |
| `TestTheInventoryAnswersWhatTheDotCannot::test_the_saved_order_cannot_hide_a_column` | Un orden guardado de un build anterior no puede esconder una columna nueva |
| `TestTheInventoryAnswersWhatTheDotCannot::test_the_cells_follow_the_column_order` | Una fila con celdas en orden fijo pondría los valores bajo el título equivocado en cuanto se mueve una columna |
| `TestTheInventoryAnswersWhatTheDotCannot::test_the_filter_sits_with_the_view_switcher` | Es el único control de esta vista, y su propia fila gastaba una banda entera en un input; la gráfica mantiene el suyo en la barra lateral, donde está la lista que filtra |
| `TestTheInventoryAnswersWhatTheDotCannot::test_it_opens_worst_first` | La razón de abrir esta vista es el final de la lista, así que empieza ahí |
| `TestTheInventoryAnswersWhatTheDotCannot::test_a_stopped_series_is_marked` | |
| `TestTheInventoryAnswersWhatTheDotCannot::test_the_staleness_rule_is_stated_on_screen` | Un umbral que nadie puede ver es una insignia en la que nadie puede confiar |
| `TestTheInventoryAnswersWhatTheDotCannot::test_never_recorded_is_not_drawn_as_very_old` | «—» y «412d» son afirmaciones distintas |
| `TestTheInventoryAnswersWhatTheDotCannot::test_a_row_opens_its_chart` | Y expande su grupo: si no, la gráfica se abre con su serie escondida en un grupo plegado |
| `TestTheLabelsExist::*` (×2) | Las dos vistas y las columnas, en los dos idiomas |

## 129. Access — cuatro tablas sobre un solo grafo

**Archivo:** `tests/test_wa_access_views.py` — 28 tests

Un usuario tiene un rol directo, pertenece a grupos, y un grupo concede roles. Cada tabla
enseña su fila y la arista que sale de ella, así que **la composición no estaba escrita en
ningún sitio**: una cuenta cuya columna de rol dice «viewer» y que está en un grupo mapeado a
admin **es** admin, y la tabla decía viewer. Enterarse pasaba por abrir Grupos, leer listas de
miembros y sostenerlo en la cabeza — que es justo el trabajo que se supone que es una revisión
de accesos.

Por eso cada sección mira el grafo desde su esquina —usuarios → acceso efectivo, roles → quién
lo tiene, grupos → qué concede— y las tres leen **los mismos helpers**: que dos vistas
discrepen sobre quién es admin es peor que no tener ninguna.

Hay una regla del backend reproducida en el cliente y estos guards la fijan: **un grupo
desactivado no concede nada** (`_is_admin_requester` comprueba `enabled`). Sobre-reportar
acceso es la única dirección en la que una revisión no se puede equivocar: te manda a perseguir
algo que no existe y entierra lo que sí.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×4) | Ficheros, registros con vista de resumen, y que el grafo cargue **antes** que las cuatro secciones |
| `TestOneGraphNotThree::test_membership_is_walked_in_one_place` | **La regla**: ninguna vista recorre la lista de miembros por su cuenta |
| `TestOneGraphNotThree::test_a_disabled_group_grants_nothing` | Igual que el servidor |
| `TestOneGraphNotThree::test_admin_is_recognised_by_its_key_not_its_label` | El rol se puede renombrar; la clave es lo que mira el backend |
| `TestOneGraphNotThree::test_the_three_access_views_read_the_shared_helpers` | |
| `TestUsersShowWhatTheRoleColumnCannot::test_it_separates_direct_from_inherited` | |
| `TestUsersShowWhatTheRoleColumnCannot::test_admin_through_a_group_is_called_out` | Es la única diferencia que cambia lo que alguien puede hacerle a todo |
| `TestUsersShowWhatTheRoleColumnCannot::test_the_warning_counts_only_the_hidden_ones` | Un admin cuya columna ya dice admin no es noticia |
| `TestUsersShowWhatTheRoleColumnCannot::test_a_disabled_group_is_shown_but_marked` | Es cómo está configurada la cuenta, pero hoy no concede nada |
| `TestRolesCountTheirReach::test_reach_is_a_union` | Quien lo tiene directo **y** por grupo no cuenta dos veces: un rol podría declarar más titulares que usuarios hay |
| `TestRolesCountTheirReach::test_a_disabled_group_adds_nobody` | |
| `TestRolesCountTheirReach::test_a_role_nobody_holds_is_marked_not_alarmed` | Configuración muerta: se ve antes de que la pregunte una auditoría, y no es un error |
| `TestGroupsSayWhatTheyDoToday::test_the_three_idle_states_are_distinguished` | Desactivado, sin roles y sin miembros son tres razones distintas de no hacer nada |
| `TestGroupsSayWhatTheyDoToday::test_admin_granting_groups_lead` | Meter a alguien ahí es más fuerte que editarle el rol, y se hace desde otra pantalla |
| `TestSessionsPerUser::test_it_counts_addresses_and_lists_them` | Varias sesiones desde una IP es alguien trabajando; la misma cuenta desde cuatro es una pregunta |
| `TestSessionsPerUser::test_the_busiest_account_leads` | |
| `TestTheSharedViewState::test_the_factory_exists_and_validates` | Cuatro secciones iban a copiar las mismas veinte líneas de «lee, valida, cae a la primera vista» |
| `TestTheSharedViewState::test_every_access_section_uses_it` | |
| `TestTheSharedViewState::test_each_list_is_wired_to_its_state` | `bodyMode`, cuerpo, conmutador y las dos direcciones de la persistencia |
| `TestTheSharedViewState::test_the_card_views_keep_the_id_the_toggle_used` | Renombrar el id resetearía en silencio a todo el mundo a la tabla |
| `TestTheSharedViewState::test_the_old_toggle_names_still_resolve` | |
| `TestTheSharedViewState::test_the_persistence_layer_has_no_view_variables_left` | Antes buscaba `_sessionsViewMode` por nombre; ahora cada tabla es dueña de su preferencia |
| `TestTheLabelsExist::*` (×3) | Las doce vistas, el vocabulario y los dos mensajes con número |

## 130. Clusters y fail2ban — las dos últimas superficies de tabla

**Archivo:** `tests/test_wa_clusters_ipban_views.py` — 29 tests

**Los clústeres existen por redundancia**: un check atado a varios hosts para que una máquina
caída no se lleve el check con ella. La tabla los lista y cuenta miembros, lo que se lee bien y
esconde las dos formas de que un clúster sea mentira:

- **un solo miembro**: una pareja de failover sin nada a lo que conmutar, y en la tabla es una
  fila con un «1» donde otra tiene un «3»;
- **varios clústeres clavados en el mismo host**: cada fila parece redundante por su cuenta y
  todos se caen juntos. Es un hecho sobre la **intersección** de las filas, así que ninguna
  vista por clúster puede enseñarlo — de ahí el pivote sobre el host.

**fail2ban** lista direcciones, y una IP es el tipo de fila cuyo dato interesante casi nunca
está en la fila. Cuarenta baneos suelen ser tres redes (quien llama rota el último octeto), y a
un historial se le pregunta por reincidencia: una dirección baneada seis veces son seis filas
desperdigadas por un log ordenado por tiempo.

Las tres vistas nuevas son resúmenes: todas las filas filtradas, sin paginación. Un «6 baneos»
que en silencio significara «6 en esta página» sería peor que no contar.

| Test | Qué comprueba |
|---|---|
| `TestTheScanItself::*` (×3) | Ficheros, los tres registros y el orden de inclusión |
| `TestClustersPivotOntoTheHost::test_a_single_member_cluster_is_named` | La columna Miembros lee «1» igual que lee «3» |
| `TestClustersPivotOntoTheHost::test_the_host_view_counts_the_shared_ones` | Varios clústeres en una máquina se caen juntos |
| `TestClustersPivotOntoTheHost::test_the_busiest_host_leads` | |
| `TestClustersPivotOntoTheHost::test_it_offers_no_per_cluster_actions` | Actúan sobre un CLÚSTER y esta vista enseña hosts |
| `TestClustersPivotOntoTheHost::test_the_per_cluster_permission_is_asked_in_one_place` | `cluster.<uid>.edit` concede exactamente una fila |
| `TestClustersPivotOntoTheHost::test_no_view_invents_the_status` | Un clúster no puede parecer sano en una vista y roto en la de al lado |
| `TestClustersPivotOntoTheHost::test_unknown_is_not_painted_as_a_state` | Un clúster del que el demonio no ha informado no tiene estado, y verde diría que sí |
| `TestClustersPivotOntoTheHost::test_the_summary_is_not_a_page` | |
| `TestFail2banGroupsAddresses::test_the_network_rule_is_stated_and_blunt` | /24 y /64: deducir el prefijo de las direcciones presentes cambiaría el agrupado cada vez que caduca un baneo |
| `TestFail2banGroupsAddresses::test_both_views_use_the_same_arithmetic` | |
| `TestFail2banGroupsAddresses::test_the_busiest_network_leads` | |
| `TestFail2banGroupsAddresses::test_the_addresses_are_listed_not_only_counted` | Cuáles es lo que copias a un baneo de rango |
| `TestFail2banGroupsAddresses::test_a_ban_and_its_unban_are_one_incident` | Contar los dos extremos convertiría seis baneos en doce filas |
| `TestFail2banGroupsAddresses::test_the_repeat_offender_leads` | |
| `TestFail2banGroupsAddresses::test_neither_summary_is_paginated` | |
| `TestFail2banGroupsAddresses::test_the_column_chooser_belongs_to_the_table` | |
| `TestFail2banGroupsAddresses::test_each_table_keeps_its_own_switcher` | Baneos e historial son dos listas de una misma sección |
| `TestTheWhitelistMeasuresItsHoles::test_the_reach_view_is_registered_and_wired` | La whitelist es la única lista del panel donde una entrada **es un agujero**, hecho a propósito |
| `TestTheWhitelistMeasuresItsHoles::test_the_address_maths_is_unsigned` | Los operadores de bits de JS trabajan con enteros **con signo**: sin `>>> 0`, toda dirección desde 128.0.0.0 sale negativa y la comparación de contención contesta lo contrario de la verdad |
| `TestTheWhitelistMeasuresItsHoles::test_ipv6_is_listed_but_not_compared` | Equivocarse en la aritmética de 128 bits sería llamar redundante a la única entrada que exime a un host |
| `TestTheWhitelistMeasuresItsHoles::test_an_unmeasured_entry_is_not_drawn_as_zero` | «0 direcciones» se lee como que no exime nada |
| `TestTheWhitelistMeasuresItsHoles::test_duplicates_do_not_cover_each_other` | Dos entradas con el mismo rango se marcarían redundantes la una por la otra, y borrar «la redundante» dos veces quita la regla entera |
| `TestTheWhitelistMeasuresItsHoles::test_the_widest_entry_leads` | Un 8 donde querías un 24 es un error de un carácter que ninguna columna enseña |
| `TestTheWhitelistMeasuresItsHoles::test_the_broad_threshold_is_stated_on_screen` | Una insignia cuya regla nadie ve es una insignia sobre la que nadie puede actuar |
| `TestTheLabelsExist::*` (×2) | Las siete vistas y el vocabulario, en los dos idiomas |
