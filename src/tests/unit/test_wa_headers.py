#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP security response headers (lib.security.headers) applied to responses.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_headers.py`` lives in ``tests/integration/test_wa_headers.py``."""



class TestFrameAncestors:
    def test_allowlist_opens_frame_ancestors_and_drops_xfo(self):
        from lib.security.headers import apply_security_headers

        class _H(dict):
            def setdefault(self, k, v):
                return dict.setdefault(self, k, v)

            def pop(self, k, d=None):
                return dict.pop(self, k, d)

        class _Resp:
            def __init__(self):
                self.headers = _H()
        r = apply_security_headers(_Resp(), frame_ancestors=['https://teams.microsoft.com'])
        csp = r.headers['Content-Security-Policy']
        assert "frame-ancestors 'self' https://teams.microsoft.com" in csp
        assert 'X-Frame-Options' not in r.headers          # can't express an allowlist → dropped

    def test_no_allowlist_keeps_framing_blocked(self):
        from lib.security.headers import apply_security_headers

        class _Resp:
            def __init__(self):
                self.headers = {}
        r = apply_security_headers(_Resp())
        assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
        assert r.headers['X-Frame-Options'] == 'DENY'

    def test_build_csp_with_origins(self):
        from lib.security.headers import build_csp
        csp = build_csp(['https://embed.example.com', 'https://*.example.org'])
        assert "frame-ancestors 'self' https://embed.example.com https://*.example.org" in csp


class TestCsrfModule:
    def test_issue_and_validate(self):
        from lib.security import csrf

        sess = {}
        tok = csrf.issue_token(sess)
        assert tok and sess[csrf.SESSION_KEY] == tok
        assert csrf.issue_token(sess) == tok      # stable within a session

        class _Req:
            def __init__(self, headers=None, form=None):
                self.headers = headers or {}
                self.form = form or {}
        assert csrf.is_valid(_Req(headers={csrf.HEADER_NAME: tok}), sess)
        assert csrf.is_valid(_Req(form={csrf.FORM_FIELD: tok}), sess)
        assert not csrf.is_valid(_Req(headers={csrf.HEADER_NAME: 'wrong'}), sess)
        assert not csrf.is_valid(_Req(), sess)                 # no token sent
        assert not csrf.is_valid(_Req(headers={csrf.HEADER_NAME: 'x'}), {})  # no session token

    def test_needs_check(self):
        from lib.security import csrf

        exempt = ('/scim/', '/auth/saml2/acs')
        assert csrf.needs_check('POST', '/api/v1/config', exempt)
        assert not csrf.needs_check('GET', '/api/v1/config', exempt)
        assert not csrf.needs_check('POST', '/scim/v2/Users', exempt)
        assert not csrf.needs_check('DELETE', '/auth/saml2/acs', exempt)


class TestElMapaAbreImgSrcYNadaMas:
    """Un mapa de teselas son miles de imágenes de un tercero, y no hay forma de tener eso con
    `img-src 'self'`. Lo que sí se elige es cuánto se abre y cuándo, y las tres cosas que se
    comprueban aquí son las tres que, si se rompen, no dan ningún error:

    * que **sin mapa la política queda igual** — una instalación sin salida no tiene por qué
      cargar con un agujero que nadie usa;
    * que se abre **solo `img-src`** y jamás `script-src`: cargar imágenes de un tercero le dice
      dónde están tus sedes; ejecutar su script le da la página entera;
    * que se abre **solo el origen configurado**, no un comodín.
    """

    def _csp(self, **kw):
        from lib.security.headers import build_csp
        return build_csp(**kw)

    def test_sin_teselas_la_politica_no_cambia(self):
        from lib.security.headers import _CSP
        assert self._csp() == _CSP
        assert self._csp(img_origins=[]) == _CSP
        assert self._csp(img_origins=None) == _CSP
        assert "img-src 'self' data:;" in _CSP

    def test_con_teselas_solo_se_abre_img_src(self):
        csp = self._csp(img_origins=['https://tile.openstreetmap.org'])
        assert "img-src 'self' data: https://tile.openstreetmap.org;" in csp
        assert "script-src 'self' 'unsafe-inline';" in csp
        assert 'tile.openstreetmap.org' not in csp.split('img-src')[0]
        assert csp.count('tile.openstreetmap.org') == 1

    def test_y_el_resto_de_la_politica_sigue_entera(self):
        csp = self._csp(img_origins=['https://tiles.example.net'])
        for directiva in ("default-src 'self'", "connect-src 'self'", "object-src 'none'",
                          "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'"):
            assert directiva in csp

    def test_las_dos_aperturas_conviven(self):
        """Un panel embebido en Teams Y con mapa: son dos decisiones distintas y ninguna puede
        deshacer la otra."""
        csp = self._csp(frame_ancestors=['https://teams.microsoft.com'],
                        img_origins=['https://tile.openstreetmap.org'])
        assert "frame-ancestors 'self' https://teams.microsoft.com" in csp
        assert 'https://tile.openstreetmap.org' in csp.split('img-src')[1].split(';')[0]


class TestElOrigenSaleDeLaPlantilla:
    """Escrito en el código sería un agujero abierto el día que nadie usa el mapa."""

    def _origins(self, tpl):
        from lib.web_admin.mixins.embed import _EmbedMixin

        class _Wa(_EmbedMixin):
            _DCIM_MAP_TILES = tpl
        return _Wa()._image_origins()

    def test_de_una_plantilla_sale_su_origen(self):
        assert self._origins('https://tile.openstreetmap.org/{z}/{x}/{y}.png') == [
            'https://tile.openstreetmap.org']

    def test_es_el_origen_y_no_la_url(self):
        """Una tesela es una ruta de un millón, y la directiva tiene que cubrirlas todas."""
        got = self._origins('https://tiles.example.net/hot/{z}/{x}/{y}@2x.png')
        assert got == ['https://tiles.example.net']

    def test_con_puerto_el_puerto_cuenta(self):
        assert self._origins('http://192.0.2.10:8080/{z}/{x}/{y}.png') == [
            'http://192.0.2.10:8080']

    def test_sin_mapa_no_hay_origen(self):
        assert self._origins('') == []
        assert self._origins('   ') == []

    def test_una_plantilla_que_no_es_una_url_no_abre_nada(self):
        """Lo que no se entiende no se deja pasar: la respuesta a un ajuste mal escrito es un
        mapa que no carga, no una política abierta a algo que nadie sabe qué es."""
        for basura in ('javascript:alert(1)', 'file:///etc/passwd', 'tile.openstreetmap.org',
                       '{z}/{x}/{y}.png', 'ftp://x/{z}'):
            assert self._origins(basura) == [], basura
