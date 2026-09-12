# SNMP

SNMP es el módulo que más datos produce de todo el panel: en una instalación real, **el 83 % de
las filas del histórico**. También es el más raro de los veintiún watchfuls, porque no comprueba
una cosa — recorre un dispositivo entero y devuelve todo lo que sabe decir.

Este documento explica cómo funciona de punta a punta, y termina con el **plan de la reforma del
almacenamiento** que ese 83 % justifica.

> Las **credenciales y el perfil de conexión** viven en el registro de dispositivos — ver
> [explica-hosts.md](explica-hosts.md). La **API** está en [ref-api.md](ref-api.md) y la
> **configuración del módulo** en [ref-modulos.md](ref-modulos.md).

---

## Dos mitades, y por qué

| Dónde | Qué es suyo |
|---|---|
| `lib/core/snmp/` | **El dispositivo**: hablar el protocolo, el formato de perfil, leer una métrica, la biblioteca de MIBs, las acciones del panel y sus rutas |
| `watchfuls/snmp/` | **El módulo**: los checks de OID, y convertir una lectura en una **serie** — el valor anterior, el nombre de la fila, el veredicto, el resultado |

El corte no es organizativo. Al núcleo lo llaman **tres** sitios que tienen que dar la misma
respuesta: el planificador, la pantalla de «probar perfiles» y el recorrido de un host desde el
registro. Un formato de perfil implementado dos veces son dos ideas de qué mide un dispositivo.

Y el estado que sobrevive al proceso —la línea base de cada contador, la racha de fallos— vive en
el watchful, porque es del módulo y no del protocolo.

`watchfuls/snmp/__init__.py` es sólo el ensamblaje:

```python
class Watchful(MibAdmin, SnmpChecks, SnmpClient, SnmpActions, SnmpSampler, SnmpWidget, ModuleBase)
```

---

## La conexión

**Biblioteca**: `pysnmp` 6+/7+ (el fork de lextudio), desde `pysnmp.hlapi.v3arch.asyncio` y
detrás de una guarda: sin ella el módulo declara `MISSING_DEPS = ['pysnmp']` y cada primitiva
devuelve un texto de error en vez de reventar. `pysmi` es dependencia **parcial** — sólo hace
falta para compilar MIBs.

**Versiones**, resueltas en un solo sitio (`lib/core/snmp/client.py`):

| Versión | Autenticación |
|---|---|
| v1 | `CommunityData(community, mpModel=0)` |
| v2c | `CommunityData(community, mpModel=1)` |
| v3 | `UsmUserData(usuario, authKey, privKey, authProtocol, privProtocol)` |

Autenticación: MD5, SHA, SHA-224/256/384/512 o ninguna. Cifrado: DES, 3DES, AES-128/192/256 o
ninguno. Un nombre que no esté en la tabla cae a MD5/DES.

> **Trampa registrada.** La autenticación llegó a estar escrita dos veces y sólo una aprendió
> v3: el recorrido de descubrimiento construía un `CommunityData` con `mpModel=1` para
> `version == '3'` — una petición v2c a un dispositivo v3. Los checks funcionaban y el
> descubrimiento devolvía silencio.

**Dónde viven las credenciales**: en el perfil de host `snmp`, declarado una vez en
`lib/core/snmp/manifest.py` (`HOST_PROFILE`) — `host`, `port`, `version`, `community`,
`snmpv3_username`, `snmpv3_auth_key`, `snmpv3_priv_key`, `snmpv3_auth_protocol`,
`snmpv3_priv_protocol`, `device_profiles`. El `schema.json` del módulo sólo dice
`"__profile_fields__": "snmp"`; el panel expande la declaración del núcleo dentro.

**Valores por defecto**, con una sola fuente (`lib/core/snmp/defaults.py`): puerto 161, versión
`2c`, comunidad `public`, timeout 5 s, 1 reintento, MD5/DES. El `schema.json` los repite para
pintar el formulario, y una guarda de `tests/meta` comprueba que los dos digan lo mismo.

**Bulk frente a get**: `bulk_walk_cmd` con `maxRepetitions=50` para todo lo que no sea v1 (que
no lo soporta y usa `walk_cmd`). Las lecturas sueltas usan `get_cmd`. Un recorrido se corta a
**512 filas**, y el recorrido manual de la interfaz a 500.

### Lo que se reutiliza, y lo que costaba no reutilizarlo

El cliente comparte, para todo el proceso:

- **un bucle asyncio** en un hilo demonio, porque el motor de pysnmp no puede sobrevivir al bucle
  donde se abrió su socket;
- **un `SnmpEngine`**. Reconstruirlo por petición costaba **~1 segundo de CPU cada vez** — trece
  módulos MIB recompilados y un analizador SMI completo la primera vez. Un dispositivo con el
  catálogo entero son 348 lecturas: **365 segundos por ciclo, de los que 6 eran el dispositivo**.
  Con el motor compartido, 6;
- **el transporte** (`UdpTransportTarget`) cacheado por `(host, puerto, timeout, reintentos)`,
  bajo un cerrojo que se sostiene durante el `await`: dos métricas simultáneas del mismo
  dispositivo resuelven el DNS una vez;
- **los objetos de autenticación** por credencial — y no meramente iguales, sino **idénticos**,
  porque el LCD de pysnmp indexa por identidad de objeto y uno nuevo por petición hace crecer la
  configuración del motor para siempre.

> **Trampa registrada.** El módulo usaba `asyncio.run`, que **se niega** cuando el hilo que llama
> ya tiene un bucle. El descubrimiento lo envolvía en un `try/except: continue`, así que en un
> hilo así todos los servidores lanzaban excepción, todos se saltaban, y la lista vacía se leía
> como «este dispositivo no tiene OIDs». Salió en CI porque la API síncrona de Playwright deja un
> bucle vivo en el hilo principal.

### `NoAnswer` no es lo mismo que `noSuchName`

`NoAnswer` es una subclase de `str` —para que todo lo que la registra o la imprime siga
funcionando— que significa **el dispositivo no dijo nada**: timeout, inalcanzable, credencial
mala. `noSuchName`, en cambio, **es una respuesta**: el dispositivo contestó que ese OID no
existe.

La diferencia manda en el abandono:

- **`_SILENT_GIVE_UP = 3`** — tres `NoAnswer` seguidos *mientras nada ha contestado todavía*
  abandonan el dispositivo por ese ciclo. Sin esto, un nodo Proxmox que rechazaba SNMP se quedaba
  en «leyendo las métricas 1/14»: catorce perfiles × doce métricas × 5 s con un reintento es
  media hora de espera.
- Un `noSuchName` **no cuenta**, deliberadamente: el dispositivo está hablando.
- **`_SAMPLE_ALERT = 2`** ciclos de silencio total antes de darlo por caído.

---

## Qué se muestrea

Hay dos caminos, y se unen antes de ejecutar.

### 1. Un check de OID

Nombra un servidor y un OID, hace un GET y compara: `any`, `eq`, `ne`, `gt`, `lt`, `gte`, `lte`,
`contains`, `regex`. Los operadores numéricos convierten los dos lados a `float` y caen a
comparación de texto para `eq`/`ne`. Produce un **veredicto**, con antirrebote por umbral
(`alert`) y una racha de fallos que sobrevive al ciclo.

Es lo que había antes de los perfiles y sigue siendo lo correcto para «vigila **este** OID».

### 2. Un perfil de dispositivo

Un perfil es **datos, nunca código**, y todo lo que no se entiende **se descarta, no se lanza**:
una métrica mal escrita cuesta su línea y un perfil mal escrito cuesta ese perfil, porque un
ciclo que no se ejecuta es un fallo peor.

**De dónde salen los perfiles** — tres orígenes, un catálogo:

| Origen | Dónde | Puede pisar un id existente |
|---|---|---|
| `shipped` | `lib/core/snmp/profiles/sources/*.json` (~40) | — |
| `custom` | `<var_dir>/snmp_profiles/*.json` | **Sí**, a propósito: un fabricante cambia un OID y el arreglo no puede esperar a una versión |
| `db` | tabla `snmp_catalog`, escritos en el panel | No |

El tercero es la base de datos y no una cuarta carpeta porque un despliegue con un contenedor
web y otro worker **comparte la base de datos y no el disco**.

**A quién se le aplica**: a un item del módulo que lleve `device_profiles`, y a **cualquier host**
del registro cuyo perfil `snmp` tenga perfiles asignados. Eso último es el punto entero: un host
con perfil SNMP y al menos un perfil de dispositivo **es** un dispositivo y se muestrea; no hace
falta que exista nada más. No pisa un «apagado» explícito, no toma la decisión de mantenimiento y
no mira los checks.

---

## El formato de perfil

Una métrica declara **exactamente uno** de:

- **`oid`** — un escalar, un GET, una fila;
- **`walk`** — una columna de tabla, un recorrido, una fila por fila de la tabla.

Los dos han de casar `^\d+(\.\d+)+$`: el catálogo **no resuelve nombres MIB**, así que un perfil
funciona en una instalación sin una sola MIB compilada. «Una declaración que dice las dos cosas es
la de alguien que no decidió.»

Las claves de las filas de una tabla son **el sufijo del OID después de la raíz recorrida**, que
es el índice de la tabla (`"3"`, o `"1.3.6.1.4.1"` en una tabla indexada por OID). A partir de
ahí, por orden:

| Declaración | Para qué |
|---|---|
| `where` | Quedarse sólo con las filas donde otra columna vale algo. Las filas de las que la columna filtro no dice nada **se descartan** |
| `from_index` | La lectura es el componente N del propio índice. Existe por `lldpRemTable`, que pone el puerto del que informa en el índice y en ninguna columna |
| `value_label` | El valor es una **referencia** a una fila de otra tabla; se resuelve a su nombre (`dot3adAggPortAttachedAggID` contesta `141` → «Po1») |
| `path` | El valor es una ruta entera; `{sep, row, value}` dice qué componente nombra la fila y cuál es la lectura. Índices negativos cuentan desde el final |
| `row_index` | Para tablas indexadas por un **par** de filas (`ifStackTable`): qué componente dice de qué fila se habla |
| `index_label` | Uno o **varios** OIDs, recorridos una vez y cacheados, unidos con ` / `. Una tabla SMART necesita dos porque ninguna columna sola nombra la fila |
| `with` | La columna que viaja en la misma fila (dirección + máscara). `as: "prefix"` convierte la máscara en prefijo y devuelve `''` para una máscara no contigua en vez de un número inventado. Sólo se aplica a `kind: text`: «un número con algo pegado detrás es un texto que antes era una medida» |
| `scale_by` | Un multiplicador por fila leído de otra columna (`hrStorageAllocationUnits`). Si la columna no da nada usable vale **1**, nunca 0 y nunca una fila descartada |

**Un recorrido por columna de apoyo, la nombren las métricas que la nombren.** Una tabla de
interfaces con cinco métricas contra un `ifDescr` es **un** recorrido, no cinco.

**Grupos**: una entrada con `includes` en vez de `metrics` es un grupo. Se expanden en un solo
sitio, a prueba de ciclos, con profundidad máxima 8 y deduplicando — dos grupos que comparten un
perfil no lo muestrean dos veces.

### Lo que la experiencia añadió al formato

| Declaración | El caso real que la trajo |
|---|---|
| `quiet_when` | Dos NAS contaban `ovs-system`, `sit0` y tres VLAN como caídas; todas contestan `ifAdminStatus = 2` por diseño. Pero `docker0` en la misma máquina está admin-UP y sí está caída, y tiene que seguir diciéndolo: **la regla es sobre lo que se PIDIÓ, no sobre qué nombres parecen virtuales** |
| `present_when` | Un NAS sin GPU contesta igualmente a SYNOLOGY-GPUINFO-MIB —0 % de uso, 0 B de memoria— así que a cada máquina así le crecía una tarjeta de GPU que no decía nada |
| `headline_rows` | HOST-RESOURCES-MIB en un NAS con contenedores: cinco anillos de memoria seguidos de treinta y nueve anillos marcando el 67 % del mismo 31 TiB |
| `verdict: false` | Un estado que **colorea pero no juzga**: un armario de switches a medio poblar salía permanentemente en rojo |
| `aggregate: sum` | El total del dispositivo. Cada fila conserva su propia línea base y se diferencia por separado; **la suma es de los resultados**, no de los contadores en bruto — sumar antes de diferenciar da un pico cada vez que se añade un puerto |
| `of_device` | Las filas de `ipAddrTable` son las direcciones de **una** máquina: se doblan en un solo hecho unido por comas, porque una respuesta por dirección es «una respuesta archivada en cinco sitios que nadie abre» |
| `evidence` | Las tablas de reenvío y las cachés ARP no llegan a ser resultados: van al almacén de indicios, archivadas por host, **y se escriben aunque estén vacías** — un switch que ha olvidado todas las MAC no puede dejar los cables de la semana pasada dibujados en el mapa |

---

## La forma del resultado

**La clave**:

```
<srv_key>/metrics      ← el dispositivo: escalares, totales y hechos de dispositivo
<srv_key>/<fila>       ← una fila de una tabla
```

donde `srv_key` es el uid del item del módulo, o **`host.<uid>`** cuando el dispositivo viene del
registro. Ejemplos reales: `srv/metrics`, `host.h1/eth0`.

El nombre de la fila se pasa por `_KEY_SAFE = [^0-9A-Za-z._:-]+` — una `/` partiría la clave del
resultado y `eth0/1` serían dos puertos.

**`other_data`** lleva cada `metric['key'] → número`, más estas claves con guion bajo, sólo cuando
tienen algo:

| Clave | Qué es |
|---|---|
| `_attrs` | `{perfil: {rol_o_clave: texto}}` — hechos de identidad |
| `_row` | El nombre de la fila antes de sanearlo |
| `_watched` | `True` si alguien marcó esta fila en el registro |
| `_role` | Como qué la marcó (`wan` es el único rol que existe) |

Una fila de interfaz muestreada, entera:

```python
{
  'if_in': 128374.2, 'if_out': 91233.0,          # contador → tasa en B/s
  'if_pkts_in': 210.5, 'if_pkts_out': 188.0,
  'if_errors_in': 0, 'if_discards_in': 0,
  'if_oper': 1, 'if_admin': 1,                   # gauge
  'if_speed': 1000000000, 'if_mtu': 1500,
  '_attrs': {'if_generic': {'alias': 'uplink to core',
                            'mac': 'aa:bb:cc:dd:ee:ff', 'kind': '6'}},
  '_row': 'eth0', '_watched': True, '_role': 'wan',
}
```

**La línea que separa lo que la fila ES de lo que la fila MIDE es `kind`**:

- **`text` → `_attrs`, y nunca una serie.** Modelos, seriales, firmware, MAC, alias. El formato lo
  dice explícitamente: las métricas de texto están fuera de `history_fields` **a propósito**,
  porque son lo que la máquina *es*, no lo que está haciendo.
- **`gauge` y `counter` → las claves numéricas.** Eso es lo que se mide.

> **Trampa registrada.** Los atributos se archivaban planos. Un NAS y el SAI enchufado a él
> contestan los dos «vendor», «model» y «version», así que el segundo perfil pisaba al primero en
> silencio: el panel enseñaba el serial de una máquina junto al firmware de otra, y cuál
> sobrevivía dependía del orden de muestreo. Nada dio error; un dato simplemente desapareció.

---

## Contadores: tasas, vuelcos y reinicios

Todo en `lib/core/snmp/metrics.py`, que es puro — sin dispositivo, sin monitor, sin E/S.

- **`text`** → `(None, None)`: no es una serie.
- **`gauge`** → el valor escalado. El escalado es **un multiplicador, jamás una fórmula**: «un
  perfil que pudiera llevar una expresión sería un perfil que puede ejecutar una».
- **`counter`** → **la primera muestra devuelve `None`**: es sólo la línea base. A partir de ahí,
  la tasa entre dos lecturas.

La regla del paso hacia atrás depende del ancho:

| Ancho | Un valor menor que el anterior es… | Qué se hace |
|---|---|---|
| 32 bits | un **vuelco** | se le suma `2**32` (una interfaz gigabit llena un Counter32 en ~34 s) |
| 64 bits | un **reinicio** | se **descarta** la muestra (~4,6 años a un terabit) |

En los dos casos se guarda la nueva línea base. «Descartar una muestra cuesta un punto de la
gráfica; inventarla cuesta la gráfica.» El ancho por defecto es **32**, porque un dispositivo que
no implementa las columnas de 64 bits está sirviendo las de 32, y tratar un vuelco de 32 como un
reinicio descartaría una muestra cada pocos minutos en un enlace con tráfico.

`max_rate` es la salida de emergencia para una tasa imposible en ese enlace.

### Dónde vive el valor anterior — y por qué ahí

```python
self._monitor.status.get_conf([self.name_module, f'{srv_key}/metrics',
                               'module_state', 'snmp_prev'], {})
```

Forma: `{fila: {métrica: {'v': float, 't': ts}}}`. Se carga una vez por dispositivo antes del
bucle de perfiles y se guarda una vez al terminar.

> **Trampa registrada, y de las caras.** El diccionario de estado del monitor *parece* libre
> —`set_conf` acepta cualquier ruta y devuelve `True`— pero lo que sobrevive a un ciclo es lo que
> la tabla `check_state` tiene columna para guardar. Así que **todos los contadores de todos los
> perfiles** —tráfico, paquetes, errores, descartes, TCP/UDP/ICMP/IP, E/S de disco— escribían su
> línea base en un diccionario que se tiraba segundos después. Cada muestra era la primera, no se
> calculaba ninguna tasa nunca, y el panel enseñaba gauges sin línea donde tenía que haber un
> contador — que se lee como un dispositivo que no los sirve.

La pantalla de prueba, a propósito, **no enseña valor para un contador**: un contador es la
diferencia entre dos lecturas, hay una, e inventar una tasa sería exactamente el error que el
formato existe para evitar. Enseña el total en bruto, que es lo que dice que el contador está
vivo.

---

## El catálogo de MIBs

**Es una ayuda para escribir perfiles y no se toca al muestrear.** Un perfil lleva números.

| Qué | Dónde |
|---|---|
| MIBs en bruto | `<var_dir>/snmp_mibs/raw` — es la parte declarada para las copias de seguridad: el árbol compilado y el índice se reconstruyen de ahí |
| Compiladas | `<var_dir>/snmp_mibs/compiled` |
| Catálogo de símbolos | `<var_dir>/snmp_mibs/mib_catalog.db`, un SQLite **aparte** |
| Índice de OIDs | `<var_dir>/snmp_mibs/oid_index.json` |

El catálogo es una **caché derivada local** y por eso no está en la base de datos de la
aplicación, que puede ser remota y compartida. Se reconstruye si falta, si la versión de esquema
no coincide o si es más viejo que cualquier `.py` compilado — y hay un `discard()` explícito
porque **borrar una MIB no hace más nuevos a los que quedan**, así que la regla de la fecha no
puede detectar una eliminación.

Lo único que roza el catálogo cerca del cable es el *resolutor* de nombres, y en dos caminos que
son de autoría: etiquetar el recorrido manual de OIDs y clasificar lo que encuentra el
descubrimiento.

---

## Dónde acaban los datos

Dos tablas, y hacen cosas distintas:

| Tabla | Qué guarda |
|---|---|
| `check_state` | **El estado de ahora**: una fila por comprobación y métrica. Sin historia. Es lo que lee la lista de la flota |
| `history` | **La serie**: una fila por serie y ciclo — `ts`, `module`, `key`, `status`, `data` (JSON). Es lo que leen la pestaña «Medidas» y la sección Historial |

La poda corre una vez al día dentro del bucle del monitor, con `history.retention_days` y **30
días por defecto**.

### Lo que eso cuesta hoy

Medido sobre una instalación real (17,4 días de datos, 19 dispositivos):

| | |
|---|---|
| `history` | 112.219 filas · **93.486 de SNMP (83 %)** en 1.959 series |
| Ritmo | 5.358 filas SNMP/día → ~161.000 filas a 30 días |
| Texto de `key` | 5,7 MB — **54 B por fila**, repetidos |
| JSON de `data` | 22,6 MB — 211 B por fila |
| `item_uid` | **0 filas** lo tienen: la columna existe, nadie la escribe, y arrastra un índice |

Y dentro de esos 163 B de JSON de una muestra SNMP media:

| Parte | Bytes | |
|---|---|---|
| `_attrs`, `_row`, `_watched` — identidad | 78 | **47 %** |
| Los **nombres** de los campos numéricos | 64 | **39 %** |
| **Los números** | 11 | **6 %** |

Con la clave fuera, **de 217 bytes por muestra, 11 son la medida**. El resto es identidad que no
cambia y nombres de campo repetidos.

---

## El plan: separar lo que la fila ES de lo que MIDE

La forma no es «una fila por OID». El OID no es un dato de la muestra sino una línea del perfil, y
la unidad que produce SNMP es una **fila** con varios números a la vez — una fila por (OID, valor)
multiplicaría las filas por trece y, con la sobrecarga por fila de SQLite, **ocuparía más**.
Tampoco hay ninguna «sesión» que guardar: el cliente comparte un motor y un transporte cacheado
para todo el proceso.

Lo que sí hay es un JSON que mezcla identidad y medida en cada muestra, y una clave de texto que
se reescribe entera cada vez.

```text
history_series   id · module · key · item_uid · attrs(JSON) · first_ts · last_ts
history          id · series_id(INTEGER) · ts · status · data(JSON, sólo medidas)
```

Esperado: **de ~217 a ~79 bytes por muestra**, sin que ninguna pantalla cambie, porque el almacén
sigue devolviendo `{campo: valor}`. El índice `(series_id, ts)` pasa de ~66 bytes por entrada a
12. Y `item_uid` vuelve a significar algo en un sitio en lugar de en ninguno.

Medido con 3.000 muestras SNMP reales, según hasta dónde se haya llegado:

| | JSON | clave | total |
|---|---|---|---|
| Antes | 153 | 57 | **210** |
| Tras el paso 5 *(hecho)* | 79 | 57 | **136** — 36 % menos |
| Tras el paso 8 | 79 | 0 | **79** — 63 % menos |

La identidad que sale de las muestras no desaparece: pasa a la serie, y las 49 series de esa
muestra la guardan entera en **4 KB**.

### Checklist

- [x] **1. Documentar el estado de partida.** Este documento, con las medidas de la instalación
      real. *(hecho)*
- [x] **2. `history.retention_days` al registro de configuración.** Eran 30 días escritos en el
      bucle de poda del monitor, sin pantalla donde cambiarlos — y con SNMP pesando el 83 %, es el
      primer número que alguien va a querer tocar. Ya está en `lib/config/spec.py`, con su tarjeta
      «Histórico de medidas» en la pestaña Monitorización; 0 sigue significando «para siempre», y
      es `admin_only` porque bajarlo borra datos que no vuelven. *(hecho)*
- [x] **3. La tabla `history_series`.** Esquema, store y migración desde las filas existentes,
      una serie por `(module, key)` distinto y con `(module, key)` **único** — dos procesos pueden
      ver la misma serie por primera vez a la vez, y quien pierde la carrera tiene que encontrarse
      la fila del otro. `sync_series()` es idempotente porque esto corre por pasos sobre una base
      en producción y se puede interrumpir entre dos. Medido sobre la instalación real: **0,15 s
      para 2.143 series de 112.219 filas**, y sólo la primera vez. Sin lectores todavía. *(hecho)*
- [x] **4. `history.series_id`.** Columna nueva y **anulable a propósito**: una muestra grabada
      cuando la serie no se pudo resolver sigue siendo una muestra —perder el id cuesta un `join`,
      rechazar la fila cuesta la medida—. Se rellena serie a serie y sólo donde está vacía, así
      que se puede interrumpir y seguir donde lo dejó. Sobre la instalación real: **112.219 filas
      apuntadas en 0,14 s**, cero mal apuntadas. `key`/`module` se quedan de momento. *(hecho)*
- [x] **5. El almacén escribe por serie.** `record()` resuelve o crea la serie, guarda el
      `series_id` y **deja fuera del `data` todo lo que empieza por `_`**, que pasa a `attrs` de la
      serie — y sólo se reescribe **cuando cambia**, o se habría cambiado un derroche de bytes por
      uno de escrituras. Las tres lecturas que devuelven `data` lo vuelven a juntar, con la muestra
      por encima: una fila anterior al cambio lleva su propia copia y esa es la que era verdad ese
      día. Medido con **3.000 muestras SNMP reales**: el JSON de una muestra pasa de 153 a 79 bytes
      y la identidad de las 49 series ocupa 4 KB **en total**. *(hecho)*
- [x] **6. Los cinco lectores, uno a uno.** `query`, `get_stats`, `get_index`, `latest_by_series`
      y `delete_series` acotan por `series_id`, y `get_index` ya no agrupa por
      `COALESCE(item_uid, module||':'||key)` — la expresión que ningún índice puede servir y que
      obligó a escribir `latest_by_series` para esquivarla. Medido sobre la instalación real:
      **1.783 ms → 976 ms**. Leer no crea (una gráfica de algo que nunca se midió no deja una
      serie fantasma), borrar una serie se lleva su identidad y olvida las cachés, y el filtro por
      módulo pasa por la serie — hacerlo por la columna de la muestra funcionaría hoy y devolvería
      de menos en el paso 8, que es la forma silenciosa de romperse.

      Con esto desaparece una diferencia que estaba escrita como tal: `get_index` doblaba dos
      nombres de un mismo `item_uid` en una serie y `latest_by_series` daba dos. Ahora **una serie
      es `(module, key)`** en todas partes, que es como el resto del producto ya la direccionaba —
      y nadie ha escrito nunca un `item_uid`. *(hecho)*
- [x] **7. Los índices.** Entra `idx_history_series_ts(series_id, ts)`, que es como se lee una
      serie desde el paso 6. Y `idx_history_uid_ts` **se retira de verdad**: el reconciliador no
      borra un índice que dejó de declararse —sólo lo reporta, y con razón: borrar algo que no
      puso él sería decidir sobre una base que no conoce— así que lo retira el store al arrancar,
      donde sí se sabe que la columna está vacía en todas las instalaciones.

      Con el índice puesto, la poda recalcula `first_ts`: después de podar era la fecha de una
      muestra que ya no existe, y una fecha inventada en la tabla que existe para no mirar el
      histórico es peor que no tenerla. *(hecho)*
- [x] **8. Quitar `key`/`module` de `history`.** El paso que no se puede deshacer, y por eso fue
      el último y con dos cerrojos: sólo si no quedaba **ni una** muestra sin `series_id`, y
      retirando primero el índice que las nombraba. Sobre la instalación real, la migración
      completa —series, ids, índices y columnas— tardó **2,76 s** sobre 112.219 filas, y el
      fichero pasó de **121,4 a 101,1 MB** tras un VACUUM. *(hecho)*

      Y después **la migración se retiró del código**. Un camino que sólo puede correr una vez y
      ya corrió es código muerto que hay que seguir manteniendo, leyendo y probando. Lo que
      reconstruye una base anterior al cambio es una copia de seguridad — que por eso se lleva
      `history_series` en la misma parte que `history`.
- [x] **9. Medir otra vez** sobre la misma instalación:

      | | JSON | clave | total |
      |---|---|---|---|
      | Antes | 153 | 57 | **210 B** |
      | Ahora | 79 | 0 | **79 B** — 63 % menos |

      Y el fichero, con las mismas 112.219 filas dentro: **121,4 → 101,1 MB**. *(hecho)*
- [x] **10. Decidido sobre el resto, con el número delante: NO.** De los 82 bytes que ocupa hoy
      una muestra, **51 son los nombres de los campos** (61 %) y 19 los números. Un array
      posicional los dejaría en unos 25 bytes.

      Lo que se gana: a cinco mil muestras SNMP al día y treinta días de retención, unos **9 MB**.
      Lo que se paga: cada muestra queda atada al conjunto de campos que tenía el perfil **ese
      día**, así que el día que un perfil gana o pierde una métrica, las muestras anteriores se
      leen desplazadas — el `if_out` de agosto contado como `if_errors_in`. No da ningún error;
      da una gráfica creíble y equivocada, que es la clase de fallo que este dominio ya ha pagado
      tres veces.

      Nueve megas no compran eso. Si algún día la retención sube a un año y el número cambia de
      orden de magnitud, la salida es un `field_set` versionado por serie — no el array a secas.
      *(decidido)*

- [x] **11. El catálogo deja de recorrer el histórico.** Los pasos 1-10 quitaron bytes; éste
      quita el **recorrido**, que es lo que de verdad crece. Escalado el histórico real a los 30
      días de retención configurados (2,03 filas/s → **5.266.008 muestras, 1.465 series, 877 MB**),
      las dos lecturas del catálogo se hunden: `get_index` **235.674 ms** y `latest_by_series`
      **69.100 ms**, mientras leer una serie entera son 234 ms y sus últimas 24 h, 8 ms. El motor
      no tenía nada que ver: eran mil cuatrocientas respuestas calculadas leyendo cinco millones
      de filas.

      `history_series` gana cuatro columnas —`samples`, `up_samples`, `last_status`, `last_data`—
      que `record()` mantiene en el mismo `UPDATE` por clave primaria que ya hacía para `last_ts`.
      Coste medido: **0,004 ms por muestra**. Y el índice de `history` pasa a
      `(series_id, ts, status)`: `status` no entra para buscar por él sino para que el recuento
      agrupado no salga del índice — **108,0 s → 2,4 s**, por 19 MB.

      Con el código definitivo contra esos 30 días: **get_index 35 ms** (×6.700),
      **latest_by_series 30 ms** (×2.300), y las 1.465 series contrastadas una a una contra las
      5.266.008 muestras, sin un solo descuadre. `prune` repara el resumen en la misma transacción
      en que borra (2,3 s sobre cuatro millones de filas), porque publicar un catálogo que cuenta
      lo que acaba de borrar es exactamente el fallo que este dominio ya ha pagado.

      Un histórico anterior a estas columnas se rellena solo al arrancar —3,1 s una vez, después
      un sondeo de 24 ms—. No es una migración con fecha de caducidad: es la respuesta a «esta
      serie no sabe cuántas muestras tiene», y por eso se queda. *(hecho)*
- [x] **12. Las medidas dejan el JSON.** Decidido que sí, y hecho. El planteamiento era: hoy las 211 claves distintas viven en un JSON por muestra, y eso obliga a
      `get_stats` a tener tres ramas por motor —`json_extract` en SQLite y MySQL,
      `jsonb_extract_path_text` en PostgreSQL— más una lista blanca contra inyección. Una tabla
      larga `(serie, ts, campo, valor)` con las mismas 30 días: 27.588.336 hechos, **2.117 MB**
      contra 877, y a cambio las preguntas que hoy no se pueden escribir — «los 10 más cargados»
      pasa de 1.264 ms a **25 ms**, «qué interfaces dieron errores» de 915 ms a **1 ms**.

      No se decidió por rendimiento sino por producto: el panel pinta una serie cada vez, y
      para eso el JSON va a 8 ms. La forma larga no acelera lo que se hace; **habilita lo que no
      se hace**, y eso es lo que se compró.

      Lo que entró: `history` suelta el documento y se queda como la muestra —`ts`, `item_uid`,
      `status`, `series_id`—; las medidas son filas en `history_fact`; los 211 nombres viven una
      vez en `history_field`. Cada valor lleva una marca de una letra que dice lo que ES, porque
      un JSON lleva el tipo escrito dentro y una columna no: sin ella `holds_vip: true` vuelve
      como `1` y `10.0` vuelve como `10`. Y un entero mayor que 2⁵³ se guarda aproximado en `num`
      —para que cuente en un promedio— y exacto en `txt`.

      Contrastado sobre la instalación real: las **4.026 muestras**, campo a campo y tipo a tipo,
      **sin una sola diferencia**. A escala de 30 días, la migración tarda 25 minutos una vez, a
      3.471 muestras/s, por lotes y reanudable.

      La capacidad no se quedó en el SQL: `facts.fields()` dice qué se puede preguntar, `top()`
      da «los diez que más», `series_where()` «cuáles cumplieron X» y `over_time()` agrega la
      flota por tramos. Una capacidad que hay que redactar a mano cada vez no está habilitada,
      está sólo permitida.

      Tres cosas se midieron mal por el camino y están anotadas porque volverían a pasar: escribir
      muestra a muestra (2,4 horas de arranque), el conector en **autocommit** —que convierte cada
      fila en una transacción con su sincronización a disco— y, dentro de eso, un `commit` en
      `_resolve` que cerraba la transacción del lote. Y en la poda escribí en un comentario que
      borrar serie a serie sería mejor «porque sale del índice»: es al revés, 93 s contra 57.
      *(hecho)*

Cada paso tiene que dejar la suite en verde por sí solo. La migración es de las que se ejecutan
sobre una base de datos de 120 MB en producción, así que va con las tres bases —SQLite, MySQL y
PostgreSQL— por delante, como el resto del esquema
([ref-esquema-bd.md](ref-esquema-bd.md)).
