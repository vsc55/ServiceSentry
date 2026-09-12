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

from lib.providers.freshservice import api


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
