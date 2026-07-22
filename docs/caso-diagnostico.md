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
