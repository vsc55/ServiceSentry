#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El contrato de la API de Freshservice, escrito una vez y comprobado aquí.

`lib/providers/freshservice/api.py` no sabe qué es un departamento: sabe cómo se llama a esa API,
cómo contesta, cómo pagina, cómo falla y cómo escribe las horas. Es lo que hace que traer agentes
o activos mañana sea una función de dos líneas — y por eso lo que se rompa aquí se rompe para
todo lo que venga después, no para una pantalla.

Sin red: se le dan respuestas de mentira con las cabeceras que ellos publican y se mira qué hace.
Cada cosa que se fija está sacada de su documentación, y lo que es decisión nuestra lo dice.
"""

import pytest

from lib.providers.freshservice import api
from lib.providers.freshservice import api as fs_api
from lib.providers.freshservice import client as fs_client


class _Resp:
    """Una respuesta como la que devolvería `requests`, con lo justo."""

    def __init__(self, status=200, body=None, headers=None, text=''):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError('no es JSON')
        return self._body


class _Sess:
    """Una sesión que contesta lo que se le diga, y apunta lo que le pidieron."""

    def __init__(self, respuestas):
        self._r = list(respuestas)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({'url': url, 'params': dict(params or {}), 'timeout': timeout})
        return self._r.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestComoSeLlama:
    """`https://<dominio>/api/v2/<recurso>`, sólo HTTPS y sólo por un dominio suyo."""

    def test_la_direccion_lleva_la_version_y_va_por_https(self):
        assert api.url('lacasa.freshservice.com', 'departments') \
            == 'https://lacasa.freshservice.com/api/v2/departments'
        assert api.API_VERSION == 'v2'

    def test_y_el_dominio_se_teclea_como_se_quiera(self):
        for escrito in ('lacasa.freshservice.com', 'https://lacasa.freshservice.com',
                        'https://lacasa.freshservice.com/', ' LaCasa.Freshservice.com ',
                        'lacasa'):
            assert api.host_of(escrito) == 'lacasa.freshservice.com', escrito

    def test_y_sin_nada_no_se_inventa_uno(self):
        assert api.host_of('') == ''

    def test_y_un_cname_propio_se_reconoce_como_lo_que_es(self):
        """«Works only via Freshservice domains and not via custom CNAMEs», dice su
        documentación — y un CNAME de la casa resuelve, contesta y devuelve cualquier cosa, que
        es un fallo que sin esto se investiga por el lado que no es."""
        assert api.is_freshservice_host('lacasa.freshservice.com') is True
        assert api.is_freshservice_host('soporte.lacasa.example') is False

    def test_y_la_clave_va_de_usuario_con_una_x_de_contraseña(self):
        """«If you use the API key, there is no need for a password. You can use any set of
        characters as a dummy password»."""
        s = api.session('k-secreta')
        assert s.auth == ('k-secreta', 'X')
        assert s.headers.get('Content-Type') == 'application/json'


class TestComoContesta:
    """Un sobre con una clave: la lista bajo el plural, el objeto suelto bajo el singular."""

    def test_lo_de_dentro_se_saca_por_su_nombre(self):
        assert api.unwrap({'departments': [1, 2]}, 'departments') == [1, 2]
        assert api.unwrap({'ticket': {'id': 7}}, 'ticket') == {'id': 7}

    def test_y_un_sobre_que_no_es_el_suyo_se_nota(self):
        """Por NOMBRE y no «lo primero que venga»: así un cuerpo inesperado da un fallo con
        nombre, en vez de convertirse en una lista vacía que parece una casa sin departamentos."""
        for cuerpo in ({'otra_cosa': []}, {}, [], 'texto'):
            try:
                api.unwrap(cuerpo, 'departments')
            except api.FreshserviceError as exc:
                assert exc.key == 'fs_err_body'
            else:
                raise AssertionError(f'ha pasado por bueno: {cuerpo!r}')


class TestComoPagina:

    def test_se_piden_de_cien_en_cien_que_es_su_maximo(self):
        assert api.PER_PAGE_MAX == 100

    def test_y_no_se_pasa_de_la_pagina_que_ellos_piden_no_pasar(self):
        """500, y es SUYO: «avoid making calls referencing page numbers over 500 (deep
        pagination)»."""
        assert api.DEEP_PAGE_LIMIT == 500

    def test_la_cabecera_link_dice_si_queda_algo(self):
        """«If you have reached the last page of objects, then the link header will not be
        set»."""
        assert api.has_next({'link': '<https://x/api/v2/departments?page=2>;rel="next"'}) is True
        assert api.has_next({}) is False
        assert api.has_next({'link': '<...>;rel="prev"'}) is False

    def test_y_se_recorren_todas_las_paginas(self):
        """Por defecto contesta treinta: una casa con cuarenta sociedades importaría treinta y
        parecería que están todas."""
        llenas = {'departments': [{'id': n} for n in range(100)]}
        sess = _Sess([_Resp(body=llenas, headers={'link': '<x>;rel="next"'}),
                      _Resp(body={'departments': [{'id': 100}]}, headers={})])
        fuera = api.page_all(sess, 'lacasa.freshservice.com', 'departments', 'departments')
        assert len(fuera) == 101
        assert [c['params']['page'] for c in sess.calls] == [1, 2]
        assert sess.calls[0]['params']['per_page'] == 100

    def test_y_una_pagina_llena_sin_cabecera_es_la_ultima(self):
        """El caso en el que **sólo** la cabecera puede decidir: exactamente cien departamentos.
        La página viene llena, así que «venía a medias» no sirve de nada, y lo único que dice que
        se acabó es que no hay `link`. Sin mirarla se pide una página de más — y a un servidor
        menos amable, un error.

        Este caso faltaba, y por faltar la comprobación de la cabecera se podía borrar entera sin
        que ninguna prueba se quejara. Encontrado por mutación.
        """
        sess = _Sess([_Resp(body={'departments': [{'id': n} for n in range(100)]}, headers={})])
        assert len(api.page_all(sess, 'h', 'departments', 'departments')) == 100
        assert len(sess.calls) == 1, 'ha pedido una página de más'

    def test_y_sin_la_cabecera_para_en_la_primera(self):
        sess = _Sess([_Resp(body={'departments': [{'id': 1}]}, headers={})])
        assert len(api.page_all(sess, 'h', 'departments', 'departments')) == 1
        assert len(sess.calls) == 1

    def test_y_una_pagina_a_medias_para_aunque_mientan_las_cabeceras(self):
        """El respaldo por si un intermediario se comiera la cabecera `link`: sin él, un proxy
        que la quite deja la petición pidiendo páginas hasta la 500."""
        sess = _Sess([_Resp(body={'departments': [{'id': 1}]},
                            headers={'link': '<x>;rel="next"'})])
        assert len(api.page_all(sess, 'h', 'departments', 'departments')) == 1
        assert len(sess.calls) == 1


class TestComoVaDeTiempo:
    """Marcas en UTC con la forma `YYYY-MM-DDTHH:MM:SSZ`; en las entradas admiten ocho formatos
    y asumen UTC cuando no se dice la zona."""

    def test_la_forma_es_la_que_publican(self):
        assert api.TIMESTAMP_FMT == '%Y-%m-%dT%H:%M:%SZ'

    def test_y_se_lee_la_suya(self):
        d = api.parse_stamp('2016-02-13T23:27:49Z')
        assert (d.year, d.month, d.day, d.hour) == (2016, 2, 13, 23)
        assert d.utcoffset().total_seconds() == 0

    def test_y_sin_zona_se_asume_utc_como_dicen_ellos(self):
        assert api.parse_stamp('2016-02-13T23:27:49').utcoffset().total_seconds() == 0
        assert api.parse_stamp('2016-02-13').utcoffset().total_seconds() == 0

    def test_y_con_desplazamiento_tambien(self):
        d = api.parse_stamp('2016-02-13T23:27:49+02:00')
        assert d.utcoffset().total_seconds() == 7200

    def test_y_lo_que_no_es_una_fecha_no_lo_parece(self):
        assert api.parse_stamp('ayer por la tarde') is None
        assert api.parse_stamp('') is None

    def test_y_se_escribe_siempre_la_larga(self):
        """La corta se admite y ahorra dos caracteres a costa de que la zona la ponga otro."""
        from datetime import datetime, timezone
        assert api.stamp(datetime(2016, 2, 13, 23, 27, 49, tzinfo=timezone.utc)) \
            == '2016-02-13T23:27:49Z'


class TestComoLimita:

    def test_el_cupo_se_lee_de_sus_cabeceras(self):
        r = api.rate({'X-RateLimit-Total': '200', 'X-RateLimit-Remaining': '12',
                      'X-RateLimit-Used-CurrentRequest': '1', 'Retry-After': '43'})
        assert r == {'total': 200, 'remaining': 12, 'used': 1, 'retry_after': 43}

    def test_y_lo_que_no_venga_vale_cero_en_vez_de_reventar(self):
        """Quien lo enseñe no tiene por qué saber que a veces esa cabecera no está."""
        assert api.rate({})['remaining'] == 0
        assert api.rate({'X-RateLimit-Remaining': 'muchas'})['remaining'] == 0

    def test_y_un_429_trae_los_segundos_que_hay_que_esperar(self):
        """`Retry-After` en segundos: «vuelve en 43 segundos» es una frase, y «error» no."""
        sess = _Sess([_Resp(status=429, body={'description': 'rate limit'},
                            headers={'Retry-After': '43'})])
        try:
            api.get(sess, 'h', 'departments')
        except api.FreshserviceError as exc:
            assert exc.key == 'fs_err_rate' and exc.retry_after == 43
        else:
            raise AssertionError('un 429 ha pasado por bueno')


class TestComoFalla:

    def test_cada_codigo_va_a_su_clave(self):
        """Detrás de cada uno hay una cosa distinta que arreglar: 401 es la clave, 403 es lo que
        ESA clave puede hacer, 404 el dominio o el recurso, 405 un fallo de este código."""
        assert api.STATUS_KEYS[401] != api.STATUS_KEYS[403]
        assert len(set(api.STATUS_KEYS.values())) == len(api.STATUS_KEYS)
        for codigo in (400, 401, 403, 404, 405, 429, 500):
            assert codigo in api.STATUS_KEYS

    def test_y_lo_que_ellos_cuentan_del_fallo_viaja_en_el_detalle(self):
        """Su cuerpo trae `description` y una lista `errors` con `field` y `message`: el código
        dice la CLASE de fallo y esto dice cuál."""
        sess = _Sess([_Resp(status=400, body={
            'description': 'Validation failed',
            'errors': [{'field': 'name', 'message': 'has already been taken', 'code': 'duplicate'}]})])
        try:
            api.get(sess, 'h', 'departments')
        except api.FreshserviceError as exc:
            assert exc.key == 'fs_err_request'
            assert 'Validation failed' in exc.detail and 'name: has already been taken' in exc.detail
        else:
            raise AssertionError('un 400 ha pasado por bueno')

    def test_y_un_cuerpo_que_no_es_json_se_dice_como_lo_que_suele_ser(self):
        """Casi siempre es el portal de acceso de un proxy o de un cortafuegos contestando por el
        servidor. Dicho así, se va a mirar ahí."""
        sess = _Sess([_Resp(body=None, text='<html>Acceso denegado por la pasarela</html>')])
        try:
            api.get(sess, 'h', 'departments')
        except api.FreshserviceError as exc:
            assert exc.key == 'fs_err_body'
            assert 'pasarela' in exc.detail
        else:
            raise AssertionError('un cuerpo que no es JSON ha pasado por bueno')

    def test_y_ninguna_llamada_se_queda_esperando_para_siempre(self):
        """Nuestro, no suyo: sin tope, un cortafuegos que traga los paquetes deja la petición —y
        la pantalla— colgada hasta que se aburra el navegador."""
        sess = _Sess([_Resp(body={'departments': []})])
        api.get(sess, 'h', 'departments')
        assert sess.calls[0]['timeout'] == api.TIMEOUT and api.TIMEOUT > 0


class TestPedirSoloUnasClasesDeActivo:
    """El filtro se le pide al origen para no traerse cuatro mil activos cuando hacen falta
    cuarenta. Pero su forma no es la misma en todos los planes, y un origen que no lo entienda
    contesta un 400 — que no puede convertirse en «no se puede importar»."""

    def _espia(self, monkeypatch, fallar_con_filtro=False):
        visto = []

        def _page_all(sess, host, path, key, params=None, per_page=100):
            visto.append(dict(params or {}))
            if fallar_con_filtro and 'filter' in (params or {}):
                raise fs_api.FreshserviceError('fs_err_request', 'no such filter')
            return [{'id': 1}]

        monkeypatch.setattr('lib.providers.freshservice.api.page_all', _page_all)
        monkeypatch.setattr('lib.providers.freshservice.api.session', lambda k: _Sesion())
        return visto

    def test_sin_clases_no_manda_filtro(self, monkeypatch):
        visto = self._espia(monkeypatch)
        fs_client.assets('casa.freshservice.com', 'k')
        assert 'filter' not in visto[0]
        assert visto[0]['include'] == 'type_fields', 'sin esto no viene ni la dirección'

    def test_con_clases_las_pide_todas_en_una_consulta(self, monkeypatch):
        """Una consulta con un `OR` y no una llamada por clase: tres clases serían tres recorridos
        completos de páginas para la misma respuesta."""
        visto = self._espia(monkeypatch)
        fs_client.assets('casa.freshservice.com', 'k', ['7001', '7002'])
        assert visto[0]['filter'] == '"asset_type_id:7001 OR asset_type_id:7002"'

    def test_lo_que_no_es_un_numero_no_llega_a_la_consulta(self, monkeypatch):
        """Viene de una pantalla. Un identificador que no sea entero no se arregla escapándolo:
        no puede ser uno suyo."""
        visto = self._espia(monkeypatch)
        fs_client.assets('casa.freshservice.com', 'k', ['7001', "1 OR 1=1", ''])
        assert visto[0]['filter'] == '"asset_type_id:7001"'

    def test_un_origen_que_no_entiende_el_filtro_sigue_trayendo(self, monkeypatch):
        """Se vuelve a preguntar sin filtro. Quien llama filtra igualmente lo que reciba, así que
        lo único que se pierde es el ahorro de viajes — no la importación."""
        visto = self._espia(monkeypatch, fallar_con_filtro=True)
        assert fs_client.assets('casa.freshservice.com', 'k', ['7001']) == [{'id': 1}]
        assert len(visto) == 2 and 'filter' not in visto[1]

    def test_pero_un_fallo_de_verdad_no_se_esconde_detras_del_reintento(self, monkeypatch):
        """Una clave que no vale contesta 401, y volver a preguntar sin filtro contestaría 401
        otra vez. Tragárselo convertiría «tu clave no vale» en «no hay activos»."""
        def _page_all(sess, host, path, key, params=None, per_page=100):
            raise fs_api.FreshserviceError('fs_err_auth')

        monkeypatch.setattr('lib.providers.freshservice.api.page_all', _page_all)
        monkeypatch.setattr('lib.providers.freshservice.api.session', lambda k: _Sesion())
        with pytest.raises(fs_api.FreshserviceError) as e:
            fs_client.assets('casa.freshservice.com', 'k', ['7001'])
        assert e.value.key == 'fs_err_auth'


class TestContarCuantosHayDeCadaClase:
    """Su catálogo de tipos **no trae ese número**, así que la única forma de saberlo es recorrer
    los activos — el mismo viaje que el paso de elegir clases existe para ahorrar. Por eso es una
    acción aparte y se pide a mano."""

    def _espia(self, monkeypatch, filas):
        visto = []

        def _page_all(sess, host, path, key, params=None, per_page=100):
            visto.append(dict(params or {}))
            return filas

        monkeypatch.setattr('lib.providers.freshservice.api.page_all', _page_all)
        monkeypatch.setattr('lib.providers.freshservice.api.session', lambda k: _Sesion())
        return visto

    def test_cuenta_por_clase(self, monkeypatch):
        self._espia(monkeypatch, [{'asset_type_id': 7001}, {'asset_type_id': 7001},
                                  {'asset_type_id': 7002}])
        assert fs_client.asset_counts('casa.freshservice.com', 'k') == {'7001': 2, '7002': 1}

    def test_y_no_pide_los_campos_de_la_plantilla(self, monkeypatch):
        """`include=type_fields` es lo que hace pesada la respuesta, y para contar no hace falta
        ni uno de esos campos: son las mismas páginas y muchísimos menos bytes."""
        visto = self._espia(monkeypatch, [])
        fs_client.asset_counts('casa.freshservice.com', 'k')
        assert 'include' not in visto[0]

    def test_un_activo_sin_clase_no_inventa_una(self, monkeypatch):
        """Se cuenta lo que se puede elegir. Una clase con la cadena vacía por nombre sería una
        casilla que no se puede marcar y que no dice nada."""
        self._espia(monkeypatch, [{'asset_type_id': None}, {'asset_type_id': 7001}])
        assert fs_client.asset_counts('casa.freshservice.com', 'k') == {'7001': 1}


class _Sesion:
    """Lo justo para que `with sess:` funcione. El cliente no llega a usarla: `page_all` está
    sustituido, que es donde de verdad se decide lo que se pregunta."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestUnaListaCortadaLoDice:
    """El tope de 500 páginas se alcanzaba en silencio: la lista volvía CORTA como si fuera la
    entera, y quien la usa para decir «esto ya no está allí» lo diría de todo lo que no llegó."""

    def _siempre_llena(self, monkeypatch, paginas):
        monkeypatch.setattr(api, 'DEEP_PAGE_LIMIT', paginas)
        llena = {'departments': [{'id': n} for n in range(100)]}
        return _Sess([_Resp(body=llena, headers={'link': '<x>;rel="next"'})
                      for _ in range(paginas)])

    def test_al_llegar_al_tope_con_mas_por_delante_se_marca(self, monkeypatch, caplog):
        sess = self._siempre_llena(monkeypatch, 3)
        with caplog.at_level('WARNING'):
            fuera = api.page_all(sess, 'h', 'departments', 'departments')
        assert len(fuera) == 300 and fuera.truncated is True
        assert any('page limit' in r.getMessage() for r in caplog.records)

    def test_una_lista_que_termina_antes_no(self):
        sess = _Sess([_Resp(body={'departments': [{'id': 1}]}, headers={})])
        fuera = api.page_all(sess, 'h', 'departments', 'departments')
        assert fuera.truncated is False and fuera == [{'id': 1}]
