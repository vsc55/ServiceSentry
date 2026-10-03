#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El guion que se sirve, ¿es JavaScript?

Parece una pregunta tonta y costó una sección en blanco. Un acento grave dentro de un comentario
HTML cierra la plantilla de cadena que lo rodea; a partir de ahí el navegador lee código donde
hay marcado, y lo que llega es un `SyntaxError` que se lleva por delante **el guion entero** —
que en este panel es uno solo para todas las pantallas.

**Nada más de la suite lo ejecuta.** Los guardianes leen el fuente: que toda función llamada esté
escrita, que ningún `async` quede colgando, que lo tecleado salga escapado. Ninguno de ellos
compila, así que los cinco mil tests siguieron en verde con el panel sin arrancar, y el único que
lo vio fue un navegador.

Esto lo compila: pide la página, saca el `<script>` grande y se lo da a `node --check`. No
ejecuta nada —`--check` sólo analiza— así que no hace falta un DOM ni un navegador.

**Se traducen antes dos formas modernas** (`?.` y `??`) porque el `node` de una máquina puede ser
viejo y no hablarlas, y sustituirlas por su equivalente clásico no cambia la ESTRUCTURA, que es
lo único que se está comprobando: dónde empieza y acaba cada cadena, cada bloque y cada
paréntesis. Si algún día una sintaxis nueva rompe esto, la lista de abajo es donde se amplía.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from tests.conftest import _login                                   # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='sin node: no hay con qué analizar el guion')

#: Lo moderno, en su equivalente clásico. Mismo esqueleto, sintaxis que entiende cualquier node.
_VIEJUNO = (('?.(', '('), ('?.[', '['), ('?.', '.'),
            ('??=', '='), ('||=', '='), ('&&=', '='), ('??', '||'))


def _bundle(client, url: str) -> str:
    """El `<script>` más grande de una página: el paquete de todas las secciones."""
    html = client.get(url).get_data(as_text=True)
    trozos = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    assert trozos, f'{url} no sirvió ningún guion'
    return max(trozos, key=len)


def _check(js: str) -> str:
    """El error de sintaxis, o `''`."""
    for viejo, nuevo in _VIEJUNO:
        js = js.replace(viejo, nuevo)
    ruta = os.path.join(tempfile.gettempdir(), 'ss_bundle_check.js')
    io.open(ruta, 'w', encoding='utf-8').write(js)
    r = subprocess.run(['node', '--check', ruta], capture_output=True, text=True)
    return '' if r.returncode == 0 else r.stderr[:1500]


class TestElGuionServidoSeAnaliza:

    def test_el_paquete_del_panel_es_javascript(self, admin, client):
        _login(client)
        error = _check(_bundle(client, '/dcim'))
        assert not error, f'el guion servido no compila:\n{error}'

    def test_y_el_de_la_pantalla_de_entrada_tambien(self, client):
        """Sin sesión: la de acceso lleva su propio guion y también puede romperse."""
        error = _check(_bundle(client, '/login'))
        assert not error, f'el guion de la pantalla de acceso no compila:\n{error}'
