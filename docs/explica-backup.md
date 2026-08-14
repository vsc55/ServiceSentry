# Copias de seguridad y restauración

> Qué es una copia en ServiceSentry, qué lleva dentro, cómo se hace, cómo se devuelve y qué
> decisiones de diseño hay detrás. Fuente única del tema: el resto de documentos enlazan aquí.
>
> Código: [`src/lib/core/backup/`](../src/lib/core/backup/), un fichero por concepto —
> `archive.py` (dónde vive una copia y cómo está dispuesta por dentro), `parts.py` (qué puede
> llevar), `create.py` / `restore.py` (las dos direcciones), `verify.py`, `locks.py`,
> `service.py` (el estante: qué copias hay y borrar una), `folders.py` (el explorador de
> carpetas del ajuste), `schedule.py` (funciones puras de *cuándo*), `runner.py` (el hilo, el
> tick y el lease) y `jobs.py` (lo que alguien está esperando delante de la pantalla),
> `routes.py` + `routes_schedule.py`, `tasks_store.py`, `profiles_store.py`, `manifest.py`.
> Todo menos las rutas es **sin Flask**. El mapa completo está en el docstring de
> [`__init__.py`](../src/lib/core/backup/__init__.py).
> Interfaz: [`templates/partials/backup/`](../src/lib/web_admin/templates/partials/backup/).

---

## Resumen en una tabla

| | |
|---|---|
| **Formato** | ZIP de ficheros JSON (uno por tabla) + ficheros sueltos + `manifest.json` |
| **Portabilidad** | Filas fuera y filas dentro **por el conector**: una copia de SQLite se restaura sobre MySQL |
| **Qué lleva** | Se elige por **partes** (`core`, `config_file`, `history`, `audit`, `syslog`, + las que aporten los módulos) |
| **Secretos** | Decisión **por copia**; el manifiesto registra cuál fue |
| **Integridad** | `sha256` por miembro dentro del manifiesto + `<copia>.zip.sha256` al lado |
| **Veredicto** | `ok` / `partial` / `error`, escrito **dentro** del archivo, con una entrada por parte |
| **Bloqueo** | `<copia>.zip.lock` al lado del archivo: ni la retención ni el botón de borrar la tocan |
| **Programación** | Lista de **tareas**, cada una con sus partes, su frecuencia y su retención por franjas (GFS) — propia o **de un perfil compartido** |
| **Quién la ejecuta** | El rol **web** (en microservicios, el contenedor `web`) |
| **Permisos** | 7 flags distintos — ver [§ Permisos](#permisos) |

---

## Por qué un ZIP de JSON y no un volcado de la base

El panel corre sobre **SQLite, MySQL, PostgreSQL o SQL Server**, y la copia tiene que
sobrevivir al salto: una instalación que creció en SQLite y se está levantando sobre MySQL es
*exactamente* cuándo se pide una copia, y un `.db` responde a eso con nada.

Así que no se copia el fichero de base de datos: se leen **filas por el conector** y se
escriben **filas por el conector**. El precio es que una copia es más lenta y más grande que un
`mysqldump`; lo que se compra es que sirva en el único momento en que hace falta.

---

## Las partes de una copia

Qué puede llevar una copia está declarado en `PARTS` ([`parts.py`](../src/lib/core/backup/parts.py)),
y ese catálogo lo leen **la API, el formulario y la restauración**. Una parte añadida ahí
aparece en los tres sin tocar nada más.

| Parte | Tipo | Base | Por defecto | Qué es |
|---|---|---|---|---|
| `core` | tablas | sistema | ✅ · **obligatoria** | **Toda tabla que ninguna otra parte reclamó** |
| `config_file` | fichero | — | ✅ | `config.json` (arranque, solo lectura) |
| `history` | tablas | sistema | ❌ | `history`, `check_state` |
| `audit` | tablas | sistema | ❌ | `audit` |
| `syslog` | tablas | **syslog** | ❌ | `syslog`, `syslog_drops` |
| *(las que declare un módulo)* | ficheros | — | según declare | p. ej. los MIB del módulo SNMP |

### La regla de `core` está invertida a propósito

`core` no es una lista de tablas: es **todo lo que nadie más reclamó**. Una tabla añadida
mañana —incluidas las que los módulos crean en ejecución vía
[`lib/db/module_tables.py`](../src/lib/db/module_tables.py)— entra en la copia **por defecto**
en vez de quedarse fuera en silencio.

> Una copia que se salta lo que no reconoció es de esos fallos que se descubren una sola vez.

### Un módulo aporta la suya

El núcleo **no lleva ninguna cadena que nombre un módulo**. Un módulo con ficheros propios lo
declara en su `schema.json`:

```json
"__backup_part__": {"id": "mibs", "dir": "snmp_mibs/raw",
                    "label_key": "backup_part_mibs", "default": false}
```

Detalle del descriptor y sus reglas (el `dir` no puede salirse de `var_dir`, no puede robar un
id del núcleo, la etiqueta sale del `lang/` del módulo) en
[explica-descubrimiento.md §6b](explica-descubrimiento.md#6b-partes-de-backup-aportadas-por-un-módulo-__backup_part__).

Las **tablas** de un módulo no se declaran: ya están en `core` por la regla invertida.

---

## Anatomía del archivo

```text
copia-20260811-210233.zip
├── db/
│   ├── hosts.json            {"columns": [...], "rows": [[...], ...]}
│   ├── users.json
│   ├── config.json           ← la tabla `config`, no el fichero
│   └── …                     una por tabla
├── files/
│   ├── config.json           ← el FICHERO de arranque (parte `config_file`)
│   └── parts/
│       └── mibs/…            ← los ficheros de un módulo (parte `mibs`)
└── manifest.json             ← escrito el ÚLTIMO, a propósito

copia-20260811-210233.zip.sha256    ← al lado, formato `sha256sum -c`
```

**El manifiesto se escribe el último** para que *un manifiesto presente sea un manifiesto
cierto*: un archivo interrumpido a medias no lo tiene, y `read_manifest` lo rechaza en vez de
anunciar una copia que lleva menos de lo que dice.

### Qué guarda el manifiesto

| Campo | Para qué |
|---|---|
| `format` | Versión del **formato del archivo** (hoy `1`). Uno mayor que el que conoce esta instalación se rechaza |
| `name`, `created_by` | Quién la hizo. En una automática, `(schedule: <tarea>)` |
| `app_version`, `engine` | Build y motor de BD que la escribieron |
| `parts`, `secrets` | Qué se pidió y si lleva credenciales |
| `tables` | `{tabla: nº de filas}` |
| `files` | `{parte: nº de ficheros}` |
| `steps` | **Una entrada por parte**: `ok`, filas, tablas y el primer motivo del fallo |
| `status` | El veredicto: `ok` / `partial` / `error` |
| `sha256` | Digest **por miembro** del ZIP |

Todo lo que enseña la ficha **Detalles** sale de aquí. Nada lo calcula la pantalla: la copia es
lo que alguien restaura meses después, y un veredicto deducido al pintar es un veredicto que no
viajó con el fichero.

---

## Flujo de una copia

```mermaid
flowchart TB
    start["POST /api/v1/backups<br/>(o el tick de una tarea)"]
    start --> valid{"¿nombre válido?<br/>¿libre?"}
    valid -- no --> ko["error, y una línea en el log"]
    valid -- sí --> job["BackupRunner._start_job()<br/>hilo + job_id"]
    job --> parts["partes pedidas + las obligatorias"]
    parts --> map["_tables_by_part()<br/>cada parte pregunta a SU base"]
    map --> loop["por cada tabla:<br/>_dump_table() → db/&lt;tabla&gt;.json<br/>sha256 del miembro<br/>progress_cb: paso/total/tabla/checklist"]
    loop --> files["config.json → files/<br/>partes de módulo → files/parts/&lt;id&gt;/"]
    files --> verdict["steps → status<br/>ok · partial · error"]
    verdict --> man["manifest.json (el ÚLTIMO)"]
    man --> rename["copia.zip.part → copia.zip<br/>+ sidecar .sha256"]
    rename --> audit["auditoría + log + toast"]
```

Puntos que no se ven en el diagrama y explican por qué está así:

- **Una tabla ilegible marca su parte y deja seguir al resto.** Una copia con nueve de diez
  tablas vale algo; una que abortó en la décima no vale nada. El manifiesto dice cuál.
- **El progreso es por tabla**, no por bytes: las filas no tienen tope (una tabla de syslog son
  seis cifras) y el tamaño del ZIP no se sabe hasta cerrarlo. *«syslog 4/11»* es una frase.
- **El resultado es por parte**, que es la unidad que alguien marcó en el formulario.
- Se escribe a `.part` y se renombra al final: un fichero a medias nunca aparece en la lista.

### La segunda base de datos

Con `syslog_db|enabled`, las tablas de syslog **no están en la base del sistema**. Cada parte
declara en qué base vive y el llamador pasa un mapa de conectores:

```mermaid
flowchart LR
    subgraph web["contenedor web"]
      runner["BackupRunner<br/>_connectors(wa)"]
    end
    runner -->|"'main'"| maindb[("BD sistema<br/>hosts · users · config · …")]
    runner -->|"'syslog'"| sysdb[("BD syslog<br/>syslog · syslog_drops")]
    maindb --> zip["copia.zip"]
    sysdb --> zip
```

`core` sigue siendo *toda tabla que nadie reclamó* **en la base del sistema**, así que nada de
la segunda base se cuela ahí por accidente. Una segunda base inalcanzable cuesta su parte y
nada más.

> Esto fue un bug real: leer las tablas de syslog del conector principal daba una copia vacía
> **en verde**. Ficha completa en [caso-diagnostico.md](caso-diagnostico.md).

---

## Secretos

Es una decisión **por copia**, y el manifiesto registra cuál fue — una copia sin credenciales
que parece completa se descubre al restaurar.

Al excluirlos se **vacía todo valor cifrado a cualquier profundidad**. El marcador es el
prefijo `enc:` con que el panel escribe lo que cifra, y no una lista de nombres de campo: los
módulos declaran sus propios campos secretos en sus esquemas, así que una pasada por nombres
conocidos enviaría el token de un módulo diciendo que no lleva ninguno. Además el secreto suele
vivir **dentro** de una columna JSON, no ser la columna.

> Los valores incluidos siguen siendo **cifrado**: solo la misma `SS_SECRET_KEY` los lee. Una
> copia restaurada en otra instalación sin esa clave deja las credenciales ilegibles aunque
> todo lo demás cuadre.

---

## Integridad: sha256

Dos niveles, porque responden preguntas distintas:

| Dónde | Qué cubre | Para qué |
|---|---|---|
| `manifest.sha256` | cada **miembro** del ZIP | *Verificar* dice **qué** miembro cambió, no solo que algo cambió |
| `<copia>.zip.sha256` | el **archivo entero** | El digest de un fichero no puede vivir dentro de él. Formato `sha256sum -c`: se valida en otra máquina sin este panel |

**Verificar** compara el fichero contra su propio manifiesto y distingue los dos fallos: *«el
fichero no coincide con su sha256»* (llegó dañado o incompleto) y *«N miembros no coinciden»*
(el contenido se alteró). Son causas distintas.

---

## Flujo de una restauración

```mermaid
flowchart TB
    ask["POST /api/v1/backups/&lt;copia&gt;/restore"]
    ask --> exists{"¿existe la copia?"}
    exists -- no --> ko404["400 + línea de auditoría<br/>(sin barra de progreso para algo que no iba a pasar)"]
    exists -- sí --> job["start_restore() → job_id"]
    job --> fmt{"¿format &gt; el de esta instalación?"}
    fmt -- sí --> ko["se rechaza"]
    fmt -- no --> want["partes: las del archivo ∩ las marcadas"]
    want --> only["tablas: las de esas partes ∩ las elegidas<br/>(sin lista = todas)"]
    only --> group["_by_database(): agrupar por base"]
    group --> tx["por cada base: UNA transacción<br/>DELETE + INSERT por tabla"]
    tx --> drop["columnas que el esquema vivo no tiene → se descartan y se REPORTAN"]
    drop --> filesr["config.json y ficheros de módulo<br/>a donde el módulo dice que viven HOY"]
    filesr --> done["steps + skipped + status"]
    done --> caches["cachés del proceso + poke a los demás contenedores"]
    caches --> ui["diálogo con el resultado → recarga al cerrarlo"]
```

### Reemplaza, no fusiona

Una tabla se **vacía y se rellena**. Fusionar daría un tercer estado que no existió nunca en
ningún sitio, y una copia es una afirmación sobre cómo era la instalación.

### Una transacción por base

Las tablas del sistema **entran juntas o no entra ninguna**: usuarios restaurados con roles sin
restaurar es una instalación en la que nadie puede entrar. Dos bases no pueden compartir una
transacción, así que cada una lleva la suya — datos masivos de log entrando en su propio paso
no dejan a nadie fuera.

### Restaurar solo una parte

`parts` acota lo que se aplica. `required` dice qué debe **contener** una copia, no qué debe
aplicarse: leerlo como lo segundo convertiría toda restauración parcial en total, que es lo
contrario de lo que se pide al restaurar solo los hosts tras una importación mala.

### Restaurar solo unas tablas

`tables` acota **dentro** de esas partes, tabla a tabla. Es la mitad «avanzada» del formulario, y
las partes siguen mandando: nombrar una tabla de una parte que no está marcada no la cuela: las
dos estrechan la misma selección, no compiten por ella.

| Qué se manda | Qué significa |
|---|---|
| `tables` ausente | Todas las tablas de las partes elegidas — la petición de siempre |
| `tables: ['hosts']` | Solo esa; las demás **ni se vacían ni se tocan** |
| `tables: []` | **Ninguna.** No es «todas»: leerlo así reescribiría la instalación entera de quien no pidió nada |

**Más fino no es más seguro, y esa es la advertencia que sale en pantalla.** Las partes son una
agrupación curada; una lista de tablas a mano no lo es. Restaurar `hosts` sin `credentials` deja
filas apuntando a una credencial que ya no existe, y nada aquí lo impedirá. Para lo que sirve es
para el caso contrario, el que la granularidad por partes no sabe decir: *una* tabla es el
problema y el resto de la instalación ha avanzado desde que se hizo la copia.

Lo que se elige a mano se registra como tal: la línea del log sube a **warning** y nombra las
tablas, la auditoría lleva `only_tables` (`all` cuando no se acotó), y el diálogo del final dice
que el resto se quedó como estaba — «148 filas en 9 tablas» se lee como una restauración completa
si nadie dice lo contrario.

El formulario pregunta qué lleva el archivo a `GET /api/v1/backups/<copia>/tables`, que agrupa
por parte con **la misma** regla que aplica la restauración. La alternativa —agrupar en el
navegador desde el manifiesto— sería una tercera implementación de «`core` es toda tabla que
nadie reclamó», correcta hasta el día que se añada una parte.

---

## Restaurar entre versiones

Lo **único** que se rechaza es un `format` de archivo más nuevo que el que esta instalación
conoce. La versión de la aplicación **no bloquea nada**: el esquema avanza en casi cada build, y
un panel que rechazara copias «viejas» sería inútil justo el día que hace falta.

Lo que hace en cambio es **no callarse**:

| Situación | Qué pasa | Qué se dice |
|---|---|---|
| Columna **añadida** desde la copia | Las filas entran sin ella (NULL/default) | nada: no se perdió nada |
| Columna **eliminada** desde la copia | Su valor se descarta | «campos descartados: X» + warning en el log + auditoría |
| **Tabla** que ya no existe | Se salta entera | «la tabla ya no existe: N filas no entraron» |
| Copia de un build **posterior** | Se descartan los campos que este esquema aún no tiene | Aviso ámbar **antes** de pulsar |
| Copia de un build **anterior** | Normal | Línea informativa con los dos builds |

```mermaid
flowchart LR
    copy["copia<br/>build.80"] -->|"restaurar en"| inst["instalación<br/>build.58"]
    inst --> warn["⚠ los campos que este panel<br/>aún no tiene se descartarán"]
    warn --> after["después: qué tabla y qué campos<br/>en el diálogo, en el log y en la auditoría"]
```

**No hay migraciones al restaurar.** Reescribir filas según lo que un build supone del anterior
es la clase de código que rompe la copia mientras la aplica; la garantía que se ofrece es la
transacción única, no una traducción.

> Riesgo que ningún chequeo detecta: si un build cambió el **significado** de un valor (la forma
> de un JSON dentro de una columna), la copia vieja entra con la forma vieja.

---

## Programación

Una **lista de tareas**, no un intervalo global. El caso que lo motivó: la configuración y el
inventario merecen copia diaria; el syslog y los MIB quizá semanal — y con una sola
programación eso no se puede decir sin copiarlo todo al ritmo de la parte más exigente, que es
como se llena un disco.

Cada tarea (tabla `backup_tasks`) lleva: **nombre**, sus **partes**, si incluye **secretos**,
**cuándo** y **cuántas conservar**.

### Cuándo: intervalo o calendario

```mermaid
flowchart TB
    tick["tick cada 10 min"] --> each["por cada tarea activa"]
    each --> mode{"modo"}
    mode -- "cada N horas" --> iv["¿han pasado N horas<br/>desde la última copia suya?"]
    mode -- "días + hora" --> cal["¿pasó la última ventana<br/>y no hay copia desde entonces?"]
    iv --> due{"¿vencida?"}
    cal --> due
    due -- no --> nothing["nada"]
    due -- sí --> lease{"¿tomo el lease?"}
    lease -- no --> other["otra réplica la hace"]
    lease -- sí --> run["copia → poda de retención"]
```

La pregunta del modo calendario es **«¿pasó la ventana sin copia desde entonces?»**, no «¿son
las 03:00 ahora?». Preguntado de la forma ingenua sería falso 1439 minutos de cada 1440 y se
perdería la ventana siempre que el proceso no estuviera arriba justo en ella. Así, un panel que
vuelve a las 09:00 **toma igualmente la copia de las 03:00**, y un tick cada diez minutos la
caza igual de bien que uno cada minuto.

- **Ningún día marcado significa TODOS los días**, nunca «ningún día»: una tarea creada que no
  se ejecuta jamás es el fallo contra el que existe toda esta función.
- Una tarea **sin modo** es de intervalo — es lo que era toda tarea antes de que existiera el
  calendario.

### Retención

Es **por tarea**, y la pregunta que responde no es *«¿cuántas guardo?»* sino *«¿cuánto hacia
atrás puedo volver, y con qué resolución?»* — siete copias pueden ser una semana a resolución
diaria o dos años a resolución mensual, y solo lo segundo sobrevive a descubrir en marzo que
algo se rompió en enero.

Por eso son **franjas**, la forma en que lo resolvieron borg y restic:

| Campo | Qué conserva |
|---|---|
| `keep_last` | Las N más recientes, diga lo que diga el calendario |
| `keep_daily` | La más reciente de cada uno de los últimos N días |
| `keep_weekly` | La más reciente de cada una de las últimas N semanas (semana ISO) |
| `keep_monthly` | La más reciente de cada uno de los últimos N meses |
| `keep_yearly` | La más reciente de cada uno de los últimos N años |
| `max_size` | Techo en bytes. 0 = sin límite |

**Una copia sobrevive si la reclama CUALQUIERA de las reglas** — la unión, no la intersección.
Eso es lo que hace que «3 últimas + 7 diarias + 4 semanales + 6 mensuales» cueste 17 copias en
vez de 180. Con 400 copias diarias, esa política deja **15** y llega **siete meses atrás**; un
`keep_last: 15` deja las mismas 15 y llega quince días.

```mermaid
flowchart LR
    all["400 copias diarias"] --> last["keep_last 3<br/>las 3 últimas"]
    all --> d["keep_daily 7<br/>1 por día × 7"]
    all --> w["keep_weekly 4<br/>1 por semana × 4"]
    all --> m["keep_monthly 6<br/>1 por mes × 6"]
    all --> y["keep_yearly 2<br/>1 por año × 2"]
    last --> u["unión = 15 copias<br/>~7 meses de historia"]
    d --> u
    w --> u
    m --> u
    y --> u
    u --> floors["suelos"]
    floors --> budget["presupuesto (si lo hay)"]
    budget --> floors2["suelos otra vez"]
    floors2 --> keep["lo que se conserva"]
```

**Todo a 0 conserva todas.** Quien poda por otro lado tiene que poder decirlo, y leer «sin
reglas» como «bórralas todas» es la lectura que pierde datos.

#### Dos suelos que ninguna franja puede expresar

- **Nunca se borra la copia más reciente.** Una política que deja una tarea sin nada ha
  configurado mal lo único que esa tarea existe para dar, y eso se descubre al restaurar.
- **Nunca se borra la más reciente CORRECTA.** Una racha de copias `partial` empujaría fuera la
  última `ok` y quedarían siete copias de las que ninguna sirve. El veredicto ya viaja dentro
  del archivo, así que esto cuesta una consulta y ninguna adivinación.

#### El presupuesto de tamaño

Las franjas dicen qué merece la pena conservar; `max_size` dice para cuánto hay sitio. Se aplica
**el último**, así que solo puede quitar de lo que las reglas ya habían elegido — nunca añadir —
y los suelos se vuelven a aplicar después: quedarse sin sitio no es motivo para quedarse sin
nada.

Cuando es el techo y no el calendario el que decide qué sobrevive, queda **auditado**
(`backup_budget_exceeded`) y es **notificable**: significa que la política pide más historia de
la que cabe, y eso es una decisión que alguien debería poder revisar en vez de descubrirla más
tarde como un hueco.

#### Cuándo se aplica

**En cada tick**, no solo después de copiar. Antes, una tarea mensual pasaba un mes sin que sus
reglas se aplicaran y una **deshabilitada** no las aplicaba nunca: apagar una tarea dice «deja
de hacer copias nuevas», no «congela las viejas fuera de todo contador».

#### Lo que la retención nunca toca

- Una copia **bloqueada** (ver abajo).
- Una copia hecha **a mano**: un contador no decide sobre algo que alguien hizo a propósito.
- Las copias de una **tarea borrada**. Siguen siendo backups; la tarea solo era la razón de que
  existieran. No se podan — pero desde esta versión tienen su propia entrada en el rail
  (*Sin tarea*), porque crecer sin que nadie las cuente y sin que nadie las vea son dos cosas
  distintas.

#### La previsualización

Nadie evalúa «7 diarias + 4 semanales + 6 mensuales» contra 200 ficheros de cabeza, y una
política que no se puede predecir es una que nadie se atreve a tocar. El formulario de la tarea
enseña, contra las copias que existen **ahora**, cuántas sobrevivirían, cuánto ocupan y cuáles
se borrarían hoy.

Lo calcula el **servidor**, con la misma función pura que usa el planificador
(`POST /api/v1/backups/tasks/preview`, permiso `backup_view`, no cambia nada). Calcularlo en el
navegador sería una segunda implementación de la regla — y una previsualización que discrepa del
planificador es peor que ninguna, porque se cree.

#### Perfiles: una política con nombre

Cinco números y un techo, reescritos de memoria en cada tarea, eran tres oportunidades de teclear
6 donde las otras dicen 4 — y nada en pantalla decía nunca que no coincidían. Un **perfil de
retención** es esa política con un nombre y un solo sitio.

Una tarea **sigue** un perfil (guarda su uid en `profile`), no lo copia: editar «GFS estándar»
cambia de una vez la retención de todas las tareas que apuntan a él. Esa es la razón entera de
que exista, en lugar de un botón que rellene las casillas.

```mermaid
flowchart LR
    subgraph tareas["Tareas"]
        t1["Diaria<br/>profile: gfs"]
        t2["Syslog<br/>profile: gfs"]
        t3["Mensual<br/>profile: ''"]
    end
    gfs["Perfil «GFS estándar»<br/>3 + 7d + 4w + 6m"]
    own["sus propios keep_*"]
    t1 --> gfs
    t2 --> gfs
    t3 --> own
    gfs --> resolve["with_profile()"]
    own --> resolve
    resolve --> prune["prune() — la misma función de siempre"]
```

Detalles que no son evidentes:

- **La resolución ocurre en un único sitio** (`schedule.with_profile`). Todo lo que hay por
  debajo —`survivors`, `prune`, la previsualización— recibe una tarea que ya sabe cuáles son sus
  números. Un segundo sitio que decidiera eso sería un segundo sitio donde el planificador y la
  pantalla pueden discrepar sobre qué está a punto de borrarse.
- **El perfil sustituye la política, no se fusiona con ella.** Un perfil que no dice nada de
  mensuales significa *ninguna mensual*. Fusionar dejaría a una tarea conservando historia que la
  política que sigue nunca menciona, y nada en pantalla diría por qué.
- **Los `keep_*` propios de la tarea se conservan debajo**, ocultos y no borrados: son a lo que
  vuelve al desvincularla, y lo que queda en pie si el perfil desaparece por otra vía. Leer «sin
  reglas» ahí significaría *conservarlo todo* y llenar el disco.
- **La lista de tareas viaja con las reglas ya resueltas** (`policies` en
  `GET /api/v1/backups/tasks`). Una tarea vinculada lleva dos juegos de números encima; una
  pantalla que eligiera por su cuenta sería una pantalla de retención adivinando.
- **Borrar un perfil en uso se rechaza (409)** nombrando las tareas. Dejarlo ir movería esas
  tareas a los números que tuvieran guardados: un cambio de política que nadie pidió y que nada
  anuncia.
- Los **puntos de partida** que ofrece el editor (`suggested`) vienen del servidor
  (`profiles_store.SUGGESTED`): son la opinión del panel sobre cuánta historia merece la pena
  guardar, y una opinión escrita en una plantilla es una que la API no puede enunciar.

Todo ello va con `backup_schedule`: editar un perfil **es** editar la retención de varias tareas,
que es exactamente la decisión que ese permiso ya cubría.

#### Bloquear una copia

Las franjas contestan *cuánta historia*; los dos suelos contestan *nunca dejes la tarea sin
nada*. Ninguno de los dos sabe decir **esta copia en concreto** — que es justo lo que se quiere
decir de la copia tomada antes de una migración, o de la última que se sabe buena.

El **bloqueo** lo dice. Una copia bloqueada no la borra la retención ni el botón de borrar:

```mermaid
flowchart TD
    p["prune(): la política elige"] --> f{"¿bloqueada?"}
    f -- sí --> keep["se queda, diga lo que diga la política"]
    f -- no --> del["se borra"]
    btn["botón Eliminar"] --> chk{"¿bloqueada?"}
    chk -- sí --> no409["409 · «desbloquéala antes»"]
    chk -- no --> del
    svc["delete_backup() del servicio"] --> chk
```

- **Es un fichero al lado del archivo** (`<copia>.zip.lock`), no una columna. `list_backups` lee
  el directorio precisamente para que no exista una segunda verdad sobre ficheros que alguien
  puede copiar, mover o borrar con el panel parado — y un bloqueo en una tabla sería justo eso,
  con el fallo de que la fila diga «protegida» de un archivo que ya no está. El marcador viaja
  con la copia, como el `.sha256`, y lleva quién y cuándo.
- **Un marcador ilegible sigue contando como bloqueo.** Su existencia es la bandera; su contenido
  es una cortesía, y leer una cortesía rota como «no protegida» es fallar en la única dirección
  en la que un cerrojo no puede fallar.
- **Se niega también en el servicio**, no solo en la ruta: un bloqueo que solo respetara la UI no
  protege nada el día que otro camino calcule la lista de condenadas por su cuenta.
- **Sigue reclamando su franja.** El filtro se aplica al final, no ocultándola de las reglas:
  proteger la copia más reciente de un día no puede comprar de regalo otra copia para ese día.
- **Gasta presupuesto pero no se puede tirar.** El sitio que ocupa está ocupado lo reconozca o no
  el techo; y un techo que pudiera borrarla anularía la única instrucción que el bloqueo existe
  para dar.
- **Los marcadores no sobreviven al archivo.** Un `.lock` huérfano haría nacer bloqueada a la
  siguiente copia con el mismo nombre, sin que nada en pantalla lo explicara.

Va con `backup_delete`, **en ambos sentidos**: el bloqueo solo afecta a si un archivo se puede
destruir, y desbloquear es pedir poder borrarlo. Lo que **no** es: protección frente a un
administrador —quien puede desbloquear puede después borrar—. Es una barrera contra la retención
y contra la fila equivocada, que es como se pierde la copia buena.

---

## Jobs: por qué nada se espera

Copiar y restaurar tardan minutos en una instalación grande, y una petición abierta ese rato es
una que el navegador o un proxy inverso acaba abandonando — dejando al operador sin saber si
funcionó. Las cuatro operaciones largas arrancan un **job** y devuelven un `job_id`.

```mermaid
sequenceDiagram
    participant N as Navegador
    participant W as Rutas (web)
    participant J as Hilo del job
    N->>W: POST …/backups (o /restore, o /tasks/<id>/run)
    W->>J: start_manual / start_restore / start_run
    W-->>N: {ok, job_id}
    loop cada segundo
        N->>W: GET …/jobs/<job_id>
        W-->>N: {step, total, table, steps, done}
        Note over N: fila en la lista + barra + checklist
    end
    J->>J: termina · auditoría · cachés · poke
    N->>W: GET …/jobs/<job_id>
    W-->>N: {done: true, status, skipped, …}
    Note over N: el diálogo NO se cierra:<br/>muestra el veredicto y espera
```

- Los jobs viven **en la memoria de ese proceso**. Un `404` tras un reinicio es la verdad, no un
  error: el navegador deja de preguntar en vez de esperar una respuesta que no llegará.
- El diálogo **no se cierra solo** al terminar. Ese es justo el instante en que su resultado
  merece leerse, y una copia parcial es el desenlace que no puede descartar la pantalla por ti.
- Tras una **restauración** la página se recarga **al cerrar** el diálogo: todo lo que había en
  pantalla se leyó antes de que las tablas cambiaran debajo.

---

## Permisos

Siete flags, no uno. El archivo es la instalación entera en un fichero, así que las acciones no
son intercambiables.

| Flag | Cubre | Por qué es propio |
|---|---|---|
| `backup_view` | Ver la lista y las tareas | Ver que existen copias ya dice qué hay y desde cuándo |
| `backup_verify` | Verificar una copia | No escribe nada, pero recorre y hashea un archivo de gigabytes |
| `backup_create` | Crear una copia · **ejecutar una tarea ahora** | Ejecutar una tarea **es** hacer una copia |
| `backup_download` | Descargar el fichero | Quien puede bajarlo tiene la instalación |
| `backup_restore` | Aplicar una copia | Sobrescribe usuarios y roles: puede entregar el panel |
| `backup_delete` | Borrar una copia del disco · **bloquearla y desbloquearla** | Destruye datos. El bloqueo solo afecta a si un archivo puede destruirse, y desbloquear es pedir poder borrarlo |
| `backup_schedule` | Crear, editar y borrar **tareas** y **perfiles de retención** | No destruye ningún archivo, pero decide cada cuánto se protege la instalación — y un perfil lo decide de golpe para todas las tareas que lo siguen |

> La **previsualización** de una política va con `backup_view`: responde una pregunta sobre
> las copias que ya están en disco y no cambia nada.

Ninguno se concede a los roles integrados: una copia es una herramienta de administración.
Los botones siguen los mismos flags — uno que devuelve 403 dice que el panel está roto, no que
falta el permiso. Catálogo completo del RBAC en [ref-permisos.md](ref-permisos.md).

---

## Auditoría y log

**Todo** queda auditado, la descarga incluida: *«quién se llevó una copia de esta máquina, y
cuándo»* es una pregunta que el registro tiene que poder responder.

| Evento | Severidad | Detalle que lleva |
|---|---|---|
| `backup_created` | success | partes, secretos, tablas, tamaño, **veredicto** |
| `backup_downloaded` | warning | nombre — escrito **antes** de que el fichero salga |
| `backup_restored` | danger | partes, `only_tables` (**qué se pidió**, `all` si no se acotó), tablas con sus filas, **build de origen** y **qué no se pudo aplicar** |
| `backup_deleted` | danger | nombre(s); en la poda, la tarea |
| `backup_verified` | warning | resultado |
| `backup_task_saved` / `_deleted` | warning / danger | la tarea |
| `backup_task_migrated` | muted | la conversión única de los ajustes anteriores |
| `backup_dir_created` | muted | la carpeta creada desde el explorador |

En el **log** del panel (`global|log_level`, ver [explica-logging.md](explica-logging.md)):

```
[INFO   ] > Backup > job a3f9c1 >> restore 'copia-20260811-2102' started
[INFO   ] > Backup > restore >> 'copia-20260811-2102' parts=['config_file', 'core'] made with 0.0.1+build.40
[DEBUG  ] > Backup > restore >> hosts: 12 rows
[WARNING] > Backup > restore >> credentials: table is gone, 4 rows not applied
[WARNING] > Backup > restore >> 'copia-20260811-2102' done, 148 rows in 9 tables, 1 could not be applied in full
```

Una restauración acotada a mano sube a **warning** desde la primera línea y nombra las tablas —
lo que se dejó fuera se dejó fuera a propósito, y esto es lo que explica meses después por qué
media instalación es más vieja que la otra media:

```
[WARNING] > Backup > restore >> 'copia-20260811-2102' parts=['core'] tables=['hosts'] made with 0.0.1+build.65
```

---

## En microservicios

```mermaid
flowchart TB
    subgraph w["contenedor web"]
      run["BackupRunner (hilo)<br/>tick cada 10 min"]
      api["rutas /api/v1/backups"]
    end
    subgraph others["worker · syslog · events"]
      poll["reconcile cada 15 s"]
    end
    run --> vol[("volumen vardata<br/>&lt;var_dir&gt;/backups")]
    api --> db[("BD compartida")]
    poll --> db
    api -.->|"poke /control/reconcile<br/>tras restaurar"| others
```

- **Las copias programadas las toma el rol `web`**, y solo ése: el hilo lo arranca el
  `WebAdmin`. El worker, el receptor de syslog y el de eventos no lo crean nunca. Con el rol web
  parado **no se toma ninguna copia programada**.
- Con **varias réplicas de web**, el *lease* (`backup`, TTL 900 s) decide cuál la hace: si no,
  cada una escribiría su archivo y leería todas las tablas.
- La carpeta de copias tiene que estar montada **en el contenedor web**. En el compose que se
  distribuye, los cuatro roles comparten `vardata`, así que caen en un sitio persistente.
- Tras restaurar, los demás contenedores reciben un **poke** (`/control/reconcile`) para
  releer ya, en vez de esperar a su poll de 15 s.

### Qué converge solo y qué no

| Cambia | ¿Se aplica sin reiniciar? |
|---|---|
| Filas (hosts, usuarios, roles, checks, credenciales) | **Sí, al instante** — se leen de la BD compartida |
| Config editable (tabla `config`) | **Sí** — poke inmediato, y en su defecto el poll de 15 s |
| Puertos de syslog, allowlist, certificados | **Sí** — el listener se recarga solo… |
| …pero el **puerto publicado de Docker** | **No.** Se fijó al crear el contenedor: hay que tocar el compose |
| Sección `database` de la copia | **No en caliente**; al siguiente reinicio podría apuntar a otro sitio si no lo fija `SS_DB_*` |
| Puertos fijados por CLI (`--port`) en un contenedor | **No, y es lo correcto**: lo que fija el despliegue no lo cambia una copia |
| `SS_SECRET_KEY` | No viaja en la copia. Sin la misma clave, los valores `enc:` no se descifran |

---

## Dónde caen las copias

`web_admin|backup_dir`, y vacío significa `<var_dir>/backups`. Es configurable porque una copia
en el mismo disco que los datos que copia sobrevive a un error humano y a nada más.

La ruta se resuelve **en cada operación**, no al arrancar: quien la cambia a mitad de día no
tiene que reiniciar, y una ruta capturada al registrar las rutas escribiría la copia siguiente
en el sitio viejo y la buscaría en el nuevo.

El campo lleva un **explorador de carpetas** (con crear carpeta y comprobación de escritura) que
cuelga de un registro genérico por ruta de config: el renderizador de campos pinta doscientos
campos y no tiene por qué saber que uno de ellos es una carpeta.

---

## Trampas conocidas

1. **`SS_SECRET_KEY`.** Restaurar en otra instalación sin la misma clave deja toda credencial
   ilegible. No lo detecta nada.
2. **Rol web parado = sin copias programadas.** Nada lo anuncia. La regla de intervalo salva el
   reinicio, no el apagado prolongado.
3. **Puertos de Docker.** La aplicación rebinda; la red del contenedor no.
4. **Cambios de significado entre builds.** Ningún chequeo de versión los ve.
5. **`backup_dir` fuera del volumen compartido** en microservicios: las copias caerían en el
   sistema de ficheros efímero del contenedor web.

---

## Ver también

- [ref-api.md](ref-api.md) — los endpoints con su permiso y su formato
- [ref-permisos.md](ref-permisos.md) — el catálogo RBAC completo
- [explica-descubrimiento.md](explica-descubrimiento.md#6b-partes-de-backup-aportadas-por-un-módulo-__backup_part__) — cómo un módulo aporta su parte
- [explica-servicios.md](explica-servicios.md) — lease de líder, control-plane y modo microservicios
- [caso-docker.md](caso-docker.md) — topologías, volúmenes y variables
- [caso-diagnostico.md](caso-diagnostico.md) — el bug de la segunda base de syslog
- [ref-tests.md](ref-tests.md) — qué cubre cada test de esta sección
