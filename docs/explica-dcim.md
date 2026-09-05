# Inventario físico (DCIM): empresas, datacenters, salas, racks y cableado

> **Estado: plan.** Nada de esto está construido todavía. Este documento fija el modelo, las
> decisiones que ya están tomadas y el orden en que se va a hacer, para que cada fase entre en
> el panel sin rehacer la anterior. Rama de trabajo: `feat/dcim`.

---

## 1. Qué es esto y por qué no es «un NetBox dentro»

NetBox es un sistema de registro de la **intención**: alguien escribe que el switch está en el
rack R3, en la U 12, y que su puerto `gi1` va al `gi24` de SW01. Es la verdad *declarada*, y se
queda tan al día como la persona que la mantiene.

ServiceSentry ya tiene la otra mitad: el **hecho**. Las sondas SNMP dicen qué puertos están
caídos, LLDP dice quién hay al otro lado de un cable, la tabla de reenvío dice por qué puerto se
ve cada MAC, el SAI dice cuánta potencia está entregando. Es la verdad *medida*, y se queda al
día sola porque nadie la escribe.

**El valor de juntarlas no es tener las dos: es la discrepancia entre ellas.**

| Lo que se declaró | Lo que se midió | Lo que el panel debe decir |
| --- | --- | --- |
| `gi1` de SW02 va al `gi24` de SW01 | LLDP dice que va a PVE03 | Alguien movió un cable y no lo apuntó |
| El rack R3 tiene 14 equipos | 11 contestan, 3 llevan 40 días mudos | Tres equipos que igual ya no están ahí |
| La U 12 la ocupa DB03 | DB03 no responde desde el corte del jueves | Dónde hay que ir a mirar, físicamente |
| La regleta A entrega 1,8 kW | El SAI mide 2,4 kW en esa rama | El inventario de potencia está mal, y eso se paga en un corte |

Eso es lo que ni NetBox solo ni una sonda sola pueden contestar. **Es la columna vertebral del
diseño, no una funcionalidad más**, y encaja con cómo está construido el resto del panel: la
separación entre *lo que alguien dijo* y *lo que el dispositivo contestó* ya es explícita en el
mapa de enlaces (`said` / deducido), en la identidad del equipo (`brand_said`), y en la salida
a internet (declarada, nunca deducida del siguiente salto).

### Lo que NO se va a construir

Decidido de antemano, porque copiar el modelo de NetBox entero es la forma más rápida de no
terminar nunca:

- **IPAM.** Prefijos, VLANs, VRFs, asignación de direcciones. El panel ya deduce las redes de
  lo que contestan los equipos (`lib/core/infra/topology.py`), que es más fiable que una hoja
  que alguien mantiene. Si algún día hace falta, será para *reservar*, no para *registrar*.
- **Circuitos y proveedores** con su facturación y sus SLAs.
- **Objetos de virtualización.** Ya hay módulo Proxmox y la flota distingue máquinas virtuales.
- **Contactos, contratos, journaling.** Nada de eso se cruza con una sonda.

---

## 2. El modelo

### 2.1 Dos árboles, no uno

Lo físico y lo que es de quién son **dos preguntas distintas** y no encajan una dentro de la
otra:

```
CONTENCIÓN (dónde está)                 PERTENENCIA (de quién es)
Datacenter ──< Sala ──< Rack ──< Item          Empresa
                                  │              ▲
                                  └── pertenece ─┘
                                  └──? Host (opcional)
```

La empresa **no es la raíz de nada**. Un holding con un departamento de IT central que da
servicio a las empresas del grupo comparte datacenter, comparte sala y comparte rack: en el
mismo armario hay 2U de una empresa, 4U de otra y un switch del propio departamento que las
sirve a todas. Colgar el datacenter de una empresa hace imposible ese caso, que es el normal en
cuanto hay más de una sociedad.

Así que **la pertenencia es un atributo, no un contenedor**, y se puede decir en cualquier
nivel: una sala entera de una empresa, un rack entero de otra, o item a item dentro del mismo
rack. Lo que no se diga se **hereda del contenedor**, y lo que se diga en un item **manda sobre
lo heredado**. Un rack sin dueño declarado dentro de una sala de la empresa A es de la empresa
A; un item dentro de ese rack que diga «empresa B» es de la B, y ya está.

**Un dueño por cosa, y decidido así** (`org_owner` lleva índice único por `(ámbito, uid)`). «¿Y si
algo es de varias empresas?» se contesta **por el nivel de abajo**, que es como funciona de verdad
un armario compartido: la sala es del que la opera y cada rack es de su empresa; el rack es del
proveedor y cada equipo es de su cliente. Los cinco ámbitos —sede, sala, rack, item y host— llegan
lo bastante abajo para que el reparto siempre se pueda decir donde toca.

Lo que **no** se puede decir es algo compartido de verdad que no se reparta por nada: una sala de
dos filiales que no se divide por racks. Se deja sin fichar, y sin fichar la ve cualquiera con
`dcim_view`. Se han mirado dos salidas y se han descartado a propósito:

* **varios dueños por cosa** —quitar el único, `may_see` como unión, la chapa como lista— parece lo
  barato y deja el modelo peor: «de quién es esto» dejaría de tener *una* respuesta, que es
  exactamente para lo que existe el campo;
* **separar «de quién es» de «quién lo ve»** —un responsable y una lista de empresas con acceso—
  es el modelo honesto para el colo compartido, y el caro: toca la visibilidad, la pantalla y los
  permisos. Es el camino si aparece un caso real que no se reparta por equipos; no se ha hecho
  porque todavía no lo hay.

Y hay una segunda pregunta que el caso del holding obliga a separar: **quién lo opera no es
quién lo posee**. El departamento de IT opera el rack; el equipo es de la filial. Las dos cosas
se preguntan de verdad —una para facturar y otra para saber a quién llamar— así que la sede
lleva su **operador** además de que cada cosa lleve su **dueño**.

La otra decisión que ordena todo lo demás está en la cadena física: **un rack contiene *items*,
y algunos items son hosts**. No al revés.

Es tentador poner `rack_uid` y `posicion_u` como columnas de `hosts` y acabar antes. No vale, y
se ve en cuanto se dibuja un rack real: un panel de parcheo ocupa 1U y no es un host. Una tapa
ciega ocupa 1U y no es nada. Un chasis de blades ocupa 7U y contiene ocho cosas que sí son
hosts. Una regleta vertical no ocupa ninguna U y sí ocupa el rack. Un equipo apagado que sigue
atornillado ocupa su sitio aunque el panel no lo monitorice.

Así que el item de rack es la entidad, con `host_uid` **opcional**. Un item con host se colorea
con el estado en vivo; uno sin host es inventario mudo, que es exactamente lo que es.

Corolario: `hosts` **no se toca**. El registro sigue siendo la fuente de verdad de qué
dispositivos hay y cómo se llega a ellos; DCIM añade *dónde están*, en su propia tabla, y la
relación se rompe sin pérdida por cualquiera de los dos lados.

### 2.2 Las tablas

Nombres provisionales; el prefijo `dc_` mantiene el espacio propio en la BD compartida.

| Tabla | Qué guarda | Notas |
| --- | --- | --- |
| `org` · `org_owner` | Quién es cada sociedad, y de quién es cada cosa | **Del core**, no de esta sección: la misma sociedad que paga el armario tiene usuarios en el directorio. Ver `lib/core/orgs` |
| `dc_site` | Datacenter, sede, armario en una oficina | Dirección, coordenadas, zona horaria, **operador** |
| `dc_room` | Sala, planta, CPD pequeño | `site_uid`, plano de fondo opcional, rejilla |
| `dc_rack` | Rack | `room_uid`, altura en U, ancho, profundidad, posición y giro en el plano, numeración ascendente o descendente |
| `dc_item` | Lo que ocupa U en un rack | `rack_uid`, `u_inicial`, `u_altura`, cara (front/rear/full), `host_uid?`, `type_uid?`, etiqueta, nº de serie, activo |
| `dc_type` | Catálogo de modelos | Importado de devicetype-library: fabricante, modelo, altura, profundidad completa, imágenes, puertos |
| `dc_power` | Regletas, tomas y de qué se alimenta cada item | Rama A/B, potencia declarada, `host_uid?` de la regleta si se mide |
| `dc_cable` | Cable físico con sus dos extremos | Etiqueta, tipo, longitud, color; extremo = (item, puerto) o (item, toma) |
| `dc_link` | Enlace entre sedes | SD-WAN, IPSEC, MPLS, fibra oscura; declarado, y contrastado con lo medido |

**Por qué la pertenencia es una tabla y no una columna en cada sitio.** La regla —«dilo donde
quieras, hereda hacia abajo, el más concreto manda»— es una sola, y escrita como una columna
`org_uid` en cinco tablas son cinco sitios donde implementarla y cinco donde equivocarse. En una
tabla aparte hay **un** resolutor: se sube por la cadena física hasta encontrar la primera
pertenencia dicha. Además admite ámbitos que no están en la cadena —un host suelto, una VM, un
VIP— que también son de alguien y no están en ningún rack.

Y por eso **no es de esta sección**: desde build.125 vive en `lib/core/orgs`, con la tabla `org`
y `org_owner`. Esta sección DECLARA sus cuatro ámbitos (`ORG_SCOPES` en su `manifest.py`) y sigue
resolviendo por su cadena; lo que ya no hace es ser dueña del registro, que es lo que impedía que
el directorio o Microsoft 365 agruparan nada por sociedad.

**La cara importa.** Un equipo de 1U ocupa la U 12 por delante *y* por detrás; un panel de
parcheo puede ocupar solo la cara trasera; dos equipos de media profundidad pueden compartir la
misma U por caras opuestas. Sin `cara` el mapa de un rack real es mentira a la primera semana.

### 2.3 Estado en vivo, hacia arriba

Cada nivel se colorea con lo peor que tenga debajo:

```
item (host) → rack → sala → datacenter → empresa
```

No hay que inventar nada: el estado por host ya lo calcula `lib/core/infra/service.py` a partir
de `_read_check_status`, con la severidad `warning` ya diferenciada del `down`. Lo que hace
falta es **un servicio de agregación** que recorra la contención una vez por render y devuelva,
por nodo, `{peor_estado, cuántos, cuántos malos, cuántos sin vigilar}`.

**Y se agrega por los dos ejes.** «Qué hay roto en la Sala 2» y «qué hay roto que sea de la
empresa C» son las dos preguntas, y las hacen personas distintas: la primera el que baja al CPD,
la segunda el que responde ante la filial. El mismo recorrido contesta las dos si lo que se
acumula por nodo se acumula también por dueño; hacerlo después significa un segundo recorrido y
dos criterios de «peor estado» que acabarán discrepando.

Dos cosas a cuidar desde el principio, porque son las que rompen esto a escala:

- **Un item sin host no es «bien»**, es *sin dato*. Un rack lleno de paneles de parcheo no puede
  salir verde: sale gris, que es la verdad. El panel ya tiene ese criterio (`HOST_STATE_COLORS['']`).
- **Una U vacía tampoco es «bien»**. La ocupación es otra lectura distinta del estado.

---

## 3. El catálogo de modelos: devicetype-library

<https://github.com/netbox-community/devicetype-library> son varios miles de ficheros YAML con,
por modelo: altura en U, si ocupa profundidad completa, imágenes de frontal y trasera, lista de
interfaces, de tomas de corriente, de puertos de consola y de bahías de módulo.

Es justo lo que necesita un alzado de rack y un cálculo de potencia, y **no hay que teclearlo**.

### Cómo se integra

**No se empaqueta.** El repositorio es grande, cambia solo y traerlo dentro convierte cada
release del panel en una release del catálogo de otro. Se sigue el patrón que ya existe para la
biblioteca de MIBs: **se importa bajo demanda** —desde una URL, un zip subido o una ruta local—
a una tabla en la BD, con su permiso propio y su trabajo de fondo visible en la sección de
Trabajos.

Eso resuelve además la instalación aislada: quien no tenga salida a internet sube el zip.

**Licencia: CC0-1.0** (dominio público), verificada el 2026-08-26. Es el mejor caso posible:
no exige atribución y no entra en conflicto con la GPLv3 del panel. Aun así la pantalla de
importación dirá de dónde salen los datos y con qué licencia — quien mire un catálogo tiene
derecho a saber quién lo escribió, y una licencia se puede cambiar en el futuro aunque lo ya
importado se quede como está.

Los campos obligatorios de cada YAML son `manufacturer`, `model`, `slug`, `u_height` e
`is_full_depth` — que son exactamente los cinco que necesita un alzado. Los opcionales que
interesan: `part_number`, `airflow`, `front_image` / `rear_image`, `subdevice_role`, `is_powered`
y `weight`. Un importador que solo entienda los cinco primeros ya sirve para la fase 1.


**Qué se trae de la biblioteca, exactamente.** El lector entiende el formato de
`devicetype-library` tal cual: `manufacturer`, `model`, `slug`, `u_height`, `is_full_depth`,
`subdevice_role`, `is_powered`, `part_number`, `airflow`, y los puertos **contados por tipo**.
Las imágenes de alzado se leen de `elevation-images/<fabricante>/<slug>.front.png`, que es la
ruta de ese repositorio.

Dos cosas que NO hace y conviene saber: **no descarga de GitHub por su cuenta** —se le apunta a
un clon local o se le sube un zip, porque esto se despliega sin salida— y los puertos se cuentan,
no se listan uno a uno. Contarlos es lo que hace falta para capacidad; listarlos serían millones
de filas que ninguna pantalla lee.

Y de ahí sale además **qué clase de dispositivo parece** cada modelo: tomas de corriente sin
interfaces es una regleta, puertos por delante y por detrás sin alimentación es un panel de
parcheo, bahías de dispositivo es un chasis. **Propone, no escribe** — la biblioteca no dice el
rol en ninguna parte, y una deducción guardada como si fuera un hecho es lo que este dominio
evita en todo lo demás.

### El encaje que lo hace valer

El panel **ya sabe qué modelo es cada equipo**, porque lo pregunta: el trabajo de identidad de
SNMP (`brand_of` / `identity_of`, perfiles con `brand` y `brands`) saca fabricante y modelo de
lo que el dispositivo contesta. Así que la asignación de modelo del catálogo **se propone sola**:

> El dispositivo dijo «PowerConnect 2848». El catálogo tiene ese modelo: 1U, 48 puertos, dos tomas.
> ¿Lo pongo?

Con la misma regla de siempre: se **propone**, y lo confirma una persona. Una coincidencia por
cadena de texto es una pista, no un hecho, y un modelo mal asignado mete un equipo de 2U en una
U que no tiene.

---

## 4. Los mapas

Aquí es donde el trabajo reciente se cobra solo. `partials/infra/_canvas.html` ya es el lienzo
compartido: ventana, zoom, encuadre, arrastre de cajas, disposición guardada por cuenta, tarjeta
de lectura al pasar por encima, **y exportación a PNG/SVG con los colores, los iconos y la fuente
metidos en el fichero**. Cuatro dibujos nuevos y ninguno de ellos vuelve a resolver eso.

| Vista | Qué dibuja | Sobre qué se apoya |
| --- | --- | --- |
| **Alzado de rack** | Las U de frente y de espalda, cada item en su sitio, coloreado por estado | Lienzo compartido; imágenes del catálogo cuando las haya |
| **Plano de sala** | Racks vistos desde arriba, con su giro y sus pasillos | Lienzo compartido + imagen de fondo opcional |
| **Mapa de sede** | Salas dentro de un datacenter | Igual |
| **Mapa entre sedes** | Datacenters y los enlaces que los unen | El mapa de enlaces actual, con nodos de otro tipo |

### La restricción que decide el mapa geográfico

Un mapa del mundo con teselas exige un servidor de teselas, que es una petición a un tercero
desde el navegador de cada persona que lo abra — y ese tercero pasa a saber dónde están los
datacenters de la organización. El panel se autohospeda y se despliega en sitios sin salida, así
que **no se depende de un proveedor de teselas: se puede usar uno, apagado por defecto.**

Las dos formas funcionan y no son la misma pantalla con otro fondo:

- **Sin teselas** (defecto) las sedes son cajas que alguien coloca, guardadas en `pos_x`/`pos_y`,
  situadas de partida proyectando sus coordenadas.
- **Con teselas** el dibujo *es* el mundo: el sistema de referencia es el Web Mercator, cada sede
  cae donde dice su latitud, y **arrastrarla cambia sus coordenadas** — que es la forma cómoda de
  decir dónde está una sede: se arrastra hasta el edificio y ya está dicho.

La plantilla es XYZ (`{z}/{x}/{y}`), que hablan OpenStreetMap, Carto, un servidor propio y un
espejo interno. **Nunca el SDK de un proveedor**: cargar imágenes de un tercero le dice dónde
están tus sedes; ejecutar su script le da la página entera. Por eso la política de contenido abre
`img-src` —solo el origen que salga de la plantilla configurada, y solo si hay una— y `script-src`
no se toca. La atribución es un campo y no una constante: la licencia de OpenStreetMap obliga a
dar crédito, y un crédito fijo nombra a quien no es en cuanto alguien apunta a otro servidor.

Latitud y longitud se guardan de todas formas: son un dato del sitio, útiles aunque no se dibujen.

Las imágenes subidas (planos, alzados) obligan a dos cosas desde el primer día: entran en la
copia de seguridad (`__backup_part__`) y se sirven con la misma validación de ruta que ya cazó
un *path traversal* en el catálogo de MIBs.

---

## 5. Cableado, etiquetas y la reconciliación

La parte más útil y la que hay que hacer más tarde, porque necesita todo lo anterior.

Un cable declarado une (item A, puerto 1) con (item B, puerto 2), y lleva **etiqueta**, que es lo
que de verdad se busca a las tres de la mañana con una linterna. Etiquetas de red y de corriente
por separado, porque son dos rotulados distintos y dos personas distintas los ponen.

Y entonces el panel puede hacer lo que ninguna hoja de cálculo hace:

- **LLDP dice quién hay al otro lado.** Si el cable declarado dice SW01 y el vecino contestado es
  otro, eso es una fila en una pantalla de discrepancias, no un error de nadie.
- **La tabla de reenvío dice por qué puerto se ve cada MAC.** Un puerto declarado como «servidor
  DB03» por el que se ven cuarenta MACs es un puerto que va a otro switch.
- **Un puerto declarado y caído** es distinto de un puerto caído y sin declarar: el primero es
  una llamada de teléfono, el segundo puede ser un PC apagado a las siete. Esa distinción ya
  existe en el panel (la marca de vigilado y el rol `wan`); el cableado la hereda gratis.

**Un cable puede cruzar empresas**, y es lo normal en el caso del holding: el puerto del switch
del departamento de IT contra el servidor de la filial. Quien pueda ver los dos extremos ve el
cable entero; quien solo pueda ver uno ve su extremo y que el otro existe, sin nombre. La
alternativa —ocultar el cable— haría que a alguien le faltara media red en su propia pantalla
sin saber por qué.

**Previsión de nuevos equipos** es la otra cara de lo mismo: U libres seguidas por rack, potencia
libre por rama, puertos libres por switch. Las tres salen de datos que ya estarán ahí, y las tres
son preguntas que se hacen antes de comprar.

---

## 6. Enlaces entre datacenters

Un `dc_link` es lo declarado: tipo (SD-WAN, IPSEC, MPLS, fibra), extremos, ancho de banda
contratado, proveedor, y **por qué equipo entra en cada sede**.

Lo medido llega por donde ya llega: un túnel IPSEC tiene interfaz y estado en el router, y un
enlace SD-WAN publica métricas. Como con todo lo demás, el panel dibuja lo declarado y marca lo
que no cuadra — un enlace declarado cuyo interfaz lleva dos días abajo, o un túnel que existe en
el router y no está en el inventario.

---

## 7. Permisos

Un dominio, un grupo de permisos, con la regla de nombre que ya rige: **todo lo que tenga
`viewer` termina en `_view`** (ver `tests/unit/test_wa_roles.py`).

| Bandera | Para qué |
| --- | --- |
| `dcim_view` | Ver el inventario, los mapas y los alzados |
| `dcim_edit` | Crear y mover sedes, salas, racks e items |
| `orgs_edit` (del core) | Crear empresas y decidir de quién es cada cosa |
| `dcim_cable_edit` | Declarar y retirar cableado y etiquetas |
| `dcim_catalog_view` | Consultar el catálogo de modelos |
| `dcim_catalog_manage` | Importar y actualizar el catálogo |

`orgs_edit` va aparte de `dcim_edit` a propósito: mover un equipo de U es ordenar el
armario, y cambiar de quién es ese equipo es mover una pertenencia entre sociedades. Lo segundo
tiene consecuencias de facturación y de quién lo ve.

### El rack compartido es el caso duro

Un rack con equipos de varias empresas **rompe la idea de que ver un sitio es ver lo que hay
dentro**. Alguien de la filial B tiene que ver el rack, tiene que ver que la U 12 está ocupada
—si no, planificar es imposible— y **no** puede ver de quién es ni cómo se llama.

Eso pide un ámbito por empresa, con el mecanismo de permisos dinámicos que ya existe para
equipos, módulos y clústeres: **`org.<uid>.view`**, junto al `server.<uid>.view` de hoy. Y tres
reglas que hay que escribir en la primera fase, no parchear en la quinta:

1. **Un item ajeno se dibuja ocupado y anónimo.** Sin nombre, sin modelo, sin estado. Ocupa,
   que es lo único que le hace falta saber a quien no es su dueño.
2. **El vuelco de estado no se filtra a través del sitio.** Si el rack dijera «3 equipos mal» y
   ninguno fuera tuyo, ese 3 sería una enumeración de la flota ajena por la puerta de atrás. Lo
   que se cuenta es lo que se puede ver.
3. **Y la ocupación sí es de todos.** «Quedan 6U libres» no dice de quién es nada y es la mitad
   del valor de tener esto.

Sin esas tres, el alzado se convierte en el sitio por donde se enumera la flota entera saltándose
el permiso — que es exactamente el patrón de la auditoría IDOR de 2026-05.

---

**A una caja se llega o porque se ve, o porque contiene algo tuyo.** Las dos mitades, y
ninguna sola vale:

* solo «lo ves» deja al holding sin pantalla. El departamento opera la sede, así que la sede es
  suya, así que la filial que tiene 2U dentro no ve ni sede, ni sala, ni rack — y su propio
  equipo queda inalcanzable salvo que alguien le pase una URL. La parte más probada del dominio
  fuera del alcance de quien la necesita;
* solo «contiene algo tuyo» escondería una sede entera vacía que sí es suya.

Juntas dan lo que hace falta: la filial ve **el camino hasta lo suyo** —`DC Norte › Sala 1 › R3`,
la sede y la sala por el nombre— y nada más de esa sede. Dentro del rack, lo suyo entero y lo
ajeno ocupando y anónimo. Las otras salas de esa sede no existen para ella.

El precio, dicho en voz alta: el nombre y la dirección de la sede del departamento pasan a ser
visibles para una sociedad que tiene equipo allí. En la práctica ya lo sabe, porque va a entrar a
tocarlo.

Se calcula en un sitio (`service.reachable`) y lo usan las cuatro pantallas que enseñan cajas.
Dos versiones de esta regla es exactamente cómo el listado y la lectura por uid acabaron
discrepando — el listado escondía un armario que abrir por uid enseñaba.

## 8. Fases

Cada fase termina con algo que se puede usar, sus tests y su entrada de CHANGELOG. Ninguna deja
la anterior a medias.

| # | Fase | Entrega | Depende de |
| --- | --- | --- | --- |
| **0** | **Modelo, pertenencia y catálogo** | Tablas, stores, permisos, **empresas con `org_owner` y el ámbito `org.<uid>.view`**, importación de devicetype-library con su trabajo de fondo. Sin mapas: listas y formularios | — |
| **1** | **Racks** | Alzado frontal y trasero, colocación de items, enlace opcional a host, color en vivo, ocupación de U, **y el item ajeno dibujado ocupado y anónimo** | 0 |
| **2** | **Salas** | Plano con racks vistos desde arriba, imagen de fondo, agregación de estado sala→rack | 1 |
| **3** | **Sedes y cuadro de mando** | Geografía, esquema de sedes, y el desglose **por sitio y por empresa** con el camino hasta el fallo | 2 |
| **4** | **Potencia** | Regletas, tomas, ramas A/B, potencia declarada frente a la medida por el SAI, capacidad libre, **y consumo por empresa dentro de un rack compartido** | 1 |
| **5** | **Cableado** | Cables, etiquetas, y la pantalla de discrepancias contra LLDP y la tabla de reenvío | 1, y el mapa de enlaces que ya existe |
| **6** | **Entre sedes** | Enlaces SD-WAN/IPSEC declarados y contrastados | 3 |
| **7** | **Previsión** | U libres, potencia libre, puertos libres; «dónde cabe esto» | 4, 5 |

La pertenencia sube a la fase 0 justo por el caso del holding: es un eje del modelo y una
condición de los permisos, no una etiqueta que se añade luego. Añadir «de quién es esto» a un
inventario ya construido significa revisar cada consulta que devuelve una lista.

**Las fases 0 y 1 son las que deciden si esto vale.** Un alzado de rack que se colorea solo con
lo que las sondas ya saben es útil el mismo día, y es la mitad del trabajo del resto.

---

## 9. Riesgos, dichos en voz alta

- **Tamaño.** Esto es, en trabajo, comparable a todo el dominio de infraestructura actual. Las
  fases están cortadas para poder parar en cualquiera de ellas con algo entero.
- **El inventario se pudre.** Todo dato declarado envejece. Es el motivo de que la
  reconciliación esté en el centro y no al final: un inventario que se corrige solo al menos se
  queja cuando no puede.
- **Imágenes.** Planos y alzados son ficheros. Copia de seguridad, validación de ruta y límite
  de tamaño desde la primera, no después.
- **Multiempresa.** Cada consulta que devuelve una lista es una fuga en potencia. Es el riesgo
  de seguridad de todo esto, y por eso el ámbito por empresa entra en la fase 0: retrofitarlo es
  auditar el dominio entero de nuevo.
- **i18n.** Cinco pantallas nuevas son varios cientos de claves en dos idiomas.
- **Rendimiento.** La agregación de estado recorre toda la contención. Se calcula una vez por
  petición y se pasa hacia abajo — igual que `_read_check_status` hoy — nunca por nodo.
- **El catálogo es de otro.** CC0 hoy; citado igualmente, y sin ninguna dependencia de que ese
  repositorio siga existiendo — lo importado se queda en la BD.

---

## 10. Lo primero, concretamente

1. `lib/core/dcim/`: `manifest.py` (permisos y eventos), `store.py` (las tablas del §2.2),
   `mixin.py`, `routes.py` — el mismo reparto que cualquier otro dominio
   (`tests/unit/test_core_domain_layout.py` lo comprueba).
2. El importador del catálogo como trabajo de fondo, con su entrada en la sección de Trabajos.
3. La sección `/dcim` en el registro de páginas, con la lista de sedes y salas.
4. Los tests de cada pieza.

Sin nada de eso hecho, **el alzado de rack no se puede empezar**: es lo que dibuja.

---

## 11. Checklist de implantación

Vivo: se marca al terminar cada punto, y «terminar» quiere decir **con sus tests pasando**, no
escrito. Un punto a medias se queda sin marcar aunque el fichero exista.

### Fase 0 — Modelo, pertenencia y catálogo

> **Cerrada** salvo el vuelco de estado, que no es de esta fase: no hay nada que volcar hasta que haya alzado. Lo que hay hoy: el modelo, la pertenencia con su ámbito por empresa, el catálogo importable y la sección con su árbol.

**0.1 El dominio existe**

- [x] `lib/core/dcim/__init__.py` con la explicación de qué contiene el paquete
- [x] `manifest.py`: permisos (`dcim_view`, `dcim_edit`, `dcim_cable_edit`,
      `dcim_catalog_view`, `dcim_catalog_manage`) y eventos de auditoría
- [x] Las banderas salen en el catálogo (`PERMISSIONS`) y tienen nombre y descripción en los
      dos idiomas
- [x] La lista de banderas del dominio, cerrada, en un test

**0.2 Las tablas**

- [x] `store.py`: `dc_site`, `dc_room`, `dc_rack`, `dc_item`
- [x] la pertenencia dicha, con su ámbito y su uid (hoy `org_owner`, del core)
- [x] Alta/baja/modificación por entidad, con columnas de auditoría
- [x] Reconciliación al arranque, como el resto de los stores
- [x] Un rack no admite dos items solapados en la misma U y la misma cara

**0.3 La pertenencia**

- [x] `owners.py`: dueño efectivo subiendo la cadena física (item → rack → sala → sede)
- [x] Ámbito por empresa `org.<uid>.view` en los permisos dinámicos *(era una clase nueva de clave por instancia: sin declararla, un rol se guardaba SIN ella y el estrechamiento no estrechaba)*
- [x] El filtro de visibilidad: qué se ve de un item ajeno (ocupado y anónimo) y qué no
- [x] El vuelco de estado cuenta **solo lo que quien mira puede ver** *(llegó con la fase 1)*

**0.4 El catálogo de modelos**

- [x] `dc_type` y el lector de YAML de devicetype-library
- [x] Importación como trabajo de fondo, visible en la sección de Trabajos
- [x] Desde zip subido y desde ruta local (instalación sin salida a internet)
- [x] Propuesta de modelo a partir de lo que el dispositivo dijo de sí mismo *(`/catalog/suggest`: propone, no escribe; falta el botón que lo ofrezca en pantalla)*

**0.5 La sección**

- [x] `routes.py` con las rutas de lectura y escritura, cada una tras su permiso
- [x] El pegamento del panel *(no hace falta un `mixin.py`: como infra e historial, el dominio son rutas + store, y el store se construye en el arranque junto al registro de hosts)*
- [x] Entrada en el registro de páginas: `/dcim`
- [x] Listas de empresas, sedes, salas y racks — sin mapas todavía *(el árbol y el contenido de un rack; crear una sede desde la propia barra)*
- [x] i18n de todo lo anterior

**0.6 Cierre de fase**

- [x] Tests unit del store, del resolutor de dueño y del filtro de visibilidad
- [x] Tests de integración de las rutas, incluido el ajeno anónimo
- [x] Tests meta de la sección (registro, bundle, permisos)
- [x] `ref-esquema-bd.md`, `ref-permisos.md`, `ref-tests.md`
- [x] `ref-api.md`
- [x] CHANGELOG

### Fases siguientes

Se desglosan al empezar cada una: desglosar la 5 hoy sería inventarse el trabajo con la mitad
de la información que habrá cuando toque.

**Fase 1 — Racks** *(el alzado)*

- [x] `service.py`: estado por item, lo peor de un rack, y el vuelco sede→sala→rack en **una
      pasada** — por nodo serían cuarenta lecturas del mismo fichero de estado
- [x] Un item **sin host no está bien**, está sin vigilar: sin color, no verde
- [x] El recuento cuenta **solo lo que quien mira puede ver**, y eso sube solo: lo que no llega
      a un rack no puede llegar a su sala
- [x] Alzado frontal y trasero, uno al lado del otro, sobre el lienzo compartido — con lo que
      trae gratis: encuadre, zoom, arrastre y **exportar a PNG/SVG**
- [x] Color en vivo, con `hostStateColor` y no uno propio
- [x] La numeración de U respeta si el rack va de abajo arriba o al revés — **y se puede decir**: la columna existía desde el principio y el alzado ya la respetaba, pero no estaba en el formulario, así que todo rack era de abajo arriba y parecía correcto
- [x] Dimensiones del armario (ancho y fondo) y **posición de los mástiles**: frente→mástil, entre mástiles y mástil→fondo — con el veredicto de si un equipo de un fondo dado entra, y el descuadre dicho cuando los tramos no suman
- [x] Un item ajeno se dibuja ocupado, anónimo y sin color
- [x] Leer un item al pasar por encima; pulsarlo abre su formulario
- [x] Insignia de estado en el árbol: rack, sala y sede
- [x] Imágenes del catálogo en el alzado. `front_image: true` no era una imagen: era la
      **afirmación de que existe una** — y existía, en el mismo repositorio, al lado del
      YAML. Se recogen en la misma pasada, las guarda el almacén de medios (que decide
      por el CONTENIDO si son imágenes y acuña el nombre) y reimportar borra las de la
      importación anterior: sin eso la carpeta crece durante toda la vida de la
      instalación. Se pintan **detrás** del nombre y del color y atenuadas: la foto dice
      qué es y el color dice cómo está, y taparlo convertiría el alzado en un catálogo
- [x] Arrastrar un item de una U a otra, con imán a la U —no hay medias U— y **el servidor
      decidiendo si cabe**: ya sabe de caras y de solapes. Lo ajeno no se arrastra
      *(la inversa altura→U tenía un desplazamiento de una U que no daba ningún error;
      ficha en `caso-diagnostico.md`)*
- [x] Enlazar un item con un host desde la pantalla — **sin esto el alzado sale gris entero**, que es tanto como no tenerlo: el color en vivo lee `host_uid` y `host_uid` no se podía escribir desde ninguna parte

**Fase 2 — Salas** *(el plano)*

- [x] Plano de la sala: los racks vistos desde arriba, a escala en milímetros, con rejilla de
      un metro
- [x] Se arrastran a su sitio — y **la posición se escribe en el servidor**: dónde ESTÁ un rack
      es un hecho de la sala, no la vista de quien lo mueve
- [x] Girar un rack un cuarto de vuelta, con su propio botón: rotar arrastrando es un gesto que
      nadie descubre y todos disparan sin querer
- [x] Color por el peor estado de lo que hay dentro, y el frente marcado — que es lo que dice
      cuál es el pasillo frío
- [x] Se abre desde la sala y se vuelve; la URL recuerda en qué sala se estaba
- [x] Imagen de fondo del plano — con **el almacén de medios** detrás: una carpeta como la de
      las MIB, configurable como la de las copias (`web_admin|dcim_media_dir`, vacío =
      `<var_dir>/dcim_media`), el tipo decidido por **el contenido** y no por la extensión, el
      nombre acuñado por el panel —lo que traía el fichero no llega nunca a un disco—, tope de
      2 MB cortado antes de leer, y **su parte en la copia**: el registro solo guarda el
      nombre, así que una copia sin los ficheros restaura salas cuyos planos se han perdido.
      Se escala con un solo número —los milímetros que abarca de ancho— y el alto sale de la
      propia imagen: dos números podrían contradecirse y estirar el dibujo, que es mentir
      sobre distancias justo donde alguien las va a medir
- [x] Colocar un rack **nuevo** desde el plano, sin pasar por el formulario
- [x] **Diseñar la sala**: lo que hay en ella además de los racks —pasillos confinados, zonas
      libres, columnas, mamparas, puertas, cuadros, SAI, climatizadores, mesas, extintores,
      bandejas y etiquetas— en su propia tabla (`dc_feature`), porque un rack es un registro
      con equipos y estado y una columna no: juntarlos haría que el recuento de una sala
      incluyera extintores y que «sin vigilar» devolviera mamparas
- [x] Rejilla de **baldosa** (la de esta sala: hay suelos de 500 y de 610) con el metro marcado
      encima, imán a la baldosa, y posiciones que se pueden decir por teléfono («B7»)
- [x] Contorno y cotas de la sala, con sus medidas escritas **desde el plano** — que es donde se
      descubre que hacen falta: se está colocando la tercera fila y hay que saber si llega
- [x] Tres capas —suelo, sala, aire— sacadas del modelo y no de quien pinta: un pasillo va
      debajo de los racks y una bandeja por encima, y al revés tapan lo que se venía a mirar
- [x] Girar, mover con las flechas (Shift = una baldosa), borrar, y el panel de la pieza con los
      mismos campos que tiene su fila y ni uno más
- [x] **Llevarse el plano y traerlo**: exportar a JSON e importarlo. La base de datos sigue
      siendo el guardado —un plano en el escritorio de alguien es un plano que la siguiente
      persona no encuentra— pero esto resuelve lo que ella no: mandarle el diseño a alguien,
      guardar una versión antes de reorganizar, y montar una sala partiendo de otra. **La
      importación no borra racks**: se emparejan por nombre y solo se mueven, y el que el
      fichero no nombre se queda — dentro hay equipos
- [x] **Visor 3D de la sala**, en WebGL del propio navegador y sin librería: el prototipo
      cargaba three.js de un CDN y aquí eso no carga —la política de contenido no ejecuta
      script de terceros y esto se despliega sin salida a internet—, y empotrarla habrían sido
      600 KB de código ajeno para dibujar cajas. Una sala son cajas: suelo, muros, racks a la
      altura que dicen sus U, columnas, mamparas translúcidas y bandejas colgadas. Con el
      **color en vivo** en el frente de cada rack, que es lo único que ninguna librería podía
      dar: sale de las sondas
- [x] **Filas declaradas** (`dc_row`), no deducidas de que los racks caigan alineados —eso
      falla de las dos formas: dos racks alineados por casualidad parecen una fila, y una
      fila con un hueco deja de parecerlo. Y no es una etiqueta: de la fila cuelga a qué
      pasillo da cada cara, y cruzarlo entre filas da el aviso que un plano no puede dar
      mirando cajas — **«la fila C aspira del pasillo donde descarga la A»**. Un rack sin
      fila sale suelto y no como error; deshacer una fila no deshace sus armarios

**Fase 3 — Sedes y cuadro de mando**

- [x] `service.board()`: una tarjeta por sede, desglose por empresa y **el camino hasta cada cosa
      que falla** — sede › sala › rack › U. No un número: un cuadro que dice «3 incidencias» y
      hay que ir a buscarlas obliga a hacer el trabajo que venía a ahorrar
- [x] Un solo recorrido del árbol (`service.walk()`) para las insignias y para el cuadro: dos
      copias de «¿puede este lector ver esto?» son dos sitios donde esa regla se desvía, y el
      día que se desvíen las dos pantallas dirían cosas distintas de la misma flota y las dos
      parecerían correctas
- [x] Estrechado de verdad: una sede que no se puede ver **no se recorre**, y el fallo del
      vecino no sale ni en la lista, ni en las tarjetas, ni en el desglose por empresa
- [x] La lista recortada **lo dice** (`capped`, `trouble_total`): una más corta que la realidad
      parece completa, y quien la lee da por resuelto lo que no ha visto
- [x] Desde una fila se va al armario y desde una tarjeta a la sede — que es el punto entero
- [x] Mapa de sedes sobre el lienzo compartido: cajas que se colocan y se guardan en el
      servidor, situadas de partida proyectando `lat`/`lon` porque empezar amontonadas en una
      esquina teniendo el dato delante es tirar lo que alguien tecleó
- [x] **Teselas de verdad, opcionales** (`dcim_map_tiles`, plantilla XYZ — OpenStreetMap, Carto,
      un servidor propio o un espejo interno). Web Mercator, así que cada sede cae donde dice su
      latitud y **arrastrarla escribe sus coordenadas**. La política de contenido abre `img-src`
      solo para el origen que salga de la plantilla, y `script-src` no se toca — que es la razón
      de no usar el SDK de un proveedor. Apagado por defecto: encenderlo le dice a un tercero
      dónde están los datacenters de la organización, y eso lo decide quien despliega
- [x] El cuadro en la URL: es la pantalla que alguien pega en un chat a las tres de la mañana
- [ ] Imagen de fondo del mapa de sedes *(el almacén de medios ya está; falta decidir de quién
      es esa imagen, porque no es de ninguna sede en particular)*
- [x] Hora local de cada sede en su tarjeta. No es adorno: «son las cuatro de la mañana
      allí» decide si se llama ahora o se espera. La convierte el navegador, y una zona
      que no conozca no rompe la tarjeta: se calla
**Fase 4 — Potencia**

- [x] `dc_pdu`: la regleta, con su **rama** (A / B / ninguna), sus tomas y lo que aguanta. Y su
      `host_uid`, porque **una PDU gestionada es un host**: contesta y dice lo que está dando,
      así que ahí tenemos las dos mitades —lo declarado y lo medido— que son toda la tesis
- [x] `dc_feed`: un cable. Una fila por cable y **no una columna en el equipo**, porque un
      equipo con una sola fila es justo el hallazgo: dos fuentes y una sin enchufar
- [x] `service.power_of_rack()`: tomas libres, carga declarada, y **qué se apaga si cae una
      rama**. Dos cables a la misma rama NO son redundancia —contando cables lo parecerían—, y
      la carga se mide contra la **mitad** de la capacidad, porque tener dos ramas no sirve de
      nada si una sola no puede con las dos
- [x] Un equipo sin enchufar no es un aviso: un panel de parcheo no consume, y pintarlo como un
      problema enseña a la gente a ignorar la pantalla — que es la forma más eficaz de que un
      aviso de verdad no se lea
- [x] En un armario compartido: los **totales** de una regleta son de todos (sin ellos la filial
      no puede planificar), de quién es cada cable no, y el aviso sobre el equipo del vecino no
      se le cuenta a nadie más
- [x] La pantalla, dentro del rack: avisos arriba con la frase entera —un aviso que hay que
      interpretar es un aviso que se ignora—, regletas con su barra, y de qué se alimenta cada equipo
- [x] Enchufar propone la rama que le **falta** al equipo, que es la elección que evita el fallo
      que todo esto existe para cazar
- [ ] Contraste con lo que mide la PDU gestionada *(el modelo ya lo permite: falta leer el
      sensor y ponerlo al lado de lo declarado)*
- [x] Consumo por empresa dentro de un rack compartido — en un holding donde el departamento
      opera la sala y factura por consumo, eso es una línea de una factura
- [x] **La cadena entera aguas arriba** (`dc_source`): acometidas, cuadros, SAI y grupos. Las
      cuatro instalaciones que hay que poder decir son **tres cadenas y un interruptor** —
      `Cuadro → PDU`, `Cuadro → SAI → PDU`, `Cuadro → SAI → Cuadro → PDU`, y esa misma con el
      bypass echado, que **no es otra instalación sino la anterior con el SAI fuera**. Por eso
      el bypass es una marca en el nodo que se salta y no una segunda cadena: dos cadenas
      serían dos verdades sobre el mismo cobre
- [x] La misma cadena se recorre **dos veces**, con el bypass y sin él: eso contesta «¿qué
      pierdo si lo echan?» **antes** de que lo echen, y convierte «esta regleta no pasa por un
      SAI» —que puede ser correcto— en «pasaría, si no fuera por el bypass»
- [x] Las **dos ramas del mismo SAI**: dos regletas, dos colores, y un solo punto de fallo tres
      metros más arriba. Es el error que la redundancia dentro del armario esconde
- [x] Echar o quitar un bypass **se audita** (`dcim_bypass`, severidad aviso): no es editar un
      campo, es una maniobra eléctrica, y quién la hizo y cuándo es lo primero que se pregunta
      cuando algo se apaga tres meses después
- [ ] Dibujar la cadena, que hoy se lee como lista
**Fase 5 — Cableado**

- [x] `dc_cable`: lo que alguien **declaró** enchufado, con sus dos extremos, sus puertos, su
      etiqueta y su color. Los extremos son **items y no máquinas**: un panel de parcheo no
      contesta a nada y es donde acaba la mitad de los cables de una sala
- [x] `service.cable_check()`: lo declarado contra lo que los dispositivos dicen ver. **Aquí el
      inventario deja de ser documentación** — «el switch ve a este servidor por la Gi1/0/7» es
      un hecho suelto; con la etiqueta al lado es «o la etiqueta miente o alguien movió el
      latiguillo»
- [x] Cuatro estados y ninguno es un error del panel: coincide, **no se ve** (una pregunta:
      puede haber un panel pasivo en medio), **otro puerto** (el hallazgo) y **sin declarar**
      (alguien enchufó y no lo apuntó)
- [x] Un extremo pasivo **no se juzga**: marcarlo como «no se ve» llenaría la pantalla de avisos
      imposibles de resolver, que es la forma más rápida de que nadie vuelva a mirarla
- [x] El mapa de la flota se arma en **un solo sitio** (`infra.service.topology`, declarado en
      el panel): dos copias serían dos pantallas contando cosas distintas de la misma flota
- [x] Declarar cableado es **su propia bandera** (`dcim_cable_edit`): mover un equipo de U y
      decir por dónde va un cable son dos trabajos, muchas veces de dos personas
- [x] Los cables y la corriente **en el alzado**, como marcas por equipo: un punto por
      cable con su color y una barra por rama con el de su regleta. Marcas y no cables
      porque cuarenta latiguillos dibujados tapan justo lo que se venía a mirar; dicen
      tres cosas —que hay cables, de qué color, y si la corriente viene de las dos
      ramas— que es lo que se comprueba de un vistazo. Nada en lo ajeno
- [~] Cableado eléctrico con la misma reconciliación — **no se hace, y no es un olvido**: ya
      está modelado y mejor. `dc_feed` ES el cable eléctrico aguas abajo (equipo ↔ regleta ↔
      toma ↔ vatios) y la cadena aguas arriba lo cubre desde el cuadro. Un cable de tipo
      `power` en `dc_cable` sería una **segunda tabla contestando lo mismo**, y este dominio ya
      sabe cómo acaba eso: dos sitios donde decir de qué se alimenta un equipo, y el día que discrepen
      las dos pantallas parecerán correctas
**Fase 6 — Entre sedes**

- [x] `dc_link`: lo que une dos sedes, con su clase (MPLS, IPSEC, SD-WAN, fibra oscura…), su
      operador, su **`circuit_id`** —la referencia que hay que decir por teléfono a las tres de
      la mañana, y lo único de la tabla que no se deduce de ninguna otra parte— y por dónde va
- [x] Las puntas son **sedes**, y opcionalmente el equipo que las termina: un circuito no tiene
      estado —es un contrato— y el router que lo termina sí
- [x] `service.links_roll()`: **qué sede se queda sola**. Una con un solo enlace se dice, y se
      dice cuál; y dos enlaces por el mismo camino o del mismo operador se dicen también —dos
      líneas en el mapa y un solo camino en el suelo es la redundancia que se descubre el día
      que pasa una excavadora
- [x] Solo se juzga lo que alguien escribió: un aviso sacado de un campo vacío es un aviso
      inventado, y esos enseñan a ignorar la pantalla
- [x] Dibujados en el **mapa de sedes**, coloreados por estado y punteados los que van sobre
      otra cosa (IPSEC, SD-WAN, internet)
- [x] El permiso se pide sobre **las dos puntas**: pedirlo sobre una sola dejaría dibujar líneas
      hasta sedes que quien las dibuja no puede ni abrir
- [ ] Contraste con lo que dice el túnel *(hace falta una sonda que lea el estado de la VPN;
      hoy el estado sale de los equipos que lo terminan)*
**Fase 7 — Previsión**

- [x] `service.free_runs()`: las U libres como **tramos seguidos** y no como recuento. Doce U
      sueltas por todo el armario no admiten nada de 2U, y «12 libres» es la respuesta que manda
      a alguien con un servidor en las manos hasta un sitio donde no entra
- [x] `service.rack_capacity()`: hueco, tomas por rama, vatios de margen —contra la **mitad** de
      la capacidad, como en toda esta sección— y fondo
- [x] `service.where_fits()` y `/api/v1/dcim/fits`: qué armarios lo admiten y **por qué no** los
      que no. El «por qué no» es la mitad del valor: decide si hay que mover un equipo, pedir
      una regleta o comprar otro armario — tres problemas muy distintos con la misma pinta en
      una lista filtrada
- [x] Dos ramas por defecto: un armario que no puede dar dos ramas a un servidor de dos fuentes
      no es un armario donde ese servidor deba ir
- [x] Sin capacidad declarada **no se descarta** por vatios: sería descartar un armario por una
      casilla vacía
- [x] La ocupación cuenta la de todos: la U 12 está ocupada aunque lo que la ocupe sea de otra
      sociedad, y quien pregunta no ve qué es — pero sabe que no cabe
- [x] Entre los que valen gana el **hueco más ajustado**: meter un 1U en el tramo de veinte
      gasta el único sitio donde luego cabrá un chasis
- [ ] Previsión en el tiempo: «con este ritmo, cuándo se llena esta sala»

**Fase 8 — Dispositivos, módulos y componentes**

*Añadida después de las siete del plan original: al usar la sección se vio que faltaba decir QUÉ
es cada cosa de un armario y QUÉ lleva dentro, y que sin eso el catálogo importado no se puede
convertir en inventario.*

- [x] **El rol de cada equipo** (`dc_item.role`): servidor, switch, router, cortafuegos, cabina,
      panel de parcheo, panel de fibra, SAI, regleta, bandeja, KVM, consola y **tapa ciega**. No
      es un icono: de aquí cuelga que lo que no contesta **por naturaleza** deje de contarse como
      «sin vigilar» — un armario de cuarenta paneles salía con cuarenta desatendidos y ninguno lo
      estaba, y cuarenta deberes imposibles enseñan a saltarse la lista
- [x] **Los componentes** (`dc_part`): discos, memoria, CPU, tarjetas, HBA, GPU, fuentes,
      ventiladores, transceptores, baterías, módulos y **accesorios** —el cargador del mini-PC de
      la bandeja, que no es elegante y es lo que hay que reponer cuando desaparece—. Una fila por
      componente con **cantidad**, porque la pregunta es «cuántos discos de 4 TB tengo y en qué
      máquinas» y a una descripción no se le puede preguntar eso
- [x] El catálogo **sugiere** el rol a partir de los puertos del modelo: tomas sin interfaces es
      una regleta, puertos por delante y detrás sin alimentación es un panel, bahías de
      dispositivo es un chasis. Propone y no escribe — la biblioteca no trae el rol
- [x] Imágenes de alzado del catálogo, leídas de `elevation-images/` en la misma pasada
- [x] **Todo lo anterior con pantalla**: el catálogo entero, los cuadros y SAI, las filas, los
      enlaces entre sedes y la pertenencia estaban construidos y probados **sin un solo botón**.
      Queda una guarda que exige que cada ruta de escritura la llame alguna plantilla
- [x] **Descargar el catálogo de GitHub**, listando qué importar antes de traerlo. Y **sin bajar
      el repositorio**: pesa ochocientos cincuenta megas porque lleva una imagen de alzado por
      dispositivo, así que lo que se pide es el índice —una petición, tres megas de nombres— y de ahí
      salen los trescientos fabricantes con sus cuentas exactas sin descargar un solo modelo. Al
      importar se piden solo los elegidos, por una conexión que se abre una vez. La dirección es
      configurable (`web_admin|dcim_catalog_url`): la de NetBox viene puesta, pero un fork propio
      o un espejo interno valen igual
- [x] **Y las tres puertas**, porque son tres situaciones: de GitHub, **subiendo un zip** —esto es
      una aplicación web, y pedir una ruta del disco del servidor es pedir un acceso que quien
      administra desde un navegador no tiene por qué tener— y una carpeta del servidor para quien
      sí lo tiene. Con el catálogo como **vista propia** que el menú despliega, en vez de un botón
      en una barra de herramientas que desaparecía al abrir un rack
- [x] **Quitar**, que era la otra mitad que faltaba: un modelo, los marcados, o un origen entero.
      Importar reemplaza una importación **completa**, así que deshacer una equivocada era
      reimportar las otras para que se la llevara por delante — rehacer lo bueno para deshacer lo
      malo
- [x] **Las tres formas de la biblioteca**, cada una entrando como lo que es: dispositivos (6411),
      **tipos de módulo** (1957) —tarjetas de línea, transceptores, lo que va en una bahía— y
      **armarios** (140), con sus medidas exteriores y el peso que aguantan. Antes entraba todo
      como dispositivo: un transceptor ocupaba U en un alzado y un armario de 42U figuraba como un
      equipo de 42U
- [x] **Un catálogo básico dentro del panel**: armarios de los tamaños que existen, servidores,
      switches, paneles, regletas, SAI, bandejas y tapas ciegas genéricos. Un botón y ninguna
      descarga — para la primera tarde y para la sala sin salida a internet
- [ ] Que de un tipo de módulo salga un **componente ya relleno** en vez de tecleado
- [ ] Generar un equipo **desde un modelo del catálogo**: elegir el modelo y que salgan la altura,
      el fondo, el rol sugerido y sus componentes de fábrica
- [ ] Leer los esquemas de `schema/` de la biblioteca para validar lo importado y saber qué
      campos existen sin tener que deducirlos de los ficheros

**Fase 9 — Plantillas: del catálogo al inventario**

*Añadida al usar la sección con equipos de verdad. La cadena entera es*
**`marca → modelo del catálogo → plantilla → equipo del inventario`**, *y le faltaban los dos
extremos: arriba, una marca no era una cosa sino un texto repetido; y entre «lo que Dell vende» y
«la máquina del U 12» faltaba el escalón que de verdad se compra, una configuración con nombre. Sin él, los doce
DIMM, los ocho discos y la controladora de veinte servidores idénticos se teclean veinte veces —
y el día que el estándar pasa a DIMM de 64 GB no queda forma de saber cuáles eran los veinte del
anterior.*

- [x] **Las marcas, como filas** (`dc_brand`), que es la raíz de todo lo demás. Hasta aquí una
      marca era una **cadena de texto repetida ocho mil quinientas veces**: alcanzaba para agrupar
      una rejilla y para nada más. No había dónde apuntar por dónde se abre un ticket ni el número
      de contrato; renombrar «HP» a «Hewlett Packard Enterprise» eran ocho mil quinientos
      `UPDATE`; y dos formas de escribir el mismo nombre eran dos marcas que nadie podía juntar.
      El `slug` —el nombre normalizado— es la identidad, así que `HP`, `H.P.` y `hp` son **una**
      y reimportar no da de alta trescientas más
- [x] **Se dan de alta solas al importar.** Nadie va a teclear trescientas antes de traerse la
      biblioteca — y si hubiera que hacerlo, no se haría. Lo que se teclea es lo que ningún
      repositorio puede saber: la web de soporte, el número de cliente. Y por eso **no se retira
      la ficha de una que tenga modelos**: el nombre sigue en cada fila del catálogo y volvería
      sola en el siguiente arranque, así que lo único perdido sería justo eso
- [x] Y el orden queda dicho en la pantalla, que es donde se lee: las pestañas del catálogo van
      **Marcas · Modelos · Esquemas · Importar**, que es el orden en que existen las cosas. Antes
      había una pestaña «Catálogo» dentro de la vista «Catálogo», que no distingue nada
- [x] **Modelos de componente en el catálogo** (`tree='component-types'`): memoria, discos, SSD,
      CPU, tarjetas de red, HBA y RAID, GPU, fuentes. **Ninguna biblioteca pública los trae** —los
      `module-types` de NetBox son tarjetas de línea y transceptores, cosas que van en una bahía—
      así que se escriben una vez y se reutilizan siempre, que es justo para lo que sirve un
      catálogo propio
- [x] En `dc_type` y no en una tabla nueva: es la misma forma —fabricante, modelo, part number,
      descripción, imagen— y la pantalla del catálogo ya sabe agrupar por fabricante, filtrar,
      buscar, clonar, editar y borrar. Otra tabla sería otra pantalla haciendo las mismas nueve
      cosas, y la segunda copia es la que se queda atrás
- [x] La clase de una fila de ese árbol sale de `PART_KINDS` y no de `KINDS`: **el árbol dice qué
      vocabulario se aplica**. Un DIMM no es «switch, servidor u otro», y meterlo en la lista de
      los que ocupan U sería ofrecerlo en un alzado
- [x] **`dc_build`, la plantilla**: un nombre nuestro —«Servidor CPD estándar 2024»—, el modelo de
      chasis del catálogo, el rol, y lo que lleva puesto. Es lo que se compra, y no figura en el
      catálogo de ningún fabricante porque no lo vende nadie: lo componemos nosotros
- [x] **Un componente se ELIGE del catálogo, no se teclea.** Un SSD no es de esta plantilla ni de
      esta máquina: es un modelo que va en veinte. Escrito a mano en cada sitio son once formas de
      teclear «Samsung PM9A3» que no se pueden contar juntas — y contar juntas es la única
      pregunta que se le hace a esto. La marca, el nombre y el tamaño los resuelve **el servidor**
      desde el modelo; la bahía, la cantidad y el número de serie son de la pieza. Escribirlo a
      mano sigue estando, para el disco que salió del cajón, pero hay que pedirlo
- [x] Y **un solo formulario** para la plantilla y para la máquina: piden lo mismo, y dos serían
      dos sitios donde arreglar cada cosa — con el que se olvida siendo siempre el mismo
- [x] **`dc_build_part`**: una fila por componente, con **la misma forma que `dc_part`** —clase,
      bahía, modelo, tamaño, cantidad— y apuntando al modelo del catálogo cuando lo hay. La misma
      forma a propósito: crear un equipo desde una plantilla es copiarlas
- [x] **Se estampa, no se enlaza.** Al crear el equipo las piezas se **copian**, y desde ese
      momento son suyas. Si el equipo las leyera de su plantilla, el día que alguien saca un disco
      averiado no habría dónde decirlo, y editar la plantilla reescribiría la ficha de veinte
      máquinas que nadie ha tocado. Que una máquina se separe de su plantilla no es un error: es
      un hecho sobre esa máquina
- [x] **`dc_item.build_uid`: de qué plantilla NACIÓ**, que es distinto de lo que lleva hoy. Sin él,
      «cuáles son los veinte del estándar de 2024» no tiene respuesta; con él la tiene aunque a
      tres les hayan cambiado los discos
- [x] **Generar el equipo desde la plantilla** —lo que la fase 8 dejó pendiente contra un modelo
      del catálogo, ahora contra la configuración entera—: salen puestos la altura, el fondo, el
      rol y los componentes, y lo que queda por teclear es solo lo que tiene esa caja y ninguna
      otra
- [x] **El serial, la compra y la garantía viven en el equipo** (`dc_item`): fecha de compra, fin
      de garantía y proveedor. Ningún modelo ni plantilla puede saberlo — es de ESA caja
- [ ] Y la pregunta que ahora ya tiene dónde contestarse y todavía no se contesta: **qué se queda
      sin garantía este trimestre**, por sede y por empresa. Los datos están; falta la pantalla
- [x] **Lo que lleva contra lo que su plantilla decía**: de más y de menos. Misma forma que el
      contraste del cableado y el del consumo —lo declarado contra lo que se ve—, que es el eje de
      toda la sección: ninguna de las dos partes es «el error», la diferencia es el dato
- [x] **Los atributos de un componente**, que no son los mismos para un disco que para una CPU:
      formato, interfaz, RPM, zócalo, núcleos, alcance. En `dc_type.extra`, la misma columna JSON
      que las medidas de un armario — y la **lista de qué preguntar en un documento**
      (`data/component_profiles.json`, `dc_profile`), no en el código: once clases con cuatro
      atributos escritas en un `.py` son una lista que hay que publicar una release para tocar, y
      quien sabe qué formato tiene la tarjeta nueva casi nunca es quien toca el código. Manda la
      **versión más alta**, así que una actualización supera a un parche local y un parche local
      sigue en pie hasta que se publique algo más nuevo
- [x] **Los adjuntos de una ficha** (`dc_file`): el manual, la hoja de características, el zip
      del firmware, las condiciones de garantía. Hoy eso vive en la carpeta de alguien —o en un
      correo de hace tres años— y el día que hace falta es un martes a las once de la noche con
      una tarjeta que no arranca. **Sin lista blanca de tipos**, porque lo útil es abierto y una
      lista se queda corta cada semana; lo que lo hace seguro es que **siempre salen como
      descarga**, con tipo genérico y `nosniff`, así que el panel no renderiza nunca un fichero
      subido. La factura NO va aquí: un modelo es genérico y una factura es de la unidad que
      tiene número de serie — eso colgará del equipo del inventario, y para eso está `scope`
- [x] **La plantilla dice qué máquina sale de ella**, mientras se configura: los gigas, los teras
      en bruto, las CPU y sus núcleos, las fuentes y los puertos de red. Quince renglones de
      piezas no contestan «qué máquina es esta» sin sumarlos a mano, que es la pregunta con la que
      se abre esa pantalla. Y **lo que no se ha podido contar se dice**: una pieza escrita a mano
      no tiene ficha de catálogo y sus núcleos no se conocen — un total al que le faltan tres
      discos y no lo dice es peor que no dar el total, porque se cree
- [x] Y la ficha de cada clase, con lo que de verdad se mira: de una **CPU**, el segmento, los
      núcleos grandes y pequeños —`cores` a secas dejó de significar algo—, el turbo, la
      litografía, las cachés, qué memoria admite y cuánta, si lleva gráficos y si tiene gestión
      fuera de banda. Y de **cualquier componente**, el lanzamiento y el fin de vida: «¿esto
      todavía se compra?» y «¿esto tiene soporte?» se preguntan de un DIMM igual que de una CPU
- [x] **Lo que se vuelve a bajar, aparte de lo que no**: la carpeta de medios se parte en
      `library/` y `own/`. Mil doscientas imágenes de alzado se recuperan con un botón; la foto
      que alguien hizo con el móvil del armario que montó el electricista, no — y compartían
      carpeta, así que mirarla no decía qué se perdería. Es la misma línea que el catálogo traza
      con `source`, aquí trazada en el disco: de ella cuelga poder guardar lo propio sin
      arrastrar ochocientos megas. Los nombres planos de antes se siguen leyendo
- [x] **La pantalla vuelve donde estaba al recargar**: la pestaña, la vista, la forma, la clase,
      la marca y lo buscado van en la dirección. Ya se hacía con el armario y con el cuadro, y
      dentro del catálogo no: F5 devolvía a la rejilla de marcas con los filtros sueltos
- [x] **El historial de una ficha** (`dc_rev`): qué decía antes y **quién la cambió**. Un modelo
      del catálogo es un dato compartido, y la corrección que rompe algo se descubre semanas
      después. Volver a una versión es **un cambio más y no un deshacer**: si borrara lo de en
      medio, la respuesta a «quién dejó esto así» sería distinta según cuándo se preguntara
- [x] **Las cuatro formas, a la vista** y no en un desplegable entre los filtros: dispositivos,
      módulos, armarios y componentes, cada una con su cuenta, lo primero de la barra. Escondidas
      ahí, los componentes «no estaban» — para llegar a ellos había que saber que existía un
      filtro por forma, abrirlo y elegir, y una sección a la que hay que llegar adivinando es una
      sección que no existe. Elegir una que cabe en una página lleva a la **tabla** y no a la
      rejilla de marcas: esa existe porque ocho mil filas no se leen, y con cuarenta componentes
      es un paso de más para llegar a lo que ya cabía entero en la pantalla
- [x] **Pantalla**: las plantillas como **vista propia** que el menú despliega, junto a Inventario,
      Cuadro, Catálogo y Fuentes; y los componentes dentro del catálogo, en su filtro por clase,
      sin una pantalla nueva que mantener
- [x] Una plantilla dice **cuántos equipos han salido de ella y dónde están**, y borrarla con
      equipos vivos lo avisa. Un estándar de compra que no sabe a cuántas máquinas afecta es una
      nota en un documento, que es de donde se viene
- [x] Permiso propio (`dcim_build_edit`): **decidir el estándar de compra no es colocar una caja en
      un U**. Lo hacen personas distintas en momentos distintos, y con una sola bandera quien
      monta un rack puede rescribir lo que compra la empresa
- [x] **Una plantilla es un estándar de compra, no una lista de piezas.** Lleva `notes` —por qué
      se eligió ese chasis, qué se probó y no valía, con quién se negoció; eso vive hoy en un
      correo y el correo se pierde antes que el servidor—, **vigencia** (`valid_from`/`valid_to`:
      «el de 2024 se compró de enero a noviembre», que sin las dos fechas solo lo sabe quien
      estaba) y **adjuntos propios**, la misma tabla `dc_file` que los de un modelo, distinguidos
      por `scope`. Clonarla se lleva los comentarios y **no** las fechas: la copia se hace para el
      año que viene, y heredar «hasta noviembre de 2024» sería nacer caducada
- [x] **Las plataformas, como filas** (`dc_platform`): con qué sale un equipo — Debian, RouterOS,
      ESXi. Era una caja de texto dentro de cada plantilla, y veinte cajas de texto son «Debian
      12», «debian 12», «Debian GNU/Linux 12» y «deb12»: entonces «cuántas máquinas hay que
      actualizar» no tiene una respuesta, tiene cuatro y ninguna entera. Misma regla que las
      marcas —el slug es la identidad—, con su pestaña en el catálogo, y **no es solo de
      dispositivos físicos**: una máquina virtual corre RouterOS igual que un router de metal y
      pregunta lo mismo
- [x] **El resumen cuenta lo que el chasis trae de serie.** `summary()` sabía doblar sus puertos
      desde el principio; lo que faltaba era que la ruta los **pidiera** — la lista de campos del
      modelo base decía, en un comentario, que los puertos sobraban. Un campo que no se pide no
      da ningún error: da un cero que parece un dato, y el mini-PC con su puerto en la placa
      decía tener solo la tarjeta que alguien le añadió. Y **por dónde se alimenta** se deduce ahora del
      YAML (`power-ports` de continua = alimentador externo, de pared = fuente dentro,
      `poe_mode: pd`
      sin tomas = se alimenta por el cable de red), con un repaso que lo rellena en lo ya importado sin
      volver a descargar nada
- [x] **Las fechas de una vida son seis, no una.** Fin de venta, fin de mantenimiento, fin de
      parches de seguridad, última alta de soporte, última renovación y fin de soporte, en su
      propio bloque y **en rojo las que ya pasaron** — que es la única razón de agruparlas: seis
      fechas sueltas en una tabla se leen igual que seis fechas cualesquiera, y lo que hay que
      ver de un vistazo es cuál ya ocurrió. Van en el documento de perfiles, así que añadir «fin
      de venta en Europa» es editar un JSON
- [x] **Importar unos fabricantes no borra los demás.** El reemplazo alcanzaba a la fuente entera,
      y como la pantalla obliga a marcar fabricantes, traerse Dell decía —sin decirlo— que HP y
      Cisco habían dejado de existir. Ahora el borrado no sale de las marcas que las filas traen;
      bajarse la biblioteca completa sí sigue limpiando lo que arriba ya no está, que es lo que
      significa «completa»
- [x] **Los básicos, en un JSON** (`data/basics.json`) y no en el código: son datos —los tamaños
      de armario que se fabrican, las formas que repite cualquier sala, las plataformas que todo
      el mundo teclea— y añadir «Ubuntu 28.04 LTS» o el armario de 45U no puede ser publicar una
      versión. El módulo rellena lo que se repite (el fabricante genérico, el slug, el árbol) para
      que el fichero diga lo que distingue a cada fila y no diez veces lo mismo. Con él vienen las
      plataformas **con su edición** —Windows 10 y 11 en Home, Pro, Enterprise, Education, IoT
      Enterprise y Enterprise LTSC; Windows Server 2016 a 2025 en Standard y Datacenter; Debian 11
      a 13; Ubuntu 22.04, 24.04 y 26.04 LTS—, que no es un adorno: una LTSC y una Pro no se
      actualizan igual ni se acaban el mismo día
- [x] **Y una plataforma tiene ciclo de vida, con las mismas seis fechas.** Del mismo grupo del
      documento de perfiles y guardadas igual, en `extra`: un sistema operativo deja de recibir
      parches igual que un servidor deja de venderse, y dos listas serían dos que se separan el
      día que alguien añada una fecha a una de ellas
- [x] **La ficha de una plantilla se lee, y editar es un modo.** Se consulta muchas más veces de
      las que se corrige, y un formulario abierto es una pantalla en la que cualquier tecla cambia
      algo. Cancelar **relee**, para no dejar en pantalla como guardado lo que se descartó
- [x] **Y enseña el ciclo de vida del dispositivo**, que era lo que se buscaba: las dos fechas que
      había eran las del estándar de compra —desde cuándo y hasta cuándo se pide así— y quien las
      miraba quería las del equipo. Ahora son dos bloques con su título, **Vigencia del estándar**
      (nuestro, editable) y **Ciclo de vida del dispositivo** (del catálogo, de solo lectura: se
      corrige en la ficha del modelo, de donde cuelgan también las veinte máquinas que salieron
      de él)
- [x] **Las plataformas se leen en árbol**: fabricante → familia → edición. Una sola columna
      (`family`) lo hace; la hoja se calcula quitándole el prefijo al nombre, porque guardar la
      edición aparte sería guardarla dos veces con la posibilidad de que discrepen. Solo la
      lista: el desplegable de una plantilla sigue plano y con el nombre entero
- [x] **La pantalla de un armario, en dos columnas.** El alzado a la izquierda, a la
      proporción del dibujo; a la derecha una caja con cuatro pestañas —equipos, cableado,
      alimentación y los componentes del equipo abierto—. Antes eran tres tarjetas que se
      insertaban **encima** del dibujo y lo empujaban hacia abajo: se pulsaba un botón y lo que
      estabas mirando se movía. Y bajar a la lista dejaba el armario fuera de la pantalla, que es
      justo cuando hace falta — un cable va de una U a otra
- [x] Y el alzado **mide lo que mide el armario**. `.ss-infra-canvas` es `flex: 1 1 auto`, que es
      correcto para los dos mapas —ocupan lo que haya— y era lo peor aquí: el dibujo de cinco U
      mide ciento cincuenta píxeles y la caja crecía hasta el borde de la pantalla. Con
      `aspect-ratio` y no con una altura calculada, porque el ancho lo decide la columna y el
      dibujo no lo sabe
- [x] **La regleta que se coloca y la regleta donde se enchufa son la misma.** Una que ocupa un U
      es un equipo del armario; una donde se enchufa es una fila con ramas y tomas — y eran dos
      cosas sin relación, así que la que acababas de colocar no aparecía como sitio donde
      enchufar y encima se contaba entre los «sin enchufar». `dc_pdu` gana `item_uid`, y el panel
      **avisa** de la que está colocada y sin declarar, con un botón que la declara con su nombre
- [x] Sin unirlas solas: declarar una regleta es decir **de qué rama cuelga y cuántas tomas
      tiene**, y eso no está en el catálogo ni lo puede adivinar nadie. Y `item_uid` vacío sigue
      siendo lo normal — la mayoría van atornilladas al lateral y no ocupan U, que es por lo que
      no son la misma tabla
- [x] Y **«+ Regleta» pregunta cuál**, en vez de acuñar un `PDU-A` que no es de nadie. El aviso
      de arriba mira el rol, y lo que se coloca desde el catálogo nace **sin rol** —nadie ha
      dicho todavía qué es—, así que en el caso más normal de todos el aviso no salía y el botón
      seguía inventando una regleta que no era la tuya. Se elige de lo que hay colocado, sin
      depender de que alguien haya contestado antes la pregunta que se está haciendo ahora; la
      última opción es la que no ocupa ningún U
- [x] Cada regleta devuelve **de qué equipo es** (`item_uid` en `/power`). Sin eso la lista
      ofrece la misma dos veces, y la segunda crea una regleta duplicada del mismo cacharro con
      sus tomas contadas dos veces
- [x] **En qué toma.** La columna `outlet` existía desde el primer commit, la API la aceptaba,
      `power_of_rack` la devolvía y la tabla la pintaba —«PDU-A·7»— y **ningún camino la
      escribía**: valía siempre 0, que es «en esa regleta, no sé en cuál». Enchufar ofrece ahora
      las tomas, con las ocupadas apagadas, y una toma mal puesta se corrige sin quitar el cable
      —quitarlo se lleva por delante lo declarado que consume
- [x] Y «no sé en cuál» sigue siendo elegible: es lo que alguien sabe mirando la foto de un
      armario, y obligarle a inventarse un número es cambiar un hueco por un dato falso. El
      choque —dos cables en la misma toma, que es imposible— lo rechaza el servidor, que es
      quien ve los demás cables de la regleta
- [x] **Lo que no lleva enchufe no pide uno.** Una bandeja salía en la tabla de alimentación
      diciendo «No lleva enchufe» y con el botón de enchufar al lado: una respuesta y su
      contraria en la misma fila. Fuera de la tabla y **dicho aparte** en una línea, que es la
      misma decisión que el recuento de un armario con sus pasivos — esconderlo es lo que hace
      dudar de una lista. Salvo que alguien le haya declarado un cable: una fila que no se
      dibuja es un cable que no se puede ni ver ni quitar
- [x] Y **un cable ya declarado se puede partir**: los enlaces se apuntan primero de punta a
      punta —«el servidor va al switch», que es lo que uno sabe— y los paneles aparecen después,
      cuando alguien mira por dónde pasa de verdad. Sin esta operación, corregirlo es borrar el
      cable y escribir tres: se pierden la etiqueta, el color y las dos bocas, así que no se
      corrige y el inventario se queda diciendo que hay un latiguillo donde hay tres
- [x] Un panel cada vez, y se repite para el segundo. El cable de siempre se queda con el lado A
      —su etiqueta, su color, su boca— y el tramo nuevo va del panel al lado B; repartir la
      etiqueta daría dos cables llamados igual. Se crea el tramo nuevo ANTES de mover el viejo:
      al revés, un fallo a mitad deja el enlace acabando en el panel y sin salida
- [x] El panel se **busca** (`GET /api/v1/dcim/items?q=`), no se elige de una lista del armario
      abierto: casi nunca está ahí — vive en el de patcheo. Y se busca por etiqueta **y por
      modelo**: la mitad de lo que hay en un armario no está rotulado, y de eso lo único que
      alguien sabe es de qué modelo es
- [x] Cada fila de esa búsqueda vuelve con **con qué nombrarse** —etiqueta, máquina, modelo y
      rol—, que es lo que mira la función que nombra un equipo. Mandando sólo la etiqueta, la
      lista salía llena de identificadores: sexta vez que aparece esta forma en esta sección
- [x] **Un enlace que pasa por un panel de parcheo son tres cables y un camino.** El latiguillo
      al panel, el enlace fijo entre paneles y el latiguillo al switch: los tres se declaran
      —los tres son cables que alguien puede desenchufar— y ninguno se puede confirmar solo,
      porque un panel es un trozo de metal que no habla. Lo que sí se confirma es el **camino**:
      si los dos extremos se ven por LLDP y hay una cadena de cables declarados que los une a
      través de equipos pasivos, el enlace deja de salir como «sin declarar» y los tres tramos
      pasan a «Por el panel». Antes, la lista de trabajo pendiente incluía trabajo ya hecho, que
      es la forma más rápida de que nadie vuelva a mirarla
- [x] **Un cable es inventario.** `length_mm` y `description` existían desde el primer commit y
      **ningún camino las escribía**: valían siempre su valor por defecto. Y de qué categoría es
      —Cat 6A, OM4— no se podía decir en ninguna parte, que es el dato que decide si un enlace de
      10 Gb va a funcionar y lo que hay que mirar en la caja de repuestos antes de bajar al
      armario. Séptima vez que sale esta forma en esta sección
- [x] La categoría depende de **de qué está hecho** el cable: las de cobre no valen para una
      fibra, y ofrecer las diez juntas es ofrecer equivocarse. Las listas viajan con la respuesta
      (`CABLE_CATEGORIES`) y son **abiertas**: un fabricante que llame a lo suyo de otra manera
      no puede quedarse sin apuntarlo — un `<datalist>` sugiere, un desplegable obliga
- [x] Los metros se piden en **metros** y se guardan en milímetros: nadie mide un latiguillo en
      milímetros y todo el mundo lo compra en metros. Con **coma o con punto**: el campo era
      `type="number"` y en un navegador en castellano lo natural es teclear `0,2`, que según el
      navegador llega vacío — el cable se guardaba midiendo cero y sin decir nada. Y sin paso de
      una décima, que daba por inválido un latiguillo de 0,25. Lo que no es un número se dice, en
      vez de guardarse como cero: cero es una longitud y «no se sabe» es otra cosa
- [x] Y **un cable se puede corregir**. Se podía dar de alta y borrar, y nada más: sus datos se
      preguntaban una vez, al crearlo. Pero un cable se apunta con prisa —se está montando— y se
      completa después, con el metro en la mano; sin poder corregirlo, añadir los metros obligaba
      a borrarlo y reescribirlo entero. Las dos PUNTAS no se tocan ahí: mover una es otra
      operación, y ofrecerla junto a la etiqueta invita a rehacer el cableado creyendo que se
      corrige una errata
- [x] El camino dice **cuánto mide de punta a punta**, que es la suma de sus tramos: si el enlace
      entero pasa de los cien metros de cobre da igual lo bien declarado que esté, y eso no se ve
      mirando tres tramos por separado. Y dice **cuántos faltan por medir** — sumar sólo los
      medidos y enseñarlo como el total diría «0,25 m» de un camino de cuatro tramos
- [x] **Por dónde pasa, entero.** La fila decía «Por el panel» y ahí se acababa: cuál de los
      cuatro paneles de la sala y en cuál de sus veinticuatro posiciones había que reconstruirlo
      a mano cable a cable, que es tanto trabajo como ir a mirarlo — y es la pregunta que se hace
      delante del armario con el latiguillo en la mano. La ficha del cable enseña el camino de
      punta a punta, con el tramo abierto resaltado
- [x] Y **en el sentido en que se recorre**: un cable se declara desde el extremo que se tenía
      delante, así que la mitad de los tramos están escritos al revés y una traza que va
      «SRV → PP» y luego «SW → PP» no se puede leer. El sentido lo pone quien anduvo el camino
- [x] Con el **nombre y el sitio de cada punta** pegados al tramo: un camino sale del armario
      abierto y nombra equipos que la pantalla no tiene delante — y «PP-A 25» no dice adónde hay
      que ir, así que va el armario y la U. De lo AJENO no se dice dónde: llega opaco a propósito,
      y decir en qué armario está sería contar qué hay en la sala de otro por la puerta de al lado
- [x] Y se **dibuja**: una cadena de paradas con el cable entre ellas, cada tramo con su
      etiqueta, su categoría y sus metros, y el que se tiene abierto marcado. Se dibujan las
      PARADAS y no los tramos: una lista de tramos repite cada parada dos veces —final de uno y
      principio del siguiente— y emparejarlas de cabeza es el trabajo que el dibujo ahorra
- [x] **Un puente en el mismo panel es un cable de verdad.** Un latiguillo corto de la boca 25
      a la 17 del mismo panel es lo más normal del mundo, y se rechazaba con «un cable va de un
      equipo a OTRO» — cierto para dos servidores y falso para un panel, que es media sala. Se
      acepta si va de una boca a **otra**, y esa regla vive ahora también en el servidor: sólo en
      el navegador es lo mismo que en ninguna parte
- [x] Y el camino se anda **por bocas y no por equipos**: lo que entra por la 12 sale por la 12,
      que es la misma posición vista por el otro lado. Andando por el panel entero, cualquier par
      de cables que lo tocaran quedaba «confirmado», y entonces la palabra deja de querer decir
      nada. Con esto un puente encaja sin ninguna regla nueva —es un cable como los demás— y sin
      bocas escritas se vuelve a lo de antes, que es exactamente lo que se sabe cuando nadie las
      apuntó
- [x] **Sólo por lo pasivo**: atravesar un switch sería inventarse un cable —dos máquinas
      enchufadas al mismo switch no están enchufadas entre sí— y atravesar un equipo ajeno sería
      confirmar un camino a través de algo que no se puede ni mirar. Un ajeno llega sin rol, así
      que el recorrido se para en él por sí solo
- [x] Y **cruza armarios**, que es donde están los paneles de verdad: se piden los cables de cada
      panel visible que se va alcanzando, con tope de tres saltos — un recorrido sin tope
      convierte un ciclo declarado por error en una consulta que no termina
- [x] **Seis veces el mismo aviso es un aviso, no seis.** Seis equipos colgando de la rama A
      eran seis renglones idénticos salvo el nombre, y lo que dicen es UN hecho: de esa rama
      cuelga todo. Media pantalla justo encima de la tabla que se venía a mirar — y una lista de
      avisos que hay que saltarse deja de leerse, que es lo contrario de para lo que está. Se
      agrupan **por rama** (colgar de la A y colgar de la B no se apagan con el mismo corte) y
      con un tope de nombres. Las cargas no se agrupan: cada una es una regleta con su
      porcentaje, y juntar dos cifras distintas sólo se puede hacer perdiendo las dos
- [x] **La tabla de cables sale antes que su contraste.** Lo declarado se lee de la base y está
      en milisegundos; comprobarlo hay que armarlo recorriendo la flota entera. Son dos
      peticiones (`?check=1`), y entre las dos la pestaña ya tiene sus filas
- [x] Y mientras llega, la columna dice **«comprobando»** y no «no se ve». `edges=None` es *no se
      ha preguntado* y `edges=[]` es *preguntado y no hay nada*: sin esa diferencia la lista
      rápida repartía veredictos sin haber mirado, que es la misma forma de fallo que un 403
      contado como «el dispositivo no ha dicho nada»
- [x] **Las cuatro listas de un armario se dibujan igual.** Son cuatro vistas del mismo
      armario, se leen una detrás de otra y se miran juntas: una que salga a otro tamaño no
      parece otra tabla, parece otra pantalla. La de equipos iba a `ss-fs-3` y las de
      alimentación y cableado al tamaño de fábrica, con lo que «Tomas libres» se partía en dos
      líneas y cada fila medía dos. Una constante (`_DC_TBL`) y no seis copias
- [x] **La pestaña de cableado no paga el mapa entero.** De todo el mapa aquí se leen sólo los
      enlaces `lldp` —lo que dos dispositivos dicen verse el uno al otro— y armarlo entero
      incluye leer **enteras** las cuatro tablas de lo que cada equipo ha visto pasar, la de MAC
      la primera y sin cota. Se leían y se tiraban en cada apertura: una pregunta sobre UN
      armario pagando el inventario de direcciones de la flota. `topology(evidence_kinds=())` lo
      deja pedir sin ellas, y el mapa —que sí las usa para colocar una máquina en el puerto de un
      switch— las sigue leyendo
- [x] Las bocas que dicen los dispositivos salen **apagadas** en la tabla, con un interruptor
      para verlas. En una fila que cuadra son las mismas que ya están dos columnas a la
      izquierda, y en un agregado son ocho nombres largos que empujan el resto. Donde sí
      significan algo —cuando NO cuadran— salen siempre: son la respuesta a «¿entonces dónde
      está enchufado?»
- [x] Y el mapa de la flota leía **dos veces** la tabla de estado, con dos nombres y a doce
      líneas de distancia — justo debajo del comentario que explica que es una de las dos
      lecturas caras del camino y que por eso se hace de golpe. No daba ningún error: daba una
      pantalla que tardaba el doble de lo que su propio comentario explicaba
- [x] **Por detrás, el orden se invierte.** Un armario visto por la espalda tiene la izquierda
      donde tenía la derecha, y los dos mini PC de una bandeja salían en el mismo orden en las dos
      caras. No es una preferencia de dibujo: quien va con un destornillador a la parte de atrás
      encuentra el primero a la derecha, y un alzado que dice lo contrario le hace desenchufar el
      que no era. Vale igual para dos equipos de media anchura compartiendo un U
- [x] Y **en vertical no se toca**: la U 5 es la U 5 por delante y por detrás, porque el número
      está serigrafiado en los dos mástiles. Sólo se da la vuelta a lo horizontal, que es lo que
      cambia al rodear el armario — y lo hace `_dceFlipX`, una sola función, porque lo horizontal
      se reparte en dos sitios y el que se quedara sin ella dibujaría media bandeja al revés que
      la otra media
- [x] **Una fila que son cuatro cables lo dice, y se puede abrir.** Un agregado entre el router
      y el switch es UN cable declarado y CUATRO latiguillos, y salía como «Router01 — SW01 ·
      Coincide»: sin bocas y sin número, que es justo el caso que más hay que mirar — el día que
      se caiga uno de los cuatro, la pantalla que existe para contarlo sigue en verde. La fila
      lleva su recuento y se pulsa para ver la ficha, con **lo declarado y lo visto uno al lado
      del otro**: enseñar sólo una de las dos convertiría esta pantalla en la otra
- [x] **Las pestañas dicen lo que tienen desde el primer dibujado.** Los recuentos salían de los
      datos de cada pestaña, así que estaban en blanco hasta que alguien entraba — y una pestaña
      sin número parece una pestaña vacía, que es la respuesta contraria a la que se busca.
      Ahora vienen con el armario (`counts`)
- [x] Y el de alimentación **contaba las ramas**: la respuesta traía un `feeds` que eran `a`, `b`
      y ninguna, y el contador lo leía como si fueran cables — un armario sin un solo cable
      declarado enseñaba un «3». La clave se llama `feed_kinds` y el número sale de los cables de
      cada equipo. Un número sacado de una lista de otra cosa no da ningún error: da una cifra
      creíble
- [x] El cableado enseña además, en ámbar, **lo que falta por apuntar**: sin eso, un armario con
      tres enlaces descubiertos y ninguno declarado enseña la misma pestaña que uno terminado
- [x] **El descubrimiento propone; lo que manda es lo apuntado.** Cada enlace que los
      dispositivos ven y nadie declaró trae un botón que lo declara con sus dos extremos y sus
      dos bocas. No se escribe solo, y no por prudencia: lo visto es *lo que hay ahora* y lo
      declarado es *lo que tiene que haber*; si el panel apuntara lo que ve, las dos cifras
      serían la misma y el contraste no podría decir nunca «esto se movió»
- [x] Y no se inventa una boca: un agregado dice varios nombres por lado, y elegir el primero
      escribiría el cable en una boca que nadie ha dicho que sea ésa
- [x] **La tabla y el dibujo leen en el mismo sentido.** La lista ordenaba «de la U más alta a
      la más baja», que sólo coincide con el alzado cuando el armario numera del suelo al techo.
      En uno numerado al revés —la U 1 arriba, y eso va serigrafiado en el mástil— el dibujo
      bajaba del 1 al 6 y la tabla del 6 al 1: ninguna de las dos equivocada por su cuenta, y las
      dos imposibles de leer juntas, que es lo único que se les pide. La regla de la numeración
      vive ahora en `_dcimUFromTop`/`_dcimUAtRow` y en ningún otro sitio — colocar una caja, leer
      dónde se soltó y ordenar la lista son la misma pregunta
- [x] **Un panel keystone se compra vacío**, así que lo que lleva no puede salir del modelo: el
      modelo dice cuántos huecos hay y cada panel dice qué hay puesto en cada uno. Va donde ya
      viven las piezas de un equipo (`dc_part`), con una clase propia — `jack`, que no es «lo de
      dentro» ni «lo que cuelga», es lo que **puebla** el hueco. Y como es una clase de
      componente, los conectores se declaran una vez en el catálogo y se reutilizan, igual que
      los transceptores
- [x] Y los huecos salen del **modelo del equipo** y no solo de su plantilla: un panel de
      parcheo no nace de ninguna —no tiene estándar de compra ni componentes que estampar—, así
      que en su ficha nunca había lista y siempre había que teclear el nombre del hueco, que es
      de donde salen `hueco 7`, `Hueco-7` y `7` para el mismo sitio. Si el modelo solo dijo
      cuántos, se numeran **con la misma función que siembra el editor de plantillas**: dos que
      numeren por su cuenta acaban numerando distinto, y entonces el 7 de la plantilla y el 7
      del equipo dejan de ser el mismo
- [x] **Un armario no puede ser un panel de parcheo.** La ficha del catálogo tenía dos casillas
      seguidas rotuladas «Tipo» —la rama y el rol— y la segunda ofrecía «panel de parcheo»
      aunque la primera dijera «Armario», porque caía al respaldo de «todas las clases». El
      resultado es un panel escrito como modelo de armario: no sale al buscar un modelo para
      colocar en un rack, y no tiene dónde declarar sus puertos. `kinds_for('rack-types')` es
      ahora vacío —un armario ya dice su forma en `form_factor`—, la casilla desaparece cuando
      no hay nada que ofrecer, y la primera se llama **«Qué es»**
- [x] Y una ficha ya guardada en la rama equivocada **lo dice**, con un botón que la mueve sin
      perder el rol: quitar la casilla arregla las de mañana, no las de ayer, y a las de ayer no
      les quedaba ni el sitio donde se veía el error
- [x] `4-post-frame` es lo que escribe NetBox, no una frase. La lista de formas era la única del
      catálogo que se saltaba el traductor de valores; y la casilla `desc_units` salía con el
      nombre de su columna en medio de un formulario en castellano
- [x] Y un equipo se llama **igual en las cuatro pestañas**. Alimentación y cableado recibían
      `label` y nada más —lo rotulado por delante, vacío en la mitad de lo que hay en un
      armario— y pintaban «Equipo» tres veces seguidas. El navegador ya tenía el nombre entero
      delante: `_dcimNameOf` busca la fila y la nombra por donde la nombran la lista y el alzado
- [x] La ficha de un equipo enseña el **nombre** del modelo y de la bandeja sobre la que va,
      no sus identificadores. El armario manda el nombre del modelo en `type_name` y la casilla
      lo buscaba en `type_uid_name` por convención: no falla, se queda con los treinta y seis
      caracteres que la casilla existe para no enseñar. El campo declara ahora dónde está
      escrito (`nameKey`), y una guarda comprueba que sea una clave que el armario manda
- [x] **No todo lo que se coloca tiene plantilla.** Una tapa ciega, una regleta, una bandeja y
      un panel de parcheo no tienen estándar de compra ni componentes que estampar, y hasta ahora
      había que declararles una plantilla para poder ponerlos — que es pedir el estándar de una
      tapa. La ficha de un equipo elige también un **modelo del catálogo**, y de él sale lo único
      que la biblioteca sabe de verdad: cuánto mide, que es el dato del que depende que quepa. Lo
      tecleado sigue mandando: quien acaba de medir la caja con un metro sabe más
- [x] Y ese modelo **se busca**, no se elige de una lista: el catálogo son miles de filas. En la
      casilla queda el nombre y en la tabla el identificador — que es lo que sigue siendo cierto
      el día que alguien corrija el modelo. A diferencia de la plantilla, se puede cambiar después:
      no estampa nada, dice de qué modelo ES
- [x] Y un equipo **sin etiqueta ya no sale con su identificador por nombre**. `_dcimItemName`
      decía desde el principio que treinta y seis caracteres de uid no son nada, y acababa en
      ellos porque no había nada mejor: con una plantilla siempre había un nombre. Ahora el orden
      es etiqueta → máquina → modelo del catálogo → clase, y el uid recortado como último recurso,
      que es lo único para lo que sirve — distinguir dos filas
- [x] **Un armario tiene historia.** Se guarda una foto de él —lo que hay dentro, dónde y con
      qué número de serie— **después de cada cambio**, sobre `dc_rev`, la misma tabla que ya
      guarda las versiones de un modelo del catálogo y de una plantilla: su `scope` nació para
      esto. De ahí salen las dos preguntas que se le hacen a un armario con un año de vida —
      **cómo estaba** en una fecha (la foto) y **qué le pasó** (la diferencia con la anterior)—
      sin dos mecanismos que mantener de acuerdo sobre qué cuenta como un cambio. Al revés no
      funciona: de una lista de acontecimientos no se reconstruye un estado sin reproducirlos
      todos, y basta que falte uno para que la reconstrucción mienta sin decirlo
- [x] Un equipo que se mueve es **un** cambio y no dos: se casan por identificador y no por
      posición, porque contarlo como una baja y un alta convierte «moví el switch una U» en dos
      líneas que no se entienden juntas. Y mudarlo de armario deja foto en **los dos**: para el de
      origen se fue, para el de destino llegó
- [x] Guardar sin cambiar nada **no es una versión** —un formulario manda la ficha entera cada vez
      que se pulsa guardar—, y la más antigua no se compara contra el vacío: diría que llegaron
      seis equipos, y lo que pasó es que ahí empezó a guardarse. El cableado y la alimentación no
      entran: enchufar un latiguillo generaría una versión del armario, y un historial donde nueve
      de cada diez renglones son ruido es uno que nadie abre
- [x] Y **una bandeja no está «sin enchufar»**: es que no lleva enchufe. El servidor ya se saltaba
      su aviso de rama única —«no es un fallo: un panel de parcheo no come»— y la pantalla no
      tenía con qué saberlo, así que le pedía un enchufe a una bandeja. Los roles que no comen son
      los mismos que ya no figuran entre los «sin vigilar» (`ROLES_MUDOS`), y viajan con la
      respuesta en vez de copiarse en el navegador
- [x] **El armario se entera de lo que pasa fuera.** El estado de cada equipo viaja con la carga
      del armario, así que recoger datos de una máquina en Infraestructura y volver aquí dejaba el
      aviso puesto hasta un F5. Ahora hay botón, y volver a la sección lo pide solo — en
      `shown.bs.tab` y no en `renderDcim`, que se llama en cada redibujado interno
- [x] **El número de serie se lo puede preguntar al dispositivo.** Está en una pegatina detrás
      del rack y el equipo lo dice por SNMP si su perfil lo publica: el rol `serial`, que ya
      recogían MikroTik, APC, Linksys y Synology, y ahora también el perfil estándar
      `entity_physical` (ENTITY-MIB) para todo lo que no tiene perfil propio. Un botón en la ficha
      lo pide y lo **ofrece**: la misma regla que la sugerencia de modelo del catálogo, porque un
      número puesto solo es un número que nadie ha comprobado y que a partir de ese momento parece
      comprobado. Con varios —un switch apilado tiene varios chasis— se enseñan y se elige
- [x] En un **Linux o un Proxmox** ese número no sale de ninguna MIB: `sysDescr` da el kernel y
      nada más, y net-snmp no sirve ENTITY-MIB. Sale del DMI a través de una directiva `extend` de
      `snmpd.conf`, que es lo que lee el perfil `ucd_extend` — ya incluido en el grupo de Proxmox.
      Las cuatro que espera, con el subárbol numérico que recorre:

      ```
      extend .1.3.6.1.4.1.2021.7890.1 distro   /usr/bin/distro
      extend .1.3.6.1.4.1.2021.7890.2 hardware /bin/cat /sys/devices/virtual/dmi/id/product_name
      extend .1.3.6.1.4.1.2021.7890.3 vendor   /bin/cat /sys/devices/virtual/dmi/id/sys_vendor
      extend .1.3.6.1.4.1.2021.7890.4 serial   /bin/cat /sys/devices/virtual/dmi/id/product_serial
      ```

      Sin ellas el perfil no llega ni a engancharse —su sonda es `…7890.1.1.0`— y la máquina no
      dice nada, que es distinto de no tener número
- [x] Y con las directivas puestas puede seguir faltando **sólo el número de serie**, que es el
      caso que se ve en un Proxmox: `product_name` y `sys_vendor` los lee cualquiera y
      **`product_serial` sólo lo lee `root`**. Con `snmpd` corriendo como `Debian-snmp`, `cat`
      contesta `Permission denied`, y el perfil **descarta esa lectura a propósito** (`skip`):
      guardar el texto del error como número de serie sería peor que no guardar nada. El efecto
      es que el equipo cuenta `os`, `model` y `vendor` y calla el serial — que es exactamente lo
      que el botón dice ahora, y por eso lo dice así.

      Se comprueba en un comando desde el propio nodo:

      ```
      snmpwalk -v2c -c <comunidad> localhost .1.3.6.1.4.1.2021.7890.4.3.1.1
      ```

      Si contesta `Permission denied`, la salida es leerlo con permisos:

      ```
      # /etc/snmp/snmpd.conf
      extend .1.3.6.1.4.1.2021.7890.4 serial /usr/bin/sudo /usr/sbin/dmidecode -s system-serial-number

      # /etc/sudoers.d/snmpd
      Debian-snmp ALL=(root) NOPASSWD: /usr/sbin/dmidecode
      ```

      `chmod` sobre el fichero de `/sys` no vale: sysfs se rehace en cada arranque
- [x] **Lo que va sobre una bandeja se dibuja dentro de ella.** «Bandeja (+2)» era lo que se
      podía decir sin sitio: un recuento no enseña cuál de los dos mini PC está en aviso, que es
      justo lo que se viene a mirar. Cada uno con su color de estado y su foto si el catálogo la
      trae, y la bandeja conserva un hueco a la izquierda para su propio nombre
- [x] Y se reparten con **los mismos cuatro campos** que dividen un U —`u_slots`, `u_slot`,
      `u_slot_span`, `u_split`— aplicados al hueco del padre. Estaban en la ficha y se guardaban
      desde el primer día: lo único que faltaba era leerlos, así que no hubo migración. **O lo
      dicen todos o lo reparte el dibujo**: con uno que diga «la mitad derecha» y otro que calle,
      el segundo valdría «entera» y saldría encima del primero; cuando no lo dicen todos se
      reparten a partes iguales en su orden, y eso no se escribe — el día que alguien lo diga,
      manda lo que diga
- [x] Y el servidor **comprueba ese trozo**, que hasta ahora se guardaba sin mirarlo: dos mini PC
      podían decir los dos «1 de 2». Comparado en fracciones, porque los hermanos no tienen por
      qué contar igual — `1 de 2` y `2 de 3` se pisan sin compartir ningún número
- [x] **El dibujo y la lista se señalan.** Pasar por una U enciende su renglón en la tabla, y
      pasar por un renglón enciende su U. El alzado dice dónde está y la tabla qué es: sin unirlos
      hay que buscar a mano en la segunda lo que se acaba de señalar en el primero
- [x] Y la tarjeta de la lupa **está fuera del dibujo**, debajo y con su hueco reservado. Dos
      intentos de meterla dentro taparon una U cada uno —pegada abajo ocultaba la última, saltando
      al otro extremo ocultaba la primera— y el error era la premisa: dentro de un armario dibujado
      no hay sitio libre, porque el armario ocupa el dibujo entero. El hueco se reserva aunque no
      haya nada señalado, o el dibujo daría un salto cada vez que el ratón entra y sale de una caja
- [x] Los botones del lienzo —acercar, alejar, ver el armario entero, llevárselo en PNG o SVG—
      en una **barra encima del dibujo**, que es sobre lo que actúan. En la barra del armario
      estaban entre los que crean y borran cosas, que es donde nadie los busca; flotando sobre el
      lienzo tapaban parte de lo que manejan
- [x] Y **el armario se agranda tapando la lista**, no moviéndola: pasa a primer plano y ocupa
      lo visible. La diferencia entre apartar algo y taparlo es que lo primero obliga a devolverlo
      a su sitio para volver a donde estabas, y lo que se pide es sitio para mirar un armario un
      rato, no una pantalla distinta. Un botón y no una regla automática — una pantalla que se
      recoloca sola es una que se mueve mientras la miras. Al agrandar se reencuadra, porque el
      mismo trozo en un hueco del doble es no haber agrandado nada; y el panel deja de
      desplazarse mientras tanto, que es lo que hace que la capa mida exactamente lo que se ve
- [x] **Un botón que tarda dibuja su hueco antes de pedir nada.** Cableado y alimentación hacían
      `await` y redibujaban después: entre el clic y la respuesta la pantalla no cambiaba, el
      botón parecía muerto y se volvía a pulsar. Ahora sale el esqueleto —la forma de lo que
      viene, que además evita el salto cuando llega
- [x] Y la tabla de equipos dice **lo que el dibujo no puede**: número de serie, de inventario y
      hasta cuándo tiene garantía, con la vencida en rojo. Las cuatro columnas de antes repetían
      el alzado de al lado con menos
- [x] **El formulario de inventario, en un cuadro y con rótulos.** Eran dieciocho cajas en
      crudo, del ancho que cupiera, diciendo qué eran sólo en su `placeholder` — que desaparece
      en cuanto se escribe. Y empujaba hacia abajo lo que se estaba mirando, que es lo que se
      venía a editar
- [x] Y **guardar dice por qué no guarda**: la comprobación era `el primer campo del tipo`, que
      en un equipo es la etiqueta — la que casi nadie rellena el primer día. Se colocaba una
      máquina con su serie, su plantilla y su fecha de compra, se pulsaba Guardar y no pasaba
      nada: ni error, ni fila, ni pista. Ahora lo obligatorio **lo declara el campo** (`req`), un
      equipo no tiene ninguno —una caja ciega que ocupa un U es un dato de pleno derecho— y lo que
      falte se dice por su nombre
- [x] **Una lista cerrada se elige, no se teclea.** Elegir una plantilla dejaba el uid escrito en
      la caja: treinta y seis caracteres que no dicen nada. Las plantillas, las máquinas, las
      filas y las bandejas son desplegables —se ve el nombre, se guarda el uid—; las zonas
      horarias siguen siendo texto con sugerencias, que es lo que permite pegar una que esta
      instalación no conozca. Un valor que ya estaba y no sale en la lista se conserva: si no, un
      equipo enganchado a una máquina que este rol no ve se guardaría desenganchado por el solo
      hecho de abrir su ficha
- [x] Y `asset` (nº de inventario) y `description` **ya se pueden escribir**: dos columnas de
      `dc_item` que se guardaban, se devolvían y ningún formulario rellenaba. Cuarta vez que sale
      esta forma de fallo aquí, y ahora hay una guarda que compara el `TableSpec` con los campos
- [x] **Un conector se puede añadir y corregir desde donde se echa en falta.** La lista era de
      solo lectura y remataba diciendo que para añadir uno hay que editar `connectors.json` — que
      fue verdad y llevaba tiempo sin serlo: el editor del documento existía, en la tarjeta de la
      pantalla de esquemas, que es donde no va a buscarlo quien descubre que le falta el suyo
      buscándolo en la lista. Ahora la lista tiene su botón y la ficha de un conector lleva al
      formulario, filtrado por él: en ciento y pico filas, eso es la diferencia entre editar el
      tuyo y buscarlo
- [x] Y **un conector puede llevar una foto**. Los dibujos son uno por *forma* —una C13 y una C15
      son la misma boca— y eso vale para los que vienen con el panel; al que alguien añada no se
      le parece ninguno, y nadie va a escribir un SVG para la regleta de su rack. La foto manda
      sobre el dibujo donde la hay (al revés no serviría: un conector añadido tiene forma `other`,
      que es justo el enchufe genérico). Se sube **en un solo paso** —el fichero y el documento a
      la vez— porque en dos hay un hueco por el que se queda un fichero al que no apunta nadie
- [x] Y la fila del formulario **dice qué es, no lo dice todo**: diez columnas de formulario no
      entran en ningún diálogo, y ensanchar el cuadro hasta que quepan es perseguir el ancho de la
      pantalla de otro. La fila contesta cómo se llama, de qué tipo, qué cara tiene y en qué
      casillas se ofrece; la letra pequeña —a cuánto va, qué generaciones caben, qué puede llevar
      y qué es— se pliega, con el galón diciendo si hay algo dentro. De los ciento veintiocho, casi
      ninguno tiene nada de lo segundo
- [x] El formulario del documento gana **filtro, forma y nota**. El filtro conserva la posición
      real de cada fila: lo que se escribe escribe en `doc.connectors[i]`, y renumerar editaría el
      conector de al lado sin decirlo. Lo que aún no tiene identificador no se esconde nunca — una
      fila que no se ve es una fila que no se puede terminar
- [x] **Pulsar la línea de una plataforma abre su ficha**, de solo lectura. La tabla enseña
      cinco columnas —nombre, clase y las tres fechas que deciden algo hoy— de los quince campos
      que tiene, así que para leer los otros diez había que abrir el formulario; y abrir el
      formulario para leer es la forma de cambiar algo sin querer. Del mirar se pasa al escribir
      con un botón, que es el orden en el que ocurre de verdad. Las fechas las pinta la misma
      función que las de un modelo del catálogo —un sistema operativo deja de recibir parches
      igual que un servidor deja de venderse— con el rótulo como único parámetro
- [x] Y los básicos traen **las fechas que el fabricante publica**, escritas solo al crear la
      fila. Donde no hay UNA fecha honesta —el canal anual de Windows 11 marca una por versión—
      no se pone ninguna y se dice por qué
- [x] **El JSON de básicos se relee cuando cambia** y **habla los dos idiomas**: un texto puede
      ser una cadena o `{"es_ES": …, "en_EN": …}`, y se elige idioma **al sembrar** porque lo que
      sale de ahí se copia a una fila que sobrevive a la sesión. El slug no sigue al idioma —es
      la identidad— así que sembrar en castellano y en inglés no crea dos catálogos
- [x] **Dos cosas en un mismo U.** La rejilla daba por hecho un elemento por U y eso deja fuera
      el patch panel de 0,5 U, los dos mini PC del kit y la bandeja de ocho Raspberry. Un solo
      mecanismo: en cuántas partes se divide el U (`u_slots`) y cuál se toma (`u_slot`), con las
      fracciones comparadas **con enteros** —un tercio no existe en coma flotante— y `u_split`
      diciendo si se parte a lo ancho o a lo alto, que es lo que el dibujo necesita saber
- [x] **Y montado sobre otro** (`parent_uid`): los mini PC sobre una bandeja. El U lo paga ella;
      ellos heredan dónde está, un solo nivel, y no se retira lo que lleva algo encima
- [x] **La ficha de una plantilla, por pestañas**: Resumen · Componentes · una por familia
      de puerto · Adjuntos · Historial, con
      la cuenta de lo que hay detrás de cada una. **Puertos** es nueva y el dato ya estaba: lo que
      trae el chasis y lo que suma con lo que se le pone, juntos porque la pregunta es una. Y el
      chasis enseña **las dos caras** — por detrás es por donde se enchufa
- [x] Y lo que **ocupa** no es lo que mide: con el U compartido, `1 U · 1/2`, dicho igual en la
      lista y en la ficha porque lo calcula la misma función
- [x] **La plantilla copia del catálogo y deja de depender de él.** Leía en vivo la ficha del
      modelo, y eso la deja enseñando huecos el día que alguien lo retira o reimporta la
      biblioteca —que regenera los `uid`—. Misma regla que entre una plantilla y un equipo, un
      escalón más arriba: **se estampa, no se enlaza**. Elegir un modelo es traerse lo suyo
      —medidas, ventilación, alimentación, puertos, fechas e **imágenes copiadas de verdad**—;
      cambiar de modelo vuelve a traerlo todo; guardar la ficha, no. Y por eso los puertos y las
      fechas se editan **en la plantilla**, que es donde se está mirando
- [x] Y el tope de 8 MiB del cuerpo de una petición, que rechazaba un fichero que el propio panel
      decía aceptar: dos topes para la misma pregunta son dos respuestas
- [x] **Y lo copiado, también en las plantillas que ya estaban.** Las columnas son nuevas y
      `ADD COLUMN` no puede inventarse el valor: una plantilla escrita antes se quedó sin
      fotos, sin medidas y sin puertos en cuanto dejaron de leerse en vivo. Se rellenan
      desde su modelo la primera vez que se abre la pantalla, **solo los huecos** y solo si
      el modelo sigue existiendo — un arreglo que pisa lo corregido a mano es peor que el
      fallo
- [x] **Una pestaña por familia de puerto**: interfaces, tomas de entrada, tomas de salida,
      consola, frontales, traseros, bahías de módulo, bahías de dispositivo. Nueve
      familias en un cajón llamado «puertos» obligaban a leerlas todas para contar dos
      tomas, y quien busca las bahías de módulo de un chasis no busca «puertos». **Solo
      las que tienen algo** —una pestaña vacía es un sitio al que se entra para nada— y
      todas mientras se escribe, o no hay dónde añadir la primera de una familia que aún
      no tiene ninguna
- [x] Y se puede **escribir sin volver a la primera pestaña**: «Editar» salía solo en
      Resumen, así que el botón de añadir un componente no aparecía nunca y los puertos se
      podían mirar y no corregir. Un componente no necesita ese modo —se guarda solo—; los
      puertos sí, y ahora lo tienen donde se editan
- [x] Y **«mi equipo no es así» deja de ser un desplegable**: era una excepción que corregía
      al catálogo, y desde que la plantilla copia son sus medidas. Esconderlas era esconder
      lo que la tarjeta de al lado está enseñando
- [x] Y **se pregunta lo mismo que en el catálogo**: la ventilación y el peso los declara el
      documento de perfiles y estaban servidos solo allí, así que una plantilla los enseñaba
      y no había forma de corregirlos aunque el dato sea suyo desde que se copia. Un
      renderizador de campos, no dos
- [x] **Las fotos de una plantilla se cambian en la plantilla.** Llegan copiadas, y copiadas
      quiere decir suyas: la del catálogo es la del chasis desnudo y la de aquí puede ser la
      del equipo montado. Y en un marco de tamaño fijo, que si no cada cara sale a su
      proporción y las dos del mismo equipo se ven de tamaños distintos
- [x] «Cambiar» y «Limpiar» fuera de la tarjeta: traerse lo del catálogo es una acción de la
      ficha —arriba, con guardar— y **«cargar del catálogo** es lo que hace. Limpiar vaciaba
      el vínculo y dejaba lo copiado, que es media cosa
- [x] **Historial de una plantilla**, en la misma tabla que el del catálogo (`dc_rev`, con su
      `scope`). Una plantilla es un dato compartido igual: de ella salieron veinte máquinas.
      Poner un componente cuenta como cambio —«¿desde cuándo lleva ocho discos?» es la
      pregunta— y volver a una versión **no** reescribe los componentes: de ellos cuelgan los
      ya estampados en los equipos
- [x] Y la columna **Plataforma** de la lista, que salía llena o vacía según por dónde se
      hubiera pasado: la ficha pedía la lista de plataformas y la lista no. Una casilla vacía
      no dice «no lo sé», dice que no tiene
- [x] **Los puertos, contados y con nombre.** Se contaban y no se listaban por una razón
      buena —un switch de 48 bocas es un renglón que dice 48—, pero eso contesta «¿es
      bastante switch?» y no «¿cuál es esta?», que es la que se hace con el latiguillo en la
      mano. `gi1` viene en el YAML de la biblioteca y se tiraba al contar; ahora se guarda
      (`port_list`) y la pestaña enseña las dos cosas — en el orden del panel, que `gi10` va
      después de `gi9` y antes en el alfabeto
- [x] Y **el tipo, no solo la velocidad**: `1000base-t` y `1000base-x-sfp` se leen los dos «1
      Gbps», así que un switch con veintiocho de cobre y dos de fibra enseñaba dos renglones
      idénticos con números distintos — que parece un fallo de la pantalla y es la verdad mal
      contada
- [x] **Un catálogo de conectores** (`data/connectors.json`, ciento y pico): C13, C14, C19,
      C20, schuko, entrada de continua, USB-A/B/C, DisplayPort, HDMI, LC, SC, MPO, SFP+,
      QSFP28… `iec-60320-c19` es lo que dice la biblioteca y «IEC C19» lo que dice alguien en
      una sala, y la c19 y la c20 se distinguen en un carácter siendo dos cosas distintas.
      **En un JSON y no en el código** —como los perfiles y los básicos— porque antes vivía
      en una constante del navegador: no se lee desde el servidor, no se corrige sin tocar
      una plantilla, y quien sabe que falta el DisplayPort no la encuentra
- [x] Y cada conector dice **en qué familias se ofrece**: una C14 es una toma de entrada y
      nunca una boca de red. Sigue siendo **sugerencia y no lista cerrada** — lo que hay
      enchufado en una sala de verdad incluye cosas que no están en ninguna lista
- [x] Y **cada conector con su cara dibujada**: una C13 y una C19 se distinguen en un
      carácter y son diez amperios y veinte, y el nombre no arregla eso del todo porque
      «IEC C19» tampoco dice qué forma tiene. Cuarenta dibujos y no ciento veintiocho —una
      C13 y una C15 son la misma boca—, en `currentColor` para que valgan en los dos
      temas, e **incrustados en la página**: `<use>` contra otro documento no lo soportan
      todos los navegadores. Dibujos y no fotos, que una foto trae su licencia y su fondo
      y bajarlas sería una dependencia de red en una sección que existe también para las
      salas que no la tienen
- [x] Y **pinchando en uno se abre su ficha**: el dibujo en grande, el identificador que se
      guarda, en qué casillas se ofrece, su velocidad si la fija y **con qué se empareja**
      —una C19 va con una C20 y no con una C14—. En la tabla el dibujo mide lo que una
      letra, que basta para reconocer el que ya se conoce; para el que no, hace falta lo
      contrario
- [x] Y el documento **sale también en Esquemas**, que es donde se mira de dónde vienen
      los vocabularios: la pestaña de conectores contesta «¿cuáles hay?» y esa otra
      «¿quién decide cuáles hay?», que es a lo que se va allí. Sin botón de editar, y eso
      se dice — un botón que no está y no se explica se lee como un botón que falta
- [x] Y **se puede sustituir sin publicar una versión**, con el mismo mecanismo que los
      perfiles y sobre la misma tabla: `dc_profile` lleva un `name` desde el primer día
      justo para el segundo documento que lo necesitara. Formulario para el conector que
      falta —que es lo que se hace casi siempre—, JSON para lo demás, historial de quién
      lo tocó, y volver al que viene con el panel. **Manda la versión más alta**, o habría
      que elegir entre que una lista mejorada no llegue a quien añadió un conector o que
      el conector añadido desaparezca sin aviso. Y lo que se descarta **se dice**
- [x] Y los dos documentos **se editan en un cuadro**, no dentro de la pestaña: quince campos
      por clase y ciento y pico conectores creciendo en la tarjeta dejaban fuera de pantalla
      lo que había encima, y con los dos editores abiertos había dos botones de guardar sin
      decir cuál guardaba qué. Los tres modos —formulario, JSON, historial— van **dentro** del
      cuadro, que son tres formas de mirar lo mismo
- [x] Y **previsualizar ya no cuesta lo escrito**: abría otro cuadro, y los dos son el mismo
      diálogo, así que el segundo tapaba al primero y cerrarlo dejaba la pantalla de detrás
      con lo no guardado perdido y sin decir nada. Ahora sale debajo del formulario, en el
      mismo cuadro. Mirar no puede costar lo escrito
- [x] Y la fila del **tamaño deja de prestar los ejemplos de un disco**: en «Ventilador» ponía
      `capacity`, `1.92 TB` y `GB, TB` en gris, que no es un hueco vacío sino una sugerencia
      —de otra clase—. Sale siempre porque es el único sitio donde ponerle tamaño a una clase
      que no lo tiene, y ahora dice qué significa dejarla en blanco
- [x] Y el cuadro **se estira y se maximiza**, que ya sabía hacerlo: `ss-modal-fit` se lo
      quitaba porque este diálogo era «aquí tienes un dato», y desde que trae formularios ya
      no lo es. La clase se pone según quién abra: los avisos siguen midiendo lo que miden
- [x] Y las familias de un conector dejan de ser un desplegable de **tres renglones por
      fila** —ciento y pico de ellos empujaban la tabla hasta sacarla por un lado— y pasan a
      nueve casillas con el icono de cada familia, que se pliegan solas
- [x] Y el **tipo de un puerto se elige del catálogo**, y se ve que se elige de ahí: era una
      caja de texto con un `<datalist>` detrás, y un `<datalist>` no se ve — la caja parece un
      sitio donde teclear a mano y los ciento veintiocho conectores no existen hasta que
      alguien acierta las tres primeras letras. Ahora es un desplegable con su nombre y su
      dibujo, y **«otro, lo escribo yo»** para lo que no esté: sigue sin ser una lista
      cerrada, pero salirse de ella es una opción que se elige y no lo que pasa por omisión
- [x] Y lo escrito que el catálogo no reconoce **se queda**, con su propia opción: pasarlo a
      «sin decir» al abrir el formulario sería borrar un dato por no tenerlo en una lista. Y
      el desplegable de familia desaparece donde solo hay una, que cada una tiene su pestaña
- [x] **Una bahía es un sitio, y los sitios tienen nombre.** `module-bays` y `device-bays` se
      editan una a una —`SODIMM-1`, `SocketCPU`, `M.2_1`, el nombre que está serigrafiado en
      la placa— y no contadas: de una bahía se pregunta **cuál**, y «dos bahías de módulo» no
      dice en cuál está el DIMM que hay puesto. Las demás familias siguen contadas: una
      plantilla no se cablea a `gi7`, eso es de la máquina que salga de ella
- [x] Y **cada componente dice en qué bahía va**, eligiéndola de las que la plantilla declara.
      Era una caja de texto, y una caja de texto para nombrar un sitio que ya está escrito en
      otro lado produce `SODIMM-1`, `sodimm 1` y `Sodimm1` para la misma ranura — y entonces
      «¿qué hay en SODIMM-1?» no tiene respuesta. Se cruzan por el nombre normalizado, así que
      lo tecleado antes sigue valiendo
- [x] Y **el recuento sale de la lista**: dos sitios donde decir cuántas bahías hay son dos
      que acaban discrepando, y el que gane depende de por dónde se guardó
- [x] Y **un kit ocupa varias ranuras**: `CT2K32G4S266M` son dos módulos que se compran
      juntos y se montan en dos ranuras distintas —esa es la gracia del kit— y con un solo
      hueco la mitad no tenía dónde decir en cuál está. Cuántas ocupa es lo que ya se
      cuenta para enseñar `1 × 2 = 2`
- [x] Y se **marcan, no se ordenan**. Un desplegable por unidad afirma que el módulo 1 va
      en una ranura y el 2 en otra, y eso no significa nada: los módulos de un kit son
      idénticos, lo que ocupan es un conjunto. Marcando cabe igual con dos que con
      dieciséis, que es lo que una fila de dieciséis desplegables no hace. Se dice cuántas
      hacen falta y cuántas llevas, porque seis de ocho es un estado a mitad de camino y
      no un error que impedir
- [x] Y **lo que cuelga se cuenta aparte de lo que va dentro** (`dc_part.mount`): el adaptador
      USB-C a red y el alimentador no van en una bahía, van enchufados a un puerto que se ve —
      y «cinco componentes» no dice cuántos hay que desmontar para llevarse la caja, que es la
      pregunta del día de la mudanza. Dos pestañas y una tabla, porque es la misma pieza
      mirada por dónde vive
- [x] Y cada una ofrece **sus** huecos: las bahías a lo de dentro y los puertos —frontales,
      traseros, tomas de corriente, consola— a lo que cuelga. Ofrecer las bahías a un
      alimentador es ofrecerle sitios donde no cabe. Una columna y no una clase nueva, porque
      `kind` dice qué es y esto dónde está: en un solo campo habría que inventar `nic_externa`
- [x] Y **a un puerto por el que cuelga algo también se le pregunta cuál**: el adaptador va en
      el USB de detrás, no en «uno de los cuatro». Los cuatro por los que se enchufa algo
      desde fuera —frontales, traseros, tomas de entrada y consola— se nombran igual que las
      bahías. Los demás siguen contados: nadie cuelga nada de la boca 37 de un switch desde la
      plantilla
- [x] Y **guardar un componente deja la ficha donde estaba**. Releerla la devuelve a la
      primera pestaña —correcto al entrar, lo contrario al guardar— y quien acababa de añadir
      un adaptador se encontraba en «Resumen» sin haber navegado, con la lista que venía de
      tocar fuera de la vista
- [x] Y **lo que ya estaba contado abre el editor con los renglones puestos**. Pasar cuatro
      familias de «contadas» a «con nombre» dejó fuera lo contado: la pestaña decía 3 y debajo
      no había nada —ni la lista, porque no hay nombres, ni el recuento, porque esa pestaña ya
      no lo enseña— y de dos cosas que se contradicen no se cree ninguna. El recuento ya dice
      cuántos hay y de qué son; lo único que falta es cómo se llaman, que es justo lo único que
      el panel no sabe. Se siembran **una vez y solo sobre lista vacía**: repetirlo a cada
      redibujado dejaría sin poder borrar un renglón —volvería solo— y sembrar sobre lo escrito
      sería duplicarlo. Nada se escribe hasta guardar, cancelar relee, y el recuento derivado
      sale idéntico al que entró
- [x] Y **la vista de lectura deja de ser un callejón**: dice lo que falta *y* ofrece el botón
      de hacerlo, en vez de señalar un «Editar» que está en otra fila y que nada relaciona con
      ponerle nombre a un puerto
- [x] Y **borrar la última bahía se guarda**. La guarda que impedía derivar cero de una lista que
      nadie había escrito contestaba igual a la que alguien acababa de vaciar: guardar decía
      «guardado» —y era verdad— pero el recuento volvía, y con él la fila sembrada al entrar otra
      vez. Se apunta qué familias se han tocado en esta ficha: la tocada manda aunque quede a
      cero, la que nadie abrió conserva lo que dijo el modelo
- [x] Y **a un puerto no se le llama bahía**. La lista con nombre sirve para las dos cosas —una
      ranura de memoria y la toma de detrás son las dos un sitio— pero el rótulo no: obliga a
      traducir cada frase mientras se lee. Las de dentro siguen siendo bahías, las cuatro de
      fuera tienen sus propios textos (`dcim_bay_*_port`), y la casilla «Hueco» del formulario
      de componentes pone **Puerto** cuando lo que se está poniendo cuelga por fuera
- [x] Y **de qué cara es cada puerto se dice dos veces**, porque son dos fallos: los tipos se
      repiten entre las caras —dos USB-A delante y cuatro detrás— y numerarlos por familia da
      cuatro «USB-A 1» que nadie distingue. Lo sembrado lleva la cara en el nombre
      («Frontal USB-A 1», «Trasero USB-A 1») y la lista donde se elige va **agrupada por
      familia**, que es lo que lo contesta aunque los nombres los haya escrito alguien a mano y
      repetidos
- [x] Y **el conector dice la forma; la generación y lo que lleva son del puerto**.
      `1000base-t` y `usb-c` no dicen la misma clase de cosa: el primero es una señal con su
      velocidad —la forma, un RJ-45, va implícita— y el segundo es una forma sin señal ninguna,
      heredado tal cual de la biblioteca. Por eso un USB-C solo podía decir que era un USB-C: ni
      de qué generación —un 2.0 y un 3.2 Gen 2 son la misma boca con veinte veces la velocidad—
      ni qué lleva, cuando el mismo cable saca vídeo, red y corriente. Son **dos ejes**, y la
      ficha del fabricante los dice los dos: «1× USB 3.2 Gen 2 Type-C con DisplayPort 1.4»
- [x] Así que el catálogo declara, por conector, qué **generaciones** caben en esa forma
      (`gens`) y qué **señales** tiene sentido que lleve, y el puerto con nombre elige una y
      marca las que van (`gen`, `signals` en `port_list`). Un conector por combinación —forma ×
      generación × modos— serían cientos de identificadores; dos casillas en el puerto son dos
      casillas. **La forma sigue siendo el `type` y el recuento sigue contando formas**: dos
      USB-C son dos USB-C aunque uno sea Gen 2, así que no se movió ni un dato de sitio
- [x] Y **la fuente que va fuera tiene formato**. ATX, SFX, CRPS y Flex ATX son las formas de
      una que se atornilla DENTRO de un chasis; el alimentador de un mini-PC no es ninguna, así
      que el campo se quedaba en «Sin decir» — que es lo mismo que no haber preguntado. Cinco
      más para lo que va fuera (ladrillo de sobremesa, adaptador de enchufe, carril DIN, placa
      abierta, inyector PoE) y las tres de dentro que faltaban (ATX12VO, SFX-L, TFX). Los nuevos
      se guardan como **identificador** y se traducen por `dcim_val_*`: los viejos son siglas y
      ATX es ATX en los dos idiomas, pero «adaptador de enchufe» no. Y la eficiencia admite
      **DoE VI** y **CoC Tier 2**, que es lo que lleva impreso un externo — 80 PLUS es de las
      fuentes de ordenador, y preguntar por una etiqueta que ese alimentador no puede tener es
      preguntar para que se quede en blanco
- [x] Y **un componente también dice por dónde se enchufa**. El editor de puertos vivía solo en
      la rama de los chasis, así que un cargador —que tiene una entrada de corriente y una salida
      de continua— o un adaptador USB-C a red —un USB-C de entrada y una RJ-45 de salida— no
      tenían dónde decirlo, y la pregunta «¿qué latiguillo le hace falta a esto?» no se podía
      contestar desde su ficha. Entrada y salida no necesitan campo propio: las familias ya lo
      dicen —`power-ports` es lo que consume y `power-outlets` lo que da
- [x] Y **cuánto consume por esa toma** (`volts`, `watts`), del puerto y por lo mismo: una C14
      alimenta un mini-PC de 65 W y una fuente de 750, y lo que se guarda es la etiqueta de esta
      máquina. El voltaje es texto —la etiqueta pone `100-240`, un rango, y quedarse con una de
      las dos sería inventárselo— y los vatios un número, que son los que se suman para
      contestar qué pide un armario. Salen **donde pasa corriente**: un conector de corriente
      que no declara señales —una C14, un borne de continua— o uno que sí las declara y alguien
      ha marcado que alimenta. Mirar solo la familia no valdría: la misma pregunta la tiene el
      USB-C trasero que carga el portátil, y ese no está en «tomas de entrada»
- [x] Y **el Resumen es el índice de la ficha**, en bloques que ocupan lo que dicen. Once
      pestañas y una primera que no decía nada de las otras diez es una pestaña más, no un
      resumen. Cada bloque lleva lo que se pregunta sin entrar —cuántas bahías quedan libres,
      qué modelo hay en cada hueco, de qué son los puertos contados— y una flecha para entrar.
      La primera versión repetía en tarjetas grandes el nombre y el número que la tira de
      pestañas ya llevaba, y ocupaba más que antes: lo que aporta un resumen es lo que hay
      **detrás** de cada pestaña, no cómo se llama
- [x] Y las dos tablas de la ficha —los datos y el ciclo de vida— dejan de ir al 100% de ancho
      para cuatro renglones de dos palabras. Una rejilla reparte el ancho que haya y cada bloque
      queda **alto de lo que dice**: sin eso, un bloque de dos renglones se estira hasta la
      altura del de ocho y deja el hueco en blanco que había que bajar a saltos
- [x] Y las **familias de puerto bajan un nivel**. «Interfaces», «Tomas de entrada», «Puertos
      frontales»… son una pregunta con seis renglones y no seis preguntas: al mismo nivel que
      «Componentes» ocupaban dos filas de tira antes de que la ficha dijera nada. Arriba quedan
      seis fijas —Resumen · Componentes · Elementos externos · **Conexiones** · Adjuntos ·
      Historial— y las familias viven dentro, en una fila que solo sale cuando estás ahí.
      Pulsar el grupo abre una familia y no una pantalla suya: la que estuviera abierta si se
      vuelve a él, la primera si se entra de nuevo
- [x] Y el número de una pestaña **nunca es menor que los nombres que tiene detrás**. El
      recuento se deriva de la lista al guardar, así que normalmente coinciden; una fila tocada
      a mano puede traer la lista sin el recuento, y entonces la pestaña decía cero al lado de
      cuatro bahías escritas. De dos cifras que se contradicen, la que se enseña es la que tiene
      los nombres detrás
- [x] Y las señales son un **vocabulario abierto** que se edita en el documento: lo que se
      enchufa en una sala de verdad incluye cosas que no están en ninguna lista. Una que no esté
      escrita se conserva y se enseña por su identificador — y se avisa al guardar, porque casi
      siempre es una errata, y una errata que funciona es la que se queda
- [x] Y **cambiar la forma se lleva lo que era de la forma vieja**: un `tb4` en un USB-A no
      significa nada, y dejarlo puesto es guardar una generación que ese conector no tiene
- [x] Y la lista con nombre **se limpia en la puerta y en una sola**: entraba tal y como la
      mandaba el navegador, que con dos campos era feo y con cuatro es una columna donde cabe
      cualquier cosa. Dos limpiadoras —la del catálogo y la de la plantilla— acabarían limpiando
      distinto, y el fallo saldría según por dónde se hubiera guardado
- [x] Y **el hueco vuelve a ser un campo**: una caja con lo elegido y un botón que abre el
      cuadro de selección. La parrilla de chapas dentro del formulario crecía con el equipo
      —tres puertos en un mini-PC, veinte en un chasis— y se comía la fila; fuera cabe todo, y
      con sitio para decir de qué cara es cada uno. Se marca sin cerrar nada: cada clic escribe
      en el borrador y redibuja las dos pantallas, la de detrás y el cuadro
- [x] Y **el formulario dice dónde acaba la pieza y empieza el sitio**. Marca, modelo, tamaño,
      hueco, cantidad y los botones iban en la misma fila corrida, ajustándose sola al ancho de
      la ventana: dónde acababa una pregunta y empezaba la otra dependía de por dónde partiera
      la línea ese día. Dos bloques con su título —«Qué es» y «Dónde va»— y una raya en medio,
      **de canto y no apilados**: son cuatro cajas, y en tres pisos ocupaban tres filas de alto
      con la mitad del ancho vacío. La raya dice lo mismo puesta de pie, y en una ventana
      estrecha las columnas caen una debajo de otra con su raya al lado
- [x] Y **una ranura ocupada no se ofrece**: sale en la lista —esconderla dejaría sin saber
      que existe— pero no se puede elegir y dice quién la tiene. Vale también contra la propia
      pieza: dos módulos en SODIMM-1 no caben en la placa
- [x] Y **el número en todas las pestañas**, no en una: con uno solo, la que lo lleva
      parece la importante y de las otras no se sabe si están vacías o si ahí no se
      cuenta. Servidos de una vez con el catálogo, o el número aparecería o no según por
      dónde se hubiera pasado — el mismo fallo que la columna Plataforma
- [x] Y **con su pestaña en el catálogo**, con buscador y filtro por familia. Un catálogo que
      solo existe cuando ya estás escribiendo en la casilla que lo usa no es un catálogo, es
      un autocompletado: «¿qué conectores conoce esto?» no tenía dónde contestarse. De solo
      lectura y diciendo **dónde vive el fichero**, o quien eche uno en falta no sabrá que se
      arregla editando un JSON. Se mira con `dcim_view`: quien está cableando a las tres de
      la mañana necesita saber si el latiguillo es un C13 o un C19 y no tiene el permiso de
      gestionar el catálogo


### Pendiente

Lo que está pedido y todavía no está. Aquí y no en `ref-pendiente.md` porque son cosas de esta
sección y se entienden con lo de arriba delante; cuando alguna empiece, su ficha se escribe en
el bloque de su fase.

- [x] **Número de inventario para un cable, aparte de su etiqueta.** `label` es lo que está
      rotulado en el propio cable —se repite, se borra y se equivoca, y aun así es con lo que
      trabaja quien está allí con una linterna— y `asset` lo pone la casa, es único y sirve para
      contar. Mezclarlos en una casilla obliga a elegir cuál de los dos se pierde
- [x] **Un cable de corriente es un cable.** `dc_feed` decía de qué toma cuelga y cuántos vatios
      se declararon, y nada más, como si el latiguillo no existiera. Existe: se compra, se guarda
      en una caja, se rompe y hay que sustituirlo. Gana `asset`, `category`, `length_mm` y
      `description` — **los mismos nombres que su hermano de datos**, porque dos tablas que
      guardan lo mismo con nombres distintos son dos pantallas que se escriben dos veces
- [x] Su categoría es el **par de conectores** (`c13-c14`, `c19-c20`…), que es lo que hay que
      mirar en la caja antes de bajar al armario. Abierta como la de datos: una instalación con
      tomas de otro país no puede quedarse sin poder apuntarlo
- [x] Y **tiene ficha**: mirarlo, corregirlo, cambiarlo de toma y desenchufarlo. Antes eran
      cuatro cosas escondidas en la misma chapa o en ninguna parte, y sus datos se preguntaban
      una vez al enchufarlo — con prisa, que es cuando se enchufa
- [x] El número de inventario sale también **en columna**, en las dos listas: es con lo que se
      cuenta, y contar es mirar una lista entera. Metido sólo en la ficha, saber cuántos INV-22xx
      hay puestos obligaba a abrirlos uno por uno. En alimentación va **uno por cable**, en el
      mismo orden que las chapas: un equipo con dos fuentes tiene dos latiguillos
- [x] Y el modo de una ficha es **de esa apertura**, no del panel. Era una variable que se
      encendía al pulsar «Editar» y sólo se apagaba al guardar: cerrando el cuadro sin guardar se
      quedaba encendida, y la siguiente fila que alguien pulsara abría el formulario de otro cable
      en vez de su ficha. Ni un error ni una pantalla en blanco — la ventana equivocada, que
      además parece la buena, y no se arreglaba más que con F5
- [x] **El alzado se puede ver sin rótulos**, con un botón. Con diez cajas y sus nombres encima
      lo que se pierde es el dibujo —dónde quedan los huecos, qué ocupa media U, qué hay montado
      sobre qué— y una foto para una presentación no lleva los nombres de la casa. Encendido por
      defecto, que es lo normal, y sin tocar el encuadre: el dibujo mide lo mismo con letras y sin
      ellas
- [x] **El cableado, fuera de su armario** (`/dcim/wiring`). Dentro de un rack se contesta «qué
      sale de aquí»; las otras dos —«dónde está el cable C-014» y «cuántos latiguillos de Cat 6A
      hay puestos»— obligaban a saber el armario ANTES de poder buscar, que es lo contrario de
      buscar. Se busca por etiqueta, número de inventario, boca y nombre de los extremos, con
      filtro por tipo y por categoría
- [x] Cada punta dice **dónde está** —armario y U—, que es la otra mitad de «dónde está este
      cable». De una punta ajena no: se estrecha como todo lo demás
- [x] **Sin contraste**, y no por ahorrar: contrastar es una pregunta sobre UN armario —qué se ve
      desde aquí— y armar el mapa de la flota para listar cables de seis salas sería pagarlo seis
      veces por un dato que esta pantalla no usa
- [x] Y **la misma ficha** que dentro del armario, con la misma corrección: dos fichas del mismo
      cable serían dos formas de escribir lo mismo, y la segunda tardaría meses en descubrirse.
      Guardar vuelve a la lista de la que se vino — recargar la otra deja lo corregido fuera de
      la vista, y una corrección que no se ve parece una que no se ha guardado
- [x] Están los **dos**: los de red y los de corriente. Son la misma pregunta y viven en dos
      tablas por dónde acaban, no por lo que son — dos listas obligarían a buscar dos veces lo
      mismo y a acordarse de cuál mirar. La regleta hace de segunda punta: tiene nombre y está en
      un armario, que es lo que se necesita de una punta, y su «boca» es el número de toma
- [x] Con **la tabla compartida del panel** (`createListTable`), la misma de Usuarios y Grupos:
      filtros, orden, columnas escondibles y paginación. Una lista con su propio buscador y su
      propia paginación se comporta distinto que las otras diez sin ninguna razón
- [x] Y **en carriles**, que contestan la otra pregunta —la de compras—: *de qué tengo montado y
      cuánto*. Cuarenta de cobre y dos de fibra se ve sin contar; en una tabla ordenada por tipo
      hay que ir sumando de cabeza. Por **tipo**, por **categoría** y por **armario**
- [x] Tres agrupaciones y **una función**: son la misma pantalla con otro criterio, y escribirlas
      tres veces sería que dos se quedaran sin el arreglo que reciba la primera. Un cable de sala
      sale en los **dos** armarios — meterlo sólo en el primero dejaría la mitad de los
      latiguillos fuera del carril de su destino
- [x] Los carriles cuentan la lista **entera** y no la página (`mode: 'summary'`): un tablero que
      cuenta veinticinco de ciento veinte contesta mal a lo único que se le pregunta, y encima con
      una cifra creíble. Y los metros de un carril dicen **cuántos faltan por medir**, que es de
      donde sale el pedido del año que viene
- [x] **Se busca en la base, no en memoria.** Las dos búsquedas —equipos y cables— recorrían la
      tabla entera y construían un diccionario por fila de toda la instalación para quedarse con
      treinta o con doscientas. En una sala pequeña no se nota, que es exactamente lo que hace
      que se escriba así y se descubra tarde
- [x] El texto, el rol, la clase y la categoría van al `WHERE`. Buscar por el **nombre de un
      extremo** o de su armario también: el nombre está en otra tabla, así que se resuelve antes
      a una lista acotada de identificadores y se pregunta por ellos — el mismo camino que la
      búsqueda de equipos por modelo
- [x] `LOWER(...)` dicho en la consulta y no dejado al motor: MySQL no distingue mayúsculas por
      defecto, SQLite sí y PostgreSQL depende del idioma del sistema. Y los comodines del `LIKE`
      **escapados**: sin eso, teclear `_` encuentra cualquier cosa y `%` las encuentra todas —
      un buscador que ignora lo que se le pide es peor que uno que no encuentra nada, porque
      contesta
- [x] Lo único que se queda fuera del `WHERE` es **quién puede ver qué**: sale de una cadena de
      pertenencia que no está en ninguna columna, y escribirla en SQL sería tener la regla en dos
      sitios. Por eso se recorre **a trozos** (`scan_pages`) con un presupuesto, y un trozo se
      termina siempre — parar a mitad dejaría fuera para siempre lo que quedaba detrás en él
- [x] Y `capped` es «se acabó el presupuesto», no «hay más»: son dos cosas y sólo una es un
      problema de quien mira
- [x] La lista está **recortada a doscientos y lo dice**: una lista más corta que la realidad
      parece completa, y con doscientas filas delante lo que se hace no es leerlas
- [x] **Los equipos, fuera de su armario** (`/dcim/devices`). La lista de equipos vivía dentro
      de su rack, así que «qué servidores hay en esta sede» y «qué se queda sin garantía este
      trimestre» obligaban a abrir armario por armario. El dato ya estaba: era la pantalla la que
      faltaba
- [x] Cada equipo dice **dónde está del todo** —armario, sala y sede—, que sube dos niveles por
      encima de su fila; y trae **lo que sólo tiene esa caja**: serie, inventario, garantía y
      proveedor. Sin ellos la lista es un recuento
- [x] Filtros por función, sede, empresa y **garantía** —caducada, caduca en 90 días, sin fecha—.
      «Sin fecha» es un grupo y no un hueco: es justo lo que hay que mirar antes de contestar
      «qué se queda sin cobertura», y esconderlo deja la respuesta corta y creíble
- [x] La empresa se filtra **fuera del `WHERE`**: un equipo hereda la de su armario cuando no
      dice la suya, y esa herencia no está en ninguna columna — escribirla en SQL sería tener la
      regla en dos sitios
- [x] **Tres maquetas y no carriles**, iguales en Equipos y en Cableado: la tabla pelada, la
      tabla **agrupada** (con la cabecera del montón pegada arriba y su recuento) y una fila de
      **recuentos** encima de la tabla que la filtra al pulsarlos. Se probaron cuatro y se
      eligieron tres; lo que no se eligió se quitó — código que no se dibuja es código que nadie
      mantiene
- [x] **Por qué se agrupa y cómo se dibuja son dos preguntas**, y van en dos controles: mezclarlas
      daría nueve vistas para contestar tres cosas. Equipos agrupa por estado, función, sede o
      empresa; el cableado por tipo, categoría o armario
- [x] Agrupar es **ordenar primero por el montón**, con la columna pulsada mandando dentro. La
      cabecera se repite al pasar de página: un montón que sigue en la siguiente empezaría sin
      ella y sus filas parecerían del montón que fuera
- [x] Los recuentos cuentan **todas las filas filtradas** y no la página — un recuento que cambia
      al pasar de página es peor que no contar — y llevan su palabra además de su color
- [x] Y **por estado**: mal, en aviso, bien, sin vigilar. Es la pregunta que hace que esta
      lista sirva para algo más que contar. **Lo peor primero** y no por tamaño: agrupado por
      estado el carril gordo es el de lo que está bien, y ordenarlo por tamaño deja lo que está
      mal al final de la fila — el mismo orden con el que un armario decide cuál de dos máquinas
      está en más apuros
- [x] «Sin vigilar» es un carril propio y **no es «bien»**: un equipo sin máquina enganchada no
      está correcto, está sin mirar. Y lo que no contesta **por naturaleza** —un panel, una
      bandeja— va aparte: meterlo entre los desatendidos llena la pantalla de deberes imposibles,
      que es la forma más rápida de que nadie vuelva a mirarla. La misma decisión que ya toma el
      recuento de un armario, y una guarda comprueba que las dos listas de roles mudos no se
      separen
- [x] También como **columna y como filtro**, ordenada por gravedad: alfabéticamente, «error, ok,
      sin vigilar, warning» pone lo que está mal en medio de lo que está bien
- [x] Y carriles **por función, por sede y por empresa**. Seis vistas en total con las del
      cableado, y **una sola función** que agrupa y cuenta (`_ssLanes`): dos copias son dos que
      se separan el día que a una se le añade algo
- [x] Y **«Actualizar» no redibuja la sección**: `renderDcim` reescribe el panel entero —tira
      el contenedor de la tabla, la barra de filtros y todo lo demás—, que es lo que hace falta
      al ENTRAR en la vista y justo lo que no hace falta para volver a pedir unas filas. El
      parpadeo era eso, y con él se perdía el foco de la barra: actualizar con algo escrito era
      perder dónde se estaba escribiendo
- [x] Pulsar una fila lleva **al equipo en su armario**, no a una ficha: una tercera forma de
      mirar lo mismo no ayuda, y lo que se quiere al pulsar es verlo en su sitio
- [x] **Estar en un armario sin ocupar U**, que era la pregunta detrás de los cinco casos: un
      SAI en el suelo al lado, un cuadro en la pared, una bandeja de fibra colgada, la regleta
      atornillada al lateral. `dc_item.placement` con tres valores —`u` (lo de siempre y el valor
      por defecto), `side` y `near`— y **una sola comprobación** decide: lo que no es `u` no entra
      en la ocupación ni en el alzado
- [x] **La ficha de un equipo va por zonas**: «Qué es», «Dónde va», «Comparte el U», «De dónde
      salió» y lo que haya que decir. Las casillas iban en una fila que se envuelve, así que los
      grupos los hacía el ancho de la ventana — «Máquina» acababa junto a «Fondo del equipo»
      porque ahí cupo, y medio palmo más estrecha eran otros dos. Un grupo que cambia de miembros
      al estirar el cuadro no es un grupo
- [x] Y **lo raro va plegado**: partir un U es de una instalación de cada veinte, y el fondo, el
      proveedor y la descripción se rellenan un mes después si es que se rellenan. De diecisiete
      casillas a trece. Pero **lo que ya está relleno se despliega solo**: esconder un dato
      escrito es peor que enseñar uno vacío, porque el escrito no se puede ni corregir ni
      descubrir
- [x] Una zona **sin casillas no se dibuja**, ni su rótulo: en un SAI que está en el suelo no hay
      ningún U que partir, y un título sobre un hueco vacío deja buscando el campo que no está
- [x] Y **ayuda en todas**. De diecisiete campos la tenía uno, y los que más falta hacían eran
      justo los que peor se adivinan: «Cuántas toma», «Se parte», «Fondo del equipo». Un campo
      que no dice para qué es sólo lo rellena quien escribió el modelo
- [x] Sólo el equipo declara zonas: una sede tiene cuatro casillas, y cinco rótulos para ordenar
      cuatro cosas es peor que ninguno
- [x] **Un campo que no significa nada no se pregunta.** La ficha seguía pidiendo la U de un
      SAI que está en el suelo, y la respuesta era 1 porque la casilla venía con un 1 puesto: un
      dato pedido sin sentido no sale vacío, sale con su valor por defecto — una mentira con
      formato de dato. Cada campo declara `when` y hay **una función** que decide, no diez `if`
- [x] Tampoco se pide lo que ya se dijo por otro sitio: elegir una plantilla o un modelo del
      catálogo dice cuánto mide, y volver a preguntarlo es pedir que alguien confirme un número
      que no ha mirado — o que lo contradiga sin enterarse
- [x] Y los campos de los que **cuelgan otros** (`drives`) redibujan la ficha al cambiar: sin
      eso, elegir «al lado del armario» dejaba las casillas de U en pantalla, preguntando por un
      sitio que la respuesta anterior acababa de dejar sin sentido
- [x] Cambiar cómo está puesto **es moverlo**, así que pasa por la misma comprobación y le quita
      la U: sin contarlo entre lo que mueve, el equipo se quedaba con la que tenía
- [x] Y en la lista va **después de todas las U, en su zona**. Ordenado con lo demás caía entre
      la U 1 y la U 2, y eso no es una lista mal ordenada: es una lista que dice que el SAI está
      ahí — la columna dice «Al lado», pero en una tabla **el orden se lee antes que la columna**
- [x] Y sigue estando **en** el armario para todo lo demás: se alimenta, se cablea, tiene estado
      y hay que ir a mirarlo. Lo único que no hace es quitarle el sitio a nada — un SAI en el
      suelo no deja de caber porque el armario esté lleno, y preguntarle si cabe sería
      preguntarle por un sitio que no ocupa
- [x] El alzado **no lo dibuja y lo nombra debajo**. Ponerlo en la U 1 por no dejarlo fuera sería
      dibujar un armario que no existe; sacarlo sin más lo convertiría en algo que hay que
      recordar. Es la misma decisión que la bandeja que no lleva enchufe
- [x] Lo montado encima **hereda cómo está puesto**: lo que va sobre una bandeja que está al lado
      del armario está también al lado, y sin heredarlo el alzado dibujaría media bandeja
- [x] Con esto, **la regleta del lateral deja de ser un caso particular**: es un equipo del
      armario que no ocupa U y que se declara como regleta igual que cualquier otra
- [x] **El número de inventario es único entre TODO lo inventariado**, no dentro de su tabla.
      INV-45 es INV-45 tanto si es un servidor como si es un latiguillo: en el albarán, en la
      hoja de la aseguradora y en la caja de repuestos hay una lista, no cuatro. Comprobarlo
      por tabla dejaría dos cosas distintas con el mismo número y ningún error el día que se
      escribe — el duplicado aparece meses después, cuando dos fichas dicen ser la misma cosa
- [x] Y **el armario también lo lleva**. Lo tenían el equipo, el cable de datos y el de
      corriente, y el mueble que los sostiene no: el que sale por más dinero en el albarán y
      el primero que pregunta la aseguradora
- [x] **`INV-?` es el siguiente.** Quien numera un armario entero teclea cuarenta veces un
      número que ya está decidido, y la vez que se equivoca no lo dice nadie. Con `INV-???` el
      mismo número escrito a tres cifras (`INV-046`): el ancho se pide con los propios
      interrogantes, y vale cualquier principio — `RACK-?`, `CBL-??`
- [x] El relleno es **cómo se escribe y no qué es**: `INV-045` y `INV-45` son el 45, así que
      una instalación que empezó sin ceros y siguió con ellos no reinicia la cuenta. Y es un
      mínimo y no un tope — con dos interrogantes hay que poder numerar el ciento uno
- [x] El siguiente es **el mayor más uno, nunca un hueco**. Si el 20 se dio de baja, el 20 no
      vuelve: su etiqueta sigue en un cajón y el historial sigue nombrándolo, y reciclarlo
      convierte dos cosas en una a los ojos de cualquiera que mire un papel viejo
- [x] Lo resuelve **el servidor al guardar**, no la pantalla: dos personas numerando a la vez
      desde dos pantallas verían las dos el mismo «siguiente». Y devuelve con qué número se
      quedó — quien escribe `INV-?` no puede verlo hasta ir a buscarlo a la lista, y ese viaje
      es justo el que este campo existe para ahorrar
- [x] En **un solo sitio** para las cinco puertas que lo escriben (armario, equipo, regleta y
      los dos cables): la unicidad no es de ninguna de ellas, es de todas a la vez, y una
      comprobación por puerta son cuatro sitios donde puede quedarse sin comprobar. Y **después
      del permiso**: gastar un número en una petición que va a acabar en 403 deja un hueco en
      la cuenta que nadie sabe explicar
- [x] Las tablas que lo llevan **se descubren** preguntándole a cada una si tiene la columna.
      Una lista escrita a mano hay que acordarse de tocarla el día que una más lo lleve, y no
      acordarse no da ningún error: da un número repetido
- [x] Dos grupos de interrogantes **se rechazan**: `INV-?-?` no es un patrón ambiguo, son dos
      patrones, y elegir por quien lo escribió guardaría un número que no pidió — que encima
      parece razonable y por eso no se descubre
- [x] **La tirada entera en la ficha de un cable**, y con el que se está mirando marcado.
      Un enlace que atraviesa un panel son tres cables y una tirada, y la ficha de uno de los
      tres enseñaba ese cable solo —«del panel A boca 12 al panel B boca 12»—, que no dice de
      dónde viene ni a dónde va. La pregunta que se hace delante del armario con el
      latiguillo en la mano es justo la otra
- [x] Es un hecho **declarado**, no una confirmación. El camino que dibujaba la pestaña de un
      armario salía de cruzar lo escrito con lo que los dispositivos ven, así que una tirada
      que nadie confirma —dos paneles y un latiguillo, sin LLDP de por medio— no salía en
      ninguna parte estando declarada entera. Eso es media instalación
- [x] **Por cable y al abrir la ficha** (`/cables/<uid>/run`), no con la lista: calcularla
      para las doscientas filas de una búsqueda sería pagar doscientas veces lo que se mira
      una. Y la ficha se dibuja antes de que llegue — esperarla dejaría la ventana en blanco
      por un dato que va abajo del todo
- [x] Se anda **por bocas**: lo que entra por la 12 sale por la 12, y otro cable en la 13 del
      mismo panel no es la misma tirada. Se para en lo que no es un panel, en lo ajeno y en
      una boca de la que salen dos cables — eso no es una tirada, es un dato torcido, y
      elegir uno de los dos sería dibujar un camino que nadie ha declarado
- [x] Y **se lee igual desde cualquiera de sus tramos**: sin eso, el sentido lo decidía por
      cuál se hubiera preguntado —la ficha del latiguillo la enseñaba «servidor → switch» y
      la del troncal al revés—, y dos dibujos distintos de lo mismo hacen dudar de si son dos
- [x] Cada tramo lleva **lo suyo**: etiqueta, inventario, categoría, metros y color viajan con
      él en vez de buscarse en la lista cargada, que sólo existe en una de las dos pantallas
- [x] La ficha va **a dos columnas** cuando hay tirada: a la izquierda lo que el cable es, a
      la derecha por dónde pasa. Uno debajo del otro dejaba media ventana en blanco y obligaba
      a bajar para ver lo que se había venido a mirar. Sin tirada, una sola — una columna
      vacía al lado no es un diseño, es un hueco
- [x] **La ficha de un cable es una para dos pantallas, y leía el global de una de ellas.**
      Abierta desde la sección de cableado, «Editar» reventaba con un TypeError antes de
      dibujar nada: ni ventana, ni aviso, nada. Ficha en `caso-diagnostico.md`
- [x] Y **meter un panel en medio dice por qué lado**. El cable que ya existe se quedaba
      siempre con el extremo A, sin decirlo, y en la mitad de los casos el latiguillo que de
      verdad sobrevive es el otro: se mete un panel de sala entre el servidor y el switch y
      el que uno tiene en la mano, ya etiquetado, es el del lado del switch. Con la elección
      al revés su etiqueta, su inventario y sus metros acaban en el tramo equivocado — y no
      da ningún error: quedan dos cables bien declarados y uno de los dos miente
- [x] Con **la cuenta hecha delante**: los dos tramos con los nombres puestos y «este» donde
      va el que ya existe. Una frase que describa lo que va a pasar hay que leerla dos veces
- [x] Y esa operación tenía el mismo fallo que «Editar»: leía la lista del armario, así que
      desde la sección de cableado la nota salía sin nombres y guardar no hacía nada
- [x] **Un cable directo también tiene tirada.** Se dibujaba sólo con dos tramos o más,
      porque con uno «sus dos puntas están en los renglones de al lado» — y no lo estaban:
      esos renglones sacaban el nombre de la lista del armario, así que desde la sección de
      cableado un cable directo se quedaba con dos «sin decir» y ni un nombre. El dibujo se
      pinta con lo que trae la propia tirada: nombre, boca, armario y U de las dos puntas
- [x] Y cuando hay dibujo, las puntas **no se dicen dos veces**: los dos renglones repetían
      peor —sin el sitio— lo que el dibujo ya da
- [x] Cómo se llama una punta se resuelve en **una función** (`_dcEndName`): la lista del
      armario lo trae en `a_label` y la de cableado en `a_at.label`, y había cuatro sitios
      leyendo sólo el primero — la ficha, la nota de partir, el desplegable del lado y el
      dibujo de cómo queda. Cuatro medias lecturas iguales son la señal de que la regla
      tenía que estar en un sitio
- [x] **El panel se mete desde la punta**, no desde un botón al pie: se pulsa la punta por la
      que ese cable sigue siendo el que se tiene en la mano y el lado queda contestado. Es la
      misma decisión que el desplegable, dicha donde se ve — un botón al pie obliga a
      traducir «lado A» a «el extremo del switch» mirando hacia arriba. Sólo en las dos
      puntas del cable abierto: las de los otros tramos son de otros cables
- [x] Y **una talla declarada no se ofrece deshacer**: un modal `wide` ya mide lo que tiene
      que medir, así que pierde el botón de maximizar — lo único que añadía era alto vacío
      debajo de lo que se ha venido a leer. La misma regla que ya tenían los `fit`
- [x] **La ficha dice también lo que falta.** Un cable sin número de inventario y sin metros
      salía con tres renglones y ni una pista de que le faltaran: las casillas vacías no se
      dibujaban, así que la ficha decía «esto es lo que hay de este cable» cuando lo que
      quería decir era «esto es lo único que alguien ha escrito». Un hueco es un dato, y es
      justo el que hay que ir a rellenar. Con el color como muestra, además del código
- [x] Y **el formulario se reparte como la ficha**: rejilla con rótulos de grupo —«Qué cable
      es», «Por qué bocas va»— en vez de ocho casillas en una fila que se envuelve con el
      ancho puesto a ojo en cada una. Es el mismo arreglo que la ficha de un equipo y por el
      mismo motivo: un grupo que cambia de miembros al estirar el cuadro no es un grupo
- [x] Con **la tirada delante mientras se corrige**, que es cuando hace falta: los metros se
      ponen después de haber visto los tres tramos y la boca se comprueba mirando el panel
- [x] La **descripción** es de varias líneas: lo que se escribe ahí es «el latiguillo pasa
      por detrás del armario y llega justo», y en un renglón eso se teclea a ciegas
- [x] La **categoría es un desplegable de verdad**, no un `<datalist>`: ése no enseña que
      haya nada que elegir —la casilla se ve igual que una vacía—, así que las categorías
      estaban ahí y nadie las veía, y «cat6» acababa escrito a mano con su errata y su
      mayúscula distinta cada vez. Sigue abierta por abajo: la última opción devuelve la
      casilla de escribir, y una categoría rara que ya estaba escrita no se pierde
- [x] Y **el color se puede elegir de los que hay**: la rueda de dieciséis millones deja la
      instalación con nueve azules que no son el mismo azul. Los corrientes los dice el
      servidor (`CABLE_COLORS`), como las categorías y como los colores de las ramas — una
      segunda copia en la pantalla es la que se queda sin el color que se añada mañana—, y
      la rueda sigue al lado para el que no esté. Los dos escriben en la misma casilla
- [x] Y **primero los que ya se usan**, que es lo que de verdad se elige: si el azul de esta
      sala es un azul concreto que llevan cuarenta cables, el cuarenta y uno tiene que ser
      ÉSE. Los cuenta el servidor sobre la tabla, del más puesto al menos —una lista escrita
      a mano es la que no sabe qué colores usa esta casa— y debajo van los corrientes, para
      la instalación que empieza. Uno que sea las dos cosas sale una vez, en «ya en uso»
- [x] Se eligen de **muestras en un desplegable propio**, no de una lista de códigos. Un
      `<select>` con cada opción pintada de su color es lo que dice el estándar y lo que
      hacen dos navegadores de tres: el tercero ignora el fondo de un `<option>` y deja
      `#3b82f6` uno debajo de otro — leer códigos hexadecimales no es elegir un color. Y en
      un desplegable y no sueltas debajo, porque lo que más ocupa es lo que menos se toca
- [x] **Sin color es un valor.** Un `<input type="color"` no tiene estado vacío: siempre
      vale un color, así que un cable sin color declarado salía pintado del azul de fábrica
      y no había forma de volver a «ninguno». Lo que se guarda es una casilla escondida —la
      rueda no puede guardar el vacío y la lista no puede guardar un color que no esté en
      ella—, y «sin color» es una muestra más
- [x] **Las empresas son un sitio, no un botón.** La contención dice dónde está algo y la
      pertenencia de quién es: dos árboles, y el segundo tenía su pantalla escondida en un
      botón de la barra del ÁRBOL — que es del árbol, así que sólo existía estando en
      Inventario y desaparecía al abrir un armario. La misma equivocación que ya se corrigió
      con el catálogo y las plantillas. Ahora es una vista (`/dcim/orgs`), la última del
      submenú: se escribe el primer día y casi nunca más
- [x] La pantalla es la MISMA —el mismo editor compacto y el mismo guardado por
      diferencias—, con una cosa que un cuadro no podía dar: **qué tiene dicho cada una**.
      Desde el árbol se pregunta de quién es un armario; desde aquí, qué es de una sociedad
- [x] Se cuenta lo **dicho** y no lo heredado: una sede de la filial B con cuarenta equipos
      dentro cuenta como una sede — los equipos no lo dicen, lo heredan, y contarlos sería
      contar la misma decisión cuarenta veces
- [x] Y **quien no puede editarlas las ve**: el árbol ya enseña las chapas de las sociedades
      a cualquiera que vea el inventario, así que esconder la lista sería esconder lo que ya
      está a la vista. Lo que se estrecha es escribir (`orgs_edit`, que ningún rol trae
      de serie)
- [x] Y **el tipo de un cable no dice de qué está hecho**. La columna se llamaba «De qué es»
      y ponía «cobre» en unas filas y «corriente» en otras: son dos ejes metidos en una
      palabra, y la elegida era la del eje que sólo vale para los de red. Ahora dice qué
      clase de cable es —lo que hay que pedir para sustituirlo— y los de red dicen además de
      qué, entre paréntesis: un latiguillo de cobre y una fibra no se sustituyen el uno por
      el otro
- [x] Las muestras van **fuera del `<label>`**: un botón dentro de la etiqueta de un campo le
      pasa el clic al campo, así que pulsar una abriría la rueda del sistema encima. Y
      escriben en la casilla de la rueda, que es la que se guarda, sin redibujar el
      formulario — redibujarlo tiraría lo tecleado en las otras casillas
- [x] Y **de todas las tablas que llevan color**: un latiguillo rojo y un cable de corriente
      rojo son el mismo rojo. Contados por separado, el rojo de veinte de datos y el de
      veinte de corriente saldrían como dos colores de veinte en vez de uno de cuarenta
- [x] **Un cable de corriente también tiene color** (`dc_feed.color`). Lo que la lista
      pintaba era el de su RAMA, metido en el mismo campo: la ficha lo enseñaba como si fuera
      el del latiguillo, y corregir cualquier otra cosa lo guardaba encima. Ahora la rama
      viaja aparte y la lista pinta el del cable o, si no tiene, el de su rama
- [x] Y **la lista de cableado se queda con la respuesta entera**. Copiaba campo a campo, así
      que los colores ya usados llegaban del servidor y se tiraban ahí mismo: el desplegable
      salía vacío en esa pantalla y lleno en la de al lado — el mismo dato, dos
      comportamientos, y ninguno de los dos daba un error
- [x] **«Cambiar de toma» no hacía nada desde la sección de cableado**: cuarta pantalla con
      la misma forma de fallo. El elector de tomas leía `_dcPower` —el estado de la pestaña
      de un armario— y allí vale `null`. Ahora las regletas se piden si no se tienen, las del
      armario de la REGLETA y no las del equipo, y en su propio estado: pisar `_dcPower`
      dejaría la pestaña de un armario contando las tomas de una sala en la que no está
- [x] Y **la ficha de un cable de corriente se lee como la de datos**: los mismos renglones
      aunque estén vacíos, la misma rejilla con rótulos de grupo, la descripción de varias
      líneas y el par de conectores en un desplegable que se ve. Son dos pantallas que hacen
      lo mismo: se parecen o no según quién las tocara la última, y la que se queda atrás es
      la que parece rota
