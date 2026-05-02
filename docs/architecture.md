# Arquitectura

Visión técnica del diseño interno de ServiceSentry: diagrama de componentes,
jerarquía de clases, estructura de directorios y flujo de ejecución.

---

## Diagrama de Componentes

```
┌─────────────────────────────────────────────────────┐
│                     main.py                         │
│  (CLI, argparse, daemon loop, config init)          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                  lib/monitor.py                     │
│  (Motor principal: carga módulos, ThreadPool,       │
│   gestión de estado, despacho de notificaciones)    │
└───────┬──────────┬──────────┬───────────────────────┘
        │          │          │
        ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Telegram │ │  Status  │ │  Watchfuls   │
│ (lib/)   │ │ (JSON)   │ │  (packages)  │
└──────────┘ └──────────┘ └──────┬───────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ModuleBase    lib/exe.py   lib/linux/
              (herencia)    (local/SSH)  (RAID, sensores térmicos)
```

---

## Jerarquía de Clases

```
ObjectBase (lib/object_base.py)
├── debug: Debug  ← instancia compartida por TODAS las clases
│
├── Main (main.py)
├── Monitor (lib/monitor.py)
├── Telegram (lib/telegram.py)
├── ConfigStore (lib/config/config_store.py)
│   └── ConfigControl (lib/config/config_control.py)
└── ModuleBase (lib/modules/module_base.py)
    ├── watchfuls.filesystemusage::Watchful  🌐 (multiplataforma)
    ├── watchfuls.hddtemp::Watchful
    ├── watchfuls.mysql::Watchful
    ├── watchfuls.ping::Watchful
    ├── watchfuls.raid::Watchful
    ├── watchfuls.ram_swap::Watchful          🌐 (multiplataforma)
    ├── watchfuls.service_status::Watchful
    ├── watchfuls.temperature::Watchful
    └── watchfuls.web::Watchful
```

---

## Estructura de Directorios

```
ServiceSentry/
├── README.md                            # Portada del repositorio
├── src/
│   ├── main.py                          # Punto de entrada
│   ├── requirements.txt                 # Dependencias de producción
│   ├── requirements-dev.txt             # Dependencias de desarrollo (pytest)
│   ├── conftest.py                      # Helper compartido para tests
│   ├── pytest.ini                       # Configuración pytest (testpaths = tests watchfuls)
│   ├── lib/
│   │   ├── __init__.py                  # Exports: ObjectBase, DictFilesPath, Monitor, Telegram, Exec, ExecResult, Mem, MemInfo
│   │   ├── object_base.py               # Clase base con Debug compartido
│   │   ├── monitor.py                   # Motor de monitorización
│   │   ├── telegram.py                  # Envío de mensajes Telegram
│   │   ├── exe.py                       # Ejecución de comandos local/remoto
│   │   ├── mem.py                       # Lectura de RAM/SWAP (multiplataforma vía psutil)
│   │   ├── mem_info.py                  # Dataclass MemInfo (total, free, used, percent)
│   │   ├── dict_files_path.py           # Diccionario de rutas de archivos
│   │   ├── tools.py                     # Utilidades (bytes2human)
│   │   ├── config/
│   │   │   ├── config_store.py          # I/O JSON (lectura/escritura)
│   │   │   ├── config_control.py        # Operaciones sobre config (get/set/exist)
│   │   │   └── config_type_return.py    # Enum tipos de retorno
│   │   ├── debug/
│   │   │   ├── debug.py                 # Sistema de debug con niveles
│   │   │   └── debug_level.py           # Enum: null, debug, info, warning, error, emergency
│   │   ├── linux/
│   │   │   ├── thermal_base.py          # Clase base para datos térmicos
│   │   │   ├── thermal_node.py          # Nodo individual de sensor térmico
│   │   │   ├── thermal_info_collection.py   # Sensores térmicos /sys/class/thermal
│   │   │   └── raid_mdstat.py           # Parser /proc/mdstat (RAID)
│   │   ├── modules/
│   │   │   ├── module_base.py           # Clase base para todos los watchfuls
│   │   │   ├── dict_return_check.py     # Estructura ReturnModuleCheck
│   │   │   └── enum_config_options.py   # Enum opciones de config comunes
│   │   └── web_admin/                   # Interfaz web de administración (Flask)
│   │       ├── app.py                   # Rutas y lógica principal
│   │       ├── i18n.py                  # Cargador de traducciones
│   │       ├── lang/                    # Ficheros de idioma globales (en_EN.py, es_ES.py)
│   │       └── templates/              # Plantillas Jinja2
│   ├── watchfuls/                       # Módulos de monitorización (packages)
│   │   ├── filesystemusage/             # 🌐 Multiplataforma (psutil)
│   │   │   ├── __init__.py              # Implementación del módulo
│   │   │   ├── watchful.py              # Alias: from . import Watchful
│   │   │   ├── schema.json              # Esquema de campos
│   │   │   ├── info.json                # Metadatos (icono, descripción)
│   │   │   ├── lang/en_EN.json          # Etiquetas en inglés
│   │   │   ├── lang/es_ES.json          # Etiquetas en español
│   │   │   └── tests/test_filesystemusage.py
│   │   ├── hddtemp/                     # (misma estructura)
│   │   ├── mysql/
│   │   ├── ping/
│   │   ├── raid/
│   │   ├── ram_swap/                    # 🌐 Multiplataforma (psutil)
│   │   ├── service_status/
│   │   ├── temperature/
│   │   └── web/
│   └── tests/                           # Tests de core y web admin
│       ├── test_config.py
│       ├── test_debug.py
│       ├── test_dict_files_path.py
│       ├── test_dict_return_check.py
│       ├── test_exe.py
│       ├── test_mem.py
│       ├── test_parse_helpers.py
│       ├── test_thermal.py
│       ├── test_tools.py
│       └── test_web_admin.py
├── data/                                # Config en modo desarrollo
│   ├── config.json
│   ├── monitor.json
│   └── modules.json
└── docs/
    ├── architecture.md                  # Este archivo
    ├── configuration.md
    ├── modules.md
    ├── web_admin.md
    ├── development.md
    └── watchful_guide.md
```

---

## Flujo de Ejecución

### Inicio

```
1. main.py: argparse procesa argumentos CLI
2. Main.__init__():
   ├── Inicializa atributos defensivamente
   ├── Añade watchfuls/ al sys.path
   ├── _args_set() → aplica argumentos (path, verbose, timer, daemon)
   ├── _init_config() → lee config.json, aplica defaults, lee valores
   ├── _init_monitor() → crea Monitor(dir_base, dir_config, dir_modules, dir_var)
   │   └── Monitor.__init__():
   │       ├── Lee config.json, monitor.json, modules.json
   │       ├── Lee/crea status.json en /var/lib/ServiSesentry/
   │       └── Inicializa Telegram (token + chat_id)
   └── _args_cmd() → ejecuta comandos (ej: clear_status)
3. Main.start():
   ├── Modo single: monitor.check() una vez
   └── Modo daemon: loop infinito con sleep(timer_check)
```

### Ciclo de Check

```
Monitor.check():
│
├── 1. Escanea watchfuls/ (packages con __init__.py y archivos *.py heredados)
├── 2. Filtra por módulos habilitados en modules.json
├── 3. Lee status.json (estado anterior)
├── 4. Crea ThreadPoolExecutor(max_workers=threads)
│
├── 5. Para CADA módulo (en paralelo):
│   └── check_module(nombre):
│       ├── importlib.import_module(nombre)
│       ├── Watchful(self) ← le pasa el Monitor
│       ├── module.check() → ReturnModuleCheck
│       │
│       └── Para CADA resultado en ReturnModuleCheck:
│           ├── Guarda other_data en status.json
│           ├── ¿Ha CAMBIADO el status? (check_status)
│           │   ├── SÍ → Actualiza status + envía Telegram (si send=True)
│           │   └── NO → No hace nada (evita spam)
│           └── return True (hubo cambios)
│
├── 6. Si hubo cambios → guarda status.json
├── 7. send_message_end() → resumen Telegram
└── 8. Fin del ciclo
```

### Detección de Cambio de Estado

El sistema solo notifica cuando el estado **cambia**. Lógica en `Monitor.check_status()`:

```python
# Busca en status.json: [modulo][sub_key][status]
# Si no existe, asume el opuesto (not status) → primer check siempre notifica
# Si el valor almacenado ≠ status actual → ha cambiado → return True
```

Esto evita enviar la misma alerta repetidamente en cada ciclo.

---

## Modelo de Concurrencia

| Capa | Mecanismo |
|------|-----------|
| Monitor → módulos | `ThreadPoolExecutor` (un hilo por módulo) |
| Dentro de cada módulo | `ThreadPoolExecutor` (un hilo por ítem: ping, mysql, hddtemp…) |
| Envío Telegram | Hilo daemon separado con cola de mensajes |

---

## Convenciones de Código

- **Prefijo `_`** (un solo guión bajo) para métodos y atributos privados (no `__`).
- **Type hints** en firmas de métodos y atributos de clase.
- **Docstrings** en todas las clases y métodos públicos.
- **`IntEnum` / `StrEnum`** para enumeraciones (no `Enum` base).
- **`match/case`** (Python 3.10+) para toda la lógica de despacho.
- **`encoding='utf-8'`** explícito en todas las operaciones de I/O.

---

## Notas Multiplataforma

| Módulo | Plataforma | Implementación |
|--------|-----------|---------------|
| `filesystemusage` | Linux / Windows / macOS | `psutil.disk_partitions()` + `psutil.disk_usage()` |
| `ram_swap` / `mem` | Linux / Windows / macOS | `psutil.virtual_memory()` + `psutil.swap_memory()` |
| `web` | Linux / Windows / macOS | `urllib.request` (stdlib) |
| `ping` | Linux / macOS / Windows\* | `pythonping` (principal, multiplataforma, sin root en Windows); fallback raw socket ICMP |
| `service_status` | Linux (systemd) | `systemctl` |

> \* **Windows (ping):** requiere `pythonping` (`pip install pythonping`). Sin él se usa el fallback raw socket ICMP, que requiere privilegios de Administrador en Windows.

| `temperature` | Linux | `/sys/class/thermal/` |
| `raid` | Linux | `/proc/mdstat` + SSH |
| `hddtemp` | Linux | Socket TCP al demonio hddtemp |
