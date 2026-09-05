#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Los conectores: por dónde se enchufa cada cosa, dicho con un nombre que alguien reconoce.

`iec-60320-c14` es lo que dice la biblioteca y no es lo que nadie dice en una sala: ahí se dice
«el conector de la fuente». `iec-60320-c19` y `c20` se distinguen en un carácter y son el macho y
la hembra de otra cosa —veinte amperios en vez de diez—, y confundirlos es pedir el latiguillo
que no entra. Un identificador no es un nombre: es una cadena que hay que reconocer, y esta
pantalla existe para no tener que reconocer nada.

**Está en un JSON, no en el código** (`data/connectors.json`), por lo mismo que los perfiles y los
básicos: es dato. La lista de conectores que existen en el mundo crece —USB-C se llevó veinte
años en llegar y el siguiente llegará igual— y añadir uno no puede ser publicar una versión.
Antes vivía en una constante del navegador, que es el peor de los sitios: no se puede leer desde
el servidor, no se puede editar sin tocar una plantilla, y nadie que sepa qué falta va a
encontrarla ahí.

**Y son dos JSON, como los perfiles**: el que viene con el panel y el que alguien guarde en la
base de datos. Editar un fichero del disco no vale en un despliegue con contenedor web y
contenedor de trabajos —comparten la base y no el disco—, ni sobrevive a una actualización, ni
viaja en la copia de seguridad. **Manda la versión más alta**: una actualización que publique la
2 supera a un parche local que iba por la 1, y un parche que va por la 3 sigue en pie hasta que
se publique la 4. Sin ese número habría que elegir entre que una lista mejorada no llegue nunca a
quien añadió un conector, o que el conector añadido desaparezca sin aviso.

**Sugerencias, no una lista cerrada.** Lo que hay enchufado en una sala de verdad incluye cosas
que no están en ninguna lista, y perder el dato por no reconocerlo es peor que guardarlo tal cual.
El formulario sigue aceptando lo que se teclee; esto decide qué se ofrece y cómo se lee después.

Cada conector dice **en qué familias se ofrece**, que es lo que hace útil la lista: una `c14` es
una toma de entrada y nunca una boca de red, y ofrecer las cien en las nueve familias sería no
haber ordenado nada.
"""

from __future__ import annotations

import json
import os

from lib.core.dcim import media
from lib.i18n import DEFAULT_LANG

#: El fichero. Al lado del de perfiles y del de básicos, y por la misma razón: es dato, se revisa
#: en un commit y lo reemplaza cada actualización.
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'connectors.json')

#: En qué se agrupan al ofrecerlos. Del documento salen los identificadores; estos son las cajas
#: en las que caben, y se traducen por su clave (`dcim_conn_group_<id>`).
GROUPS = ('power-in', 'power-out', 'copper', 'fibre', 'wireless', 'console', 'video', 'bay',
          'other')

#: Cómo se llama este documento en `dc_profile`, que guarda documentos por nombre.
NAME = 'connectors'

#: Y con qué nombre viven sus versiones en `dc_rev`. Distinto del de los perfiles porque son dos
#: documentos: uno dice qué se pregunta de un componente y el otro por dónde se enchufa.
SCOPE = 'connector'

#: Cuántas generaciones y cuántas señales se le admiten a un conector. Un tope y no una lista
#: cerrada: lo que sobra de un documento raro son renglones que nadie va a leer en un desplegable,
#: y lo que se pierde al recortar es detalle de más, nunca el conector.
GENS_MAX = 32
SIGNALS_MAX = 16

#: Las familias en las que un conector puede ofrecerse. Cerrada a propósito: una escrita a mano
#: en el documento no crearía una casilla nueva —no hay pantalla que la dibuje— sería un conector
#: que está escrito y no se ofrece en ninguna parte, sin que nada lo diga.
FAMILIES = ('interfaces', 'power-ports', 'power-outlets', 'console-ports',
            'console-server-ports', 'front-ports', 'rear-ports', 'module-bays', 'device-bays')

_CACHE: dict | None = None
#: Cómo estaba el fichero cuando se leyó: `(mtime, tamaño)`.
_SEEN: tuple = ()


def effective(store=None) -> dict:
    """El documento **en vigor**: el guardado si es más nuevo, y si no el que viene con el panel.

    Sin almacén —o sin nada guardado— es el del fichero, que es el caso normal.
    """
    dentro = packaged()
    if store is None:
        return dentro
    try:
        guardado = store.get(NAME)
    except Exception:                           # pylint: disable=broad-except
        return dentro                           # una fila ilegible no es una versión más nueva
    fuera = (guardado or {}).get('body') or {}
    return fuera if int(fuera.get('version') or 0) > int(dentro.get('version') or 0) else dentro


def packaged() -> dict:
    """El fichero, releído **cuando cambia**.

    Misma regla que el de básicos y por el mismo motivo: guardarlo para siempre en memoria
    convierte «editar un JSON» en «editar un JSON y reiniciar», con la trampa de que lo segundo
    no está escrito en ninguna parte.

    Uno roto **no tumba la sección**: salen cero conectores y las casillas dejan de sugerir, que
    es un formulario más pobre y no un formulario que no abre. Lo que se teclee sigue guardándose.
    """
    global _CACHE, _SEEN                        # noqa: PLW0603
    try:
        st = os.stat(FILE)
        firma = (st.st_mtime, st.st_size)
    except OSError:
        firma = ()
    if _CACHE is None or firma != _SEEN:
        try:
            with open(FILE, encoding='utf-8') as fh:
                _CACHE = json.load(fh)
        except Exception:                       # pylint: disable=broad-except
            _CACHE = {}
        if not isinstance(_CACHE, dict):
            _CACHE = {}
        _SEEN = firma
    return _CACHE


def _text(v, lang: str = '') -> str:
    """Un texto del fichero, en el idioma que se pida.

    Puede venir como cadena —lo que no hace falta traducir, que aquí es casi todo: `USB-C` se
    llama igual en los dos idiomas— o como ``{'es_ES': …, 'en_EN': …}`` donde sí.
    """
    if isinstance(v, dict):
        for clave in (str(lang or ''), DEFAULT_LANG):
            if v.get(clave):
                return str(v[clave])
        for valor in v.values():
            if valor:
                return str(valor)
        return ''
    return str(v or '')


def normalise(doc) -> dict:
    """Un documento limpio: lo que esta pantalla sabe leer, y nada más.

    Se limpia **al leerlo** y no solo en la puerta de entrada, porque también se lee el que viene
    dentro: una comprobación que solo corre al guardar no protege del fichero que llega por la
    otra puerta. Es la misma regla que el documento de perfiles.

    Lo que se descarta se **dice** aparte, con `problems()`: un conector sin `id`, o con una
    familia que ninguna pantalla dibuja, se guardaría igual y no saldría en ningún sitio — y
    quien lo escribió no se enteraría hasta ir a buscarlo.
    """
    if not isinstance(doc, dict):
        return {}
    fuera = {'version': int(doc.get('version') or 0), 'connectors': []}
    if doc.get('_comment'):
        fuera['_comment'] = str(doc['_comment'])
    senales = _signals_doc(doc)
    if senales:
        fuera['signals'] = senales
    vistos = set()
    for c in (doc.get('connectors') or ()):
        if not isinstance(c, dict):
            continue
        ident = str(c.get('id') or '').strip()
        # Repetido no: gana el que pille el bucle, que es como el mismo conector se lee distinto
        # en dos pantallas según por dónde se recorriera la lista.
        if not ident or ident in vistos:
            continue
        fams = [f for f in (c.get('families') or ()) if f in FAMILIES]
        if not fams:
            continue                            # escrito y ofrecido en ninguna parte
        vistos.add(ident)
        fila = {'id': ident, 'families': fams,
                'group': (str(c.get('group') or '') if c.get('group') in GROUPS else 'other'),
                'shape': str(c.get('shape') or 'other').strip() or 'other'}
        # El nombre y la nota pueden venir en un idioma o en los dos: se guardan como llegan y se
        # eligen al leerlos, que es lo que permite que el documento hable los dos.
        for campo in ('name', 'note'):
            v = c.get(campo)
            if isinstance(v, dict):
                trad = {k: str(x) for k, x in v.items() if x}
                if trad:
                    fila[campo] = trad
            elif str(v or '').strip():
                fila[campo] = str(v).strip()
        if str(c.get('speed') or '').strip():
            fila['speed'] = str(c['speed']).strip()
        # La imagen, si la tiene. Un conector que alguien añade no tiene dibujo —los que vienen
        # con el panel los trae `_conn_shapes.html`, y nadie va a escribir un SVG para su
        # regleta— así que puede traer una foto en su lugar.
        #
        # Se comprueba con la MISMA regla que el almacén de medios, importada y no copiada: un
        # nombre que no acuñó él no es un fichero de este disco, y aceptarlo aquí sería dejar
        # que un documento decida qué ruta se lee después.
        img = str(c.get('image') or '').strip()
        if img and media.is_name(img):
            fila['image'] = img
        gens = _gens(c.get('gens'))
        if gens:
            fila['gens'] = gens
        # Las señales que este conector puede llevar. **Sugerencias**, igual que el conector lo
        # es del puerto: una que no esté en el vocabulario se conserva y se enseña tal cual, que
        # es lo que hace que el documento se pueda ampliar sin que el panel tenga que enterarse.
        sen = []
        for x in (c.get('signals') or ()):
            ident_s = str(x or '').strip()
            if ident_s and ident_s not in sen:
                sen.append(ident_s)
        if sen:
            fila['signals'] = sen[:SIGNALS_MAX]
        fuera['connectors'].append(fila)
    return fuera


def _signals_doc(doc) -> list:
    """El vocabulario de señales del documento: ``[{'id', 'name'}, …]``.

    **Abierto**: se escribe aquí y no en el código, porque lo que un cable puede llevar crece
    igual que la lista de conectores. Lo que hace es dar nombre: una señal que no esté escrita
    sigue valiendo en un puerto, y lo que se pierde es el rótulo, no el dato.
    """
    fuera, vistos = [], set()
    for x in (doc.get('signals') or ()):
        if not isinstance(x, dict):
            continue
        ident = str(x.get('id') or '').strip()
        if not ident or ident in vistos:
            continue
        vistos.add(ident)
        fila = {'id': ident}
        v = x.get('name')
        if isinstance(v, dict):
            trad = {k: str(y) for k, y in v.items() if y}
            if trad:
                fila['name'] = trad
        elif str(v or '').strip():
            fila['name'] = str(v).strip()
        fuera.append(fila)
        if len(fuera) >= SIGNALS_MAX * 4:
            break
    return fuera


def _gens(v) -> list:
    """Las generaciones de un conector: ``[{'id', 'name', 'speed'}, …]``, en su orden.

    En su orden y no ordenadas, por lo mismo que los conectores: están escritas de la más vieja a
    la más nueva, y eso es lo que hace que la lista se lea sin buscar.

    Sin `id` no hay generación: es lo que se guarda en el puerto, y una fila que solo tiene nombre
    no se puede volver a encontrar cuando alguien corrija el nombre.
    """
    fuera, vistos = [], set()
    for g in (v or ()):
        if not isinstance(g, dict):
            continue
        ident = str(g.get('id') or '').strip()
        if not ident or ident in vistos:
            continue
        vistos.add(ident)
        fila = {'id': ident}
        nombre = g.get('name')
        if isinstance(nombre, dict):
            trad = {k: str(x) for k, x in nombre.items() if x}
            if trad:
                fila['name'] = trad
        elif str(nombre or '').strip():
            fila['name'] = str(nombre).strip()
        if str(g.get('speed') or '').strip():
            fila['speed'] = str(g['speed']).strip()
        fuera.append(fila)
        if len(fuera) >= GENS_MAX:
            break
    return fuera


def problems(doc) -> list:
    """Qué se va a tirar de este documento y por qué. Para decirlo al guardar.

    Sin esto, un JSON con una familia mal escrita se guarda, no sale en ninguna casilla, y quien
    lo subió cree que funcionó — que es peor que rechazarlo.
    """
    fuera = []
    if not isinstance(doc, dict):
        return ['not an object']
    vocabulario = {x['id'] for x in _signals_doc(doc)}
    vistos = set()
    for i, c in enumerate((doc.get('connectors') or ())):
        if not isinstance(c, dict):
            fuera.append(f'#{i}: not an object')
            continue
        ident = str(c.get('id') or '').strip()
        if not ident:
            fuera.append(f'#{i}: no id')
            continue
        if ident in vistos:
            fuera.append(f'{ident}: repeated')
            continue
        vistos.add(ident)
        malas = [str(f) for f in (c.get('families') or ()) if f not in FAMILIES]
        if malas:
            fuera.append(f'{ident}: unknown families {", ".join(sorted(malas))}')
        if not [f for f in (c.get('families') or ()) if f in FAMILIES]:
            fuera.append(f'{ident}: offered in no family')
        if c.get('group') and c.get('group') not in GROUPS:
            fuera.append(f'{ident}: unknown group {c["group"]}')
        sin_id = [g for g in (c.get('gens') or ()) if not str((g or {}).get('id') or '').strip()]
        if sin_id:
            fuera.append(f'{ident}: {len(sin_id)} generation(s) with no id')
        # No se tiran, se DICEN: una señal fuera del vocabulario sigue valiendo y se enseña tal
        # cual, pero casi siempre es una errata — y una errata que funciona es la que se queda.
        sueltas = sorted({str(x) for x in (c.get('signals') or ())
                          if str(x or '').strip() and str(x) not in vocabulario})
        if sueltas:
            fuera.append(f'{ident}: signals outside the vocabulary: {", ".join(sueltas)}')
        # Una imagen que no es un nombre del almacén se descarta en silencio y el conector sale
        # con el dibujo genérico — que se lee como «este no tiene foto» y no como «la foto que
        # pusiste no vale».
        img = str(c.get('image') or '').strip()
        if img and not media.is_name(img):
            fuera.append(f'{ident}: image is not a stored name')
    return fuera


def next_version(store=None) -> int:
    """La versión que hay que ponerle a un documento para que MANDE.

    Una más que la mayor de las dos que compiten, y no una más que la guardada: con la del panel
    por delante —una actualización que publicó la 3 sobre un parche local que iba por la 2—
    sumarle uno a la guardada da otra vez 3, que no gana, y el guardado se aplica sin efecto y
    sin decir nada.

    Aquí y no en cada sitio que guarda: son tres —el formulario, el JSON y las dos rutas de la
    imagen— y la regla es una.
    """
    return max(int(packaged().get('version') or 0),
               int(effective(store).get('version') or 0)) + 1


def with_image(doc, ident: str, name: str) -> tuple:
    """El documento con la imagen de UN conector puesta (o quitada), y la que tenía antes.

    Una función sobre el documento y no un método del almacén: lo que se guarda es el documento
    entero —es como se guarda esto— y quien la llama ya lo tiene leído. Devuelve la anterior
    porque hay que borrarla del disco, y solo quien sustituye sabe cuál era.

    Sin tocar la versión: subirla es cosa de quien guarda, y hacerlo aquí obligaría a esta
    función a saber qué hay guardado.
    """
    ident = str(ident or '').strip()
    fuera = json.loads(json.dumps(doc or {}))
    vieja = ''
    for c in (fuera.get('connectors') or ()):
        if isinstance(c, dict) and str(c.get('id') or '').strip() == ident:
            vieja = str(c.get('image') or '')
            if name:
                c['image'] = str(name)
            else:
                c.pop('image', None)
            return fuera, vieja
    return None, ''


def all(lang: str = '', store=None) -> list[dict]:          # noqa: A001
    """Todos, en el orden del documento.

    **En el orden del documento y no ordenados**: están escritos de menos a más raro dentro de
    cada familia —una C13 antes que una Saf-D-Grid— y eso es lo que hace que la primera opción
    de la lista sea casi siempre la buena. Ordenar alfabéticamente pondría delante lo que empieza
    por `b`.
    """
    fuera = []
    for c in (effective(store).get('connectors') or ()):
        if not isinstance(c, dict):
            continue
        ident = str(c.get('id') or '').strip()
        if not ident:
            continue
        fila = {'id': ident,
                'name': _text(c.get('name'), lang) or ident,
                'group': str(c.get('group') or 'other'),
                # Qué cara tiene. Una por FORMA y no por conector: una C13 y una C15 son la
                # misma boca con distinto aguante, y un LC/APC y un LC/UPC se distinguen por el
                # color del pulido. `other` cuando no se sabe, que dibuja un enchufe genérico —
                # un hueco donde los demás tienen dibujo se lee como que falta algo.
                'shape': str(c.get('shape') or 'other'),
                'families': [str(f) for f in (c.get('families') or ()) if f]}
        # La velocidad, solo donde el conector la fija. Un RJ-45 no dice a cuánto va y una
        # `10gbase-t` sí: inventarle una al primero sería afirmar algo que el conector no dice.
        if c.get('speed'):
            fila['speed'] = str(c['speed'])
        if c.get('note'):
            fila['note'] = _text(c.get('note'), lang)
        # Su foto, cuando la tiene. La pantalla la prefiere al dibujo: uno que alguien subió es
        # de SU conector, y el dibujo es el de la forma que más se le parecía.
        if c.get('image'):
            fila['image'] = str(c['image'])
        # La generación y lo que lleva: del conector salen las que CABEN, y cuál de ellas es la
        # de un puerto lo dice el puerto. Aquí es un vocabulario, no un dato del equipo.
        gens = []
        for g in (c.get('gens') or ()):
            if not isinstance(g, dict) or not str(g.get('id') or '').strip():
                continue
            uno = {'id': str(g['id']).strip(), 'name': _text(g.get('name'), lang) or str(g['id'])}
            if g.get('speed'):
                uno['speed'] = str(g['speed'])
            gens.append(uno)
        if gens:
            fila['gens'] = gens
        sen = [str(x) for x in (c.get('signals') or ()) if str(x or '').strip()]
        if sen:
            fila['signals'] = sen
        fuera.append(fila)
    return fuera


def signals(lang: str = '', store=None) -> list[dict]:
    """El vocabulario de señales, con su nombre en el idioma que se pida.

    Viaja con los conectores y no aparte: una señal marcada en un puerto es un identificador, y
    sin la lista que le pone nombre la pantalla enseñaría `power-out` a quien quiere leer
    «alimenta». Vacío cuando el documento no trae ninguno, que es un documento antiguo y no un
    error: los puertos que ya tengan señales las siguen enseñando por su identificador.
    """
    fuera = []
    for x in (effective(store).get('signals') or ()):
        if not isinstance(x, dict):
            continue
        ident = str(x.get('id') or '').strip()
        if ident:
            fuera.append({'id': ident, 'name': _text(x.get('name'), lang) or ident})
    return fuera


def by_family(lang: str = '', store=None) -> dict:
    """``{familia: [conector, …]}`` — lo que se ofrece en cada casilla.

    Un conector puede estar en varias: una `usb-c` es una toma de entrada en un mini-PC y un
    puerto de consola en un switch, y es el mismo conector. Repetirlo en el documento serían dos
    filas que se separan el día que alguien corrija el nombre de una.
    """
    fuera: dict = {}
    for c in all(lang, store):
        for fam in c['families']:
            fuera.setdefault(fam, []).append(c)
    return fuera


def name(ident: str, lang: str = '', store=None) -> str:
    """Cómo se llama este conector, o ``''`` si no está en el catálogo.

    Vacío y no el identificador: quien llama decide qué enseñar cuando no se reconoce, y en esta
    pantalla lo que se enseña es lo que se tecleó — que es un dato que alguien puso y no un
    hueco.
    """
    ident = str(ident or '').strip()
    if not ident:
        return ''
    for c in all(lang, store):
        if c['id'] == ident:
            return c['name']
    return ''


def count(store=None) -> int:
    return len(effective(store).get('connectors') or ())
