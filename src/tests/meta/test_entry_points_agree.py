#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Que `main.py` y lo que llama sigan hablando el mismo idioma.

**El fallo que esto existe para que no vuelva.** Un renombrado amplio cambió el parámetro `host`
de `_ServerMixin.run()` —que es la dirección donde se ESCUCHA, no un dispositivo— y `main.py`
seguía llamándolo por su nombre: `run(host=...)` contra `def run(device=...)`. El panel no
arrancaba, y **ninguna prueba lo veía**: `run()` enlaza puertos, así que no se ejecuta en la
suite; todo lo demás pasaba en verde mientras `main.py --web` moría en el primer segundo.

Se comprueba comparando firmas con llamadas, que es lo que un test puede hacer sin abrir un
socket. Lo otro que hace falta —arrancarlo de verdad— es un e2e, y esto es lo que cubre el hueco
mientras tanto.
"""

from __future__ import annotations

import ast
import inspect
import io
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


def _llamadas_con_nombre(ruta):
    """``[(receptor, método, {nombres de los argumentos con nombre}), …]`` de un fichero."""
    with io.open(ruta, encoding='utf-8') as fh:
        arbol = ast.parse(fh.read(), filename=ruta)
    fuera = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
            continue
        recep = nodo.func.value
        fuera.append((getattr(recep, 'id', ''), nodo.func.attr,
                      {k.arg for k in nodo.keywords if k.arg}))
    return fuera


class TestMainCallsWhatIsActuallyThere:

    def test_the_web_entry_point_calls_run_with_the_names_it_declares(self):
        """`main.py` es el único llamante de `run()` en todo el repositorio, y no está en `lib/`:
        un renombrado dentro de la librería no lo arrastra."""
        from lib.web_admin.mixins.server import _ServerMixin      # noqa: PLC0415
        acepta = set(inspect.signature(_ServerMixin.run).parameters)
        usados = set()
        for recep, metodo, nombres in _llamadas_con_nombre(os.path.join(SRC, 'main.py')):
            if metodo == 'run' and recep in ('admin', 'wa', 'web'):
                usados |= nombres
        assert usados, 'main.py ya no llama a run() con argumentos con nombre'
        faltan = usados - acepta
        assert not faltan, (
            'main.py llama a run(%s) y la firma no los acepta: %s'
            % (', '.join(sorted(usados)), ', '.join(sorted(faltan))))

    def test_and_the_bind_address_is_still_called_host(self):
        """Porque es una dirección de escucha, no un dispositivo del registro. Es el mismo
        criterio que dejó `hostname`, `ssh_host` y `bind_host` donde estaban."""
        from lib.web_admin.mixins.server import _ServerMixin      # noqa: PLC0415
        assert 'host' in inspect.signature(_ServerMixin.run).parameters
