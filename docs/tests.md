# Documentación de Tests — ServiceSentry

**Total: ~2931 tests** | Todos deben pasar con `pytest` para que el build sea válido. Los 6 tests de RAID local se saltan en Windows/macOS (`skipif sys.platform != 'linux'`).

> Los tests se ejecutan **en paralelo automáticamente** gracias a `-n auto` de `pytest-xdist` (configurado en `src/pytest.ini`). Tiempo típico ~2 min en una máquina con 8 cores. Para ejecutar en serie usa `-n 0`.

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

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| Conversión de bytes a unidades legibles | `bytes2human(1024)` → `"1.0 KiB"`, etc. | String con unidad correcta | Si la unidad o valor es incorrecto |

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

---

## 10. Integridad de módulos Watchful

**Archivo:** `tests/test_watchfuls_integrity.py`  
> Estos tests se ejecutan sobre los **9 módulos reales**: `filesystemusage`, `hddtemp`, `mysql`, `ping`, `raid`, `ram_swap`, `service_status`, `temperature`, `web`.

### `TestRealModuleDiscovery` — Descubrimiento en producción

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_discovers_all_expected_modules` | `_get_enabled_modules()` encuentra los 9 módulos reales | Los 9 módulos presentes | Si falta alguno |
| `test_no_extra_unexpected_entries` | No aparecen entradas `__pycache__` ni `.py` planos | Lista limpia | Si hay entradas no válidas |

### `TestRealModuleImport` — Importación (× 9 módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_module_imports[<mod>]` | El módulo importa sin errores | Import exitoso | Si lanza cualquier excepción |
| `test_watchful_has_item_schema[<mod>]` | `Watchful.ITEM_SCHEMA` existe y es dict no vacío | Dict con entradas | Si es `None`, no es dict, o está vacío |
| `test_item_schema_collections_are_dicts[<mod>]` | Cada colección en el schema es dict y cada campo tiene clave `type` | Todo correcto | Si algún campo no tiene `type` o no es dict |

### `TestRealModuleInfoJson` — Validez de `info.json` (× 9 módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_info_json_exists[<mod>]` | Existe `watchfuls/<mod>/info.json` | Archivo presente | Si no existe |
| `test_info_json_is_valid_json[<mod>]` | El archivo es JSON válido | Parseable sin errores | Si está malformado |
| `test_info_json_has_required_keys[<mod>]` | Tiene `name`, `version`, `description`, `icon`, `dependencies` | Todas las claves presentes | Si falta alguna |
| `test_info_json_name_is_nonempty_string[<mod>]` | `name` es string no vacío | String con contenido | Si es vacío o no es string |
| `test_info_json_icon_is_nonempty_string[<mod>]` | `icon` es string no vacío (emoji) | String con contenido | Si es vacío o no es string |

### `TestRealModuleLangFiles` — Validez de `lang/*.json` (× 9 módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_lang_dir_exists[<mod>]` | Existe `watchfuls/<mod>/lang/` | Directorio presente | Si no existe |
| `test_expected_locales_present[<mod>]` | Existen `en_EN.json` y `es_ES.json` | Ambos archivos presentes | Si falta alguno |
| `test_lang_files_are_valid_json[<mod>]` | Todos los `.json` de `lang/` son válidos | Sin errores de parseo | Si alguno está malformado |
| `test_lang_files_have_required_keys[<mod>]` | Tienen `pretty_name` y `labels` | Ambas claves presentes | Si falta alguna |
| `test_lang_pretty_name_is_nonempty_string[<mod>]` | `pretty_name` es string no vacío | Nombre legible | Si es vacío |
| `test_lang_labels_is_dict[<mod>]` | `labels` es un dict | Dict con etiquetas | Si es otro tipo |

### `TestDiscoverSchemasRealModules` — Integración completa del sistema i18n y schemas (× 9 módulos)

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_returns_non_empty` | `discover_schemas()` devuelve algo | Dict no vacío | Si está vacío |
| `test_module_has_at_least_one_schema_collection[<mod>]` | Módulo contribuye al menos una colección de schema | Al menos una clave `<mod>\|<col>` | Si no aparece ninguna |
| `test_module_has_i18n_entry[<mod>]` | Existe clave `<mod>\|__i18n__` | Presente | Si no existe |
| `test_i18n_entry_has_expected_locales[<mod>]` | `__i18n__` contiene `en_EN` y `es_ES` | Ambos locales presentes | Si falta alguno |
| `test_i18n_pretty_name_populated[<mod>]` | Cada locale tiene `pretty_name` no vacío | String con contenido | Si es vacío |
| `test_i18n_icon_populated[<mod>]` | Cada locale tiene `icon` no vacío | Emoji o string | Si es vacío |
| `test_schema_fields_have_label_i18n_when_lang_exists[<mod>]` | Todos los campos del schema tienen `label_i18n` mergeado de `lang/` | Clave `label_i18n` en cada campo | Si falta (indica que el merge de idiomas falló) |

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

Verifica el endpoint `GET|POST /api/v1/watchfuls/<module>/<action>` — autenticación, validación de entrada, despacho a classmethods y seguridad de importación.

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

### `TestFilesystemUsageInit`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación del Watchful | Sin excepción, monitor asignado | Si lanza |

### `TestFilesystemUsageCheck`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_check_no_partitions` | Lista vacía en config | `ReturnModuleCheck` vacío | Si lanza |
| `test_check_disabled_partition` | Partición con `enabled: false` | Entrada omitida del resultado | Si aparece |
| `test_check_partition_ok` | Uso por debajo del umbral | `status = True` | Si es `False` |
| `test_check_partition_alert` | Uso igual o superior al umbral | `status = False` | Si es `True` |
| `test_check_other_data` | `other_data` contiene información de uso | `used_percent`, `total`, `used` presentes | Si faltan |
| `test_check_invalid_config_uses_default` | Config malformada | Usa defaults, no lanza | Si lanza |

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

---

## 21. Watchful: raid

**Archivo:** `watchfuls/raid/tests/test_raid.py` y `test_raid_mdstat.py`

### `TestRaidInit`, `TestRaidCheckLocal`, `TestRaidCheckRemote`, etc.

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_check_local_no_raids` | Sin arrays RAID en el sistema | Resultado vacío | Si lanza |
| `test_check_local_raid_ok` | RAID en estado activo | `status = True` | Si es `False` |
| `test_check_local_raid_degraded` | RAID degradado | `status = False` | Si es `True` |
| `test_check_local_raid_recovery` | RAID en reconstrucción | `status = False` | Si es `True` |
| `test_check_local_disabled` | Entrada con `enabled: false` | Omitida | Si aparece |
| `test_check_remote_ok` | RAID remoto (SSH) OK | `status = True` | Si es `False` |
| `test_check_remote_disabled` | Entrada remota deshabilitada | Omitida | Si aparece |
| `test_label_local` | Etiqueta de array local | Nombre del dispositivo | Si devuelve otro |
| `test_label_remote_with_label` | Etiqueta personalizada en remoto | Etiqueta configurada | Si usa el host |
| `test_check_remote_with_key_file` | SSH con clave privada | No lanza, usa la clave | Si lanza |
| `test_md_analyze_unknown_status` | Estado RAID desconocido | Reportado como error | Si se ignora |
| `test_recovery_details` | Parseo de línea de recuperación de mdstat | Porcentaje y tiempo restante extraídos | Si el parseo falla |
| `test_recovery_malformed_falls_back_empty` | Línea de recuperación malformada | Dict vacío sin excepción | Si lanza |
| `test_read_ok` / `test_read_degraded` / `test_read_recovery` | Parseo de `/proc/mdstat` local | Estado correcto según el contenido | Si el parseo es incorrecto |
| `test_read_remote_stderr_raises` | Error SSH | `OSError` lanzada | Si no lanza |

---

## 22. Watchful: ram\_swap

**Archivo:** `watchfuls/ram_swap/tests/test_ram_swap.py`

### `TestRamSwapInit`, `TestRamSwapCheckConfig`, `TestRamSwapCheck`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_default_alert_values` | Thresholds por defecto (60% RAM, 60% swap) | Valores correctos | Si difieren |
| `test_check_normal_usage` | Uso por debajo de ambos thresholds | `ram: True`, `swap: True` | Si alguno es `False` |
| `test_check_high_ram_usage` | RAM por encima del threshold | `ram: False` | Si es `True` |
| `test_check_high_swap_usage` | Swap por encima del threshold | `swap: False` | Si es `True` |
| `test_check_exact_threshold` | Uso exactamente igual al threshold | `status = False` (umbral inclusivo) | Si es `True` |
| `test_check_other_data` | `other_data` contiene detalles de uso | `total`, `used`, `percent` presentes | Si faltan |
| `test_check_invalid_config_uses_default` | Config malformada | Usa defaults, no lanza | Si lanza |

---

## 23. Watchful: service\_status

**Archivo:** `watchfuls/service_status/tests/test_service_status.py`

### `TestServiceStatusInit`, `TestServiceStatusClearStr`, `TestServiceStatusReturn`, `TestServiceStatusCheck`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_clear_str_parentheses` | `clear_str()` elimina contenido entre paréntesis | Texto limpio | Si conserva paréntesis |
| `test_clear_str_empty` / `test_clear_str_none` | `clear_str("")` y `clear_str(None)` | Sin excepción, devuelve string | Si lanza |
| `test_service_running` | Servicio activo en systemd | `status = True` | Si es `False` |
| `test_service_inactive` | Servicio inactivo | `status = False` | Si es `True` |
| `test_service_failed` | Servicio en estado fallido | `status = False` | Si es `True` |
| `test_service_active_exited` | Servicio tipo `oneshot` completado | `status = True` | Si es `False` |
| `test_service_no_stdout` | Sin salida de systemctl | `status = False` | Si es `True` |
| `test_check_empty_list` | Lista vacía | Resultado vacío sin excepción | Si lanza |
| `test_check_disabled_service` | Servicio con `enabled: false` | Omitido del resultado | Si aparece |
| `test_check_service_running` | Servicio corriendo | `status = True` | Si es `False` |
| `test_check_service_stopped` | Servicio detenido | `status = False` | Si es `True` |
| `test_check_multiple_services` | Múltiples servicios | Cada uno con su estado correcto | Si se mezclan |

---

## 24. Watchful: temperature

**Archivo:** `watchfuls/temperature/tests/test_temperature.py`

### `TestTemperatureInit`, `TestTemperatureCheck`, `TestTemperatureGetConf`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_check_normal_temp` | Temperatura por debajo del threshold | `status = True` | Si es `False` |
| `test_check_high_temp` | Temperatura por encima del threshold | `status = False` | Si es `True` |
| `test_check_exact_threshold` | Temperatura exactamente en el threshold | `status = False` (inclusivo) | Si es `True` |
| `test_check_no_sensors` | Sin sensores detectados | Resultado vacío sin excepción | Si lanza |
| `test_check_multiple_sensors` | Varios sensores | Cada uno con su estado | Si se mezclan |
| `test_check_disabled_sensor` | Sensor con `enabled: false` | Omitido | Si aparece |
| `test_other_data_contains_temp_info` | `other_data` con temperatura actual y threshold | `temp`, `alert` presentes | Si faltan |
| `test_get_conf_custom_label` | Label personalizado recuperado de config | Label correcto | Si usa el default |
| `test_get_conf_none_raises` | `get_conf(None)` | `ValueError` | Si no lanza |
| `test_get_conf_invalid_option_raises` | Opción no válida | `TypeError` | Si no lanza |

---

## 25. Watchful: web

**Archivo:** `watchfuls/web/tests/test_web.py`

### `TestWebInit`, `TestWebCheck`, `TestWebReturn`, `TestWebUrl`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_init` | Instanciación | Sin excepción | Si lanza |
| `test_schema_has_url` | `ITEM_SCHEMA['list']` contiene campo `url` | Campo presente | Si no está |
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
| `test_key_used_in_message` | La clave (no la URL) aparece en el mensaje | Clave en el mensaje de estado | Si aparece la URL |

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

### `TestCpuInit`, `TestCpuCheck`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_init` | Instanciación del módulo | Sin excepción | Si lanza |
| `test_check_disabled_returns_empty` | Módulo deshabilitado | Resultado vacío | Si procesa |
| `test_check_ok_below_threshold` | Uso de CPU por debajo del umbral | `status = True` | Si es `False` |
| `test_check_alert_above_threshold` | Uso de CPU por encima del umbral | `status = False` | Si es `True` |
| `test_check_exact_threshold_is_not_ok` | Uso exactamente igual al umbral | `status = False` (no estrictamente menor) | Si es `True` |
| `test_check_other_data_populated` | `other_data` contiene `used` y `alert` | Ambos campos presentes | Si faltan |
| `test_check_uses_default_alert` | Sin config → usa `alert=85` por defecto | Umbral correcto | Si difiere |
| `test_check_custom_interval` | Config con `interval` personalizado | `psutil.cpu_percent` llamado con ese intervalo | Si ignora el config |
| `test_check_exception_handled` | Excepción en `psutil.cpu_percent` | Resultado con `status=False` sin lanzar | Si lanza al caller |

---

## 28. Watchful: ssl\_cert

**Archivo:** `watchfuls/ssl_cert/tests/test_ssl_cert.py`

### `TestSslCertInit`, `TestSslCertCheck`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_init` | Instanciación del módulo | Sin excepción | Si lanza |
| `test_check_disabled_returns_empty` | Módulo deshabilitado | Resultado vacío | Si procesa |
| `test_check_empty_list_returns_empty` | Lista vacía | Resultado vacío | Si lanza |
| `test_check_disabled_item_skipped` | Ítem con `enabled: false` | Omitido del resultado | Si aparece |
| `test_check_cert_valid_ok` | Certificado con días restantes > umbral | `status = True` | Si es `False` |
| `test_check_cert_within_warning_window` | Certificado dentro de la ventana de aviso | `status = False` | Si es `True` |
| `test_check_cert_expired` | Certificado expirado | `status = False`, mensaje "EXPIRED" | Si es `True` |
| `test_check_connection_error_handled` | Error de conexión SSL | `status = False` sin lanzar | Si lanza al caller |
| `test_check_other_data_populated` | `other_data` contiene `days_left`, `expires`, `host`, `port` | Todos los campos presentes | Si faltan |
| `test_check_per_item_warning_days_overrides_module` | `warning_days` por ítem anula el valor del módulo | Umbral correcto del ítem | Si usa el global |

---

## 29. Watchful: process

**Archivo:** `watchfuls/process/tests/test_process.py`

### `TestProcessInit`, `TestProcessCheck`, `TestProcessDiscover`

| Test | Qué comprueba | OK | Error |
| --- | --- | --- | --- |
| `test_init` | Instanciación del módulo | Sin excepción | Si lanza |
| `test_check_disabled_returns_empty` | Módulo deshabilitado | Resultado vacío | Si procesa |
| `test_check_empty_list_returns_empty` | Lista vacía | Resultado vacío | Si lanza |
| `test_check_disabled_item_skipped` | Ítem con `enabled: false` | Omitido del resultado | Si aparece |
| `test_check_process_running_ok` | Proceso encontrado con instancias suficientes | `status = True` | Si es `False` |
| `test_check_process_not_running` | Proceso no encontrado | `status = False` | Si es `True` |
| `test_check_min_count_not_met` | Instancias encontradas < `min_count` | `status = False` | Si es `True` |
| `test_check_min_count_exactly_met` | Instancias encontradas == `min_count` | `status = True` | Si es `False` |
| `test_check_case_insensitive` | Nombre del proceso insensible a mayúsculas | Coincidencia independientemente del case | Si no coincide |
| `test_check_empty_process_uses_key` | Campo `process` vacío → usa la clave del ítem | Búsqueda con la clave | Si usa string vacío |
| `test_check_other_data_populated` | `other_data` contiene `process`, `count`, `min_count` | Todos los campos presentes | Si faltan |
| `test_check_exception_handled` | Excepción en `psutil.process_iter` | `status = False` sin lanzar | Si lanza al caller |
| `test_discover_returns_list` | `discover()` devuelve lista de dicts con `name`, `display_name`, `status` | Lista con claves requeridas | Si falta alguna clave |
| `test_discover_counts_instances` | `discover()` cuenta múltiples instancias del mismo proceso | `status = '×2'` para 2 instancias | Si el conteo es incorrecto |
| `test_discover_sorted_by_name` | `discover()` devuelve procesos ordenados alfabéticamente | Lista ordenada (insensible a mayúsculas) | Si el orden es incorrecto |
| `test_discover_exception_returns_empty` | Excepción en `process_iter` durante discover | `[]` devuelto | Si lanza al caller |
| `test_discover_skips_empty_names` | Procesos con nombre vacío excluidos del resultado | Ningún ítem con `name == ''` | Si aparecen procesos sin nombre |

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

**Archivo:** `tests/test_config_spec.py` — 33 tests

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

**Archivo:** `tests/test_credentials.py` — 29 tests

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

**Archivo:** `tests/test_hosts_profiles.py` — 9 tests

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

**Archivo:** `tests/test_hosts_config_resolution.py` — 20 tests

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

**Archivo:** `tests/test_syslog_server.py` — 10 tests

| Test | Qué comprueba |
|---|---|
| `test_blank_defaults_to_all_ipv4_and_ipv6` | Blank defaults to all ipv4 and ipv6 |
| `test_detects_family_and_multiple` | Detects family and multiple |
| `test_dedup` | Dedup |
| `test_receive_udp` | Receive udp |
| `test_allowlist_blocks` | Allowlist blocks |
| `test_drop_logging_counts_and_rate_limits` | Drop logging counts and rate limits |
| `test_newline_framing` | Newline framing |
| `test_octet_counted_framing` | Octet counted framing |
| `test_bind_failure_reported` | Bind failure reported |
| `test_no_ports_no_threads` | No ports no threads |

## 50. Syslog — SyslogStore

**Archivo:** `tests/test_syslog_store.py` — 16 tests

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

**Archivo:** `tests/test_syslog_service.py` — 20 tests

| Test | Qué comprueba |
|---|---|
| `test_reads_shared_config` | Reads shared config |
| `test_load_webhooks_returns_list` | Load webhooks returns list |
| `test_read_config_file_is_effective` | Read config file is effective |
| `test_udp_message_is_stored` | Udp message is stored |
| `test_disabled_does_not_bind` | Disabled does not bind |
| `test_enable_only_still_has_default_ports` | Enable only still has default ports |
| `test_alert_dispatched` | Alert dispatched |
| `test_no_alert_below_threshold` | No alert below threshold |
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

**Archivo:** `tests/test_wa_admin_check.py` — 5 tests

| Test | Qué comprueba |
|---|---|
| `test_direct_admin` | Direct admin |
| `test_admin_via_enabled_group` | Admin via enabled group |
| `test_not_admin_via_disabled_group` | Not admin via disabled group |
| `test_plain_non_admin` | Plain non admin |
| `test_stamps_updated_fields` | Stamps updated fields |

## 53. Panel Web — LDAP

**Archivo:** `tests/test_wa_ldap.py` — 21 tests

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

**Archivo:** `tests/test_wa_oidc.py` — 20 tests

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

**Archivo:** `tests/test_wa_saml2.py` — 22 tests

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

## 56. Panel Web — Servidores (hosts)

**Archivo:** `tests/test_wa_hosts.py` — 38 tests

| Test | Qué comprueba |
|---|---|
| `test_requires_auth` | Requires auth |
| `test_create_list_and_mask` | Create list and mask |
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

**Archivo:** `tests/test_wa_webhook.py` — 32 tests

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

**Archivo:** `tests/test_wa_events.py` — 17 tests

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

**Archivo:** `tests/test_wa_services.py` — 10 tests

| Test | Qué comprueba |
|---|---|
| `test_requires_auth` | Requires auth |
| `test_status_lists_all_services` | Status lists all services |
| `test_database_reports_driver_and_connectivity` | Database reports driver and connectivity |
| `test_worker_reflects_history_activity` | Worker reflects history activity |
| `test_start_then_stop` | Start then stop |
| `test_unknown_service_404` | Unknown service 404 |
| `test_bad_action_400` | Bad action 400 |
| `test_start_disabled_is_409` | Start disabled is 409 |
| `test_start_stop_when_enabled` | Start stop when enabled |
| `test_control_requires_services_control` | Control requires services control |


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

**Archivo:** `watchfuls/m365/tests/test_m365.py` — 26 tests

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

**Archivo:** `watchfuls/proxmox/tests/test_proxmox.py` — 43 tests

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

**Archivo:** `watchfuls/snmp/tests/test_snmp.py` — 63 tests

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

**Archivo:** `tests/test_config_layout.py` — 8 tests

### `TestLayoutCoherence` — Coherencia layout ↔ registro

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_tabs_and_cards_present` | `config_layout()` devuelve tabs y cards, cada tab con `id`/`label_key`/`icon` | Ambas listas no vacías y tabs completos | Si falta alguna lista o clave |
| `test_every_card_targets_a_real_tab` | Cada card apunta a un `tab` existente en `TABS` | Todos los `card['tab']` están en los ids de tabs | Si una card referencia un tab desconocido |
| `test_card_is_generic_xor_bespoke` | Cada card tiene exactamente uno de `fields` (genérica) o `renderer` (a medida) | XOR se cumple en todas las cards | Si una card tiene ambos o ninguno |
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

**Archivo:** `tests/test_entraid_provision.py` — 9 tests

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

**Archivo:** `tests/test_wa_scim.py` — 13 tests

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

### `TestScimGroups`

| Test | Qué comprueba | OK | Error |
|---|---|---|---|
| `test_create_group_with_members` | POST /Groups con miembros | 201; grupo con `source='scim'` (persiste tras recarga) y uid en `user.groups`; miembros en el GET | No crea, no vincula o no marca `source` |
| `test_patch_remove_member` | PATCH `remove` de un miembro | 200; grupo fuera de `user.groups` | No lo quita |
| `test_delete_group_unlinks_members` | DELETE /Groups/{id} | 204; grupo borrado y desvinculado de los miembros | No desvincula |

## 80. Panel Web — Utilidades genéricas (`/api/v1/util/*`)

**Archivo:** `tests/test_wa_util.py` — 7 tests

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
