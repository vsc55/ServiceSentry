#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Con qué se dibuja un mapa en este panel: el catálogo de proveedores y la puerta de Google.

Aquí y no dentro del inventario porque ya lo preguntan tres sitios que no se conocen entre sí —la
cabecera de seguridad, el cuadro del inventario y la tarjeta del panel de control—, y el que se
quedara atrás no daría ningún error: dejaría un mapa vacío.
"""

from lib import APP_NAME

from .catalog import CUSTOM, GOOGLE, OFF, ORDER, PROVIDERS, known, origin_of, resolve

__all__ = ['CUSTOM', 'GOOGLE', 'OFF', 'ORDER', 'PROVIDERS', 'known', 'origin_of',
           'resolve', 'settings', 'probe_tile', 'fetch_tile']


def settings(wa) -> dict:
    """``{provider, tiles, attribution}`` de esta instalación, **listo para el navegador**.

    Lo que separa esto de :func:`lib.maps.catalog.resolve` es Google: su dirección lleva dos
    huecos que sólo puede rellenar el servidor, y para eso hay que hablar con ellos. Si esa
    llamada falla —clave equivocada, API sin activar, una instalación sin salida— el mapa se
    queda **apagado** en lugar de servir una dirección que va a dar error en cada una de las
    sesenta imágenes: un mapa que dice «no hay mapa» se entiende; sesenta cuadros rotos, no.

    Y **se dice por qué**, con una clave que la pantalla traduce. Apagarse en silencio dejaría a
    quien acaba de pegar su clave mirando el mismo cuadro vacío que antes de pegarla, sin nada
    que distinga «no lo he configurado» de «lo he configurado mal».
    """
    from lib.maps import google as gmaps                             # noqa: PLC0415
    cfg = {}
    try:
        cfg = wa._config_section('web_admin') or {}
    except Exception:                                # pylint: disable=broad-except
        cfg = {}
    fuera = resolve(cfg)
    if fuera['provider'] != GOOGLE:
        return fuera
    try:
        # En el idioma del panel: unas teselas en inglés dentro de un panel en castellano son
        # las etiquetas de un mapa que no se leen igual, y la región decide cómo se dibujan las
        # fronteras en litigio — que no es un detalle estético.
        lang, region = gmaps.lang_of(getattr(wa, '_DEFAULT_LANG', '') or '')
        fuera['tiles'] = gmaps.tiles(fuera['tiles'],
                                     str(cfg.get('dcim_map_google_key') or ''),
                                     lang=lang, region=region,
                                     map_type=str(cfg.get('dcim_map_google_type') or ''))
    except gmaps.MapKeyError as exc:
        return {'provider': GOOGLE, 'tiles': '', 'attribution': '', 'zmax': 0,
                'error': exc.key}
    except Exception:                                # pylint: disable=broad-except
        return {'provider': GOOGLE, 'tiles': '', 'attribution': '', 'zmax': 0,
                'error': 'gmaps_err_session'}
    return fuera

#: Qué tesela se pide para probar. La del nivel 1 y esquina 0,0 —un cuarto del mundo— porque
#: existe en todos los servidores y en todas las zonas: una de una calle concreta puede no estar
#: cargada en un espejo interno, y entonces la prueba diría que no funciona algo que funciona.
PROBE_Z, PROBE_X, PROBE_Y = 1, 0, 0

#: Cuánto se espera. Corto: quien pulsa el botón está mirando.
PROBE_TIMEOUT = 10


def probe_tile(template: str) -> dict:
    """Traerse UNA tesela desde este servidor y contar qué pasó.

    Que el navegador de cada persona pueda o no pedirla es otra pregunta —eso lo decide la
    política de contenido, y por eso se dice también el origen—, pero esto separa las dos causas
    que se confunden siempre: «esta máquina no tiene salida» y «lo que hay al otro lado no nos
    quiere dar imágenes».

    Nunca levanta: un botón de diagnóstico que revienta es un diagnóstico menos.
    """
    url = (str(template or '').replace('{z}', str(PROBE_Z)).replace('{x}', str(PROBE_X))
           .replace('{y}', str(PROBE_Y)).replace('{s}', 'a'))
    fuera = {'ok': False, 'status': 0, 'type': '', 'bytes': 0, 'detail': ''}
    try:
        from urllib.request import Request, urlopen                  # noqa: PLC0415
        # Con un agente identificado: la política de uso de teselas de OpenStreetMap lo pide, y
        # un cliente que no dice quién es se lleva un 403 de varios servidores.
        req = Request(url, headers={'User-Agent': f'{APP_NAME} map check'})
        with urlopen(req, timeout=PROBE_TIMEOUT) as r:               # noqa: S310
            datos = r.read(65536)
            fuera['status'] = int(getattr(r, 'status', 0) or 200)
            fuera['type'] = str(r.headers.get('Content-Type') or '')
            fuera['bytes'] = len(datos)
        # Una imagen, y no una página de error con un 200 encima: hay servidores que contestan
        # «no autorizado» en HTML sin cambiar el código.
        fuera['ok'] = fuera['bytes'] > 0 and fuera['type'].startswith('image/')
        if not fuera['ok'] and not fuera['detail']:
            fuera['detail'] = f"{fuera['status']} {fuera['type']}".strip()
    except Exception as exc:                         # pylint: disable=broad-except
        fuera['detail'] = str(exc)
    return fuera

def fetch_tile(template: str, z: int, x: int, y: int) -> tuple:
    """Una tesela concreta, en bytes. `(b'', '')` si no se pudo.

    Para el cuadro de prueba, que las pide POR EL PANEL en vez de directamente: la política de
    contenido sólo abre el origen que sale de la configuración **guardada**, así que un proveedor
    recién elegido tendría todas sus imágenes bloqueadas en silencio.

    Nunca levanta, por lo mismo que la sonda: un diagnóstico que revienta es un diagnóstico
    menos.
    """
    url = (str(template or '').replace('{z}', str(int(z))).replace('{x}', str(int(x)))
           .replace('{y}', str(int(y))).replace('{s}', 'a'))
    if not url.startswith(('http://', 'https://')):
        return b'', ''
    try:
        from urllib.request import Request, urlopen                  # noqa: PLC0415
        req = Request(url, headers={'User-Agent': f'{APP_NAME} map check'})
        with urlopen(req, timeout=PROBE_TIMEOUT) as r:               # noqa: S310
            tipo = str(r.headers.get('Content-Type') or '')
            datos = r.read(TILE_MAX)
        # Sólo imágenes: hay servidores que contestan una página de error con un 200 encima, y
        # devolverla como si fuera una tesela sería servir el HTML de otro desde este origen.
        return (datos, tipo) if tipo.startswith('image/') else (b'', '')
    except Exception:                                # pylint: disable=broad-except
        return b'', ''


#: Lo más grande que se acepta de una tesela. Una imagen de 256×256 no pasa de unos cientos de
#: kilobytes ni siendo una foto aérea; más que esto es que al otro lado no hay una tesela.
TILE_MAX = 2 * 1024 * 1024
