#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Los recursos de Freshservice que este panel pide. Uno por función, y cada una de dos líneas.

Todo lo que es cierto de la API entera —cómo se llama, cómo autentica, cómo pagina, cómo falla,
cómo escribe las fechas y cómo dice que se acabó el cupo— vive en :mod:`.api`. Aquí sólo está lo
que cambia de un recurso a otro: su ruta y el nombre de su sobre.

Esa es toda la gracia: traer los agentes, los activos o los tickets mañana es escribir una función
de dos líneas, no volver a leerse la documentación y volver a equivocarse con la paginación.

Hoy hay uno, porque es el que se ha pedido: los **departamentos**, que en Freshservice son las
empresas — lo dice su propia documentación, que titula esa sección «Departments / Companies».
"""

from __future__ import annotations

from lib.providers.freshservice import api
from lib.providers.freshservice.api import (          # noqa: F401  (la puerta de este paquete)
    DEEP_PAGE_LIMIT, PER_PAGE_MAX, TIMEOUT, FreshserviceError, host_of, is_freshservice_host,
    rate,
)

#: Los nombres con los que este fichero llamaba a dos de esas constantes cuando lo genérico y lo
#: concreto estaban juntos. Se quedan porque son los que se leen desde fuera.
PER_PAGE = PER_PAGE_MAX
MAX_PAGES = DEEP_PAGE_LIMIT


def _abrir(domain: str, api_key: str):
    """El dominio comprobado y una sesión abierta, que es lo que necesita cualquier recurso.

    Se comprueba **antes de llamar** que el dominio sea de Freshservice: su API «works only via
    Freshservice domains and not via custom CNAMEs», y un CNAME de la casa resuelve, contesta y
    devuelve cualquier cosa — un fallo que sin esto se investiga por el lado que no es.
    """
    host = api.host_of(domain)
    if not host:
        raise api.FreshserviceError('fs_err_domain')
    if not api.is_freshservice_host(host):
        raise api.FreshserviceError('fs_err_cname', host)
    if not str(api_key or '').strip():
        raise api.FreshserviceError('fs_err_key')
    return host, api.session(api_key)


def departments(domain: str, api_key: str) -> list:
    """Todos los departamentos —las empresas—, con sus páginas recorridas.

    Devuelve las filas tal cual las da Freshservice: emparejarlas con lo de aquí es de
    :mod:`lib.providers.freshservice.plan`, que no tiene red delante y por eso se puede probar.
    """
    host, sess = _abrir(domain, api_key)
    with sess:
        return api.page_all(sess, host, 'departments', 'departments')


def probe(domain: str, api_key: str) -> dict:
    """Una página de uno, para contestar «¿esto conecta?» sin traerse diez mil filas.

    Devuelve además lo que la respuesta diga del cupo: «te quedan 12 de 200» es la otra mitad de
    la respuesta cuando alguien está mirando por qué una importación va a trompicones.
    """
    host, sess = _abrir(domain, api_key)
    with sess:
        _cuerpo, cabeceras = api.get(sess, host, 'departments', {'page': 1, 'per_page': 1})
    return {'host': host, 'rate': api.rate(cabeceras)}


# ── La página de estado ─────────────────────────────────────────────────────────────────
#
# Su módulo de «Status Page»: las páginas publicadas, los incidentes abiertos y los componentes
# de servicio. Se lee al probar la conexión porque contesta la otra mitad de la pregunta — la
# clave vale, ¿y qué se ve con ella? —, y porque es lo que dice si esa casa está ahora mismo con
# algo caído, que es lo que se quiere saber cuando una importación va rara.
#
# **Todo esto es opcional, y por eso se lee en blando.** El módulo no está en todos los planes,
# la clave puede no alcanzarlo, y su documentación publica los verbos pero no la lista de campos.
# Que falte no puede convertir una clave buena en una prueba fallida: lo principal es la clave.

def status_pages(domain: str, api_key: str) -> list:
    """Las páginas de estado publicadas."""
    host, sess = _abrir(domain, api_key)
    with sess:
        cuerpo, _cab = api.get(sess, host, 'status_pages')
    return api.unwrap_soft(cuerpo, 'status_pages') or []


def status_incidents(domain: str, api_key: str) -> list:
    """Los incidentes de la página de estado."""
    host, sess = _abrir(domain, api_key)
    with sess:
        cuerpo, _cab = api.get(sess, host, 'status_pages/incidents')
    return api.unwrap_soft(cuerpo, 'incidents') or []


def service_components(domain: str, api_key: str) -> list:
    """Los componentes de servicio que esa página publica."""
    host, sess = _abrir(domain, api_key)
    with sess:
        cuerpo, _cab = api.get(sess, host, 'status_pages/service_components')
    return api.unwrap_soft(cuerpo, 'service_components') or []


def status_summary(domain: str, api_key: str) -> dict:
    """Lo que se puede decir de la página de estado de esa casa, sin que falle nada.

    Devuelve `{available, pages, incidents, components, error_key}`. **Cada lectura por su
    cuenta**: que no haya componentes no puede esconder los incidentes, y que el módulo entero no
    exista no puede tumbar la prueba de la clave — que es lo que de verdad se estaba probando.

    Los nombres se sacan con `api.name_of`, que prueba `name`, `title` y `subject` y se cae al
    identificador: su documentación no publica los campos de este recurso, y adivinar uno sería
    una pantalla en blanco el día que sea otro.
    """
    fuera = {'available': False, 'pages': [], 'incidents': [], 'components': [],
             'error_key': ''}
    for clave, fn in (('pages', status_pages),
                      ('incidents', status_incidents),
                      ('components', service_components)):
        try:
            filas = fn(domain, api_key) or []
        except api.FreshserviceError as exc:
            # La primera que falle deja dicho POR QUÉ, y las demás se siguen intentando: un 403
            # en componentes no dice nada de los incidentes.
            fuera['error_key'] = fuera['error_key'] or exc.key
            continue
        fuera['available'] = True
        fuera[clave] = [{'name': api.name_of(f),
                         'status': str((f or {}).get('status') or '')} for f in filas]
    return fuera
