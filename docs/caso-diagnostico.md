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
que estar proyectado o excluido a propósito. Fijado por `tests/test_module_check_runner.py`
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
la propia petición que se está contestando. Cubierto por `tests/test_wa_cookie_lockout.py`,
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
`tests/test_cfg_group_role_map.py`.

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

**Solución** — `name=` en los 11 sitios, y `tests/test_watchful_emit_patterns.py` lo
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
`tests/test_wa_ui.py::TestPaneDisplayRules`, que recorre el CSS y falla ante cualquier
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
(`tests/test_wa_auth.py`), verificada fallando con el bug y pasando con el fix.

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
