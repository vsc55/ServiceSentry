#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El proveedor de GitHub: analizar una URL, mirar sin traer, y traer sin volver a saludar.

Lo que se prueba aquí es lo que no se ve funcionar hasta que falla. Traerse un repositorio como
un zip vale mientras el repositorio quepa; el catálogo de modelos del inventario pesa ochocientos
cincuenta megas y hay que preguntarle qué tiene sin bajarlo. Y traer noventa ficheros uno a uno
son noventa saludos TLS, que es la diferencia entre importar un fabricante en quince segundos o
en minuto y medio.

Nada de esto habla con GitHub: lo que se comprueba son las decisiones —qué URL se construye, qué
significa cada código, qué pasa cuando la conexión se cae a mitad— y no que internet exista.
"""

import pytest

from lib.providers import github as gh


class TestUnaUrlEsUnRepositorioONoLoEs:
    """De lo que se escriba en un hueco sale una petición. Si no sale, hay que decirlo antes."""

    def test_la_raiz_de_un_repositorio_vale(self):
        assert gh._ref_of('https://github.com/netbox-community/devicetype-library') == \
            ('netbox-community', 'devicetype-library', 'master', '')

    def test_una_rama_escrita_manda_sobre_la_de_por_defecto(self):
        """Quien apunta a un fork suyo escribe `main` donde el original tiene `master`, y esa es
        exactamente la diferencia entre traerse el catálogo y un 404."""
        ref = gh._ref_of('https://github.com/quien-sea/lo-suyo/tree/main/device-types')
        assert ref == ('quien-sea', 'lo-suyo', 'main', 'device-types')

    def test_lo_que_no_es_github_no_se_intenta(self):
        assert gh._ref_of('https://example.com/algo') is None
        assert gh.list_tree('https://example.com/algo') == ([], 'bad_url')


class TestPorQueFalloSeDiceEnPalabras:
    """404 y 403 son dos problemas con dos soluciones, y «no se pudo» no distingue cuál fue."""

    def test_una_rama_que_no_existe_se_nombra(self):
        assert gh._http_reason(_HttpError(404)) == 'not_found'
        assert gh._status_reason(404) == 'not_found'

    def test_el_limite_agotado_se_nombra(self):
        """Sesenta peticiones por hora sin credencial. Se arregla esperando, no reescribiendo
        la dirección — y quien lea «no se pudo descargar» probará lo segundo."""
        assert gh._http_reason(_HttpError(403)) == 'rate_limited'
        assert gh._status_reason(403) == 'rate_limited'

    def test_un_codigo_que_no_se_conocia_se_dice_entero(self):
        """Inventar una frase para un 502 sería tapar el único dato que hay."""
        assert gh._http_reason(_HttpError(502)) == 'http_502'

    def test_sin_codigo_queda_el_motivo_de_la_red(self):
        assert gh._http_reason(OSError('conexión rechazada')) == 'conexión rechazada'


class TestElEnvoltorioSeDetectaAunqueSeaElMismo:
    """Un zip de GitHub trae la entrada de directorio de su propia carpeta envoltorio.

    Leída como si fuera un fichero, `devicetype-library-master/` es un nombre de un solo trozo —
    o sea, algo en la raíz— así que la función concluía que no había envoltorio: **el envoltorio
    impedía detectarse a sí mismo**. Con eso cada nombre lo conservaba delante y ninguna imagen se
    encontraba nunca, sin que fallara nada: ocho mil aparatos sin foto es un resultado creíble,
    porque miles de modelos de verdad no traen ninguna.
    """

    def test_la_carpeta_del_envoltorio_no_cuenta_como_raiz(self):
        miembros = [_Miembro('lo-suyo-master/'),
                    _Miembro('lo-suyo-master/device-types/'),
                    _Miembro('lo-suyo-master/device-types/HP/DL380.yaml'),
                    _Miembro('lo-suyo-master/elevation-images/HP/dl380.front.png')]
        assert gh.wrapper_of(miembros) == 'lo-suyo-master'

    def test_un_FICHERO_en_la_raiz_sigue_diciendo_que_no_hay_envoltorio(self):
        """Que es lo que la comprobación buscaba de verdad: un archivo con estructura propia se
        queda entero, porque quitarle un nivel le quitaría significado."""
        miembros = [_Miembro('LEEME.txt'), _Miembro('mibs/ALGO-MIB.txt')]
        assert gh.wrapper_of(miembros) == ''

    def test_dos_carpetas_arriba_tampoco_son_un_envoltorio(self):
        miembros = [_Miembro('una/a.txt'), _Miembro('otra/b.txt')]
        assert gh.wrapper_of(miembros) == ''


class TestFetchManyNoVuelveASaludar:
    """Noventa ficheros por una conexión, no por noventa."""

    URL = 'https://github.com/quien-sea/lo-suyo'

    def test_se_abre_una_sola_conexion_para_todos(self, monkeypatch):
        conexiones = _finge(monkeypatch, {'/quien-sea/lo-suyo/master/a.yaml': (200, b'A'),
                                          '/quien-sea/lo-suyo/master/b.yaml': (200, b'B')})
        salida = list(gh.fetch_many(self.URL, ['a.yaml', 'b.yaml']))
        assert [(r, d, e) for r, d, e in salida] == [('a.yaml', b'A', ''), ('b.yaml', b'B', '')]
        assert len(conexiones) == 1, 'un saludo TLS por fichero es lo que se venía a evitar'

    def test_si_la_conexion_se_cae_se_abre_otra_y_se_sigue(self, monkeypatch):
        """Un servidor puede cerrar cuando quiera. Perder los ochenta ficheros que quedaban por
        eso sería perderlos por algo que no es un error."""
        conexiones = _finge(monkeypatch, {'/quien-sea/lo-suyo/master/a.yaml': (200, b'A')},
                            romper_en=1)
        salida = list(gh.fetch_many(self.URL, ['a.yaml']))
        assert salida == [('a.yaml', b'A', '')]
        assert len(conexiones) == 2, 'no se reintentó con una conexión nueva'

    def test_un_fichero_que_falta_no_para_los_demas(self, monkeypatch):
        _finge(monkeypatch, {'/quien-sea/lo-suyo/master/a.yaml': (200, b'A'),
                             '/quien-sea/lo-suyo/master/no.yaml': (404, b'')})
        salida = list(gh.fetch_many(self.URL, ['no.yaml', 'a.yaml']))
        assert salida[0][2] == 'not_found' and salida[1][1] == b'A'

    def test_lo_que_pasa_del_tope_no_se_devuelve(self, monkeypatch):
        """El tope corta de verdad: se lee un byte de más para saber que sobraba."""
        _finge(monkeypatch, {'/quien-sea/lo-suyo/master/g.bin': (200, b'x' * 50)})
        salida = list(gh.fetch_many(self.URL, ['g.bin'], max_bytes=10))
        assert salida[0][1] is None and salida[0][2] == 'too_large'

    def test_una_url_que_no_es_un_repositorio_lo_dice_de_cada_fichero(self, monkeypatch):
        salida = list(gh.fetch_many('https://example.com/x', ['a.yaml']))
        assert salida == [('a.yaml', None, 'bad_url')]

    def test_una_ruta_con_espacios_se_escapa_sin_romper_las_barras(self, monkeypatch):
        """Las barras son estructura y no texto: escaparlas convertiría una ruta en un nombre de
        fichero larguísimo que no existe."""
        conexiones = _finge(monkeypatch,
                            {'/quien-sea/lo-suyo/master/dir/Con%20Espacio.yaml': (200, b'ok')})
        salida = list(gh.fetch_many(self.URL, ['dir/Con Espacio.yaml']))
        assert salida[0][1] == b'ok'
        assert conexiones[0].pedidas == ['/quien-sea/lo-suyo/master/dir/Con%20Espacio.yaml']


# ── El andamiaje ────────────────────────────────────────────────────────────────────────
#
# Una conexión de mentira que anota lo que le piden. Con esto se puede comprobar que se abrió
# UNA y no noventa, que es la única forma de verlo: por fuera las dos devuelven lo mismo.


class _Miembro:
    """Una entrada de zip con lo único que `wrapper_of` mira: cómo se llama."""

    def __init__(self, filename):
        self.filename = filename

    def is_dir(self):
        return self.filename.endswith('/')


class _HttpError(Exception):
    def __init__(self, code):
        super().__init__('HTTP %s' % code)
        self.code = code


class _Resp:
    def __init__(self, status, cuerpo):
        self.status = status
        self._cuerpo = cuerpo

    def read(self, n=-1):
        return self._cuerpo[:n] if n and n > 0 else self._cuerpo


class _Conn:
    def __init__(self, respuestas, romper_en=0):
        self._respuestas = respuestas
        self._romper_en = romper_en
        self.pedidas = []
        self.cerrada = False

    def request(self, method, url, headers=None):
        self.pedidas.append(url)
        if self._romper_en and len(self.pedidas) >= self._romper_en:
            raise OSError('la conexión se cerró')

    def getresponse(self):
        status, cuerpo = self._respuestas.get(self.pedidas[-1], (404, b''))
        return _Resp(status, cuerpo)

    def close(self):
        self.cerrada = True


def _finge(monkeypatch, respuestas, romper_en=0):
    """Sustituye `http.client` por conexiones de mentira. Devuelve la lista de las que se abrieron.

    La lista es el dato que importa: `fetch_many` existe para que esa lista tenga un elemento.
    """
    abiertas = []

    class _Lib:
        @staticmethod
        def HTTPSConnection(host, timeout=0):          # noqa: N802  (imita la de verdad)
            # Solo la primera se rompe: la segunda es el reintento, y tiene que funcionar.
            conn = _Conn(respuestas, romper_en if not abiertas else 0)
            abiertas.append(conn)
            return conn

    monkeypatch.setattr(gh, '_httplib', lambda: _Lib)
    return abiertas


if __name__ == '__main__':                              # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
