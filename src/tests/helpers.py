#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers compartidos por las guardas de estructura (los tests que leen plantillas y JS).

Antes de existir este módulo, cada fichero de guardas llevaba su propia copia de estas tres
funciones: 21 copias byte a byte idénticas de ``_read``, 18 de ``_fn`` y 6 de
``_strip_comments``.  Arreglar una era arreglar una de veinte, en silencio.

No es ``conftest.py`` a propósito: eso es para *fixtures*, y estas son funciones normales que
se importan.  Tampoco se llama ``test_*.py``, así que pytest no lo recoge como suite.
"""

import io
import re


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _fn(src: str, name: str) -> str:
    """El cuerpo de una función JS de primer nivel dentro de ``src``."""
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _strip_comments(js: str) -> str:
    """Solo código.  Una guarda que lee también la prosa tropieza con el comentario que
    explica la regla que está comprobando — y todos estos ficheros llevan uno."""
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)
