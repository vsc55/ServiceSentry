#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for server-side session registry and management.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_sessions.py`` lives in ``tests/integration/test_wa_sessions.py``."""


import pytest

# Estos tests importan Flask dentro de los casos (registro de sesiones del panel), asi que
# siguen dependiendo de el aunque vivan en unit/.
try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


# ──────────────────────────── Session registry ─────────────────────


class TestAnUnwritableSecretKeyIsNotSilent:
    """The secret-key file signs Flask sessions AND derives the Fernet key for every stored
    secret. If it cannot be written the process runs on an in-memory key: on the next
    restart a DIFFERENT one is generated, every session dies and — far worse — everything
    encrypted in the meantime becomes undecryptable.

    Not raised (refusing to start is worse than running with a short-lived key), but never
    silent: this is one of the ways an installation ends up with the "wrong key" that
    secret_manager then reports on every read."""

    class _Fake:
        _SECRET_KEY_FILE = 'secret.key'

        def __init__(self, cfg_dir):
            self._config_dir = cfg_dir

    def _mixin(self, tmp_path):
        from lib.core.sessions.mixin import _SessionsMixin

        class _M(_SessionsMixin, self._Fake):
            pass

        return _M(str(tmp_path))

    def test_a_write_failure_is_logged_with_the_path(self, tmp_path, caplog, monkeypatch):
        m = self._mixin(tmp_path)
        monkeypatch.setattr('os.open', lambda *a, **k: (_ for _ in ()).throw(OSError('denied')))
        with caplog.at_level('ERROR', logger='lib.core.sessions.mixin'):
            m._save_secret_key('abc123')
        assert caplog.records, 'losing the secret key must not be silent'
        msg = caplog.records[0].getMessage()
        assert 'secret.key' in msg, 'the operator needs to know which path failed'

    def test_the_key_itself_is_never_logged(self, tmp_path, caplog, monkeypatch):
        m = self._mixin(tmp_path)
        monkeypatch.setattr('os.open', lambda *a, **k: (_ for _ in ()).throw(OSError('denied')))
        with caplog.at_level('ERROR', logger='lib.core.sessions.mixin'):
            m._save_secret_key('SUPERSECRET')
        assert 'SUPERSECRET' not in caplog.text

    def test_it_does_not_raise(self, tmp_path, monkeypatch):
        """Refusing to start over this would be a worse outcome than a short-lived key."""
        m = self._mixin(tmp_path)
        monkeypatch.setattr('os.open', lambda *a, **k: (_ for _ in ()).throw(OSError('denied')))
        m._save_secret_key('abc123')          # must not raise

    def test_a_successful_write_stays_quiet(self, tmp_path, caplog):
        m = self._mixin(tmp_path)
        with caplog.at_level('ERROR', logger='lib.core.sessions.mixin'):
            m._save_secret_key('abc123')
        assert not caplog.records
        assert (tmp_path / 'secret.key').read_text(encoding='utf-8') == 'abc123'
