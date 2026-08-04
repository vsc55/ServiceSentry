#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The secret key has to be pinnable by environment, not only by file.

That key signs sessions AND derives the Fernet key every stored secret is encrypted with,
so **every process sharing a database must hold the same one**. It lived in exactly one
place — ``.flask_secret`` inside ``config_dir`` — and had no ``SS_*`` to set it with, which
is the one setting that most needs one:

* on a single host the compose files get away with it, because all four services mount the
  same ``config`` volume. Take that volume away (``down -v``) and every stored secret in the
  database becomes unreadable, with nothing reporting an error;
* the documented Kubernetes deployment mounts **no** volume there, so each pod minted its
  own key. A credential saved by the web pod could not be decrypted by the worker, and a
  restart made the data unrecoverable.

Pinned here: the environment wins, the file remains the fallback, a malformed value is
refused rather than silently replaced, and — the property that matters — two processes
holding different files but the same env key can read each other's secrets.
"""

import os
import tempfile

import pytest

from lib.config import secret_key_from_env, secret_key_path, SECRET_KEY_ENV
from lib.security import secret_manager


@pytest.fixture()
def no_env(monkeypatch):
    monkeypatch.delenv(SECRET_KEY_ENV, raising=False)


def _hex_key(byte: int = 0xAB) -> str:
    return f'{byte:02x}' * 32


def _dir_with_key(hex_key: str) -> str:
    d = tempfile.mkdtemp()
    with open(secret_key_path(d), 'w', encoding='utf-8') as fh:
        fh.write(hex_key)
    return d


class TestReadingTheEnvironment:

    def test_unset_is_empty_not_an_error(self, no_env):
        assert secret_key_from_env() == ''

    def test_a_valid_key_comes_back(self, monkeypatch):
        monkeypatch.setenv(SECRET_KEY_ENV, _hex_key())
        assert secret_key_from_env() == _hex_key()

    def test_surrounding_whitespace_is_tolerated(self, monkeypatch):
        """Copy-pasting from a Secret manifest brings a newline more often than not."""
        monkeypatch.setenv(SECRET_KEY_ENV, f'  {_hex_key()}\n')
        assert secret_key_from_env() == _hex_key()

    @pytest.mark.parametrize('bad', ['short', 'zz' * 32, _hex_key()[:-1], _hex_key() + 'ab'])
    def test_a_malformed_key_is_refused(self, monkeypatch, bad):
        """Refused, not ignored: falling back would encrypt with a key nobody chose."""
        monkeypatch.setenv(SECRET_KEY_ENV, bad)
        with pytest.raises(ValueError) as e:
            secret_key_from_env()
        assert '64 hex' in str(e.value)

    def test_the_message_says_how_to_make_one(self, monkeypatch):
        monkeypatch.setenv(SECRET_KEY_ENV, 'nope')
        with pytest.raises(ValueError) as e:
            secret_key_from_env()
        assert 'token_hex(32)' in str(e.value)


class TestTheFernetKeyFollowsIt:

    def test_the_environment_wins_over_the_file(self, monkeypatch):
        d = _dir_with_key(_hex_key(0x11))
        monkeypatch.setenv(SECRET_KEY_ENV, _hex_key(0x22))
        env_f = secret_manager.fernet_from_secret_file(secret_key_path(d))
        monkeypatch.delenv(SECRET_KEY_ENV)
        file_f = secret_manager.fernet_from_secret_file(secret_key_path(d))
        with pytest.raises(Exception):
            file_f.decrypt(env_f.encrypt(b'x'))     # different keys → the env one was used

    def test_the_file_still_works_when_the_env_is_unset(self, no_env):
        """An existing install must not need the variable to keep reading its own data."""
        d = _dir_with_key(_hex_key(0x33))
        f = secret_manager.fernet_from_secret_file(secret_key_path(d))
        assert f is not None
        assert f.decrypt(f.encrypt(b'kept')) == b'kept'

    def test_two_instances_sharing_the_env_key_read_each_other(self, monkeypatch):
        """The bug, stated as a property: this is what a pod-per-role deployment needs.

        Both sides even have their own (different) key FILE, standing in for the ephemeral
        filesystem each pod gets — the point is that the environment overrides them.
        """
        monkeypatch.setenv(SECRET_KEY_ENV, _hex_key(0x44))
        web = secret_manager.fernet_from_secret_file(secret_key_path(_dir_with_key(_hex_key(0x55))))
        worker = secret_manager.fernet_from_secret_file(secret_key_path(_dir_with_key(_hex_key(0x66))))
        assert worker.decrypt(web.encrypt(b'ssh-password')) == b'ssh-password'

    def test_without_it_they_cannot(self, no_env):
        """The control: without the variable this is exactly what used to happen."""
        web = secret_manager.fernet_from_secret_file(secret_key_path(_dir_with_key(_hex_key(0x77))))
        worker = secret_manager.fernet_from_secret_file(secret_key_path(_dir_with_key(_hex_key(0x88))))
        with pytest.raises(Exception):
            worker.decrypt(web.encrypt(b'ssh-password'))


class TestTheSessionKey:
    """The web side of the same key — it must agree with the Fernet one, or sessions and
    secrets end up signed and encrypted by different keys."""

    def _mixin(self, config_dir):
        from lib.core.sessions.mixin import _SessionsMixin      # noqa: PLC0415

        class _Fake(_SessionsMixin):
            _SECRET_KEY_FILE = '.flask_secret'

            def __init__(self, d):
                self._config_dir = d

        return _Fake(config_dir)

    def test_the_environment_key_is_used(self, monkeypatch):
        monkeypatch.setenv(SECRET_KEY_ENV, _hex_key(0x99))
        assert self._mixin(_dir_with_key(_hex_key(0x11)))._load_or_create_secret_key() == _hex_key(0x99)

    def test_it_is_not_written_to_disk(self, monkeypatch):
        """Persisting a copy would leave a second source of truth to drift from it."""
        monkeypatch.setenv(SECRET_KEY_ENV, _hex_key(0xAA))
        d = tempfile.mkdtemp()
        self._mixin(d)._load_or_create_secret_key()
        assert not os.path.exists(secret_key_path(d)), \
            'the env-supplied key was written to disk — now there are two of them'

    def test_the_file_is_still_used_when_unset(self, no_env):
        d = _dir_with_key(_hex_key(0xBB))
        assert self._mixin(d)._load_or_create_secret_key() == _hex_key(0xBB)
