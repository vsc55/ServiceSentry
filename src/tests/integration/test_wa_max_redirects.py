#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The redirect ceiling of guarded outbound fetches is a setting: `web_admin|max_redirects`.

Map tiles, MIB imports and the web check follow redirects hop by hop through the SSRF guard. The
ceiling was a constant (5 in one place, urllib's unsaid 10 in another); it is now one setting,
10 by default, admin-only, overridable with `SS_MAX_REDIRECTS`, applied in the web process when
the config loads or is saved and in the worker every cycle.
"""

from __future__ import annotations

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


@pytest.fixture(autouse=True)
def _reset():
    from lib.security import net_guard
    yield
    net_guard.set_max_redirects(net_guard.MAX_REDIRECTS)


class _Resp:
    def __init__(self, status, location=None):
        self.status_code = status
        self.headers = {'Location': location} if location else {}


def _chain(n):
    """A getter that answers *n* redirects (192.0.2.x, allowed by the guard) then a 200."""
    seen = []

    def get(url, **_kw):
        seen.append(url)
        return _Resp(302, f'http://192.0.2.{len(seen)}/x') if len(seen) <= n else _Resp(200)
    return get, seen


def test_the_default_is_ten():
    from lib.config.spec import cfg_default
    from lib.security import net_guard
    assert cfg_default('web_admin|max_redirects') == 10 == net_guard.max_redirects()


def test_guarded_get_follows_exactly_the_ceiling():
    from lib.security import net_guard
    net_guard.set_max_redirects(2)
    get, _ = _chain(2)
    assert net_guard.guarded_get('http://192.0.2.100/x', getter=get).status_code == 200
    get, _ = _chain(3)
    with pytest.raises(net_guard.RedirectBlocked):
        net_guard.guarded_get('http://192.0.2.100/x', getter=get)


def test_a_bad_value_falls_back_to_the_default():
    from lib.security import net_guard
    for bad in (None, 'x', -1, 99):
        net_guard.set_max_redirects(bad)
        assert net_guard.max_redirects() == net_guard.MAX_REDIRECTS


def test_the_environment_wins_in_the_worker(monkeypatch):
    from lib.security import net_guard
    assert net_guard.max_redirects_from({'max_redirects': 4}) == 4
    monkeypatch.setenv('SS_MAX_REDIRECTS', '7')
    assert net_guard.max_redirects_from({'max_redirects': 4}) == 7
    monkeypatch.setenv('SS_MAX_REDIRECTS', 'nope')
    assert net_guard.max_redirects_from({'max_redirects': 4}) == 4


def test_saving_the_setting_applies_it_and_only_an_admin_may(admin, client):
    from lib.security import net_guard
    c = _login_as(admin, 'cfgonly', perms=['config_view', 'config_edit'])
    assert c.put('/api/v1/config', json={'web_admin': {'max_redirects': 2}}).status_code == 403
    _login(client)
    r = client.put('/api/v1/config', json={'web_admin': {'max_redirects': 3}})
    assert r.status_code == 200, r.get_json()
    assert net_guard.max_redirects() == 3


def test_the_worker_applies_it_every_cycle(monkeypatch, tmp_path):
    """The web check runs in the worker, which never builds the web admin's attributes."""
    from types import SimpleNamespace
    from lib.config import manager as cfg_manager
    from lib.security import net_guard
    from lib.services.monitoring.monitor import Monitor

    class _Cfg:
        data: dict = {}

        def get_conf(self, path, default=None):
            node = self.data
            for k in path:
                if not isinstance(node, dict) or k not in node:
                    return default
                node = node[k]
            return node

    monkeypatch.setattr(cfg_manager.ConfigManager, 'read',
                        lambda self: {'web_admin': {'max_redirects': 4}})
    monkeypatch.setattr(cfg_manager.ConfigManager, '__init__', lambda self, *a, **k: None)
    monkeypatch.setattr('lib.core.config.store.ConfigStore.__init__', lambda self, db: None)
    fake = SimpleNamespace(_db=object(), dir_config=str(tmp_path), config=_Cfg(), _fernet=None)
    Monitor._apply_db_config(fake)
    assert net_guard.max_redirects() == 4
