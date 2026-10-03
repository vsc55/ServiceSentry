#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""De dónde salen las imágenes que hay debajo de un mapa. El catálogo, y nada más.

Un mapa de este panel son **teselas XYZ**: imágenes numeradas por nivel, columna y fila, que es
lo que hablan OpenStreetMap, Carto, un servidor propio, un espejo interno y —por otra puerta—
Google. Y **nunca el SDK de un proveedor**: cargar las imágenes de un tercero le dice dónde están
tus sedes; ejecutar su guion le da la página entera. Lo primero se paga; lo segundo no se puede
pagar.

Aquí no hay red ni Flask: una tabla de proveedores y la función que contesta *«¿con qué dibuja
esta instalación, y a quién hay que dar las gracias?»*. Está en `lib/maps` y no dentro del
inventario porque ya lo preguntan tres sitios que no se conocen entre sí —la cabecera de
seguridad, el cuadro del inventario y la tarjeta del panel de control— y el que se quedara atrás
no daría ningún error: dejaría un mapa vacío.

**La atribución no es adorno.** La licencia de OpenStreetMap la exige, y una cadena fija dejaría
de ser cierta en cuanto alguien apunte esto a otro sitio — un crédito que nombra al proyecto
equivocado es peor que ninguno. Por eso viaja con el proveedor y se puede escribir a mano en el
personalizado.
"""

from __future__ import annotations

#: Apagado. **El defecto**, y a propósito: encender el mapa hace que el navegador de cada
#: persona que abra el panel le pida miles de imágenes a un tercero, que a partir de ahí sabe
#: dónde están los datacenters de esta organización. En una instalación sin salida, además, no
#: cargarían. Es una decisión de quien despliega, no un ajuste que se hereda.
OFF = ''

#: Lo que se teclea a mano: una plantilla propia, un espejo interno, un proveedor de pago que no
#: está en esta lista. Sigue existiendo porque una lista cerrada de proveedores sería una lista
#: que hay que editar para usar el servidor de teselas de tu propia casa.
CUSTOM = 'custom'

#: Por la puerta de su Map Tiles API, que es la única forma legítima de tener sus imágenes sin
#: ejecutar su código. No es una plantilla y ya: hace falta una clave, y el servidor tiene que
#: pedir antes una «sesión» (ver :mod:`lib.maps.google`).
GOOGLE = 'google'

#: Los que son una dirección y nada más, con las dos cosas que hay que saber de cada uno:
#:
#: * `attribution`, lo que hay que DECIR al pintar sus imágenes;
#: * `zmax`, hasta qué nivel de tesela llegan **según ellos**. No es un detalle: pedir una imagen
#:   que no existe no da ningún error visible — da un hueco en blanco al acercarse, y quien mira
#:   cree que el mapa se ha roto. Y pasado su tope no hay nada más que ver: es la misma foto
#:   agrandada.
PROVIDERS: dict[str, dict] = {
    'osm': {
        'tiles': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        'attribution': '© OpenStreetMap contributors',
        'zmax': 19,
        # Es un servicio de voluntarios, no una CDN. Quien lo elija hace bien en leerse antes su
        # política de uso de teselas — y en un panel con muchas pantallas abiertas, en pensarse
        # un espejo propio.
        'label_key': 'dcim_map_provider_osm',
    },
    'carto_light': {
        'tiles': 'https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
        'attribution': '© OpenStreetMap contributors © CARTO',
        'zmax': 20,
        'label_key': 'dcim_map_provider_carto_light',
    },
    'carto_dark': {
        # El oscuro no es una preferencia estética: este panel se deja abierto en una pantalla
        # de pared, y un mapa blanco en una sala a oscuras es una linterna.
        'tiles': 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        'attribution': '© OpenStreetMap contributors © CARTO',
        'zmax': 20,
        'label_key': 'dcim_map_provider_carto_dark',
    },
    # ── Ortofoto ─────────────────────────────────────────────────────────────────────────
    #
    # Un callejero no dibuja una antena en un monte ni una caseta en una finca, y hay sedes que
    # son exactamente eso. Y para las que sí están en un polígono, una foto de la nave es lo que
    # evita dar dos vueltas a la manzana de noche.
    #
    # **OpenStreetMap no tiene**, y no es que falte: son datos vectoriales dibujados por
    # voluntarios, y las imágenes aéreas con las que dibujan son de terceros y con licencias que
    # no dejan volver a servirlas. Así que la ortofoto viene de quien la vuela.
    'esri_imagery': {
        # Ojo al orden: aquí la fila va ANTES que la columna. No es un descuido copiando — es
        # como la sirven, y por eso las marcas se sustituyen por su nombre y no por su posición.
        'tiles': ('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery'
                  '/MapServer/tile/{z}/{y}/{x}'),
        'attribution': 'Esri, Maxar, Earthstar Geographics, and the GIS User Community',
        # Global hasta el 19; en algunas zonas hay más, pero pedirlo donde no lo hay son huecos
        # en blanco, así que el catálogo promete lo que se cumple en todas partes.
        'zmax': 19,
        'label_key': 'dcim_map_provider_esri',
    },
    'ign_pnoa': {
        # El Plan Nacional de Ortofotografía Aérea, del IGN. Sólo España — y por eso lo dice su
        # rótulo—, pero para una casa con sus sedes aquí es la mejor foto que hay y no pide
        # clave, ni facturación, ni registrarse. Se sirve por WMTS, que es teselas con otro
        # nombre y con los parámetros en la dirección.
        'tiles': ('https://www.ign.es/wmts/pnoa-ma?service=WMTS&request=GetTile&version=1.0.0'
                  '&layer=OI.OrthoimageCoverage&style=default&tilematrixset=GoogleMapsCompatible'
                  '&format=image/jpeg&tilematrix={z}&tilerow={y}&tilecol={x}'),
        'attribution': '© Instituto Geográfico Nacional de España',
        'zmax': 19,
        'label_key': 'dcim_map_provider_ign',
    },
    GOOGLE: {
        # La dirección lleva dos huecos más que los otros: la sesión y la clave. Los rellena
        # `lib.maps.google`, que es quien habla con ellos.
        'tiles': ('https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}'
                  '?session={session}&key={key}'),
        'attribution': 'Map data ©Google',
        'zmax': 22,
        'label_key': 'dcim_map_provider_google',
        'needs_key': True,
    },
    CUSTOM: {
        'tiles': '',                    # la que haya escrito quien despliega
        'attribution': '',
        # Lo que trae un servidor propio no lo sabe nadie más que quien lo montó — un espejo
        # interno con hasta el 16 y este panel pidiendo el 19 son huecos en blanco al acercarse,
        # sin un solo error por ninguna parte. Por eso hay un ajuste, y por eso su defecto es el
        # más común y no una promesa.
        'zmax': 19,
        'label_key': 'dcim_map_provider_custom',
    },
}

#: El orden del desplegable: primero el que casi todo el mundo quiere.
ORDER = ('', 'osm', 'carto_light', 'carto_dark', 'esri_imagery', 'ign_pnoa', GOOGLE, CUSTOM)

#: Qué clase de mapa se pide a Google. `roadmap` es el callejero de toda la vida —lo que sirve
#: para encontrar una nave en un polígono—; el de satélite se ve muy bien y no dice el nombre de
#: ninguna calle, y el de terreno está en medio. Sólo lo entiende Google: los demás sirven lo que
#: sirven.
GOOGLE_TYPES = ('roadmap', 'satellite', 'terrain')

#: Hasta dónde deja acercarse cualquiera. Ni por debajo del mundo entero ni por encima de lo que
#: ha existido nunca: un número fuera de esto no es una preferencia, es una errata.
ZMAX_MIN, ZMAX_MAX = 1, 22


def known(provider: str) -> bool:
    return str(provider or '') in PROVIDERS


def label_key(provider: str) -> str:
    """Cómo se llama un proveedor, **preguntándoselo al catálogo**.

    Y no componiendo `'dcim_map_provider_' + id`, que es lo que se hizo y salió a la pantalla:
    el del IGN se llama `ign_pnoa` y su rótulo es `dcim_map_provider_ign`, así que la clave
    compuesta no existía y lo que se leyó fue «dcim_map_provider_ign_pnoa» en medio de una
    frase. Una clave construida así no la ve nadie —ni el guardián de palabras ni un `grep`— y
    es la tercera vez que muerde en este panel.
    """
    return str((PROVIDERS.get(str(provider or '')) or {}).get('label_key')
               or 'dcim_map_provider_off')


def origin_of(tiles: str) -> str:
    """El ORIGEN de una plantilla, que es lo que necesita la política de contenido.

    Una tesela es `.../{z}/{x}/{y}.png` y la directiva tiene que cubrir el millón de rutas que
    hay debajo, no una. Vacío si no se puede leer: abrir un comodín porque una dirección venía
    rara sería exactamente lo contrario de lo que hace esta función.
    """
    try:
        from urllib.parse import urlsplit                            # noqa: PLC0415
        p = urlsplit(str(tiles or '').strip())
        if p.scheme in ('http', 'https') and p.netloc:
            return f'{p.scheme}://{p.netloc}'
    except Exception:                                # pylint: disable=broad-except
        pass
    return ''


def origins_for(cfg: dict) -> list:
    """Los orígenes de los que esta instalación puede cargar imágenes.

    **Vacío mientras no haya mapa**, que es la propiedad que importa y la que se defiende: una
    instalación sin mapa no le puede pedir una imagen a nadie, y su política queda exactamente
    como estaba.

    Pero en cuanto HAY mapa se abren todos los del catálogo, y no sólo el elegido. La razón es
    una pregunta que se hizo desde la pantalla y que no tenía buena respuesta: la política viaja
    en la cabecera de cada página, así que cambiar de proveedor obligaba a recargar antes de que
    el mapa nuevo pudiera cargar — y mientras tanto no cargaba **nada**, en silencio.
    Costaba una recarga y un «¿por qué?» cada vez.

    Lo que se paga por evitarlo es esto: cinco servidores de imágenes conocidos en lugar de uno.
    Quien ya tiene un mapa ya confía en cargar imágenes de un servidor de teselas; que la lista
    tenga los otros cuatro del catálogo no cambia la forma de lo que se puede hacer con ella, y
    los cinco son direcciones fijas escritas aquí, no un comodín. Lo que sí cambiaría la forma
    —abrir esto en una instalación que no usa mapas— es justo lo que no pasa.
    """
    elegido = resolve(cfg)
    if not elegido['provider']:
        return []
    # Una plantilla propia que no se entiende es un mapa que no va a cargar, así que tampoco es
    # razón para abrirle la política a nada: la respuesta a un ajuste mal escrito es un mapa que
    # no sale, no una lista de permisos por un mapa que no existe.
    if elegido['provider'] == CUSTOM and not origin_of(elegido['tiles']):
        return []
    fuera = []
    for datos in PROVIDERS.values():
        origen = origin_of(datos.get('tiles') or '')
        if origen and origen not in fuera:
            fuera.append(origen)
    # Y el suyo, que en «personalizado» no está en la tabla.
    propio = origin_of(elegido['tiles'])
    if propio and propio not in fuera:
        fuera.append(propio)
    return fuera


def resolve(cfg: dict) -> dict:
    """``{provider, tiles, attribution}`` a partir de los ajustes de `web_admin`.

    Sin red: para Google devuelve su plantilla **con los huecos sin rellenar**, porque el origen
    —que es lo único que necesita la cabecera de seguridad— no depende de ninguna sesión. Quien
    vaya a dibujar de verdad pasa después por :func:`lib.maps.google.tiles`.

    **Compatible hacia atrás sin decirlo dos veces:** una instalación que ya tenía escrita su
    plantilla y ningún proveedor elegido sigue funcionando, porque eso ES el personalizado. Al
    revés —obligar a elegir «personalizado» para que lo de ayer siga valiendo— sería apagarle el
    mapa a quien no ha tocado nada.
    """
    cfg = cfg or {}
    provider = str(cfg.get('dcim_map_provider') or '').strip()
    propia = str(cfg.get('dcim_map_tiles') or '').strip()
    if not provider:
        provider = CUSTOM if propia else OFF
    if provider == OFF or not known(provider):
        return {'provider': OFF, 'tiles': '', 'attribution': '', 'zmax': 0}
    p = PROVIDERS[provider]
    # Hasta dónde se puede acercar: lo que ofrece el proveedor, salvo que alguien lo diga. Lo
    # segundo existe por los espejos internos, que traen lo que traigan.
    zmax = p.get('zmax') or ZMAX_MAX
    try:
        dicho = int(cfg.get('dcim_map_max_zoom') or 0)
    except (TypeError, ValueError):
        dicho = 0
    if ZMAX_MIN <= dicho <= ZMAX_MAX:
        zmax = dicho
    if provider == CUSTOM:
        return {'provider': CUSTOM, 'tiles': propia, 'zmax': zmax,
                'attribution': str(cfg.get('dcim_map_attribution') or '')}
    return {'provider': provider, 'tiles': p['tiles'], 'zmax': zmax,
            'attribution': p['attribution']}
