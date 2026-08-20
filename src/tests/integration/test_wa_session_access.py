#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a SESSION did, not merely that one exists.

The sessions screen answered who is signed in, from where and since when. What that sign-in
had DONE was not answerable anywhere: the audit log records the actions that have a name
('config_saved'), attributed to the ACCOUNT — so two sessions of the same person read as one —
and a request that was REFUSED left no trace at all. "Somebody's session tried to reach the
user list and was told no" is exactly the line an access review is looking for, and it existed
nowhere.

So: a ring per session, the twin of ``api_token_access``, filled by an ``after_request`` hook
and read by the Activity view of Access › Sessions.

**The rule is the design, and most of this file is about it.** Not every request is recorded —
the panel polls ITSELF (health every 6 s, the keepalive every 20 s, the access tab every 30 s),
so a ring that kept successful reads would be two hundred rows of heartbeat with the one
interesting line already evicted, and a database write on the response path of every poll of
every open tab. What is kept is the ACTS (POST/PUT/PATCH/DELETE) and the REFUSALS (>= 400).
"""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


def _sid(client):
    """The public id of the session this client is holding."""
    with client.session_transaction() as s:
        return s.get('session_id', '')


def _rows(admin, client):
    return admin._sessions_store.access_for(_sid(client))


def _as(admin, username, role='admin', password='pw-secret'):
    """A second signed-in client, for the permission checks."""
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash(password)}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    return c


class TestWhatIsRecorded:
    """The rule, from both sides: what lands in the ring and what must not."""

    def test_signing_in_is_the_first_thing_in_it(self, admin, client):
        """The POST that created the session is an act like any other, and it is the one row
        that makes the history readable: everything after it happened inside this sign-in."""
        _login(client)
        rows = _rows(admin, client)
        assert len(rows) == 1
        assert rows[0]['method'] == 'POST' and rows[0]['path'] == '/login'

    def test_a_successful_read_is_not_recorded(self, admin, client):
        """The one that would drown everything else. `/api/v1/me` is the keepalive: every open
        tab asks for it three times a minute, and it did nothing worth remembering."""
        _login(client)
        before = len(_rows(admin, client))
        assert client.get('/api/v1/me').status_code == 200
        assert len(_rows(admin, client)) == before

    def test_an_act_is_recorded_with_the_answer_it_got(self, admin, client):
        """Recorded AFTER the fact on purpose: a POST that was refused and a POST that
        succeeded are the same request until the status is attached to it."""
        _login(client)
        r = client.post('/api/v1/account/tokens',
                        json={'name': 'ci', 'permissions': ['users_view']})
        assert r.status_code == 200
        top = _rows(admin, client)[0]
        assert top['method'] == 'POST' and top['path'] == '/api/v1/account/tokens'
        assert top['status'] == 200

    def test_a_refused_read_is_recorded_although_it_is_a_read(self, admin):
        """The point of the whole thing. "This session asked for something it may not have" is
        a GET as often as not, and the rule that drops successful reads must not drop it."""
        c = _as(admin, 'nobody', role='none')
        assert c.get('/api/v1/sessions').status_code == 403
        rows = admin._sessions_store.access_for(_sid(c))
        assert any(r['path'] == '/api/v1/sessions' and r['status'] == 403 for r in rows)

    def test_a_404_keeps_the_url_it_asked_for(self, admin, client):
        """Every other row stores the route PATTERN, which is what keeps the column readable
        and keeps usernames out of it. A 404 has no pattern — and it is the one case where the
        URL is the entire point of the row."""
        _login(client)
        assert client.get('/api/v1/there-is-no-such-thing').status_code == 404
        assert _rows(admin, client)[0]['path'] == '/api/v1/there-is-no-such-thing'

    def test_the_route_pattern_is_stored_and_not_the_url(self, admin, client):
        """`/api/v1/sessions/<uid>/access` rather than the forty paths it resolves to: a ring
        full of one id per row answers "which endpoints" with a wall of near-identical
        strings, and the raw path is where a username would end up in a table shown to
        everybody who may read the sessions list."""
        c = _as(admin, 'nope', role='none')
        c.post('/api/v1/sessions/revoke/whatever-uid')
        rows = admin._sessions_store.access_for(_sid(c))
        assert rows[0]['path'] == '/api/v1/sessions/revoke/<uid>'

    def test_zero_is_no_ceiling_and_not_no_rows(self, admin):
        """The same `0` means "no limit" in `audit_max_entries` and `syslog|max_rows`, so it
        cannot mean "no rows" here: whoever zeroes every cap in the panel to keep everything
        would switch this off believing the opposite."""
        for i in range(30):
            admin._sessions_store.log_access('s-all', ts=f'2026-01-01T00:{i:02d}:00', ip='',
                                             method='POST', path='/x', status=200, keep=0)
        assert len(admin._sessions_store.access_for('s-all', limit=999)) == 30

    def test_the_switch_is_what_stops_it(self, admin, client):
        """Recording nothing is a decision of its own, and it is a switch."""
        admin._SESSION_LOG_ENABLED = False
        _login(client)
        client.post('/api/v1/account/tokens', json={'name': 'x', 'permissions': []})
        assert _rows(admin, client) == []

    def test_a_token_request_writes_nothing_here(self, admin, client):
        """A token is not a session. Its calls belong to the ring beside the token, and a row
        here would attribute them to a sign-in that never happened."""
        _login(client)
        raw = client.post('/api/v1/account/tokens',
                          json={'name': 'ci', 'permissions': ['users_view']}).get_json()['token']
        before = len(_rows(admin, client))
        bearer = admin.app.test_client()
        bearer.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {raw}'
        # Refused (credential management never accepts a token) — so the session rule WOULD
        # have recorded it, which is what makes this a test and not a tautology.
        assert bearer.post('/api/v1/account/tokens', json={'name': 'x'}).status_code == 403
        assert len(_rows(admin, client)) == before


class TestTheRing:
    """It is bounded, and it is bounded per session."""

    def _fill(self, admin, sid, n, keep=10, start=0):
        for i in range(n):
            admin._sessions_store.log_access(
                sid, ts=f'2026-08-20T10:{(start + i) // 60:02d}:{(start + i) % 60:02d}',
                ip='1.2.3.4', method='POST', path=f'/api/v1/x/{i}', status=200, keep=keep)

    def test_it_stops_growing(self, admin):
        """A table that grows with web traffic is not bookkeeping."""
        self._fill(admin, 's-one', 30, keep=10)
        assert len(admin._sessions_store.access_for('s-one', limit=999)) <= 10

    def test_one_busy_session_does_not_evict_a_quiet_one(self, admin):
        """Per session and not globally, for the reason the quiet one matters: a session that
        made three requests is where a single unexpected one is the whole signal."""
        self._fill(admin, 's-quiet', 3, keep=10)
        self._fill(admin, 's-busy', 40, keep=10, start=100)
        assert len(admin._sessions_store.access_for('s-quiet', limit=999)) == 3

    def test_the_feed_across_sessions_is_capped_too(self, admin):
        """The per-session rings bound the total; this bounds what one request carries."""
        self._fill(admin, 's-a', 12, keep=200)
        self._fill(admin, 's-b', 12, keep=200, start=200)
        assert len(admin._sessions_store.access_all(limit=5)) == 5


class TestItIsForgottenWithTheSession:
    """Activity keyed to a session that no longer exists is invisible in the panel — which
    only shows the activity of sessions that exist — and unbounded on disk, which is the one
    thing a ring is for."""

    def test_revoking_a_session_forgets_what_it_did(self, admin, client):
        _login(client)
        sid = _sid(client)
        assert admin._sessions_store.access_for(sid)
        admin._revoke_session_by_uid(sid)
        assert admin._sessions_store.access_for(sid) == []

    def test_signing_everybody_out_forgets_all_of_it(self, admin, client):
        """`save_all` is the path behind "revoke every session" and behind dropping expired
        ones at startup, so the prune belongs there rather than at each call site."""
        _login(client)
        admin._sessions_store.log_access('s-ghost', ts='2026-08-20T10:00:00', ip='',
                                         method='POST', path='/x', status=200, keep=200)
        admin._revoke_all_sessions()
        assert admin._sessions_store.access_all(limit=999) == []

    def test_revoking_one_user_forgets_only_theirs(self, admin, client):
        _login(client)
        mine = _sid(client)
        theirs = _as(admin, 'ed', role='viewer')
        their_sid = _sid(theirs)
        assert admin._sessions_store.access_for(their_sid)
        admin._revoke_user_sessions('ed')
        assert admin._sessions_store.access_for(their_sid) == []
        assert admin._sessions_store.access_for(mine), 'it took the wrong history with it'


class TestTheReads:

    def test_the_feed_names_the_account_behind_each_row(self, admin, client):
        """Resolved on the server, where the listing beside it already does that lookup: two
        answers to "whose is this" is one more than a screen survives."""
        _login(client)
        data = client.get('/api/v1/sessions/access').get_json()
        assert data['access'], 'the feed is empty after a sign-in'
        assert all(r['username'] == 'admin' for r in data['access'])
        assert data['access'][0]['is_current'] is True
        assert data['max'] == 500

    def test_the_feed_drops_a_row_whose_session_is_gone(self, admin, client):
        """Those rows are pruned with the session, so this only ever catches the race — but a
        row the screen cannot attribute to anybody is worse than no row."""
        _login(client)
        admin._sessions_store.log_access('s-nobody', ts='2026-08-20T23:59:59', ip='',
                                         method='POST', path='/x', status=200, keep=200)
        paths = [r['path'] for r in client.get('/api/v1/sessions/access').get_json()['access']]
        assert '/x' not in paths

    def test_one_session_answers_with_its_depth(self, admin, client):
        """`max` travels with the rows so the dialog can tell "this session has done nothing
        recordable" from "the recording is switched off"."""
        _login(client)
        data = client.get(f'/api/v1/sessions/{_sid(client)}/access').get_json()
        assert data['max'] == 200
        assert data['access'][0]['path'] == '/login'

    def test_an_unknown_session_is_a_404_and_not_an_empty_list(self, client):
        """An empty list reads as "this session did nothing", which is a different answer."""
        _login(client)
        assert client.get('/api/v1/sessions/not-a-session/access').status_code == 404

    def test_both_reads_need_the_permission_the_list_needs(self, admin):
        """`sessions_view` and not a flag of their own: this screen already shows every
        session in the installation with its account, its address and its browser."""
        c = _as(admin, 'outsider', role='none')
        assert c.get('/api/v1/sessions/access').status_code == 403
        assert c.get('/api/v1/sessions/whatever/access').status_code == 403
