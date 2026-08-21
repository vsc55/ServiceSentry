# Bugs resueltos y trampas conocidas

> Registro de bugs no evidentes que costaron aislar, con su **causa raíz**, la
> **solución** y la **lección** generalizable para no repetirlos. No es un
> changelog (eso vive en [`CHANGELOG.md`](../CHANGELOG.md)) ni un manual de uso:
> aquí se documenta *por qué* fallaba algo y *qué patrón* lo evita.

## Cómo añadir una entrada

Cada bug es una sección `##` con esta estructura fija:

- **Síntoma** — qué se observa (lo que reportaría un usuario).
- **Diagnóstico** — cómo se aisló (comandos, pruebas que descartaron hipótesis).
- **Causa raíz** — el defecto concreto, con referencia a archivo/función/líneas.
- **Solución** — el cambio aplicado.
- **Lección** — el patrón generalizable para no reintroducirlo.

Ordena las entradas de más reciente a más antigua.

---

## La sección de MIBs tardaba cuatro minutos en abrir

**Fecha:** 2026-08-21 · **Área:** `watchfuls/snmp/mib_admin.py::_duplicate_sources`,
`mib_resolver.py::resolve_raw_sources`, `mib_lint.py::_mask`

**Síntoma** — «Sistema / SNMP / MIBs tarda muchísimo en cargar»; el rueda de carga se queda
girando y al final la sección pinta un **«⚠ Error»** sin texto. La biblioteca tenía 4970
ficheros (LibreNMS entero, tras quitar el tope de 2000).

**Diagnóstico** — Cronometrar por fases, y luego `cProfile` sobre la llamada real:

```console
list_mibs                       257.9 s
└─ _duplicate_sources           248.1 s
   └─ resolve_raw_sources       248.1 s
      └─ pysmi get_data (151×)  246.7 s
         └─ nt._path_exists × 1.193.019 → 226.5 s
```

El resto —recorrer el árbol, leer la cabecera de cada fichero, calcular pendientes— sumaba
menos de 10 s.

**Causa raíz** — Para cada módulo duplicado **sin compilar**, el listado le preguntaba a pysmi
*«¿qué fichero leerías tú?»*. El lector de pysmi prueba cada variante de nombre en **cada
directorio** que se le da: 151 consultas sobre una biblioteca de 408 carpetas = 1,19 millones
de comprobaciones de existencia. Y eso se pagaba **en cada carga de la sección**, para rellenar
paneles de duplicados que nadie había abierto. La petición acababa muriendo, y morir sin
cuerpo es el «Error» sin texto.

**Solución** — El listado contesta lo que ya sabe: **qué** módulos colisionan es agrupar
hechos que ya tiene. Lo que cuesta leer —los hashes, si el contenido es el mismo, el
parentesco y la predicción de pysmi— se calcula en una acción aparte (`mib_dupe_details`)
cuando alguien abre un grupo, y para ese grupo solo. De paso: el enmascarado de comentarios y
cadenas salta de token en token en vez de ir carácter a carácter (12 ms → 1,6 ms por fichero),
sólo se mira la cabecera (16 KB, ampliando si no aparece), lo leído de cada fichero
**sobrevive al reinicio** en `.facts-cache.json`, y el árbol se recorre **una vez** en lugar de
dos.

**Resultado medido**: **257 s → 3,6 s**, y abrir un grupo de duplicados cuesta ahora lo que
antes se pagaba 257 veces sin pedirlo.

**Lección** — Un listado no debe contestar preguntas que nadie ha hecho todavía, sobre todo si
la respuesta se lee del disco. Y para saber dónde está el tiempo, cronómetro y perfil: el
sospechoso obvio (hashear 529 ficheros) resultó ser una fracción, y el culpable estaba a tres
saltos de distancia dentro de una librería de terceros.

---

## Una caché que no guardaba nada, y 7,4 GB en el temporal

**Fecha:** 2026-08-21 · **Área:** `watchfuls/snmp/mib_admin.py::_download_archive`

**Síntoma** — Se pulsa **Comparar** contra el archivo de LibreNMS (86 MB), y a continuación
**Actualizar**: se vuelve a descargar entero. La caché recién escrita no reutilizaba nada.

**Diagnóstico** — Lo primero, descartar al servidor: `codeload` **sí** revalida.

```console
$ ETag: "cef4c89153bbf45c9b0d2fa69f68d1c43548d36cf2f79a91c94285617dda15f9"
$ (segunda petición con If-None-Match) -> HTTPError 304
```

Entonces se miró el disco:

```console
$ ls data/snmp_mibs/.archive-cache/     # vacío
$ ls %TEMP%/ss-mib-archive-*.zip | wc -l
93                                       # 7,4 GB
```

**Causa raíz** — El temporal se creaba con `tempfile.mkstemp()`, o sea en `%TEMP%` (C:), y la
caché vive junto al directorio de datos (D:). **`os.replace` no mueve ficheros entre
volúmenes en Windows**: lanzaba `OSError`, y el `except OSError` lo interpretaba como «pues me
quedo con el temporal». Resultado: no se guardaba nada, cada uso volvía a descargar, y cada
descarga dejaba 86 MB en C:. Encima, en la rama del 304 —que en `urllib` es una excepción— el
descriptor de `mkstemp` no llegaba a adoptarlo ningún objeto fichero, así que quedaba
**abierto**: en Windows un fichero con manejador abierto no se puede borrar, y el `.part`
vacío se quedaba también.

**Solución** — El temporal nace **dentro del directorio de la caché**, así que el `os.replace`
es un renombrado en el mismo volumen —atómico, que es justo para lo que se usa—; el descriptor
se adopta **antes** de la petición (`with os.fdopen(fd,'wb') as out, urlopen(...) as r`), de
modo que se cierra pase lo que pase; lo que no acaba siendo entrada de caché (un `.part`) lo
borra quien lo pidió; y la poda barre los `.part` de más de una hora, que no son descargas en
curso sino cuelgues.

**Lección** — `os.replace` es atómico **dentro de un volumen** y un error fuera de él: un
temporal que va a acabar en un sitio se crea en ese sitio, no en `%TEMP%`. Y un `except OSError`
que convierte un fallo en «sigo sin caché» es un fallo que no se nota nunca — sólo se ve
mirando lo que hay en el disco, que es lo que hubo que hacer.

---

## «Actualiza» de un MIB a su misma versión, y una biblioteca entera con `\r\r\n`

**Fecha:** 2026-08-21 · **Área:** `watchfuls/snmp/mib_admin.py::_archive_member`,
`_normalized` / `_text_of`, y los cuatro escritores de MIB en crudo

**Síntoma** — Comparar contra el archivo del fabricante devuelve
`librenms/2n/TEL2N-MIB — 201505011057Z → 201505011057Z` etiquetado **«actualiza»**. La misma
versión declarada a los dos lados, y aun así dice que hay algo más nuevo. Importar no lo
arregla: a la siguiente comparación vuelve a salir.

**Diagnóstico** — Se miró el fichero instalado en bytes, no en texto:

```console
$ od -c raw/librenms/2n/TEL2N-MIB | head -2
0000000  \r  \r  \n   T   E   L   2   N   -   M   I   B ...
$ tr -cd '\r' < f | wc -c   # 284
$ tr -cd '\n' < f | wc -c   # 142
```

Dos CR por cada LF. Y no era ese fichero: **2137 de 2137**. Un `open(p,'w',encoding='utf-8')`
en Windows lo reproduce exacto — `a\r\nb` se guarda como `a\r\r\nb`.

**Causa raíz** — Dos defectos que se sostenían el uno al otro:

1. *Escribir.* Los cuatro escritores de MIB en crudo (importar de URL, de carpeta de GitHub,
   de archivo comprimido y subir un fichero) abrían el destino en **modo texto**. En Windows
   eso traduce cada `\n` de salida a `\r\n`, así que un fichero que llega con CRLF se
   guarda con `\r\r\n`. Nada falla: el compilador no mira los espacios en blanco.
2. *Comparar.* `_archive_member` comparaba **byte a byte** el miembro del archivo con el
   fichero instalado. Dos copias del mismo MIB que sólo difieren en cómo terminan sus líneas
   son el mismo MIB — pero nunca eran iguales, así que **todos** salían «más nuevo que el
   instalado», y como importarlos volvía a dañarlos, para siempre.

Y encima de los dos, un tercer defecto de vocabulario: con las dos versiones declaradas
idénticas, la clasificación caía en el `else` y decía «actualiza», que afirma algo que no
afirmó nadie.

**Solución** — Los escritores usan `newline=''` (se guarda lo que llegó); las comparaciones
pasan por `_normalized()`, que es **la** definición de «el mismo contenido» y es la que ya
usaban el diff y el detector de duplicados; un contenido distinto con el mismo `LAST-UPDATED`
tiene su propio estado, `same_version` («misma versión»), que se importa igual pero no se
cuenta como más nuevo; y la biblioteca ya dañada se repara **una vez** en sitio
(`_repair_line_endings`), **conservando el mtime** — el cambio es espacio en blanco, el
módulo compilado sigue vigente, y tocar dos mil mtimes habría encargado una recompilación
completa: horas de ASN.1 para un cambio que ningún compilador ve.

**Segunda vuelta** — La primera versión de esa reparación colapsaba `\r\r\n` → `\r\n`, y
eso está mal por un motivo que sólo se ve mirando el origen:

```console
$ # lo que sirve LibreNMS, comparado con nuestra copia
2n/TEL2N-MIB         remoto CR= 142 LF= 142 rr=  0     # CRLF normal: el `\r\r\n` era NUESTRO
alcatel/HPOV-NNM-MIB remoto CR= 504 LF= 252 rr=252     # el fabricante lo escribe así
adva/CM-FACILITY-MIB remoto CR=   0 LF=29698 rr=  0    # LF puro; nosotros lo guardamos CRLF
```

Hay MIBs que **vienen con `\r\r\n` de origen**. Colapsarlos borra una línea en blanco que
escribió el fabricante, y ese fichero difiere para siempre del archivo del que salió — que es
exactamente lo que apareció después como tres filas «misma versión» que no se iban. La undo
correcta es el **inverso exacto** de lo que hacía el escritor roto: quitar **un** `\r` de
cada final de línea, sea `\r\n` → `\n`, `\r\r\n` → `\r\n` o `\r\r\r\n` → `\r\r\n`.
Reconstruye los bytes que llegaron, vinieran como vinieran.

**Lección** — En Windows, escribir texto que ya trae sus saltos de línea **exige**
`newline=''`; el modo texto no es «guardar lo que me diste». Comparar ficheros de texto por
sus bytes responde a una pregunta que nadie hizo: lo que se quiere saber es si es el mismo
contenido, y esa comparación tiene que estar escrita **una vez** — este repositorio ya la
tenía en `_text_of`, y el fallo fue que la ruta de importación no la usaba. Y al reparar datos
ya dañados: la reparación es **el inverso de la transformación**, no «lo que deja el fichero
bonito». Lo segundo no distingue el daño propio del contenido ajeno, y lo borra.

---

## «Probar servidor» que no vuelve, contra un NAS que sólo tiene SNMP

**Fecha:** 2026-08-21 · **Área:** `watchfuls/snmp/sampler.py::_sample_server`,
`lib/modules/module_base.py::is_probe`

**Síntoma** — Se pulsa **Probar servidor** en un NAS con SNMP y perfiles (sin SSH y sin checks
de OID) y el modal se queda en «Probando…» sin sacar nada. No hay error, no hay resultados.

**Diagnóstico** — `/api/v1/hosts/test` ejecuta cada check enlazado del host, y para SNMP eso
incluye el **muestreo de perfiles**, cuyo docstring lo dice entero: *«Read every metric of
every profile assigned to the server»*. Un walk por columna de soporte, por métrica, por
perfil. Con los quince perfiles de Synology puestos, medido en un banco con walks de 50 ms:

```
planificador (ciclo normal)    6.9s | walks: 135
```

Contra un NAS de verdad, donde un walk de la tabla de discos o de interfaces son cientos de
round-trips, eso son minutos — dentro de una sola petición HTTP y sin nada en pantalla.

**Causa raíz** — El muestreo existe **para escribir historial**, y una sonda no escribe
historial: `ProbeMonitor._history` es `None` a propósito. Así que en una prueba el trabajo se
hacía entero y su resultado se tiraba. No era un cuelgue: era una cosecha completa disfrazada
de comprobación.

**Solución** — El monitor dice de qué clase de ejecución se trata (`Monitor.is_probe = False`,
`ProbeMonitor.is_probe = True`) y los módulos lo preguntan por `ModuleBase.is_probe`. El
muestreo SNMP **para en la primera métrica que contesta** cuando es una prueba: 135 walks → 2,
0.1 s. Sigue contestando —un host con sólo perfiles y ningún check tiene que producir algo en
el test, que es una decisión anterior y está probada—, pero demuestra en vez de cosechar.

La propiedad compara con `is True` y no por verdad-aproximada: en los tests el monitor es un
doble que contesta que sí a todo, y un ciclo del planificador que se creyera un ensayo dejaría
de rellenar las gráficas — el fallo contrario y mucho más difícil de ver.

**Lección** — Antes de optimizar un «cuelgue», mirar **para qué existe** el trabajo que lo
causa. Éste existía para alimentar un historial que en ese camino no se escribe: no había que
hacerlo más rápido, había que no hacerlo. Y una ejecución que hace menos tiene que decir por
qué, o el siguiente que lea el código lo restaura.

---

## Un MIB compilado que salía como pendiente para siempre

**Fecha:** 2026-08-20 · **Área:** `watchfuls/snmp/mib_resolver.py::pending_raw_mibs`,
`mib_admin.py::list_mibs`

**Síntoma** — `custom/MBs_LGS500_V1_1/trunk.mib` sale **pendiente**. Se pulsa compilar y el
panel contesta **«los MIB ya estaban actualizados»**. Sigue saliendo pendiente. No hay error
en ninguna parte: el fichero está bien, el compilador está contento y la lista no se mueve.

**Diagnóstico** — La primera línea del fichero lo dice todo:

```
$ head -1 trunk.mib
IEEE8023-LAG-MIB DEFINITIONS ::= BEGIN
$ ls compiled/ | grep -i lag
IEEE8023-LAG-MIB.py
```

El MIB **había compilado**, y en el sitio correcto. Lo que no existía —ni iba a existir— era
`trunk.py`, que es lo que el panel buscaba para darlo por hecho. Recontado sobre la biblioteca
real: **132 pendientes de los que 117 eran una ilusión**, 97 módulos etiquetados como
«dependencia» que los había traído el propio usuario, y 6 duplicados donde había 30.

**Causa raíz** — Un MIB en bruto tiene **dos nombres** y se usaban como si fuera uno. pysmi
*localiza* el fuente por el nombre del **fichero** (`FileReader` prueba `trunk`, `trunk.txt`,
`trunk.mib`…) y *escribe* la salida con el nombre del **módulo** que declara dentro
(`IEEE8023-LAG-MIB.py`), que es además con el que resuelve todo `IMPORTS`. Cualquier pregunta
del tipo «¿está esto compilado?» hecha con el nombre del fichero pregunta por algo que nadie
va a producir jamás. Estaba en tres sitios: `pending_raw_mibs`, el índice del listado
(`raw_index`, y con él los errores, las versiones y los huérfanos) y el modelo de filas del
navegador. Con nombres de fichero de fabricante (`rfc2011.mib`, `lsInventoryEnt.mib`,
`draft-ietf-hubmib-etherif-mib-v3-00.mib`) eso es la mitad de la biblioteca.

**Solución** — `raw_module_name(path)`: el módulo se lee **de dentro del fichero**, cacheado
por `(mtime, size)` porque el listado lo pregunta de todos en cada refresco. Lo pendiente se
resuelve contra `<MÓDULO>.py` y **sigue contestando el nombre del fichero**, que es lo que el
compilador necesita para encontrarlo; el listado publica el módulo de cada fichero y el panel
teclea las filas por él, mostrando el nombre del fichero al lado cuando no coinciden. El botón
de «compilar pendientes» pasa a contar **la lista que el servidor va a recorrer** en vez de sus
propias filas: una fila es un módulo y el trabajo va por ficheros, y en un archivo de fabricante
eso no es lo mismo casi nunca.

**Lección** — Cuando una herramienta *encuentra* algo por un nombre y lo *produce* con otro,
son dos identidades y hay que nombrarlas por separado desde el primer día. El síntoma no fue
un error sino una **contradicción entre dos respuestas** («ya estaba actualizado» / «sigue
pendiente»), y ése es el olor característico de una identidad usada para dos cosas: cada mitad
del sistema tenía razón sobre la suya.

---

## En Windows, un MIB compilado no se podía volver a compilar

**Fecha:** 2026-08-20 · **Área:** `watchfuls/snmp/mib_resolver.py::_pysmi_overwrites`

**Síntoma** — Dos MIB (`NET-SNMP-MIB`, `NET-SNMP-TC`) aparecen como **desactualizados** y
siguen así por mucho que se pulse compilar. Ninguna otra pista: el fuente está bien y el
módulo compilado existe.

**Diagnóstico** — El almacén de motivos de fallo —añadido el mismo día para otra cosa— lo tenía
escrito palabra por palabra:

```
failure writing file ...\compiled\NET-SNMP-MIB.py:
[WinError 183] No se puede crear un archivo que ya existe:
'...\compiled\tmpagl7873v' -> '...\compiled\NET-SNMP-MIB.py'
```

Un `grep` por `os.rename` en pysmi da dos resultados, uno de ellos en `writer/pyfile.py`.
Comprobado en tres líneas: renombrar sobre un fichero que existe lanza `FileExistsError 183`.

**Causa raíz** — pysmi escribe el módulo en un temporal y lo pone en su sitio con
`os.rename`. En POSIX eso **sobrescribe**; en Windows **falla** si el destino existe. Es
decir: en Windows pysmi no podía sustituir jamás un módulo que ya hubiera escrito. Las únicas
víctimas visibles eran los dos MIB cuyo `.py` ya estaba ahí (bajados como dependencia antes de
que su fuente se importara), pero el alcance real era mayor: **editar un MIB lo dejaba
desactualizado para siempre, y «recompilar todo» no podía recompilar nada**.

**Solución** — Un `os` proxy para el módulo escritor de pysmi, cuyo `rename` llama a
`os.replace` —la misma operación con semántica POSIX en las dos plataformas—, instalado sólo
durante la compilación. Un proxy sobre el módulo y no un parche a `os.rename`, que lo comparte
el proceso entero.

**Lección** — Una diferencia de plataforma en una llamada de una dependencia produce un fallo
que no se parece a un fallo de plataforma: aquí se leía como «este MIB está desactualizado»,
que es una frase sobre el MIB. Lo que acortó el diagnóstico de horas a minutos fue **haber
guardado el motivo**: el mensaje del compilador, entero y sin reescribir, esperando en un
fichero. Un estado que sólo dice *qué* pasa cuesta lo que cueste averiguar *por qué*.

## Ficheros «rechazados» al importar, y nunca los mismos

**Fecha:** 2026-08-20 · **Área:** `watchfuls/snmp/mib_admin.py::_confined_path`

**Síntoma** — Importando la carpeta `mibs/` de Net-SNMP (79 ficheros), entre tres y seis
aparecen como fallidos con el motivo `rejected`. **Un puñado distinto en cada ejecución**, y
todos con nombres perfectamente normales (`DISMAN-EVENT-MIB.txt`).

**Diagnóstico** — `rejected` sólo lo produce `_save` devolviendo `False`, y sus tres caminos
son el nombre, la guarda SSRF y `_confined_path`. Se descartaron los dos primeros a mano
—`validate_external_url` devuelve `None` para esas URL, incluso con 16 hilos a la vez— y se
instrumentó el tercero: era `_confined_path`. Reducido fuera del panel a 80 hilos escribiendo
en una carpeta que ellos mismos crean, con las dos rutas impresas:

```
base   C:\Users\...\snmp_mibs\raw
target \\?\C:\Users\...\snmp_mibs\raw\net-snmp\F-1.txt
```

**Causa raíz** — `pathlib.Path.resolve()` en Windows devuelve la ruta con prefijo extendido
(`\\?\`) cuando puede abrirla, y la forma normal cuando no. La función resolvía **los dos
lados**, así que `str(target).startswith(str(base) + os.sep)` era falso en cuanto uno de los
dos existía y el otro no — y con dieciséis hilos de descarga creando la carpeta destino a la
vez, cuál de los dos era eso cambiaba a cada llamada. Una comprobación de seguridad cuya
respuesta dependía del reloj.

**Solución** — La base se resuelve una vez (es nuestra y es estable), el destino se une a ella
y se normaliza **léxicamente**, y sólo se resuelve el destino **cuando existe**, que es el
único caso en el que un enlace simbólico tiene a dónde apuntar. La comparación pasa por
`os.path.normcase`. 0 rechazos de 200 en el mismo montaje que producía 5.

**Lección** — Una comprobación de seguridad que responde distinto según lo que haya en disco
en ese instante no es estricta, es aleatoria: aquí denegaba de más, y una función que se
equivoca en una dirección puede equivocarse en la otra el día que cambie el sistema de
ficheros. Y el mensaje lo tapaba todo — `rejected` para una ruta que estaba perfectamente bien,
sin decir qué la había rechazado.

## Un MIB que no compila y una pantalla que dice «pendiente»

**Fecha:** 2026-08-20 · **Área:** `watchfuls/snmp/mib_resolver.py::_classify_compile_results`
y la lista del gestor de MIBs

**Síntoma** — Reportado desde el panel: de los 20 MIB de Synology, uno —`SYNOLOGY-SMB-MIB`—
aparece como pendiente y no compila nunca. Pulsar «compilar» sobre él no cambia nada y no dice
nada.

**Diagnóstico** — Primero, comprobar el disco en vez de creerse el contador del trabajo: en
`compiled/` había 21 ficheros, que con dos dependencias son 19 de 20 — uno faltaba de verdad.
Compilándolo suelto con pysmi a mano, el estado devuelto es `failed`… y nada más. La causa está
en el objeto, no en la cadena: `getattr(status, 'error', None)` da
`Bad grammar near offset 558 at MIB SYNOLOGY-SMB-MIB, line 21`. El offset cae exactamente en
`SMBCpuTable OBJECT-TYPE`.

**Causa raíz** — Dos, en dos sitios distintos. (1) El fichero de Synology está **mal formado**:
en SMI un descriptor de objeto empieza en minúscula —una inicial mayúscula es una referencia de
*tipo*, no de valor— y este MIB los escribe todos en mayúscula; encima llama `SMBCpuEntry` a la
fila y `SMBCpuInfo` al `SEQUENCE`, así que el `SEQUENCE OF` apunta a algo que no es un tipo.
Bajar las iniciales sólo mueve el error de la línea 21 a la 22. No hay nada que arreglar aquí:
el fichero viene roto de fábrica. (2) Lo nuestro: **el motivo se tiraba**. El envoltorio de
resultado llevaba la lista de fallidos y ningún porqué, así que la fila decía «pendiente» — que
es lo mismo que dice un MIB que nadie ha compilado todavía. Indistinguibles, y con acciones
opuestas: uno necesita un clic, el otro que el fabricante arregle el fichero.

**Solución** — El motivo viaja los tres saltos (clasificación → trabajo → sondeo) y la fila lo
lleva como insignia de error con el mensaje en el tooltip. El veredicto de un trabajo sustituye
los motivos de los módulos que cubrió y de ninguno más, para que compilar una fila no borre lo
que se sabe de las demás.

**Lección** — Cuando dos estados distintos se pintan igual, el usuario no está viendo un estado:
está viendo una pantalla rota. «Pendiente» era correcto y aun así era mentira, porque callaba lo
único que decidía qué hacer a continuación. Y el contador de un trabajo no es una comprobación:
20 de 20 «procesados» y 19 ficheros en disco conviven sin contradecirse.

## «Compilando 0/20» para siempre: un espejo dejó de contestar y nadie tenía prisa

**Fecha:** 2026-08-20 · **Área:** `watchfuls/snmp/mib_resolver.py::_http_reader_with_timeout`
y las fuentes HTTP por defecto de la compilación

**Síntoma** — Reportado desde el panel: se importan los 20 MIB de Synology, se seleccionan
todos, se pulsa Compilar y la barra se queda en `Compilando 0 / 20 — SYNOLOGY-CAM-MIB · 0%`.
Indefinidamente. Sin error, sin toast, sin nada en el log.

**Diagnóstico** — Primero pareció que el trabajo no arrancaba, porque justo antes se había
arreglado un escaneo plano del directorio. Se reprodujo fuera del panel llamando a
`compile_raw_mibs_progressive` con un `progress_cb` que imprime tiempos: el trabajo **sí**
arrancaba y encontraba los 20. Con `faulthandler.dump_traceback_later(35)` salió el punto
exacto: `pysmi/reader/httpclient.py::get_data` → `requests` → `urllib3` → `ssl_wrap_socket`.
Estaba en un handshake TLS. Un `requests.get` a mano lo confirmó:
`https://mibs.pysnmp.com/asn1/SNMPv2-SMI` agota el tiempo, y el espejo de net-snmp en GitHub
contesta 200 en 1,2 s.

**Causa raíz** — Dos cosas que solas no bastan y juntas cuelgan la pantalla. (1) El único
espejo por defecto para los módulos estándar —`SNMPv2-SMI`, `-TC`, `-CONF`— era
`mibs.pysnmp.com`, y dejó de responder; **todo** MIB de fabricante los importa, así que sin
copia local no compila nada. (2) El timeout por petición existía (15 s) pero no salva nada:
`HttpReader.get_data()` pide **varias variantes de nombre** por módulo (`SNMPv2-SMI`, `.txt`,
`.mib`…) y se traga la excepción entre intentos (`except Exception: continue`), así que un host
caído se paga una vez por variante, por módulo. Veinte MIB detrás de un host muerto son horas.

**Solución** — Las fuentes por defecto pasan a ser una lista: el repositorio de net-snmp
primero, que es el que contesta, y el espejo de pysnmp detrás por si vuelve. Y el lector se
rinde: tras `_HTTP_DEAD_AFTER` fallos **consecutivos** deja de ir a la red y lanza al instante,
que es lo que pysmi ya sabe manejar; una respuesta —incluido un 404, que es una respuesta—
reinicia la cuenta. El timeout baja a 8 s. Los 20 MIB compilan en 48 s.

**Lección** — Un timeout acota **una** petición, no el trabajo. Cuando quien llama reintenta en
bucle y se traga los errores, el timeout es el tamaño del paso y no el del recorrido: hace falta
además dejar de intentarlo. Y un único origen por defecto para algo que necesita *todo* el
producto es un punto único de fallo que un día falla — con el agravante de que aquí no fallaba
rápido, se quedaba pensando.

## Todo se medía, se guardaba y se nombraba bien, y la pantalla estaba vacía

**Fecha:** 2026-08-20 · **Área:** `lib/core/hosts/service.py::build_host_status._matches`
(el join entre los resultados de un módulo y los items enlazados a un host)

**Síntoma** — Tras cablear el muestreo de perfiles SNMP, un NAS con perfiles asignados aparecía
en Infraestructura **sin una sola métrica**, y «Últimos datos» del host salía igual de vacío. No
hay error, no hay petición fallida, no hay nada en el log. La sección se lee como una máquina
que nunca ha informado de nada.

**Diagnóstico** — Todo lo de aguas arriba estaba bien y eso es lo que costó: los resultados se
emitían (`res.list` los tenía), se guardaban en `check_state`, el historial los indexaba, y
`history_meta()` devolvía sus 128 campos con etiqueta y unidad traducidas. Se comprobó cada
eslabón por separado hasta llegar al único que no tenía tests: el que empareja las claves de
resultado de un módulo con los items que el host tiene enlazados.

**Causa raíz** — `_matches()` conocía dos formas de clave: la que **es** el item (`<uid>`) y la
derivada con sufijo (`<uid>_ram`, de ram_swap). El muestreo emite la forma **compuesta** —
`<uid>/metrics`, `<uid>/eth0`— que es la convención que el resto del producto ya habla
(`check_label()` del historial la resuelve exactamente así). Al no reconocerla, `base` acababa
siendo la clave entera, no estaba entre las del host, y la fila se descartaba. Todas.

**Solución** — `_matches()` prueba tres formas, de más específica a menos: la clave exacta, el
primer segmento antes de `/`, y el sufijo tras el último `_`. Y `tests/unit/test_hosts_status_rows.py`,
que ese join no tenía: incluye que **sólo** el primer segmento es el item (proxmox emite
`<uid>/node/pve04`), y que `srv-uid2/metrics` **no** pertenece a `srv-uid` — un `startswith`
habría hecho que sí.

**Lección** — Un join silencioso necesita tests más que un cálculo. Cuando algo se descarta por
no encajar, el fallo no se parece a un fallo: se parece a que no había datos, que es
indistinguible del caso legítimo. Y una convención de claves que dos sitios del producto
interpretan por su cuenta (`check_label` la entendía, este join no) es una convención que
todavía no existe — o la comparten, o uno de los dos está equivocado y nadie lo nota.

## El panel se quedaba en el spinner: un comentario tumbó los 90 ficheros de JS

**Fecha:** 2026-08-19 · **Área:** `web_admin/templates/partials/cfg/auth/_group_role_map.html`
(un comentario dentro de un *template literal*)

**Síntoma** — Reportado desde el panel tras un cambio de una sola línea en una tabla de
Configuración: la pantalla de carga no se levanta. No hay contenido, no hay error visible, no
hay petición fallida. En la consola del navegador, una línea:
`Uncaught SyntaxError: unexpected token: identifier — overview:16112`.

**Diagnóstico** — El número de línea no corresponde a ningún fichero del repositorio: el front
end son ~90 ficheros de JavaScript dentro de plantillas Jinja que se concatenan en **un solo**
`<script>`, así que 16112 es una posición del bundle renderizado y no de un fuente. Se renderizó
`/admin` a disco, se extrajeron los bloques `<script>` sin `src` y se le pasó cada uno a
`node --check`; el fallo salió en el bloque grande, y el `sed` de esa línea del bundle apuntó al
comentario recién escrito.

**Causa raíz** — El comentario se puso **dentro** de una plantilla de cadena (`` ` … ` ``) y
llevaba backticks: `` `text-nowrap` ``. El primero cerró la cadena y el resto de la frase pasó a
ser código. Y como todo el panel es un único `<script>`, un error de sintaxis en cualquier punto
tumba el bundle entero: no se define nada, el arranque no llega a ejecutarse y el spinner se
queda puesto. **Todos los tests de servidor seguían pasando**: el HTML se renderiza perfecto y
lo que lleva dentro, para Flask, es una cadena. Las demás guardas leen las plantillas como
**texto**, así que tampoco lo veían.

**Solución** — El comentario sale del literal y pasa a sintaxis JS (`//`). Y una guarda para la
clase entera, no para la línea: `tests/integration/test_wa_inline_js_syntax.py` renderiza
`/admin`, `/account` y `/overview` y le pasa cada script en línea a `node --check` — el navegador
más barato posible, sin DOM y sin ejecución. Se salta si no hay node ≥ 16, porque la suite tiene
que correr en una máquina sin toolchain de JavaScript; ese suelo de versión también salió de un
tropiezo, un node v12 en el PATH que marcaba cada `?.` del panel como error de sintaxis.

**Lección** — Un proyecto que genera JavaScript desde plantillas de servidor no tiene *ningún*
test que compruebe que ese JavaScript es un programa, y la ausencia no se nota hasta que algo lo
rompe: los tests de plantilla comprueban que cierta cadena está presente, y una cadena rota está
igual de presente. Basta un `node --check` sobre lo renderizado. Corolario: en este panel un
error de sintaxis no degrada una sección, las tumba todas — el radio de daño de un solo carácter
es la página entera, así que la guarda barata sale rentable al primer uso.

---

## «Mi configuración» dejaba de abrirse tras visitar cualquier otra sección

**Fecha:** 2026-08-19 · **Área:** `web_admin/templates/partials/init/_sidebar.html`
(listener global `shown.bs.tab`)

**Síntoma** — Reportado desde el panel: se abre «Mi configuración» una vez, se navega por
Sistema (Configuración, Módulos…), y al volver a pulsar «Mi configuración» **no pasa nada**.
Ni error en consola, ni petición, ni parpadeo: el menú se cierra y la pantalla se queda como
estaba. Volvía a funcionar recargando la página.

**Diagnóstico** — La ausencia total de error apuntaba a un `return` temprano, no a una
excepción. `openAccountPage()` hace `bootstrap.Tab.getOrCreateInstance(btn).show()`, así que se
leyó el Bootstrap que se sirve: `grep -o "show(){const t=this._element;if(this._elemIsActive(t))return"`
sobre `static/js/bootstrap.bundle.min.js` (5.3.3) lo confirma — `show()` no hace nada si su
propio disparador ya lleva `.active`. Quedaba explicar por qué se lo quedaba: el listener que
mantiene un único elemento activo barre `#ss-sidebar .ss-sb-item.active`, y el disparador de
cuenta es `<button class="nav-link" id="btn-nav-account">`, sin esa clase.

**Causa raíz** — Dos hechos que por separado son correctos. Bootstrap solo desactiva dentro del
grupo del disparador (`Tab._parent = element.closest('.list-group, .nav, [role="tablist"]')`) y
las secciones de Sistema viven en un `ul.ss-sb-sub.nav` anidado, distinto del `ul` exterior
donde está el botón oculto de cuenta; y el barrido que el panel añadió precisamente para cubrir
ese hueco seleccionaba por **la clase de aspecto** de un ítem de barra lateral en vez de por lo
que lo hace un disparador. El botón de cuenta se quedaba marcado como activo para siempre y a
partir de ahí `show()` volvía en su primera línea.

**Solución** — El barrido pasa a
`#ss-sidebar .ss-sb-item.active, #ss-sidebar [data-bs-toggle="tab"].active`. Cinco tests nuevos
en `tests/meta/test_wa_spa_nav.py`, validados reintroduciendo el selector viejo: el que fija la
regresión falla y los otros cuatro siguen pasando.

**Lección** — Un barrido de estado escrito en términos de **a qué se parece** un elemento se
dejará siempre los que no se parecen a los demás, y en este caso el que no se parecía era el
único que estaba oculto — o sea, el único cuyo `.active` sobrante no se ve en pantalla. Cuando
lo que se limpia es el estado de un mecanismo (aquí, un disparador de pestaña), el selector
tiene que nombrar el mecanismo (`[data-bs-toggle="tab"]`) y no la decoración. Corolario del
mismo caso: un fallo *silencioso* de una librería —un `return` en la primera línea— se localiza
antes leyendo la librería que releyendo el código propio.

---

## Un paquete a dos versiones tenía los avisos de la otra

**Fecha:** 2026-08-16 · **Área:** `lib/core/diagnostics/advisories.py` (`vulnerabilities`)

**Síntoma** — Ninguno visible: la tabla se pinta igual acierte o no. Salió leyendo
`lib/core/diagnostics` en la auditoría, y la sospecha vino del comentario de la propia ruta
—«nombre Y versión: tres listas pueden nombrar el mismo paquete»— aplicado a los contadores pero
no a la respuesta.

**Diagnóstico** — Reproducido en 30 líneas: `check()` con dos filas del mismo paquete a dos
versiones (`urllib3` 2.2.1 local y 1.26.0 de otro contenedor) y un OSV simulado que sólo marca
la vieja como vulnerable. OSV recibe **las dos preguntas correctas** —se comprueba imprimiendo
el cuerpo del lote— y aun así las dos filas vuelven con `GHSA-OLD`. Con el aviso puesto en la
versión nueva, el resultado es el simétrico: la vulnerable sale limpia.

**Causa raíz** — `vulnerabilities()` devolvía `by_name`, un diccionario indexado sólo por
nombre; la segunda respuesta pisaba a la primera. Y como la lista de los otros contenedores se
pregunta la **última** (`rows + extra + elsewhere`), lo que pisaba la fila de este proceso era
siempre de otro. La invariante estaba escrita en tres sitios —el docstring del test de
instancias, los contadores `behind` de la ruta y el `byPin` del navegador— y no en el escalón
que hay entre ellos.

Debajo había un segundo defecto del mismo origen: el clic que abre la lista de avisos de una
fila llevaba **sólo el nombre**, así que abría la primera coincidencia bajo un título que
nombraba la versión pulsada.

**Solución** — `by_pin`, indexado por `(nombre, versión)`, leído igual en `check()`. Los totales
van detrás: `vuln_total` y `vuln_packages` cuentan avisos y paquetes **distintos** en vez de
sumar filas, que es la misma queja que existe para `collapse_aliases` entrando por la otra
puerta. En el navegador, el badge pasa el pin y un aviso nombra cada paquete una vez. Cinco
tests, los cuatro fijables validados reintroduciendo la conducta.

**Lección** — Cuando una lista deja de tener una fila por entidad, **todo lo que la indexe por
el nombre de la entidad pasa a estar mal**, en silencio y sin excepción. La invariante nueva
—«un paquete es un nombre Y una versión»— se había escrito en los sitios donde se estaba
trabajando; el paso intermedio, que nadie tocó, siguió con la vieja. Al ampliar la clave de una
colección, la revisión no es del código que se cambia sino de **todos** sus índices.

---

## El check se autorizaba por dónde aterriza, no por de dónde sale

**Fecha:** 2026-08-15 · **Área:** `lib/core/modules/authz.py` (`authorize_module_write`)

**Síntoma** — Ninguno; leyendo `lib/core/modules` detrás de `hosts`. Un guardado así se ve
idéntico en pantalla salga bien o mal.

**Diagnóstico** — El guardado de módulos autoriza **ítem a ítem**, y un check atado a un host se
autoriza con el permiso de ese host. La atadura se obtenía con `item_host_uid(o, n)`, que
recorre `(n, o)` y devuelve **la primera que encuentre**: la del ítem nuevo. Para un alta y una
baja eso es correcto —sólo hay una—; para una **modificación** hay dos, y sólo se miraba la de
destino. Comprobado con las tres variantes seguidas, con `server.mine.edit` como único permiso:
mover el check de `victim` a `mine` → **autorizado**; moverlo de `mine` a `victim` → denegado;
editarlo en su sitio → denegado.

**Causa raíz** — Un cambio de atadura es una edición de **dos** hosts: del que pierde el check y
del que lo recibe. Preguntar sólo por el destino convierte el permiso por servidor —que existe
para confinar a alguien a sus máquinas— en la única escritura del panel que alcanzaba fuera de
ellas. Y el daño no está donde uno lo busca: en el host del atacante no pasa nada raro; el que
se queda **sin monitorizar** es el otro.

**Solución** — Las dos ataduras por separado (`_item_host_uid`, sobre un lado cada vez, en vez
del helper que responde por el par y prefiere el nuevo): un alta autoriza el destino, una baja el
origen, y una modificación **ambos** cuando difieren. Ocho tests en
`tests/unit/test_modules_authz.py`, con el caso validado reintroduciendo la regla vieja, y
control positivo para lo que sí debe seguir permitido: `servers_edit` global sí puede mover un
check entre hosts, porque ese permiso no está confinado a ninguno.

**Lección** — Cuando un permiso se resuelve a partir de un **atributo del dato**, cambiar ese
atributo es parte de lo que hay que autorizar. La forma general: en toda modificación,
comprobar el estado **antes y después**, y desconfiar de cualquier helper que «resuelva» dos
valores en uno — que es justo lo que hacía el que había aquí, y por eso se dejó de usar en este
punto.

---

## El guard estaba en la acción pequeña y no en la grande

**Fecha:** 2026-08-15 · **Área:** `lib/core/groups/routes.py`

**Síntoma** — Ninguno; leyendo `lib/core/groups` detrás de `users`.

**Diagnóstico** — `PUT /api/v1/groups/<uid>` lleva un guard explícito: si el grupo tiene el rol
admin y quien pide no es administrador, **403**. `DELETE` del mismo grupo no llevaba ninguno.
Medido con las dos peticiones seguidas y el mismo solicitante —un titular de `groups_delete` sin
más—: `PUT → 403`, `DELETE → 200`, y la lista de grupos de los miembros vacía.

**Causa raíz** — Borrar el grupo hace más que editarlo: le quita el rol a **todos** sus miembros
de golpe. El guard se escribió donde se estaba trabajando (la edición) y no donde el efecto es
mayor. `delete_group` sólo se negaba con los grupos integrados, así que un grupo *personalizado*
que concede admin —que es como se concede en cuanto hay más de dos personas— quedaba a merced de
cualquiera con `groups_delete`.

**Solución** — El mismo guard de contexto en el DELETE, decidido por UID de rol
(`_carries_admin`, sobre `_is_admin_role`); y además una regla de integridad que ata también al
administrador: si borrar ese grupo dejaría la instalación **sin ningún administrador**, se
rechaza. Se cuenta contra el mapa de grupos *sin* ese grupo, que es exactamente lo que el borrado
provoca. Cuatro tests.

**Lección** — Cuando una operación tiene hermanas (crear / editar / borrar), el guard hay que
escribirlo para **la familia**, no para la que se está tocando; y la que más daño hace casi nunca
es la que se está escribiendo en ese momento. Un repaso barato: por cada `if not admin: 403` de
un PUT, buscar el DELETE correspondiente.

---

## Los administradores por grupo no contaban como administradores

**Fecha:** 2026-08-15 · **Área:** `lib/core/users/service.py`, `lib/core/users/routes.py`

**Síntoma** — Ninguno, otra vez: encontrado leyendo `lib/core/users` seguido después de la
escalada de los roles.

**Diagnóstico** — El panel hace administrador de dos maneras: por el rol de la cuenta o por
pertenecer a un grupo que lleva el rol admin —el grupo integrado *Administrators* existe para
eso, y `_is_admin_requester()` resuelve las dos—. Pero **todas** las protecciones del «último
administrador» preguntaban por la primera: `role_is_admin(u.get('role'))`, sobre el rol propio y
nada más. Igual el guard de jerarquía de las rutas de usuarios, que decidía con
`requester.get('role')` en lugar de con el método unificado.

**Causa raíz** — Dos preguntas distintas con el mismo nombre: «¿esta cuenta tiene el rol admin?»
y «¿esta cuenta es administradora?». En una instalación donde el acceso de administrador se
concede por grupo —lo normal en cuanto hay más de dos personas— el resultado es que **ninguna
de esas cuentas estaba protegida**: un titular de `users_delete` podía borrarlas, y los
contadores de «tiene que quedar un admin» no las veían, así que se podían deshabilitar o degradar
una detrás de otra hasta dejar el panel sin ningún administrador. Verificado ejecutando las
peticiones.

**Solución** — `user_is_admin(user, groups)` y `count_admins(users, groups)` en el servicio, que
responden la pregunta como la define el panel (rol propio **o** grupo habilitado que lleve el
rol admin), y los cuatro guards pasan por ahí: `set_role`, `set_enabled`, el `update_user` y el
borrado. La CLI les pasa `ctx.groups`. El guard de jerarquía de las rutas usa
`wa._is_admin_requester()`, y el envoltorio local que duplicaba la comprobación desaparece.
Ocho tests, y el del conteo validado reintroduciendo la versión vieja.

**Lección** — Cuando un sistema concede un privilegio por dos caminos, cada comprobación que
sólo mira uno es un agujero esperando a que alguien use el otro — y el que se olvida es siempre
el indirecto, porque el directo es el que se escribió primero. La forma de no repetirlo es que
la pregunta tenga **una sola implementación** con nombre propio: aquí `user_is_admin`, del mismo
modo que `_is_admin_requester` ya lo era para la sesión.

---

## Un rol llamado «admin» era admin

**Fecha:** 2026-08-15 · **Área:** `lib/core/permissions/mixin.py` (`_is_admin_requester`),
`lib/web_admin/routes/pages.py`, `lib/core/roles/service.py`

**Síntoma** — Ninguno. No lo reportó nadie: salió leyendo `lib/core` línea a línea, que es
justamente lo que un barrido de patrones no encuentra.

**Diagnóstico** — `_is_admin_requester()` preguntaba
`self._uid_to_role_name(role) == 'admin'`. Ese método devuelve la **clave interna** cuando el
UID es de un rol integrado, y el **nombre visible** cuando es de uno personalizado. Se comprobó
ejecutándolo: un rol personalizado llamado `admin`, con la lista de permisos **vacía**, daba
`_is_admin_requester() → True`, `_perms_grantable(['users_delete', 'config_edit']) → True` y
`_get_session_permissions() → []`. Es decir, admin a todos los efectos y con la pantalla de
permisos diciendo que no tiene ninguno.

Faltaba saber si ese nombre se podía registrar. `role_name_taken()` compara contra los
**nombres visibles** de los roles integrados, y por defecto el de admin es `Admin`, que colisiona
con `admin` sin distinguir mayúsculas. Pero el panel permite renombrar los roles integrados
(`update_builtin_role`), y en cuanto pasa a `Administrador` —lo primero que hace una instalación
en español— el nombre `admin` queda libre. Verificado también ejecutándolo.

**Causa raíz** — Se decidía «es el rol admin» comparando **cadenas de presentación** en vez del
UID. El coste es total: `_perms_grantable`, `_role_grantable` y `_groups_grantable` devuelven
`True` para un admin sin mirar nada más, así que responder que sí a esa pregunta salta todas las
barreras de escalada a la vez. Y el camino de entrada son dos concesiones **delegables**:
`roles_add` para acuñar el rol y `users_edit` para asignarlo. Ninguna de las dos es la de
administrador.

El mismo error, con otra forma, en el guard de las páginas de sección: resolvía los permisos
desde `session['role']` —otro nombre visible— y se equivocaba en las dos direcciones. Un rol
personalizado no resolvía a nada (`_custom_roles` está indexado por UID, no por nombre) y a su
titular lo echaban de una sección que su rol concede; y uno llamado `admin` casaba con la clave
integrada en `BUILTIN_ROLE_PERMISSIONS` y recogía **el juego completo** de permisos de admin.

**Solución** — `_is_admin_role(role_ref)`, un único sitio que decide por UID (y acepta la clave
heredada `'admin'` sólo mientras ningún rol personalizado esté indexado por ella);
`_is_admin_requester` y el `_role_is_admin` de las rutas de usuarios lo llaman. El guard de
secciones pasa a `_get_session_permissions()`. Y una segunda cerradura independiente:
`role_name_taken()` reserva las claves integradas (`admin`, `editor`, `viewer`, `none`) como
nombres, pase lo que pase con los visibles. Ocho tests de regresión, todos validados
reintroduciendo el fallo.

**Lección** — Un identificador y una etiqueta no son la misma cosa, y una función que devuelve
«la clave si es integrado, el nombre si no» convierte esa diferencia en un detalle que se olvida
en la siguiente llamada. Cuando una decisión de autorización se toma sobre una cadena, hay que
preguntarse quién puede escribir esa cadena — aquí, cualquiera con permiso para crear roles. Y
las dos cerraduras no son redundancia: la comprobación es una regla que alguien puede volver a
romper refactorizando, y el nombre reservado es una fila que ya no existe en la base de datos.

---

## Un paquete de otro contenedor preguntado por su nombre y respondido por otro

**Fecha:** 2026-08-15 · **Área:** `lib/core/diagnostics/service.py` (`elsewhere_rows`)

**Síntoma** — Ninguno visible, que es lo peor: en la lista de paquetes de un contenedor,
algunos salían con la columna «Última» vacía y **0 avisos**, exactamente igual que un paquete
sano. Nada fallaba, nada se registraba, y el número de CVE del contenedor salía más bajo de lo
que era.

**Diagnóstico** — Salió de una auditoría de código, no de un reporte. La comprobación remota
pregunta por la unión de los paquetes de todos los procesos en una sola tanda, y `elsewhere_rows`
construye esa lista comparando **canónicamente** (PEP 503) para no preguntar dos veces por lo
mismo. Al mirar qué nombre viajaba en la respuesta se vio que era el canónico, mientras la
pantalla vuelve a unir esa respuesta con la lista del contenedor por **nombre y versión**, y esa
lista lleva el nombre tal cual lo publica el proceso. Contado en el entorno real: **ocho** de los
paquetes instalados aquí se escriben de una forma y canonicalizan a otra — `PyYAML` → `pyyaml`,
`typing_extensions` → `typing-extensions`, `CacheControl` → `cachecontrol`…

**Causa raíz** — `elsewhere_rows` devolvía la tupla canónica *(nombre, versión)* como fila. El
paquete **sí** se preguntaba y la respuesta **sí** llegaba, pero bajo una clave que el navegador
no buscaba: `byPin['PyYAML@6.0.1']` no encuentra la respuesta guardada en `pyyaml@6.0.1`. Un
`undefined` se dibuja igual que «no hay nada que decir».

**Solución** — Comparar en canónico y **reportar con el nombre que usa ese contenedor**: la
deduplicación sigue siendo insensible a la forma de escribirlo, y la fila que sale conserva el
nombre con el que la pantalla la va a buscar. Dos tests nuevos fijan las dos mitades, y el
primero se validó reintroduciendo el fallo.

**Lección** — Normalizar es correcto para **comparar** y peligroso para **devolver**. Cuando dos
lados se juntan por una clave, el que responde tiene que hablar en el idioma del que pregunta;
si en medio hay una normalización, o viaja con el dato o la unión se pierde en silencio. Y el
modo de fallo elegido importa: una clave que no casa produce «sin hallazgos», que es la misma
imagen que «está limpio» — el único caso en que un fallo silencioso se lee como buena noticia.

---

## Cinco tests que solo fallaban con el navegador delante, y un descubrimiento SNMP que se rendía en silencio

**Fecha:** 2026-08-15 · **Área:** `watchfuls/snmp/client.py` (`run_coroutine`),
`watchfuls/snmp/actions.py` (`discover`)

**Síntoma** — CI en rojo con cinco fallos en `watchfuls/snmp/tests/test_snmp.py`, todos de
descubrimiento y todos con la misma forma: el walk parcheado nunca se llamaba y `discover`
devolvía `[]`. En local, ese fichero pasaba entero (131 tests). También pasaba junto a `unit`,
junto a `meta` y con el árbol de watchfuls completo.

**Diagnóstico** — no estaba en el assert, estaba en los *warnings* del log de CI:

```
watchfuls/snmp/actions.py:175: RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call'
was never awaited
    continue
```

La línea 175 es el `continue` del `except Exception` que envuelve la llamada. O sea: el
`asyncio.run` **lanzaba**, y la corrutina se quedaba sin esperar. Con eso, la combinación que
faltaba era evidente: `tests/e2e watchfuls/snmp -n auto` reproduce los cinco en 60 segundos.
La API **síncrona de Playwright** mantiene un event loop vivo en el hilo principal mientras dura
su fixture de sesión, y `asyncio.run()` se niega a arrancar otro ahí.

**Causa raíz** — `discover` llamaba `asyncio.run(...)` **dentro de un `try/except: continue`
por servidor**. En un hilo con loop vivo, cada servidor lanzaba, cada servidor se saltaba, y la
lista vacía se leía como *este dispositivo no tiene OIDs* — que es exactamente el síntoma que el
walk ya se había reescrito una vez para arreglar, por una causa completamente distinta. El mismo
`asyncio.run` estaba en `snmp_get`, la ruta de los checks.

**Solución** — `run_coroutine(coro)` en `client.py`: si el hilo ya tiene un loop corriendo,
ejecuta la corrutina en un hilo propio con su propio loop; si no, `asyncio.run` como siempre. Lo
usan los dos sitios. Guarda nueva `TestItDoesNotAssumeItOwnsTheThread` (4 tests), verificada en
rojo revirtiendo el arreglo.

**Lección** — dos, y la segunda es la cara:

- **`asyncio.run` no se puede llamar desde código que no controla su hilo.** El panel atiende
  desde el hilo que le toque, así que cualquier API asíncrona envuelta en una fachada síncrona
  necesita el camino de los dos casos. Que aquí lo destapase Playwright es accidental; el motivo
  para arreglarlo no.
- **Un `except` por elemento convierte «no pudimos preguntar» en «no hay nada».** Es la misma
  familia que la tabla de dependencias que decía «todo bien» siendo el recorte nuestro: cuando
  el fallo es de quien pregunta y no de quien responde, el resultado no parece un error, parece
  una respuesta — y nadie va a mirar. La pista útil no estaba en el assert sino en un
  `RuntimeWarning` que el log traía desde el principio.

---

## La tabla de dependencias decía «todo bien» tres veces, y ninguna era el dato

**Fecha:** 2026-08-14 · **Área:** `lib/core/diagnostics/advisories.py`,
`lib/core/diagnostics/collect.py`, `lib/core/diagnostics/routes.py`

**Síntoma** — recién estrenadas las dos columnas remotas, la tabla mostraba **0 CVE en las
41 dependencias** y prácticamente todas «en la última versión». El usuario no se lo creyó
—«es raro que no tengan CVE ningún paquete»— y tenía razón tres veces seguidas, cada una por
un motivo distinto y ninguno en los datos.

**Diagnóstico** — la sospecha no se podía resolver mirando la pantalla, porque una columna de
ceros y una columna que nadie consultó se dibujan igual. Hizo falta un **control**: las mismas
funciones, el mismo servicio, sobre versiones viejas a propósito. `urllib3 1.24.1` devolvió 24
avisos, `cryptography 41.0.0` devolvió 22 y `requests 2.19.0` devolvió 10. Con el camino
demostrado vivo, cada «todo bien» que quedaba pasó a ser un defecto que buscar:

1. ocho paquetes mostraban «—» en la columna de versión, no un fallo. Eran los **más grandes**:
   el documento por proyecto de PyPI trae todas las releases y todos los ficheros, y
   `cryptography` son 3,1 MB. El tope de lectura era de 1 MiB, y un cuerpo truncado no es JSON,
   así que llegaban como `not_json` — un error que manda a mirar la salida de PyPI;
2. los ceros eran ciertos… **de los 41 paquetes que fija el lock**. `pip`, `setuptools` y
   `pytest` sumaban cinco avisos y no se preguntaba por ellos: la tabla nació del lock y la
   pregunta que la gente le hace es «¿tiene esta máquina algo con avisos?»;
3. ya con avisos en pantalla, `pip` mostraba dos donde hay uno: `GHSA-wf93-…` y `PYSEC-2026-196`
   son el mismo path traversal con dos nombres. El total decía el doble.

**Causa raíz** — los tres son el mismo error de forma: **el panel respondía una pregunta más
estrecha que la que se leía en la pantalla**, y en los tres casos el recorte era nuestro (un
tope de lectura, el alcance de una lista, un identificador tomado como si fuera el fallo), no
del dato ni del servicio.

**Solución** — tope a 16 MB, con `too_large` como respuesta propia y distinta de `not_json`;
`collect.installed_outside_lock()` añade lo instalado que el lock no fija, en su propio pliegue
y sin contarlo como desviación; y los identificadores se colapsan por los **alias** que publica
la ficha de cada aviso. Y, por encima de los tres, la pantalla dice ahora **cuántos paquetes se
consultaron**, que es lo que convierte «0 avisos» en una afirmación comprobable.

**Lección** — **un límite propio se lee como un dato limpio.** Cuando el recorte lo pone
nuestro código —un tope, un alcance, una deduplicación que falta—, el resultado no parece un
error: parece una buena noticia, y por eso nadie va a mirar. Dos hábitos lo evitan: que cada
modo de fallo tenga **su propia respuesta** (`too_large` ≠ `not_json`) y que la pantalla lleve
**el denominador** —cuántos se preguntaron, con qué alcance—, porque un número sin él no se
puede dudar. Corolario: la forma de comprobar un «no hay nada» es un **control positivo** por
el mismo camino, no releer el código.

---

## Cuatro tests que solo fallaban en CI, y nunca en local

**Fecha:** 2026-08-12 · **Área:** `tests/conftest.py`, `tests/unit/test_backup_service.py`
(`TestItSaysWhatItIsDoingOnTheLog`), `lib/core/object_base.py` (`ObjectBase.debug`)

**Síntoma** — el workflow de GitHub daba `4 failed, 5364 passed` en la suite completa:

```text
FAILED …::test_a_copy_says_it_started_and_how_it_ended - assert "create >> 'copia'" in ''
FAILED …::test_a_refusal_says_why - assert 'already exists' in ''
```

La captura de stdout estaba **vacía**, no equivocada. En local, `pytest tests/unit` pasaba
siempre.

**Diagnóstico** — que la diferencia sea *local pasa / CI falla* con el mismo código apunta al
vecino, no al test: la suite completa mete tests de integración en el mismo proceso, y con
`-n auto` xdist decide cuál cae antes en cada worker. Los cuatro afirman sobre lo que **imprime**
la copia, y quién imprime es `ObjectBase.debug`.

**Causa raíz** — `ObjectBase.debug` es un **atributo de clase**: un único objeto para todo el
proceso, con `enabled`/`level` compartidos. Dos cosas normales lo apagan y ninguna lo restaura:
`WebAdmin.__init__` aplica `global|log_level`, cuyo default es **`off`** (`spec.py`), y
`test_wa_services.py::TestDebugAccessor` pone `off` a propósito para comprobar el accesor.
Cualquiera de las dos antes que estos cuatro tests, en el mismo worker, los deja leyendo una
captura vacía. Ninguno estaba mal: lo que estaba mal es que el siguiente test heredara el estado.

**Solución** — dos capas. Un fixture `autouse` en `tests/conftest.py` devuelve
`ObjectBase.debug` al estado en que lo encontró **después de cada test**, así que ningún test
puede romperse por lo que corrió antes; y la clase de los cuatro declara en voz alta el estado
que necesita (`enabled=True`, nivel `debug`) en vez de heredarlo. Verificado con un plugin de
pytest que envenena el estado a `off` antes de la sesión: con él, los cuatro pasan.

**Lección** — un test que **lee** estado global tiene que fijarlo, y quien lo escribe tiene que
devolverlo. Y el síntoma «falla en CI, pasa en local» rara vez es CI: casi siempre es un vecino
distinto, y con `xdist` el vecino cambia entre ejecuciones —de ahí que reproducirlo pida
provocar el estado, no repetir el comando.

---

## El rail se desplazaba y se comía la barra de herramientas

**Fecha:** 2026-08-12 · **Área:** `static/css/web_admin.css` (`.ss-shell`, `.ss-main`),
`templates/partials/core/_utils.html` (`ssRailShell`)

**Síntoma** — reportado desde *Copias de seguridad*: *«en la zona del rail se ha añadido un
scroll que desplaza el rail y no se ve correctamente»*. En la captura, la primera entrada del
índice aparecía cortada por arriba y la barra de herramientas de la sección —con *Recargar* y
*Nuevo*— no estaba en pantalla. Afectaba a **todas** las secciones con rail (Configuración,
Módulos, Copias), no solo a la que se reportó.

**Diagnóstico** — el rail cabía de sobra en su columna, así que lo que se desplazaba no era él:
era la página entera. Se reprodujo en un HTML mínimo con el CSS y el `ssRailShell` reales, medido
con Playwright (`scrollHeight - clientHeight` de `#ss-main` y la altura de cada columna):
**52 px de desbordamiento**, exactamente el alto de las barras que hay por encima del shell, y la
columna de detalle midiendo `880px` (el `100vh` de la ventana) dentro de un shell de `828px`.

**Causa raíz** — una **colisión de nombres silenciosa**: `ssRailShell` bautizaba la columna de
detalle como `.ss-main`, que es el nombre de la columna de contenido de la aplicación
(`height: 100vh` + `overflow-y: auto`, el único contenedor con scroll de la página). Son dos
bloques CSS con **la misma especificidad**, así que el segundo solo gana las propiedades que
nombra —`display`, `flex`, `min-height`— y el `height: 100vh` del primero sobrevive. Un shell
que empieza *debajo* de la miga de pan con un hijo de un viewport completo desborda la página
justo por el alto de esas barras; y al desplazar ese desbordamiento se van hacia arriba la barra
de herramientas y la cabecera del rail. Nada estaba mal escrito ni faltaba ninguna regla: por eso
no lo veía ningún guard.

**Solución** — la columna de detalle tiene nombre propio, `.ss-shell-main`, y con él las tres
reglas que ya eran suyas (`> .ss-bleed-top` ×2 y `> .ss-scroll-pad`) dicen lo que querían decir
en lugar de coincidir también con la columna de la aplicación. El guard que lo defiende es **el
nombre**, más el bloque sin `height` ni `overflow`
(`test_wa_config_views.py::TestItSitsBesideTheSection`).

**Lección** — dos cosas distintas con la misma clase CSS no dan error: dan una herencia parcial
donde la regla más nueva parece haber ganado. Cuando un componente genérico crea nodos desde
JavaScript, sus clases se eligen con el mismo cuidado que un nombre global — y un layout que
«casi» encaja se mide en el navegador, porque 52 px de desbordamiento es un dato y «parece que
scrollea de más» no lo es.

---

## La copia de seguridad ignoraba la segunda base de datos de syslog

**Fecha:** 2026-08-11 · **Área:** `lib/core/backup/` — entonces todo en `service.py`, hoy
repartido: `parts.py` (`PARTS`, `tables_by_part`, `conn_for`), `create.py`, `restore.py` y
`jobs.py` (`_connectors`)

**Síntoma** — reportado así: *«el backup creo que está mal a nivel de la tabla de syslog, si
tengo activada una segunda base de datos, la recuperación no ha recuperado los datos»*. Con
`syslog_db|enabled`, marcar la parte *Syslog* al hacer la copia no daba ningún error, la copia
se creaba con estado **correcto**, y al restaurar no volvía ni una línea de syslog.

**Diagnóstico** — la clave es que el fallo **depende de una opción de configuración**, así que
en la instalación por defecto (una sola base) todo funciona y ningún test lo veía. La parte
`syslog` declara sus tablas (`syslog`, `syslog_drops`) y `_tables_by_part` las buscaba en
`connector.list_tables()` — el conector **principal**. Con la segunda base activada esas tablas
no están ahí: la intersección salía vacía, la parte copiaba cero tablas, y como la copia no
distingue *«pedí syslog y no había nada»* de *«no pedí syslog»*, el manifiesto se escribía en
verde. `lib/web_admin/mixins/stores.py::_init_syslog_stores` construye
`_syslog_db_connector` con `build_syslog_connector`, y ese conector no llegaba al backup por
ningún camino.

**Causa raíz** — el servicio de copias asumía **un solo conector** para todo. Es la única
suposición que la instalación por defecto no desmiente nunca: con `syslog_db` desactivado
`build_syslog_connector` devuelve el conector principal, así que las dos rutas coinciden y la
suposición parece cierta.

**Solución** — la parte declara en qué base vive (`'db': 'syslog'`), y tanto `create_backup`
como `restore_backup` aceptan un mapa `connectors={'syslog': conn}` que el runner construye
desde el web admin, y solo cuando el conector de syslog **no es** el principal. `conn_for()`
decide en un único sitio, `_tables_by_part` pregunta a la base de cada parte —así `core` sigue
siendo *toda tabla que nadie reclamó* **en la base del sistema**, sin arrastrar nada de la
otra— y la restauración agrupa por base con `_by_database`: **una transacción por base**,
porque dos bases no pueden compartirla y la garantía que importa (las tablas del sistema
entran juntas o no entra ninguna) se conserva donde significa algo.

**Lección** — cuando una opción de configuración **mueve dónde viven unos datos**, todo lo que
los lee de forma transversal hereda esa opción: no basta con que el store la respete. Y una
parte que se pide y no encuentra nada no puede reportarse igual que una que no se pidió — el
silencio ahí es exactamente lo que convierte un fallo de copia en un descubrimiento el día de
la restauración.

---

## Añadir un check a un servidor activaba seis módulos que nadie tocó

**Fecha:** 2026-08-04 · **Área:** `lib/web_admin/templates/partials/servers/_save.html`
(`_applyHostChecks`), `lib/modules/discovery/schemas.py`

**Síntoma** — reportado con los pasos exactos, que es lo que permitió aislarlo rápido: activar
solo el módulo `ping`, crear un servidor, comprobar que en Módulos seguía habiendo únicamente
`ping`, ir al servidor, activar `ping` en la sección *monitoring* y guardar. Al volver a
Módulos aparecían **activados** `cpu`, `hddtemp`, `ntp`, `raid`, `ram_swap` y `snmp`, todos
**sin un solo ítem**; solo `ping` tenía el suyo.

**Diagnóstico** — la lista de módulos era la pista. `module_host_multiple()` los clasifica, y
los de **un solo check** son exactamente `cpu hddtemp keepalived ntp ping proxmox raid ram_swap
snmp`: el conjunto reportado más `ping` (activado a propósito). Ni un solo módulo multi-check
apareció, así que el sospechoso era el hueco *placeholder* que la sección monitoring crea solo
para los de un check (`if (!multiple && !items.length) items.push({_key: null, enabled: false})`).
Confirmado ejecutando la función real en el navegador con el estado que produce un modal, sin
tocar el flujo completo: devolvía `['cpu']` para un módulo que el test nunca activó.

**Causa raíz** — dos hechos inofensivos por separado. `_applyHostChecks` reservaba la entrada
del módulo **antes** de decidir si había algo que escribir:

```js
modulesData[mk] = modulesData[mk] || {};          // ← reserva
modulesData[mk][coll] = modulesData[mk][coll] || {};
...
if (!it._key && !it.enabled) continue;            // ← y solo aquí descarta el hueco vacío
```

…y un módulo que se queda como `{}` **cuenta como activado**: `schemas.py` declara
`'enabled': {'default': True}`, así que la ausencia de la clave no significa «apagado» sino lo
contrario. Guardar el único check real ponía `changed = true` y el `PUT /api/v1/modules` enviaba
el objeto entero, persistiendo de paso las entradas vacías de los demás.

**Solución** — creación perezosa: `col` empieza en `null` y la entrada del módulo se materializa
en la primera escritura de verdad (`_col()`), ya pasado el `continue`. El bucle de borrado
comprueba `col` porque ahora puede no existir. Fijado con un test de navegador que alimenta la
función con el estado de un modal real y exige que un módulo intacto no aparezca — con control
positivo, para que no se pueda satisfacer no escribiendo nada.

**Lección** — cuando la ausencia de un valor significa «activado», crear un contenedor vacío
**es** una decisión del usuario aunque no lo parezca. Reservar estructura «por si acaso» es
gratis solo cuando el vacío y el no-existir significan lo mismo; aquí no lo significaban. Y el
patrón «guardar una parte reenvía el objeto entero» convierte cualquier resto en memoria en un
cambio persistido: si el envío es total, la construcción tiene que ser exacta.

---

## Clonar un elemento lo guardaba y decía que había fallado — y el fallo no dejaba rastro

**Fecha:** 2026-08-01 · **Área:** `lib/core/modules/routes.py` (`api_save_modules`),
`partials/actions/_field_ops.html` (`cloneItem`), `lib/web_admin/mixins/hooks.py`
(`_hook_unhandled_error`), `partials/core/_api.html`

### Síntoma

En el módulo m365 (cierto en todos): crear un elemento guarda bien. **Clonarlo**, cambiarle el
nombre y guardar → el registro **se guarda**, pero sale «Error al guardar», el botón Guardar
sigue marcando cambios pendientes, y en auditoría no aparece ni el guardado ni el error.

### Diagnóstico

Los tres síntomas juntos acotan el punto exacto: si el registro está escrito y la auditoría
vacía, el fallo ocurre **entre** la escritura y la línea de auditoría — dos sentencias.

Reproducido contra el endpoint real (no la UI) enviando lo que manda el navegador al clonar:
copia profunda del elemento, clave nueva en el diccionario, **mismo `uid` dentro**.

```text
lib/core/modules/routes.py:119: in api_save_modules
    changes = (changes or '') + f'\nduplicate item uid(s): {", ".join(dup_uids)}'
E   TypeError: can only concatenate list (not "str") to list
```

### Causa raíz

Dos defectos alineados:

1. **[`_field_ops.html` → `cloneItem`](../src/lib/web_admin/templates/partials/actions/_field_ops.html)**
   copiaba el elemento con `JSON.parse(JSON.stringify(...))`, **incluido su `uid`**. Un uid es
   identidad, no dato; el servidor solo genera uno cuando falta
   ([`items.py` → `ensure_item_uids`](../src/lib/core/modules/items.py)), así que la copia
   llegaba diciendo ser el original. El re-keying lo repara dándole un uid nuevo, pero
   `duplicate_item_uids` lo registra — correctamente: **había** llegado un duplicado.
2. **[`routes.py:119`](../src/lib/core/modules/routes.py)** anotaba ese duplicado con `+` sobre
   el resultado de `_diff_dicts`, que devuelve `list[dict]`, no `str`. `TypeError` **después**
   de que `_save_modules` hubiera confirmado y **antes** de `wa._audit(...)`.

Nada del camino de error hablaba, y ese es el defecto de fondo:

- no había ningún `errorhandler` registrado → Flask respondía con su 500 HTML;
- `after_request` **no** corre cuando una excepción sale del handler, así que la línea de traza
  por endpoint (`_hook_trace_end`, que registra todo 4xx/5xx con su motivo) tampoco saltaba;
- la traza iba al logger de Flask, que el panel **no** engancha a su salida de debug ni a su
  fichero de log → bajo servicio o contenedor, a ningún sitio donde alguien mire;
- en el cliente, [`apiPut`](../src/lib/web_admin/templates/partials/core/_api.html) hacía
  `await r.json()` a pelo: el cuerpo HTML lanzaba en el parseo y caía en el **mismo** `catch`
  que una conexión caída, devolviendo el mismo `null`. `saveModules` imprime `r?.error ||
  t('save_error')` → «Error al guardar», sobre un valor que ya no tenía ni status ni cuerpo.

### Solución

1. `cloneItem` limpia el uid con `_stripItemUids(...)`, recursivo (un elemento puede contener su
   propia colección de elementos, como los `checks` por servidor de snmp, también keyed por uid).
   Borrado por **nombre exacto**: `cred_uid` y `host_uid` son *referencias*, y el clon debe
   seguir apuntando a la misma credencial y al mismo host.
2. La nota del duplicado pasa a ser una **fila más** de la lista de cambios
   (`{field, old, new}`), que es lo que la UI de auditoría pinta como tabla.
3. `_HooksMixin._hook_unhandled_error` (registrado en `_register_request_hooks`): devuelve las
   `HTTPException` intactas (un 404 o un 403 son *respuestas*, no fallos), y para lo demás
   genera **una referencia corta que aparece en tres sitios a la vez** — la línea de log, la
   entrada de auditoría `internal_error` (ruta, método, endpoint, tipo y mensaje) y el mensaje
   en pantalla. Bajo pytest/debug **sigue relanzando**, reproduciendo el `PROPAGATE_EXCEPTIONS`
   de Flask: registrar un handler para `Exception` tiene precedencia sobre él, y no
   reproducirlo habría convertido cada crash de la suite en un 500 educado.
4. `_readJson(r, method, url)` en `_api.html`: `apiPut`/`apiPost`/`apiDelete` ya no parsean a
   pelo. Un cuerpo no-JSON produce `{error: "HTTP 500: …"}` en vez de borrar la respuesta
   entera, y cada fallo escribe una línea en consola.

La traza **nunca** viaja en la respuesta: una página de error no es donde se publican los
internos a quien alcance la URL, y la referencia es lo que hace que no haga falta.

### Lección

**Un fallo silencioso no es uno: son dos.** El defecto y la ausencia de rastro se arreglan por
separado, y el segundo es el caro — porque hace que el primero solo se pueda diagnosticar
reproduciéndolo.

Tres patrones concretos:

- **Un `TypeError` colocado entre «ya escrito» y «aún sin registrar» produce el peor estado
  posible**: el usuario ve fallo sobre algo que sí ocurrió, y su reacción natural (guardar otra
  vez, o deshacer) actúa sobre una premisa falsa. Cuando una operación tiene efecto y luego
  registra, todo lo que va entre medias debe ser trivialmente incapaz de lanzar.
- **Un `catch` que cubre dos causas distintas las vuelve indistinguibles.** Parsear un cuerpo
  dentro del mismo `try` que la petición hace que un error del servidor y una red caída
  devuelvan lo mismo. Sepáralos, aunque el resultado sea el mismo valor.
- **Copiar un objeto no es clonar una entidad.** Toda copia profunda de algo que tiene identidad
  debe decidir explícitamente qué campos son *identidad* (se descartan) y cuáles son
  *referencias* (se conservan). Un `JSON.parse(JSON.stringify(x))` no decide nada.

---

## Un test que solo podía fallar en la máquina de otro

**Fecha:** 2026-07-28 · **Área:** `tests/unit/test_wa_favicon.py`
(`TestTheBinaryIsReproducible`), `tools/make_favicon.py`

**Síntoma** — GitHub Actions en rojo con
`the icon and tools/make_favicon.py have diverged`, y un diff binario enorme en el que solo
difería el PNG de 48 px: los de 16 y 32 eran idénticos, y el IDAT de 48 medía **exactamente lo
mismo** (384 bytes) en ambos lados. En local, los 10 tests del favicon en verde. Siempre.

**Diagnóstico** — la primera trampa fue el signo del diff. Pytest pinta `-` para el operando
**derecho** y `+` para el **izquierdo**, al revés de lo que sugiere la intuición, así que la
lectura ingenua atribuía cada mitad al lado contrario. Se resolvió empíricamente, con un test
de dos líneas que compara `b'IZQUIERDA'` con `b'DERECHA'` y mira qué signo le toca a cada uno.
Con los lados bien asignados: el fichero commiteado coincide byte a byte con el mío, y lo que
difiere es lo que **CI genera**.

**Causa raíz** — `build_ico()` termina en `zlib.compress(raw, 9)`, y `zlib.compress` **no es
una función estable entre implementaciones**. Este Python trae `zlib-ng` (`zlib.ZLIB_VERSION`
lo dice: `1.3.1.zlib-ng`); el runner trae zlib estándar. Para las mismas scanlines emiten
DEFLATE distintos, ambos válidos y aquí incluso de la misma longitud. Solo divergió el de 48 px
porque es el único con entropía suficiente para que las dos elijan distinto.

Y de ahí lo que hace este caso interesante: **el test comparaba el artefacto commiteado con el
resultado de regenerarlo en la máquina que lo ejecuta**. El icono se generó aquí, así que aquí
la igualdad es cierta *por construcción*. No es que se escapara entre 4000 tests: es que era
**imposible** que fallara en esta máquina, y seguro que fallara en cualquier otra. Estaba roto
desde el commit que añadió el icono.

**Solución** — comparar imágenes, no bytes: `_ico_images()` recorre el directorio del `.ico`,
saca el IHDR y **descomprime** el IDAT de cada PNG, y el test compara geometría y píxeles.
Verificado en las dos direcciones: forzando otra compresión (nivel 1) los bytes difieren y el
test pasa —que reproduce el fallo de CI en local—, y cambiando el color del escudo en el
generador falla nombrando los píxeles.

**Lección** — **un test que regenera un artefacto y lo compara con el commiteado solo vale si
la generación es determinista entre entornos**, y la compresión no lo es. Pinear la salida de
un compresor convierte una diferencia que no es diferencia en un rojo que nadie puede arreglar.
Corolario más general y más útil: **desconfía del test que no puede fallar donde lo escribes**.
Si su resultado depende de que la máquina sea la que fabricó el dato, el verde local no
significa nada — y el único sitio donde da información es aquel al que no estás mirando.

---

## Un escáner que se mudó un directorio y devolvió un catálogo vacío, sin quejarse

**Fecha:** 2026-07-28 · **Área:** `lib/modules/discovery/schemas.py` (`discover_schemas`)

**Síntoma** — al sacar `discover_schemas` de `module_base.py` a su paquete, media docena de
tests de esquema empezaron a fallar con `KeyError: 'ping|list'`, `'raid|list'`,
`'service_status|list'`… lejos de la causa. En la UI habría sido peor: los módulos aparecerían
sin ningún campo, sin ningún error.

**Diagnóstico** — el `KeyError` decía qué faltaba, no por qué. La función resuelve su
directorio por defecto **contando `..` desde su propio fichero**: desde `lib/modules/` la
cuenta `../../watchfuls` daba `src/watchfuls`; desde `lib/modules/discovery/` da
`lib/watchfuls`, que no existe.

**Causa raíz** — y aquí está lo que importa: `discover_schemas` comprueba
`if not os.path.isdir(watchfuls_dir): return schemas`, o sea **devuelve un diccionario vacío**.
Un directorio ausente no es un error para ella, es un resultado. Así que la mudanza no rompió
nada de forma visible: dejó de encontrar los módulos.

**Solución** — la ruta **ya no se cuenta**: `_find_watchfuls_dir()` sube desde el fichero
hasta el primer ancestro que contenga a la vez `lib/` y `watchfuls/`, así que sobrevive a que
este fichero se mueva a cualquier sitio dentro de `lib/` —que es justo lo que lo rompió—. Hay
un bloque de comentario en su definición explicando por qué, y `TestTheDefaultPathStillFindsTheModules` (3 tests): el catálogo no está vacío, contiene todos los módulos descubiertos, y la
ruta derivada da **lo mismo** que pasar el directorio a mano —esto último porque una derivación
equivocada puede apuntar a otro sitio que sí exista—. Comprobado además copiando el fichero un
nivel arriba: la búsqueda sigue acertando.

**Lección** — **una ruta relativa a `__file__` es una dependencia oculta con la posición del
fichero**, y mover el fichero es justo lo que uno hace al reorganizar. El agravante no es la
cuenta, es que el fallo sea *mudo*: cuando «no encontrado» se traduce a «vacío» en vez de a un
error, el defecto viaja hasta donde alguien intenta usar el resultado y allí se manifiesta como
otra cosa. Si una función deriva una ruta, la prueba que hay que escribir no es la de la
función con la ruta dada —esa seguirá pasando— sino la de la función **sin argumentos**.

## La misma comprobación salía ámbar o roja según quién la ejecutara

**Fecha:** 2026-07-28 · **Área:** `lib/core/hosts/probe.py` (`run_module_check`) · afectaba
a toda ejecución bajo demanda: refresco en vivo de páginas de módulo (`run_item_once`) y
"probar" una credencial/host desde Servers

**Síntoma** — en la página de Microsoft 365, *Unused licences* aparecía **entera en rojo**:
insignia de sección, icono de la fila y anillo de uso, los tres. La comprobación emite
`severity='warning'` y el resultado guardado por el monitor sí se pintaba ámbar. Reportado
como «esta todo rojo, si es warning deberia ser amarillo».

**Diagnóstico** — una traza del camino cacheado (`page_data` → `_page_sections`) daba
`section: unused -> warn` y `row -> warn`, o sea el dato de origen era correcto. Eso dejaba
una sola ruta sin verificar: la **mitad en vivo**. `page_refresh` no lee el estado guardado,
llama a `run_item_once` → `run_module_check`, y ahí la lista de resultados no es la del
módulo: se **reconstruye campo a campo**.

**Causa raíz** — esa proyección era una lista blanca de cuatro claves (`key`, `status`,
`message`, `other_data`) y `severity` no estaba en ella. Como `_page_sections` solo asigna
`warn` cuando ve `severity == 'warning'`, cualquier fila no-OK llegada por refresco en vivo
caía en la rama `error`. No era un fallo de M365: afectaba a cualquier módulo con umbrales
blandos, y el comentario de `page_refresh` ya *prometía* `{status, severity, message,
other_data}` — describía la forma que hacía falta, no la que llegaba.

**Solución** — `severity` entra en la proyección, vacío cuando no lo hay: la ausencia tiene
que seguir siendo una ausencia porque es lo que significa «esto sí es un error». Y como la
decisión no era de hosts, el runner (`ProbeMonitor` + `run_module_check`) se mudó a
[`lib/modules/check_runner.py`](../src/lib/modules/check_runner.py), junto a su consumidor
natural; en `probe.py` se queda `ProbeHostsStore`, que sí es de hosts, **sin re-exportar** el
runner: un import de conveniencia lo dejaría pareciendo código de hosts y el siguiente lo
volvería a buscar ahí. La lista blanca dejó de ser una lista a mano: `RESULT_FIELDS` se
compara contra lo que escribe `ReturnModuleCheck.set()` y un campo nuevo del contrato tiene
que estar proyectado o excluido a propósito. Fijado por `tests/unit/test_module_check_runner.py`
(11 tests), verificado fallando sin el arreglo.

**Lección** — **una proyección con lista blanca de campos caduca en silencio.** Copiar un
resultado clave a clave congela el esquema del día en que se escribió: cuando el emisor gana
un campo, el consumidor no falla, *pierde información* — y pierde justo la que distingue dos
estados, no la que salta a la vista. Se defiende derivando la lista del contrato en vez de
mantenerla a mano. Segunda lección, la que explica por qué nadie miró ahí: **el código
genérico que vive dentro de un dominio no se busca donde está.** Esta decisión era sobre el
contrato de resultado de un módulo y estaba en un fichero de hosts, así que quien añadió
`severity` a `_emit` revisó `module_base` y el monitor, que es exactamente donde uno mira. La
entrada [Un aviso de umbral llegaba como caída
dura](#un-aviso-de-umbral-llegaba-como-caída-dura-y-el-panel-lo-pintaba-ámbar) es el mismo
defecto por el otro extremo: allí el dato viajaba dos veces y una copia se olvidó de él;
aquí viaja por dos caminos y uno lo filtra. Corolario práctico: cuando dos vistas del mismo
hecho se contradicen, el sospechoso no es el hecho sino el camino menos recorrido — y la
prueba que lo cierra es la que afirma que el campo **existe** incluso cuando está vacío.

---

## Permitir el iframe de Teams dejaba a todo el mundo fuera del panel

**Fecha:** 2026-07-27 · **Área:** `lib/web_admin/app.py` (`_apply_embed_cookie_policy`,
`_enforce_fqdn`)

**Síntoma** — entrando por `http://192.168.0.1:8080`, el navegador mostraba «La página no está
redirigiendo adecuadamente» (`ERR_TOO_MANY_REDIRECTS`) en `/login`. El login **funcionaba**:
credenciales correctas, sin mensaje de error, sesión creada.

**Diagnóstico** — la primera hipótesis fue el ajuste que redirige al dominio
(`force_fqdn`), pero el usuario confirmó que estaba **apagado**, y ese guardián sale en su
primera línea. Descartado eso, el bucle solo puede venir de una sesión que no persiste: si la
cookie no llega de vuelta, la página siguiente ve un anónimo y devuelve a `/login`, que vuelve
a autenticar correctamente, y así indefinidamente. Un bucle de login **con credenciales
válidas** es siempre la cookie, no la autenticación.

**Causa raíz** — tres ajustes marcan la cookie de sesión como `Secure`, y un navegador
descarta una cookie `Secure` sobre `http://`. Dos son explícitos y legítimos (`secure_cookies`,
`force_https`); el tercero no: `_apply_embed_cookie_policy` la marcaba **sin condiciones** en
cuanto había cualquier origen permitido en frame-ancestors, y activar «embed in Teams» basta
para eso. Lo llamativo es que el mismo fichero razona correctamente el caso análogo treinta
líneas más arriba, para `public_url`, y anota que forzar `Secure` desde ahí «rompería el login
en silencio sobre HTTP plano». Y el trato nunca compensaba: un iframe cross-site necesita
`SameSite=None`, los navegadores rechazan `SameSite=None` sin `Secure` y rechazan `Secure`
sobre HTTP — así que en un despliegue http:// la política tampoco habilitaba el embed.

**Solución** — la política del embed se condiciona a una intención explícita de HTTPS
(`secure_cookies` o `force_https`) y avisa por log cuando se permite un origen sin ella, en vez
de no hacer nada. De paso se arregló `force_fqdn`, que comparaba `request.host` —que lleva el
puerto— contra una URL pública que puede no llevarlo: `192.168.0.1:8080` se leía como host
distinto de `192.168.0.1` y redirigía al puerto 80. Ahora una URL pública sin puerto acepta
cualquier puerto, con puerto lo exige, la comparación ignora mayúsculas y nunca se redirige a
la propia petición que se está contestando. Cubierto por `tests/integration/test_wa_cookie_lockout.py`,
verificado fallando contra el código original.

**Lección** — **un ajuste de seguridad que no puede aplicarse no debe aplicarse a medias.** Los
dos defectos tienen la misma forma: el endurecimiento era imposible en ese despliegue (cookie
Secure sin HTTPS, redirección a sí misma) y aun así se aplicó la mitad que rompe. No redirigir,
o dejar la cookie usable, es siempre preferible: el peor caso es que el endurecimiento no se
aplique, que es exactamente donde ya estabas — mientras que el bloqueo se lleva por delante la
página desde la que se desactiva.

Corolario operativo: cuando un ajuste puede dejar el panel inalcanzable, conviene que tenga
salida por variable de entorno. `secure_cookies` y `force_https` la tienen
(`SS_SECURE_COOKIES`, `SS_FORCE_HTTPS`); `embed_in_teams` y `frame_ancestors` no, y por eso
este bug solo se podía deshacer tocando la BD.

---

## Guardar decía que sí y el mapeo Grupo→Rol nuevo no aparecía

**Fecha:** 2026-07-27 · **Área:** web-admin / Configuration › Authentication
(`partials/cfg/auth/_group_role_map.html`)

**Síntoma** — añadir una fila «Group → Role mapping» en SSO (OIDC), pulsar Guardar y
recargar dejaba el mapeo nuevo sin rastro. El toast decía que se había guardado
correctamente. Cambiar el *Role* de un mapeo **ya existente** se guardaba siempre.

**Diagnóstico** — esa asimetría era todo. Las dos mitades de la misma fila pasan por
handlers distintos: el `<select>` de Role llama a `_grmUpdate` directamente —síncrono— y el
`<input>` del id de grupo llamaba a `_grmRowIdChanged`, que en una sección con fuente de
grupos (oidc, saml2 y ldap declaran una) **esperaba antes una búsqueda de nombre en el
directorio**. Lo que confirma el diagnóstico es *cuándo* corre ese handler: en `change`, que
dispara cuando el botón Guardar toma el foco. El clic caía con la búsqueda en vuelo.

**Causa raíz** — `saveConfig` envía únicamente `_dirtyFields`. Con el mapeo aún sin apuntar,
mandaba todos los campos sucios **menos ése**, y el servidor contestaba éxito con toda la
razón: el payload que recibió se guardó entero. El mapeo se apuntaba un instante después, ya
sin nadie que lo guardara. Ningún error en ningún lado, en ninguna de las dos partes.

**Solución** — apuntar el mapeo antes de que el handler pueda bifurcarse, y apuntar en
`oninput` (cada pulsación) en vez de solo en `change`. La búsqueda de nombre sigue esperando,
pero solo decora la columna de nombre, que es otro campo. Cubierto por
`tests/meta/test_cfg_group_role_map.py`.

**Segunda mitad — el botón se quedaba encendido después de guardar bien.** Con el mapeo ya
persistiendo, *Save Configuration* volvía a marcarse como «cambios pendientes» justo tras el
mensaje de éxito. F5 mostraba el valor guardado, y volver a pulsar Guardar era lo que lo
callaba. Mismo widget, dirección contraria: `markDirty` decide el estado del botón comparando
`configData` con `_serverConfigData` —la foto de lo que tiene el servidor—, y este widget
guarda un campo **por su cuenta** (`group_display_names`, nombres que resuelve él y que el
usuario nunca tecleó). Ese guardado fuera de banda borraba la ruta de `_dirtyFields` pero no
movía la foto: las dos discrepaban ya para siempre y el botón se lo creía. La secuencia
completa es que la búsqueda de nombre termina **después** del guardado, apunta el nombre
recién resuelto, lo persiste ella sola y deja la foto atrasada. Arreglado con un único
`applySavedField` —token de versión, conjunto sucio y foto se mueven juntos, porque describen
el mismo hecho— y, sobre todo, sacando los nombres de la maquinaria de «cambios sin guardar»:
se escriben directamente en `configData` y se persisten al momento, así que la vía automática
ya no puede encender el botón pase lo que pase con el orden. Solo reconciliar la cola no
bastaba: mientras el guardado automático llegara a completarse funcionaba, pero cualquier
camino que apuntase algo después del guardado volvía a encenderlo.

**Lección** — tres, y las dos últimas son sobre el propio guard. La primera: **un handler `change`
que espera algo compite con el clic que lo disparó**; si además el guardado manda solo lo
sucio, la carrera se convierte en un éxito que miente. Lo que se persiste tiene que quedar
apuntado antes del primer `await`, y lo que hay en pantalla tiene que estar siempre en la
cola (`oninput`, no `change`).

La segunda: **un dato que describe un solo hecho no se puede escribir a trozos.** «El
servidor ya tiene esto» son tres cosas —token de versión, campo fuera de la cola, foto del
estado guardado— y cualquier camino que actualice dos de las tres deja la interfaz
contradiciendo al servidor. Estaban embebidas dentro de `saveConfig`, así que el segundo sitio
que necesitó guardar un campo no tenía nada que reutilizar y se dejó una.

La tercera: el primer test que escribí para esto **pasaba con el código roto**. Comprobaba
que el apuntado apareciera antes del primer `await` — y así era, dentro de un `if` que
retorna, en un camino que el usuario no recorre. La invariante real no es «antes del primer
await» sino «antes de cualquier bifurcación». Un guard de regresión hay que verlo fallar
contra el código original (`git show HEAD:...`) antes de creérselo.

---

## Un aviso de umbral llegaba como caída dura, y el panel lo pintaba ámbar

**Fecha:** 2026-07-26 · **Área:** `lib/modules/module_base.py` (`_emit`), monitor
(`_alert_kind`) · afectaba a `azure`, `m365`, `keepalived`, `proxmox`

**Síntoma** — una VM apagada, una cuota rozando el límite o un secreto por caducar salían
**ámbar** en el panel, pero la notificación llegaba como **caída** (`down`), con el tono y
el enrutado de un servicio muerto. Nadie lo reportó como bug: cada mitad, por separado,
parecía correcta.

**Diagnóstico** — apareció comparando módulos al unificar el emparejamiento
`registrar + notificar`. `ntp` pasaba `severity` **a las dos** llamadas; `_emit` solo a
una. La pregunta siguiente fue si eso importaba, porque el monitor también sabe leer la
severidad del resultado guardado (`_process_module_result` → `_alert_kind(tmp_status,
tmp_severity)`). Y sí importaba: esa ruta está condicionada a `if tmp_send`, y `_emit`
registra con `send_msg=False`.

**Causa raíz** — `_emit` pasaba `severity` a `dict_return.set(...)` (de ahí el ámbar del
panel) pero **no** a `send_message(...)`. Como su propio `send_msg=False` apaga la ruta
automática del monitor, ese envío explícito era la **única** notificación, y sin severidad
`_alert_kind(False, '')` devuelve `down`. El defecto vivía copiado **byte a byte en cuatro
módulos**, porque cada uno tenía su propia copia de `_emit`.

**Solución** — `_emit` subió a `ModuleBase` (una sola copia) pasando la severidad a las
dos salidas. Cubierto por `TestModuleBaseEmitCarriesSeverity`, verificado fallando sin el
arreglo.

**Lección** — **un dato que viaja dos veces se desincroniza.** El patrón alternativo
(registrar y dejar notificar al monitor, que lee la severidad del resultado) hace este
fallo *estructuralmente imposible*, y por eso es ahora el predeterminado — ver
[ref-watchful-emit.md](ref-watchful-emit.md). Corolario: un emparejamiento duplicado en N
sitios se equivoca en N sitios.

---

## Un mock hace pasar un test aunque el token se pida para la audiencia equivocada

**Fecha:** 2026-07-26 · **Área:** `watchfuls/azure`, `lib/providers/entraid/graph_api.py`

**Síntoma** — ninguno todavía: se detectó **antes** de llegar a producción, y ese es el
punto. Al unificar el transporte de `m365` y `azure`, el helper compartido `_get_token`
quedó con `scope=GRAPH_SCOPE` por defecto. Azure necesita la audiencia **ARM**.

**Diagnóstico** — la suite entera seguía en verde. El motivo es que **todos** los tests de
azure mockean `_get_token`, y un mock devuelve un token pidas el scope que pidas. Ningún
test de comportamiento podía distinguir un token ARM de uno de Graph.

**Causa raíz** — un valor por defecto correcto para un módulo (Graph) e incorrecto para el
otro (ARM), en un helper que ahora comparten. ARM rechaza un token de Graph: cada
comprobación habría devuelto 403.

**Solución** — `scope=ARM_SCOPE` explícito en las dos llamadas de azure (el bucle del
monitor y el picker de regiones), y una clase `TestTokenAudience` que afirma **qué scope
se pidió**, no qué devolvió el mock. Se verificó quitando el `scope=` : el test falla.

**Lección** — cuando un mock sustituye a la frontera exacta donde vive el bug, la
cobertura verde no significa nada. Si un parámetro decide *contra qué sistema* hablas,
el test tiene que afirmar **ese parámetro**. Aplica igual a URLs base, versiones de API y
audiencias de token.

---

## La alerta nombraba el host enlazado en vez del check que falló

**Fecha:** 2026-07-26 · **Área:** 11 watchfuls (ramas de error), monitor (`_item_label`)

**Síntoma** — un check DNS llamado `A example.com` aparecía en la columna *Item* del
digest como `ns1` (el host al que está enlazado) — pero **solo** cuando fallaba por
excepción. Fallando de forma normal salía con su nombre correcto.

**Diagnóstico** — apareció auditando por AST quién usa cada patrón de publicación. Nueve
módulos usan `_emit` en el camino normal y `dict_return.set(...)` automático en sus ramas
de excepción. Esas ramas **calculaban** la etiqueta para el texto del mensaje pero no la
pasaban a `set(...)`.

**Causa raíz** — sin `name=`, el monitor cae a `_item_label()`, que resuelve el
`host_uid` al nombre del host. Dos módulos parecían correctos a simple vista porque
ponían el nombre en `other_data={'name': …}` — que `get_name()` **no lee**, porque mira el
campo de nivel superior. Y `proxmox` tenía una variante peor: suprimía la notificación del
monitor (`send_msg=False`) **y** no enviaba ninguna a mano, así que una excepción no
controlada ponía el check en rojo sin avisar a nadie.

**Solución** — `name=` en los 11 sitios, y `tests/meta/test_watchful_emit_patterns.py` lo
vigila (incluido el caso `other_data['name']`, que parece bien y no lo está).

**Lección** — las **ramas de error** son las que menos se prueban y las que más importan
en una notificación. Cuando un valor tiene dos sitios donde ponerse y solo uno funciona,
no basta con documentarlo: hay que hacer que el equivocado falle el build.

---

## Tras visitar Historial, las demás secciones aparecen al fondo de una página kilométrica

**Fecha:** 2026-07-25 · **Área:** web-admin / frontend (`static/css/web_admin.css`,
`templates/dashboard.html`)

**Síntoma** — recargando con F5 sobre `/syslog` la sección se veía bien, pero si se
navegaba a Historial y luego se volvía, Syslog (y también Servidores, Clusters y
Servicios) aparecía **al final de una página con scroll enorme**, precedida de una franja
vacía de miles de píxeles, y la barra lateral —que es `sticky` dentro de un shell de
`100vh`— se quedaba anclada arriba en vez de acompañar al contenido.

**Diagnóstico** — la pista decisiva la dio el propio patrón: *F5 bien, tras pasar por
Historial mal*. Eso descarta la sección afectada (su cadena `.ss-vfill`/`.ss-vscroll`
estaba intacta) y apunta a algo que Historial deja atrás. Revisando las reglas de panel
en el CSS: `#tab-history { display: flex; … }`.

**Causa raíz** — un selector **por id** tiene especificidad 1-0-0 y gana a la regla de
Bootstrap `.tab-content > .tab-pane { display: none }` (0-2-0). El panel de Historial
quedaba por tanto **siempre renderizado**, debajo de la sección activa. Recién cargada la
página aún estaba vacío (sólo el spinner) y no se notaba; tras visitarlo una vez pasaba a
contener la gráfica y la lista de series, y empujaba todo lo demás fuera del viewport.

**Solución** — acotar la regla de layout al estado activo (`#tab-history.active`) y dejar
los márgenes full-bleed sin cualificar (son inocuos con el panel oculto). Además `.ss-main`
pasó a hacer scroll de su propio desbordamiento, para que ningún contenido alto vuelva a
hacer scroll del documento entero y despegue la barra lateral. Test de regresión en
`tests/unit/test_wa_ui.py::TestPaneDisplayRules`, que recorre el CSS y falla ante cualquier
`#tab-*` sin cualificar que fije `display`.

**Lección** — en un SPA donde Bootstrap decide la visibilidad por clase, **cualquier regla
por id que toque `display` secuestra el mecanismo**. Las reglas de layout de un panel se
cualifican con `.active`, o mejor se escriben con clases. Un corolario: si el fallo depende
de *qué visitaste antes* y no de la sección que falla, el culpable es un estado global que
la sección anterior deja atrás — no la que se ve mal.

## Las páginas independientes se quedan en el spinner; y el navegador pide confirmación al salir

**Fecha:** 2026-07-22 · **Área:** web-admin / frontend (`partials/init/_wiring.html`,
`partials/actions/_dirty.html`)

**Síntoma** — dos fallos tras sacar Historial y Syslog del panel a páginas propias:
(1) `/overview`, `/history` y `/syslog` cargaban pero **nunca pintaban nada**, con el
spinner girando indefinidamente, mientras `/admin` funcionaba perfectamente;
(2) ya arreglado lo anterior, **cada** navegación entre secciones abría el diálogo del
navegador *"Esta página le pide que confirme que desea salir…"*, sin haber tocado nada.

**Diagnóstico** — el HTML servido era correcto (los tests de plantilla pasaban) y el JS
era sintácticamente válido: extraído del `<script>` y pasado por `node --check` (bajando
`?.`/`??`, que Node 12 no parsea) no daba error. Eso descartó el error de parseo y dejó
como única explicación un **throw en tiempo de ejecución**. La consola del navegador lo
confirmó: `Uncaught TypeError: can't access property "addEventListener",
document.getElementById(...) is null`. Para el segundo, `_isDirty()` era el único camino
al `beforeunload`, y en `/syslog` ni siquiera se renderiza Config — luego no podía haber
cambios reales.

**Causa raíz** — el mismo tema de fondo, dos formas:

1. `_wiring.html:29,33` accedía a `document.getElementById('btn-tab-status')` **sin `?.`**
   (las otras 10 referencias a `btn-tab-*` sí lo usaban). Al dejar de renderizarse la barra
   de pestañas, ese acceso lanza **fuera del `try/catch` del init**, a nivel superior, y
   aborta **el script entero** antes de ejecutar ningún render.
2. `_isDirty()` hacía `return !document.getElementById(id)?.classList.contains('d-none')`.
   Si el elemento **no existe**, el optional chaining devuelve `undefined` y `!undefined`
   es **`true`** → "hay cambios sin guardar". Los badges viven en los paneles Modules y
   Config, ausentes en una página independiente: estado sucio permanente.

**Solución** — (1) `?.` en las dos referencias, más un test estático
(`TestNoUnguardedPanelElementAccess`) que falla ante cualquier acceso sin guarda a un
elemento exclusivo del panel; verificado reintroduciendo el bug. (2) `_isDirty()` resuelve
el elemento primero y trata su ausencia como *limpio*. Además, salir del panel con cambios
**reales** ahora se intercepta (`a[data-nav-section]`) y reutiliza el modal in-app
Cancelar/Descartar/**Guardar** — el diálogo del navegador no puede ofrecer Guardar.

**Por qué los tests no lo cogieron** — todos comprobaban el **HTML servido**, y el HTML
era correcto: el fallo ocurría en el navegador, al ejecutarlo. Ninguna aserción sobre la
respuesta puede ver eso.

**Lección** — al **dejar de renderizar** parte del DOM, el riesgo no está en lo que se
quita sino en el código que **daba por hecho** que estaba ahí; hay que barrer los accesos
a esos elementos, no solo la plantilla. Y `!expr?.prop` es una trampa: invierte el
significado cuando `expr` es nulo, devolviendo `true` justo en el caso "no hay nada". Si
la ausencia debe leerse como *falso*, resuelve el elemento y compruébalo explícitamente
(`!!el && …`).

**Coda: dos spinners a la vez** — ya funcionando, la carga mostraba **dos** indicadores
superpuestos. Costó tres intentos porque los dos primeros dieron por hecho que el segundo
spinner lo pintaba el JS:

1. *Esperar el render* (`await _fn()`) para que el overlay cayera con contenido ya listo:
   **empeoró** el solapamiento, alargando justo la ventana en que ambos convivían.
2. *Retirar el overlay justo antes del render*: tampoco cambió nada.
3. Mirar el **HTML servido** en vez del JS. Ahí estaba: cada `tab-pane` lleva su propio
   placeholder con spinner **en el marcado**, y en una página independiente ese panel nace
   `show active` → visible desde el primer frame, debajo del overlay. Ningún cambio de
   orden en el script podía afectarlo, porque no lo pintaba el script.

Además, un cuarto intento erróneo: eliminar el overlay en estas páginas "para dejar un solo
spinner". `#loading` **no es un spinner**, es la capa que oscurece la página y **bloquea la
interacción** con los menús mientras arranca; quitarla cambiaba un defecto cosmético por
uno funcional. La solución final conserva el overlay en todas las páginas, **no emite** el
placeholder del panel cuando ese panel es la página, y pasa el testigo al esqueleto de la
sección justo al arrancar el render.

**Lección** — cuando algo "no reacciona" a cambios en el código que crees responsable, el
responsable es otro: mira el **artefacto entregado** (el HTML servido), no solo la lógica.
Y antes de eliminar un elemento que estorba, pregunta **qué más hace**: aquí el overlay
parecía decorativo y era el bloqueo de interacción.

---

## `GET /` con sesión rompe con `ImportError: cannot import name '_landing_url'`

**Fecha:** 2026-07-22 · **Área:** web-admin / rutas (`routes/pages.py`)

**Síntoma** — con la sesión iniciada, entrar en la raíz `/` devolvía un 500 con
`ImportError: cannot import name '_landing_url' from 'lib.web_admin.routes.auth'`.
Anónimo funcionaba bien (redirigía a `/login`), y `/admin` también: solo fallaba `/`
estando autenticado.

**Diagnóstico** — el traceback señalaba directamente `pages.py::_root`. Un `grep` de
`_landing_url` mostró que **todos** los demás llamantes (`routes/auth.py`,
`providers/oidc`, `providers/saml`, `entraid/sso_routes`) lo invocan como
**método** (`wa._landing_url(user)`), y que está definido en
`lib/web_admin/mixins/auth.py:177`. Solo `pages.py` conservaba la forma antigua
(función de módulo importada de `routes/auth.py` y llamada con `wa` como primer
argumento).

**Causa raíz** — regresión del refactor de auth (ruta `/login` fina + resolver sin
Flask): `_landing_url` se movió de `routes/auth.py` al `_AuthMixin`, pero el
`import` diferido dentro de `_root` no se actualizó. Al ser un import **dentro de
la función** (puesto ahí para evitar un ciclo al cargar), no falla al arrancar ni lo
detecta un import-check: solo estalla al ejecutar esa rama.

**Por qué los tests no lo cogieron** — los únicos tests que hacían `GET /` lo hacían
**sin sesión**, y esa rama hace `return redirect(url_for('login'))` *antes* de llegar
al import. La rama autenticada no estaba cubierta.

**Solución** — usar el método del mixin, igual que el resto de llamantes:
`return redirect(wa._landing_url(user))`, eliminando el import diferido. Se corrigió
también el único test que importaba el símbolo antiguo (`test_wa_config.py`) y se
añadió la regresión que faltaba: `test_root_logged_in_redirects_to_landing`
(`tests/integration/test_wa_auth.py`), verificada fallando con el bug y pasando con el fix.

**Lección** — un **import diferido dentro de una función** esquiva tanto el arranque
como cualquier chequeo estático de imports; su única red de seguridad es un test que
ejecute *esa* rama. Al mover un símbolo, `grep` de TODOS los llamantes (no solo los
que el IDE resuelve) y comprobar que cada rama de una ruta —anónima **y**
autenticada— tiene cobertura.

---

## El placeholder heredado (`placeholder_module`) desaparece al expandir un item

**Fecha:** 2026-07-16 · **Área:** web-admin / render de campos (`_field_render.html`)

Los campos numéricos de un item que heredan un valor de nivel de módulo (meta
`placeholder_module`, p.ej. el *Timeout* de un item DNS o el *Max connections* de
un item datastore) deben mostrar ese valor heredado como *placeholder* gris
cuando el item lo deja en blanco. Ver [ref-modulos.md](ref-modulos.md) y
[ref-schema-json.md](ref-schema-json.md) para el significado de `placeholder_module`.

### Síntoma

El item mostraba el campo *Timeout* / *Max connections* completamente vacío, sin
el placeholder gris del valor heredado — mientras que el mismo campo a nivel de
módulo sí mostraba su placeholder (p.ej. `15`, el global `modules|timeout`).
Pulsar el botón *Reload* de la barra de módulos "lo arreglaba" temporalmente.

### Diagnóstico

Se descartaron varias hipótesis en orden hasta dar con la real:

1. **¿Lógica de resolución incorrecta?** Se ejecutó el helper en la consola con
   los datos reales: `_placeholderModuleValue('dns|list|x|timeout','timeout')`
   devolvía `15` correctamente, y `configData.modules` = `{"threads":5,"timeout":15}`
   estaba poblado. La resolución era correcta.
2. **¿Servidor sirviendo plantilla vieja?** Flask no tiene `TEMPLATES_AUTO_RELOAD`
   activado, así que cachea la plantilla compilada; el JS va embebido en ella. Se
   confirmó que tras reiniciar el proceso el HTML servido contenía el código nuevo.
   No era (solo) esto.
3. **El botón *Reload* de la UI no recarga código.** `reloadModules()`
   ([`actions/_save.html`](../src/lib/web_admin/templates/partials/actions/_save.html))
   solo re-descarga el JSON de `/api/v1/modules` y re-renderiza con el JS **ya
   cargado** — no baja plantilla nueva. Que "arreglara" el fallo era la pista clave.
4. **Prueba decisiva.** En carga en frío, sin tocar nada, se listaron todos los
   inputs con `data-placeholder-module` leyendo `getAttribute('placeholder')`:
   **todos tenían `ph:"15"`**. Pero inspeccionando en el panel *Elements* un item
   **expandido**, el mismo input tenía el atributo `placeholder` **vacío**. Esa
   contradicción (render pone el valor → algo lo borra al expandir) señaló al
   culpable: el refresco dinámico que se dispara en `show.bs.collapse`.

### Causa raíz

Había **dos rutas** que fijaban el placeholder, con lógicas divergentes:

- **Render** — `_renderFieldInner` usa el helper unificado `_placeholderModuleValue`
  ([`core/_field_render.html`](../src/lib/web_admin/templates/partials/core/_field_render.html)),
  que hace el cascade correcto: valor de módulo → global *Configuration → Modules*
  → default del schema `__module__`, y **conserva el `0`** como valor real.
- **Refresco dinámico** — `_refreshConditionalFields`, disparado al expandir el
  item (`show.bs.collapse`), conservaba la lógica **vieja y rota**:

  ```js
  const ph = modName ? (modulesData[modName] || {})[modField] : null;
  el.placeholder = (ph != null && ph !== 0) ? String(ph) : '';
  ```

  Solo miraba `modulesData[mod][field]` (sin caer al global ni al default) y
  **suprimía el `0`**. Como el timeout de módulo estaba en blanco (hereda del
  global), `modulesData['dns'].timeout` era `null` → ponía `placeholder=''` y
  **pisaba el `15` que el render acababa de poner correctamente**.

Secuencia: render pinta `placeholder="15"` ✅ → el usuario expande el item →
`show.bs.collapse` → `_refreshConditionalFields` recalcula con la lógica vieja →
`placeholder=""` ❌.

### Solución

Unificar el refresco dinámico para que use el **mismo** helper que el render
([`core/_field_render.html`](../src/lib/web_admin/templates/partials/core/_field_render.html)):

```js
container.querySelectorAll('input[data-placeholder-module]').forEach(el => {
    try {
        const modField = el.dataset.placeholderModule;
        const cfgPath  = el.dataset.cfgPath || '';
        const ph = cfgPath ? _placeholderModuleValue(cfgPath, modField) : null;
        el.placeholder = (ph != null && ph !== '') ? String(ph) : '';
    } catch {}
});
```

Así el placeholder heredado (módulo → global → default) sobrevive a la expansión,
y un `0` real (p.ej. `alert_connections` = "sin límite") se muestra en vez de
suprimirse.

### Lección

**Todo valor derivado que se calcula en el render debe recalcularse con la
*misma* función en cualquier handler que lo refresque en vivo.** Cuando existen
dos rutas (render inicial + refresco por evento) que fijan el mismo atributo,
tienen que compartir el helper de resolución; si divergen, la que corra la última
gana y reintroduce el bug de forma intermitente (aquí, solo al expandir). Extraer
la lógica a una función única (`_placeholderModuleValue`) y llamarla desde ambos
sitios es la defensa.

Corolario de diagnóstico: cuando "recargar datos" (no la página) arregla algo, el
problema casi nunca es el dato ni el servidor, sino **código cliente que
sobre-escribe un estado ya correcto**.
