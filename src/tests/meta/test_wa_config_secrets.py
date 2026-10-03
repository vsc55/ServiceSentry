#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un secreto de la configuración se guarda cifrado **y se sigue pudiendo escribir**.

Son dos listas, y hay que estar en las dos:

* `secret_manager.ENCRYPT_KEYS` decide qué se cifra en reposo y qué sale **enmascarado** — el
  servidor manda `null` en lugar del valor, que es lo correcto: una clave de API no vuelve a
  salir de aquí;
* `_AuditMixin._SENSITIVE_FIELDS` es lo que la PANTALLA sabe que es un secreto, y lo único que
  tiene el dibujante de campos para reconocer ese `null`.

Estar en la primera y no en la segunda no da ningún error: el valor llega como `null`, no encaja
en ninguna rama del dibujante —ni texto, ni número, ni interruptor— y la última línea de esa
función devuelve una cadena vacía. **La caja desaparece de la pantalla.** Quien acaba de guardar
su clave abre la configuración y ya no tiene dónde volver a escribirla.

Salió con la clave de Freshservice, reportado desde la pantalla; y al mirarlo apareció que el
token de GitHub de la biblioteca MIB llevaba igual desde que se cifró.

Y detrás venía el segundo, del mismo `null`: **«puesto» y «sin poner» se escriben igual**. La
regla que decide si una opción sigue en su valor de fábrica trata el vacío como «sin poner», y
sin poner ES el de fábrica — correcto para una dirección de escucha, y al revés para un secreto,
donde `null` significa «puesto, y el servidor no lo manda». Con la regla a secas, una clave
guardada contaba como intacta: no salía marcada, no entraba en el recuento de la tarjeta y
desaparecía al filtrar por «sólo lo modificado».

Sólo se exige de los campos que dibuja el renderizador GENÉRICO —los que declaran `card`—. Una
tarjeta escrita a mano (el canal de Teams, por ejemplo) dibuja sus secretos ella misma y sabe lo
que hace con ellos.
"""

from __future__ import annotations


def _campos_de_tarjeta():
    """Los campos de configuración que dibuja el renderizador genérico."""
    from lib.config.spec import CONFIG_FIELDS                        # noqa: PLC0415
    return [c for c in CONFIG_FIELDS if c.card]


class TestLoQueSeCifraSeSiguePudiendoEscribir:

    def test_todo_secreto_de_una_tarjeta_lo_sabe_la_pantalla(self):
        from lib.core.audit.mixin import _AuditMixin                 # noqa: PLC0415
        from lib.security.secret_manager import ENCRYPT_KEYS         # noqa: PLC0415
        malos = []
        for c in _campos_de_tarjeta():
            nombre = c.path.split('|')[-1]
            if nombre in ENCRYPT_KEYS and nombre not in _AuditMixin._SENSITIVE_FIELDS:
                malos.append(c.path)
        assert not malos, ('se cifran y la pantalla no lo sabe, así que su caja desaparece en '
                           'cuanto se guardan: ' + ', '.join(malos))

    def test_y_los_dos_que_lo_estropearon_siguen_en_su_sitio(self):
        """Uno lo reportó una persona y el otro apareció al mirarlo. Nombrados aquí porque un
        recuento no dice cuál se ha caído."""
        from lib.core.audit.mixin import _AuditMixin                 # noqa: PLC0415
        from lib.security.secret_manager import ENCRYPT_KEYS         # noqa: PLC0415
        for nombre in ('api_key', 'github_token'):
            assert nombre in ENCRYPT_KEYS, nombre
            assert nombre in _AuditMixin._SENSITIVE_FIELDS, nombre

    def test_y_la_rama_que_los_dibuja_sigue_existiendo(self):
        """La otra mitad del arreglo está en el dibujante: un `null` de un campo sensible se
        pinta como una caja de secreto vacía con «definido» de marcador. Sin esa rama, estar en
        las dos listas no sirve de nada."""
        import io                                                    # noqa: PLC0415
        import os                                                    # noqa: PLC0415
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        js = io.open(os.path.join(src, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                  '_field_render.html'), encoding='utf-8-sig').read()
        assert "value === null && (SENSITIVE.has(key)" in js
        assert "kind: 'secret'" in js


class TestUnSecretoPuestoCuentaComoPuesto:
    """`null` quiere decir dos cosas opuestas según el campo: en uno normal es «sin poner» —y
    sin poner es el valor de fábrica—, y en uno secreto es «puesto, y no te lo mando».

    El orden de las dos reglas es el arreglo entero: la del secreto tiene que decidir ANTES que
    la del vacío, porque la segunda se traga cualquier `null`."""

    def _js(self):
        import io                                                    # noqa: PLC0415
        import os                                                    # noqa: PLC0415
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        return io.open(os.path.join(src, 'lib', 'web_admin', 'templates', 'partials', 'cfg',
                                    '_views.html'), encoding='utf-8-sig').read()

    def _cuerpo(self):
        return self._js().split('function _cfgIsDefault(')[1].split(chr(10) + '}')[0]

    def test_un_null_secreto_no_se_da_por_de_fabrica(self):
        cuerpo = self._cuerpo()
        assert 'SENSITIVE.has(' in cuerpo, 'vuelve a contar una clave guardada como intacta'
        assert 'return false' in cuerpo

    def test_y_lo_decide_antes_que_la_regla_del_vacio(self):
        """Si la del vacío va primero, la del secreto no llega a ejecutarse nunca — y todo
        parecería estar bien escrito."""
        cuerpo = self._cuerpo()
        assert cuerpo.index('SENSITIVE.has(') < cuerpo.index("cur === ''")

    def test_y_el_vacio_sigue_siendo_sin_poner(self):
        """Que es lo que dice el marcador gris de una caja vacía: una dirección de escucha en
        blanco no es una opción modificada."""
        assert "cur === ''" in self._cuerpo()
