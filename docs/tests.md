# Documentación de Tests — ServiceSentry

**Total: 1400 tests** | Todos deben pasar con `pytest` para que el build sea válido.

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
17. [Watchful: filesystemusage](#17-watchful-filesystemusage)
18. [Watchful: hddtemp](#18-watchful-hddtemp)
19. [Watchful: datastore](#19-watchful-datastore)
20. [Watchful: ping](#20-watchful-ping)
21. [Watchful: raid](#21-watchful-raid)
22. [Watchful: ram\_swap](#22-watchful-ram_swap)
23. [Watchful: service\_status](#23-watchful-service_status)
24. [Watchful: temperature](#24-watchful-temperature)
25. [Watchful: web](#25-watchful-web)

---

## 1. Core — Configuración

**Archivo:** `tests/test_config.py`

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
| `test_respects_enabled_false_in_config` | `modules.json` marca módulo como `enabled: false` | Módulo excluido | Si se incluye |
| `test_respects_enabled_true_in_config` | `modules.json` marca módulo como `enabled: true` | Módulo incluido | Si se excluye |
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

**Archivos:** `tests/test_wa_init.py` — `TestWebAdminInit` · `tests/test_wa_auth.py` — `TestAuthentication`, `TestRememberMe`

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
| `test_login_wrong_password` | Login con contraseña incorrecta | `401` o redirección a `/login` | Si entra al dashboard |
| `test_login_wrong_user` | Login con usuario inexistente | `401` o redirección a `/login` | Si entra |
| `test_logout` | `GET /logout` cierra la sesión | Redirección a `/login` | Si sigue logueado |
| `test_protected_redirect` | Acceder a `/` sin login | Redirección a `/login` | Si devuelve `200` |

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
| `test_modules_enabled_flag` | Flag `enabled` por módulo | Valor correcto según `modules.json` | Si difiere |
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
| `test_groups_default_administrators` | Sin `groups.json` → grupo `administrators` creado | `total=1`, `members=0` | Si difiere |
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
| `test_audit_persisted_to_file` | Entradas se guardan en disco | Archivo actualizado tras evento | Si solo en memoria |
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
| `test_clear_all_persisted_to_disk` | Vaciar audit persiste en disco | Archivo en disco vacío tras borrar | Si sólo en memoria |
| `test_delete_single_entry` | `DELETE /api/audit/<idx>` elimina entrada puntual | `200`, entrada ya no en lista | Si permanece |
| `test_delete_single_entry_oob` | Índice fuera de rango | `404` | Si borra o lanza |
| `test_delete_single_entry_negative` | Índice negativo | `404` | Si borra o lanza |
| `test_delete_single_entry_viewer_forbidden` | Viewer no puede borrar entradas | `403` | Si borra |
| `test_delete_single_entry_persisted` | Borrado puntual persiste en disco | Archivo actualizado sin la entrada | Si sólo en memoria |

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
| `test_unauthenticated_api_access` | Acceso sin autenticar a múltiples endpoints | `302` en todos | Si alguno devuelve `200` |
| `test_login_wrong_password` | Credenciales incorrectas | `401` o redirección al login | Si entra |
| `test_login_nonexistent_user` | Usuario inexistente | `401` o redirección al login | Si entra |
| `test_login_empty_credentials` | Credenciales vacías | `401` o redirección al login | Si entra |
| `test_forged_session_token_rejected` | Token de sesión falsificado | Redirección a login | Si acepta la sesión |
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
| `test_status_empty_when_no_status_file` | Sin archivo `status.json` | `200` sin tarjetas de módulo | Si falla o muestra módulos |
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
| `test_roles_persisted_to_file` | Rol creado se guarda en `roles.json` | Archivo contiene el nuevo rol | Si no persiste |
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

> **`conftest.py` (tests/):** El hash de la contraseña de admin se pre-computa una sola vez a nivel de módulo usando `pbkdf2:sha256` en lugar de scrypt. Esto evita recalcular el hash en cada fixture de test y reduce el tiempo de suite de ~4 min a ~2 min con xdist.

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
