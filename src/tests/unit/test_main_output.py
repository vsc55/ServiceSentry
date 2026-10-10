#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py survives an output that cannot carry every character.

On Windows with the output redirected (a service manager, a pipe, a log file) the encoding is the
ANSI code page, and the default-credentials banner's «⚠» raised UnicodeEncodeError: the panel
died at start-up. Reported from a verification run that redirected the output.
"""

import importlib.util
import io
import os
import sys

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


def _main():
    spec = importlib.util.spec_from_file_location('_ss_main_for_test', os.path.join(SRC, 'main.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_character_the_encoding_lacks_is_replaced_not_fatal(monkeypatch):
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding='cp1252')
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', io.TextIOWrapper(io.BytesIO(), encoding='cp1252'))
    _main()._tolerant_output()
    print('  \u26a0  admin/admin')
    out.flush()
    assert raw.getvalue() == '  ?  admin/admin\n'.encode('cp1252').replace(b'\n', os.linesep.encode())


def test_a_stream_that_cannot_be_reconfigured_is_left_alone(monkeypatch):
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    _main()._tolerant_output()                       # no AttributeError
