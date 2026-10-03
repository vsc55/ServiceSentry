#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las teselas de Google, por la única puerta que se puede usar: su **Map Tiles API**.

Google no sirve teselas en una dirección suelta. Su API pide dos pasos:

1. una **sesión**: `POST /v1/createSession?key=…` con qué clase de mapa se quiere, que contesta
   un identificador y cuándo caduca;
2. y ya entonces las imágenes: `GET /v1/2dtiles/{z}/{x}/{y}?session=…&key=…`.

Ese primer paso lo da **el servidor** y no el navegador, por dos razones que no son la misma:
crearla desde cada pestaña sería una sesión por persona que abre el panel, y hay un solo mapa;
y la respuesta caduca, así que alguien tiene que acordarse de cuándo — un navegador no es el
sitio donde acordarse de nada.

La clave sí acaba en el navegador, dentro de la dirección de cada tesela, porque así está
diseñada esta API: es una clave de cliente y se protege **restringiéndola** en la consola de
Google (por referente HTTP y a la Map Tiles API), no escondiéndola. Aquí se guarda cifrada y
sale enmascarada de la configuración, como cualquier otro secreto, pero eso protege el panel y
no la clave: quien pueda abrir el mapa puede leerla. Está dicho en la ayuda del campo.

Y el guion de Google **no se carga nunca**. Cargar sus imágenes le dice dónde están tus sedes;
ejecutar su código le da la página entera.
"""

from __future__ import annotations

import json
import time

#: Dónde se pide una sesión.
SESSION_URL = 'https://tile.googleapis.com/v1/createSession'

#: Qué clase de mapa se pide si nadie dice otra cosa. El callejero, que es lo que sirve para
#: encontrar una nave en un polígono. Lo elige quien despliega (`dcim_map_google_type`), porque
#: hay casas cuyas sedes están en sitios que ningún callejero dibuja — una antena en un monte,
#: una caseta en una finca — y ahí el satélite es la única forma de reconocer el sitio.
MAP_TYPE = 'roadmap'

#: Cuánto se espera a que conteste. Corto: esto se pide mientras alguien mira una tarjeta que
#: ya está pintada, y un mapa que tarda medio minuto en salir es un mapa que no sale.
TIMEOUT = 10

#: Cuánto antes de su caducidad se considera gastada una sesión. Un margen y no una fecha
#: exacta: entre pedir la dirección y cargarse la última tesela pasa un rato, y una sesión que
#: caduca por el camino deja media pantalla sin dibujar.
MARGIN = 300


class MapKeyError(Exception):
    """No se ha podido conseguir una sesión. Lleva una clave de idioma y el detalle de quien
    contestó — que no se traduce, porque no es texto de este panel."""

    def __init__(self, key: str, detail: str = ''):
        super().__init__(key)
        self.key = str(key or 'gmaps_err')
        self.detail = str(detail or '')


#: La sesión en curso: `{'key_hash': …, 'session': …, 'expiry': …}`. En memoria y no en la base
#: de datos a propósito — es una credencial de corta vida y de un solo uso, y guardarla sería
#: una fila más que cifrar, que caducar y que explicar. Que cada proceso del panel pida la suya
#: es una llamada al arrancar y ninguna más.
_CACHE: dict = {}


def _hash(key: str) -> str:
    """Con qué clave se pidió la sesión guardada, sin guardar la clave.

    Cambiar la clave en la configuración tiene que tirar la sesión: si no, el panel seguiría
    pidiendo teselas con la clave vieja hasta que caducara, y lo que se vería es que cambiar la
    clave «no hace nada» durante dos semanas.
    """
    import hashlib                                                   # noqa: PLC0415
    return hashlib.sha256(str(key or '').encode('utf-8')).hexdigest()


def _open(url, data, timeout):
    """La llamada, aparte para poder sustituirla en las pruebas: una prueba que llama a Google
    falla el día que se cae, el día que caduca una clave y el día que alguien la ejecuta en un
    tren."""
    from urllib.request import Request, urlopen                      # noqa: PLC0415
    req = Request(url, data=data, method='POST',
                  headers={'Content-Type': 'application/json'})
    return urlopen(req, timeout=timeout)                             # noqa: S310


#: Con qué idioma y región se piden si nadie dice otra cosa. Un último recurso y no una
#: decisión: quien llama pasa el del panel (`lib.maps.settings`), porque unas teselas en inglés
#: en un panel en castellano son las etiquetas de un mapa que no se leen igual — y la región
#: decide cómo se dibujan las fronteras en litigio, que no es un detalle estético.
LANG = 'en-US'
REGION = 'US'


def lang_of(code: str) -> tuple:
    """El idioma y la región que entiende Google, del código del panel (`es_ES`).

    Ellos hablan BCP-47 —`es-ES`— y una región de dos letras aparte. Traducirlo aquí y no en
    quien llama: es una manía de esta API y no del panel.
    """
    c = str(code or '').strip().replace('_', '-')
    if not c:
        return LANG, REGION
    trozos = c.split('-')
    return c, (trozos[1].upper() if len(trozos) > 1 else trozos[0].upper())


def new_session(key: str, *, lang: str = LANG, region: str = REGION,
                map_type: str = MAP_TYPE) -> dict:
    """Pedir una sesión. Devuelve ``{'session', 'expiry'}`` o levanta :class:`MapKeyError`."""
    if not str(key or '').strip():
        raise MapKeyError('gmaps_err_nokey')
    cuerpo = json.dumps({'mapType': str(map_type or MAP_TYPE),
                         'language': lang, 'region': region})
    url = f'{SESSION_URL}?key={str(key).strip()}'
    try:
        with _open(url, cuerpo.encode('utf-8'), TIMEOUT) as r:
            datos = json.loads(r.read().decode('utf-8') or '{}')
    except Exception as exc:                         # pylint: disable=broad-except
        # El detalle es lo que dijo el otro extremo —un 403 de una clave sin la API activada,
        # un fallo de DNS en una instalación sin salida—, y por eso no se traduce.
        raise MapKeyError('gmaps_err_session', str(exc)) from exc
    sesion = str(datos.get('session') or '')
    if not sesion:
        raise MapKeyError('gmaps_err_session', json.dumps(datos)[:200])
    try:
        expira = int(str(datos.get('expiry') or 0))
    except (TypeError, ValueError):
        expira = 0
    return {'session': sesion, 'expiry': expira}


def session_for(key: str, *, lang: str = LANG, region: str = REGION,
                map_type: str = MAP_TYPE) -> str:
    """La sesión en vigor para esas condiciones, pidiendo una nueva si hace falta."""
    ahora = int(time.time())
    # TODO lo que se pidió cuenta, no sólo la clave: una sesión pedida en inglés y de callejero
    # sigue dando teselas en inglés y de callejero hasta que caduque, así que cambiar cualquiera
    # de las tres cosas «no haría nada» durante dos semanas.
    firma = _hash(f'{key}|{lang}|{region}|{map_type}')
    if (_CACHE.get('key_hash') == firma
            and _CACHE.get('session')
            and int(_CACHE.get('expiry') or 0) - MARGIN > ahora):
        return str(_CACHE['session'])
    nueva = new_session(key, lang=lang, region=region, map_type=map_type)
    _CACHE.update(nueva, key_hash=firma)
    return str(nueva['session'])


def forget() -> None:
    """Tirar la sesión guardada. Para las pruebas y para cuando cambia la clave."""
    _CACHE.clear()


def tiles(template: str, key: str, *, lang: str = LANG, region: str = REGION,
          map_type: str = MAP_TYPE) -> str:
    """La plantilla del catálogo con sus dos huecos rellenos, lista para el navegador."""
    sesion = session_for(key, lang=lang, region=region, map_type=map_type)
    return (str(template or '').replace('{session}', sesion)
            .replace('{key}', str(key or '').strip()))
