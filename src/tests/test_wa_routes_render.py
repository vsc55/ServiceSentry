#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Every page the panel serves has to render.

Found the hard way: an experimental page returned **500** on every engine because its
template linked to ``url_for('overview')`` and that endpoint had been renamed. A renamed
endpoint does not produce a dead link — Jinja raises ``BuildError`` and the whole page becomes
a crash. Nothing pointed at it: no test opened the page, and the route index listed it as
existing, which it did. (That page has since been deleted; the blind spot it revealed is what
this file closes.)

So the sweep is taken from Flask's own ``url_map`` rather than a list somebody maintains: a
page added tomorrow is covered without anyone remembering to add it here, which is the only
way this kind of guard stays true.
"""

import pytest

try:
    from lib.web_admin import WebAdmin           # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

# Routes deliberately skipped, each for a reason that is not "it fails":
#   /logout                      ends the session the rest of the sweep needs
#   /api/v1/config/db/<op>       maintenance: would rewrite the test database mid-run
SKIP = {'/logout'}
SKIP_PREFIXES = ('/static', '/api/v1/config/db/')


def _sweepable(app):
    """Every GET route that takes no path parameters — the ones openable as-is."""
    return sorted({
        r.rule for r in app.url_map.iter_rules()
        if 'GET' in (r.methods or ()) and '<' not in r.rule
        and r.rule not in SKIP and not r.rule.startswith(SKIP_PREFIXES)
    })


class TestTheSweepItself:
    """If this fails the guard is broken, not the pages."""

    def test_it_finds_the_pages(self, admin):
        rules = _sweepable(admin.app)
        assert len(rules) > 30, f'only {len(rules)} routes — the sweep is looking wrong'
        # The real pages, not just the API: a template that cannot render is the failure mode.
        assert {'/overview', '/status', '/account'} <= set(rules), \
            'the HTML pages are not being swept — only the API would be covered'


class TestEveryPageRenders:

    def test_no_route_answers_5xx(self, admin, client):
        """A 4xx is an answer (permission, missing resource, bad query). A 5xx is the server
        failing to produce one, and for a GET with no parameters there is no input to blame."""
        _login(client)
        broken = []
        for rule in _sweepable(admin.app):
            resp = client.get(rule)
            if resp.status_code >= 500:
                broken.append(f'{rule} -> {resp.status_code}')
        assert not broken, 'routes returning 5xx: ' + '; '.join(broken)

    def test_no_route_raises(self, admin, client):
        """Separate from the status check because a template that raises can be turned into a
        clean 500 by the error handler — and then it reads as "handled" while the page is
        still gone. This asserts nothing propagated at all."""
        _login(client)
        admin.app.config['PROPAGATE_EXCEPTIONS'] = False
        raised = []
        for rule in _sweepable(admin.app):
            try:
                client.get(rule)
            except Exception as exc:            # pylint: disable=broad-except
                raised.append(f'{rule}: {type(exc).__name__}: {exc}')
        assert not raised, 'routes raising: ' + '; '.join(raised)

    def test_the_pages_render_logged_out_too(self, admin, client):
        """Logged out, a protected page must REDIRECT, never crash: the guard runs before the
        view, so a broken template behind it would still be invisible here — but a guard that
        forgets a page shows up as a 500 instead of a 302."""
        bad = []
        for rule in _sweepable(admin.app):
            resp = client.get(rule)
            if resp.status_code >= 500:
                bad.append(f'{rule} -> {resp.status_code}')
        assert not bad, 'routes returning 5xx while logged out: ' + '; '.join(bad)
