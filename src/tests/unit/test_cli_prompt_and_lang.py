#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two CLI defects found by the 2026-10-12 audit (E13).

- `-l es` (or `SS_LANG=es`) was assigned to the context as it came; `es` is not a language
  code, so every message fell back to English. It is matched now the way main.py matches
  it for the banners: exact code, two-letter prefix, or a locale string.
- `user add` / `user passwd` with no `--password` and no terminal (cron, a pipe) let
  getpass's EOFError out as a traceback. They now fail with the hint instead.
"""

from __future__ import annotations

import getpass
from types import SimpleNamespace

import pytest

from lib.cli import commands


class TestLangIsMatched:

    @pytest.mark.parametrize('raw,code', [
        ('es', 'es_ES'), ('ES', 'es_ES'), ('es_ES', 'es_ES'), ('es-ES', 'es_ES'),
        ('es_ES.UTF-8', 'es_ES'), ('en', 'en_EN'), ('xx', None), ('', None), (None, None),
    ])
    def test_match(self, raw, code):
        assert commands._match_lang(raw) == code

    @pytest.mark.parametrize('raw,expect', [('es', 'es_ES'), ('xx', None)])
    def test_run_applies_the_matched_code(self, tmp_path, monkeypatch, raw, expect):
        seen = {}

        def _handler(ctx, _args):
            seen['lang'] = ctx.lang
            return 0

        monkeypatch.setitem(commands._HANDLERS, ('status', None), _handler)
        d = str(tmp_path)
        base = commands.run(SimpleNamespace(cmd='status', sub=None, lang=None), d, d)
        panel = seen['lang']
        assert base == 0
        assert commands.run(SimpleNamespace(cmd='status', sub=None, lang=raw), d, d) == 0
        # An unknown code keeps the panel's language instead of overwriting it.
        assert seen['lang'] == (expect or panel)


class TestNoTerminalNoTraceback:

    @pytest.fixture(autouse=True)
    def _no_tty(self, monkeypatch):
        def _eof(_prompt=''):
            raise EOFError
        monkeypatch.setattr(getpass, 'getpass', _eof)

    def test_user_add(self, tmp_path, capsys):
        d = str(tmp_path)
        rc = commands.run(SimpleNamespace(
            cmd='user', sub='add', username='bob', password=None, role='none', display='',
            email='', group=None, disabled=False, lang=None), d, d)
        assert rc == 1
        assert '--password' in capsys.readouterr().err

    def test_user_passwd(self, tmp_path, capsys):
        d = str(tmp_path)
        assert commands.run(SimpleNamespace(
            cmd='user', sub='add', username='bob', password='Abcd1234', role='none',
            display='', email='', group=None, disabled=False, lang=None), d, d) == 0
        rc = commands.run(SimpleNamespace(cmd='user', sub='passwd', username='bob',
                                          password=None, lang=None), d, d)
        assert rc == 1
        assert '--password' in capsys.readouterr().err
