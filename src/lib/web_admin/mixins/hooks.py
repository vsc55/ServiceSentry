#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What runs around every request, and in what order.

Flask calls ``before_request`` handlers in REGISTRATION order, so until now the order of this
panel's security was the order of five decorators down the middle of ``_create_app`` — true,
load-bearing, and stated nowhere. Moving a block while tidying would have changed who guards
what, and the tests that would notice are not the ones anybody runs after a tidy-up.

:data:`_BEFORE_REQUEST` makes the order the thing you edit, with the reason for each position
written beside it. The handlers are methods rather than closures for the same reason: one can
be read, and tested, without reading the four around it.

Two of them are not merely ordered but ORDERED-CRITICAL:

* ``ipban`` runs first because a banned address must not reach anything — not a cache refresh,
  not a redirect, not a login form;
* ``csrf`` runs after the caches so a rejection is audited against fresh users, and BEFORE the
  FQDN redirect, so a state-changing request that arrived on the wrong hostname is judged on
  its token rather than bounced to a URL that would drop its body;
* ``api_token`` runs before ``csrf`` because CSRF has to know how the request authenticated.
  A bearer call is not a browser being tricked into posting — no cross-site page can attach an
  ``Authorization`` header — so it is exempt, and deciding that afterwards would mean rejecting
  every write an API client makes.
"""

import time
import traceback
import uuid

from flask import (current_app, flash, g, jsonify, redirect, request,
                   session, url_for)
from werkzeug.exceptions import HTTPException, InternalServerError

from lib.debug import DebugLevel
from lib.core.object_base import ObjectBase
from lib.security import csrf as _csrf
from lib.security.headers import apply_security_headers


class _HooksMixin:
    """The request lifecycle: gate, trace, refresh, protect, redirect, close."""

    # Registration order IS the running order. Edit here, not by moving code.
    _BEFORE_REQUEST = (
        '_hook_ipban_gate',        # first: a banned address reaches nothing
        '_hook_trace_start',       # start the clock before any work is done
        '_hook_refresh_caches',    # fresh roles/users/groups for whatever authorises next
        '_hook_api_token',         # BEFORE csrf: how a request authenticated decides whether
                                   # CSRF applies to it at all (a bearer call is not a browser
                                   # being tricked — no cross-site page can set that header)
        '_hook_csrf_protect',      # judged on the token, before any redirect can move it
        '_hook_enforce_fqdn',      # last: only a request that survived everything is bounced
    )

    def _register_request_hooks(self, app) -> None:
        """Wire the lifecycle onto *app*, in the declared order."""
        for name in self._BEFORE_REQUEST:
            app.before_request(getattr(self, name))
        # Before `_hook_trace_end` is irrelevant, but before Flask's `save_session` is not:
        # after_request handlers all run ahead of it, which is the only window in which a
        # token request can be stopped from being handed a session cookie.
        app.after_request(self._hook_api_token_access)
        # Its counterpart for a signed-in browser. Not the same hook with a condition inside:
        # they record different things about different clients (see `_LOGGED_METHODS`), and
        # one function that decided which would be one function to get the decision wrong in.
        app.after_request(self._hook_session_access)
        app.after_request(self._hook_api_token_no_cookie)
        app.after_request(self._hook_trace_end)
        app.teardown_request(self._hook_close_thread_db)
        app.register_error_handler(Exception, self._hook_unhandled_error)

    # ── before_request ────────────────────────────────────────────────────────
    def _hook_ipban_gate(self):
        """Internal fail2ban gate (must run first) — logic in _IpBanMixin."""
        return self._ipban_gate_response()

    def _hook_trace_start(self):
        g._req_start = time.perf_counter()

    def _hook_refresh_caches(self):
        """Roles, users and groups live in memory for the life of the process, so another
        writer against the same database — the CLI, or a second web replica — would be
        invisible to this one.

        Here, and only here: the reload replaces the dict wholesale, so it has to happen
        before a handler starts rather than in the middle of an edit.

        Static files authorise nothing and arrive by the dozen per page, so they do not get a
        probe — with the re-check set to 0 (every request) they would otherwise turn one page
        load into thirty queries.
        """
        if request.endpoint != 'static':
            self._reload_roles_if_stale()
            self._reload_users_if_stale()
            self._reload_groups_if_stale()

    def _hook_csrf_protect(self):
        """Double-submit CSRF: a state-changing request must echo the session token in the
        ``X-CSRF-Token`` header (JSON APIs) or the ``csrf_token`` field (form posts).

        Exempt prefixes are DISCOVERED, not hardcoded: each route module declares its own via
        ``wa._register_csrf_exempt(...)`` in its ``register()`` (token-authenticated SCIM,
        inbound IdP callbacks, Teams SSO/bot — cross-site by design, protected instead by their
        own protocol/token). ``register_all()`` runs during app creation, before any request,
        so the list is fully populated by the time this first reads it.
        """
        app = current_app
        # Enabled in production; OFF under pytest (TESTING) so the many mutating
        # requests in the suite need no token plumbing — unless a test opts in by
        # setting wa._csrf_enabled = True (see test_wa_csrf.py). An explicit
        # attribute (True/False) always wins.
        enabled = getattr(self, '_csrf_enabled', None)
        if enabled is None:
            enabled = not app.config.get('TESTING', False)
        if not enabled:
            return None
        # A bearer-authenticated request is exempt, and not as a convenience: the
        # double-submit token defends against a cross-site page making the BROWSER issue a
        # request with its cookies attached. No such page can attach an `Authorization`
        # header — it would need CORS consent from this origin — so there is no attack for
        # the token to prevent here, and requiring one would reject every write an API
        # client makes. This is why `_hook_api_token` runs before this hook.
        if getattr(g, 'api_token', None):
            return None
        if not _csrf.needs_check(request.method, request.path, self._csrf_exempt_prefixes):
            return None
        if not _csrf.is_valid(request, session):
            # A CSRF failure with NO session cookie is the classic "Secure cookie
            # over plain HTTP" symptom (the browser drops a Secure cookie on http://)
            # — surface it clearly so it isn't mistaken for a bad password.
            # Only on /login (not every bot POST): a CSRF failure with no cookies +
            # Secure cookies on is the "Secure cookie dropped over HTTP" footgun,
            # which otherwise looks like a silent login loop.
            if (request.path == '/login' and not request.cookies
                    and app.config.get('SESSION_COOKIE_SECURE')):
                self._dbg(
                    f"> CSRF >> /login received no session cookie over {request.scheme} "
                    f"while SESSION_COOKIE_SECURE is on — the browser drops a Secure "
                    f"cookie on HTTP. Use HTTPS, or disable force_https/secure_cookies "
                    f"for HTTP access.", DebugLevel.warning)
            self._audit('csrf_failed', session.get('username', ''), request.remote_addr,
                        detail={'path': request.path, 'method': request.method})
            self._ipban_offense('csrf_failed')
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'error': self._t('csrf_invalid')}), 403
            flash(self._t('csrf_invalid'), 'danger')
            return redirect(url_for('login'))
        return None

    def _hook_enforce_fqdn(self):
        """Send a request that arrived on the wrong host to the public URL.

        Opt-in (``web_admin|force_fqdn``) and only with a public URL configured.  Two
        things it must never do, because both make the panel unreachable — including the
        page that would let you turn it off:

        * **redirect over a port difference.**  ``request.host`` carries the port,
          ``public_url`` need not.  Comparing the raw strings made ``192.168.0.1:8080``
          a "different host" from ``192.168.0.1`` and sent the browser to port 80, where
          nothing is listening.  The setting is about the *hostname* you arrived on, so
          a public URL that names no port accepts any port;
        * **redirect to itself.**  If the target is the request we are answering, the
          browser follows it forever (``ERR_TOO_MANY_REDIRECTS``).  Refusing is always
          better than looping: the worst case is that the redirect does not happen.
        """
        if not self._FORCE_FQDN or not self._PUBLIC_URL:
            return None
        want = self._PUBLIC_URL.strip().lower()      # host[:port], never a scheme
        have = (request.host or '').strip().lower()
        if ':' not in want:
            have = have.split(':', 1)[0]
        if have == want:
            return None
        scheme = 'https' if self._FORCE_HTTPS else 'http'
        target = f"{scheme}://{self._PUBLIC_URL}{request.path}"
        if target == request.base_url:
            return None
        qs = request.query_string.decode('utf-8')
        if qs:
            target += '?' + qs
        return redirect(target, code=302)

    # ── after_request ─────────────────────────────────────────────────────────
    def _hook_trace_end(self, response):
        """Security headers, the fail2ban offence count, cache policy, and one trace line."""
        # Security headers (defense-in-depth; policy in lib.security.headers).
        # An admin-defined frame-ancestors allowlist (+ optional Teams hosts) opens
        # framing to those origins so the Teams personal tab can embed the panel.
        apply_security_headers(response,
                               frame_ancestors=self._frame_ancestors_list or None,
                               img_origins=self._image_origins() or None)
        # fail2ban: count a 401/403 as an offense for the client IP (logic in
        # _IpBanMixin; skips gate blocks and requests that already counted).
        self._ipban_capture(response)
        # Dynamic API responses must never be browser-cached: a stale GET
        # (e.g. /api/v1/users or /api/v1/me) would show an admin a user's
        # pre-clear table layout even after a full page reload, and would
        # break the keepalive live-sync of layout changes.
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        # …and a static file is the opposite question. Flask leaves these to revalidate, which
        # is a round trip per asset per load — and on a page whose stylesheets are half a
        # megabyte that wait is the difference between a dressed page and a screenful of serif
        # text while the browser gives up waiting (see base.html).
        #
        # A YEAR for anything whose URL carries a version, because such a URL cannot go stale:
        # a new build is a new URL. A day for the rest — the fonts a stylesheet pulls in under
        # a name of its own, which nothing versions and nobody can bust.
        elif request.path.startswith('/static/') and response.status_code == 200:
            response.headers['Cache-Control'] = (
                'public, max-age=31536000, immutable' if request.args.get('v')
                else 'public, max-age=86400')
        # Generic per-endpoint trace, for EVERY API, gated by log_level:
        # GET/static at debug, mutations at info, 4xx/5xx at warning. Logs the
        # endpoint, input KEYS (query + json body — never values, so no
        # secrets), status, timing, reason and payload size.
        path = request.path
        if path.startswith('/static/') or not ObjectBase.debug.enabled:
            return response
        start = getattr(g, '_req_start', None)
        ms = f"{(time.perf_counter() - start) * 1000:.0f}ms" if start else '?'
        status = response.status_code
        # Input shape (keys only — values may carry passwords/tokens/secrets).
        inp = []
        if request.args:
            inp.append('args=' + ','.join(request.args.keys()))
        if request.is_json:
            _b = request.get_json(silent=True)
            if isinstance(_b, dict) and _b:
                inp.append('body=' + ','.join(list(_b.keys())[:15]))
        in_s = (' ' + ' '.join(inp)) if inp else ''
        reason = ''
        if status >= 400:
            level = DebugLevel.warning
            # Surface the rejection reason (the JSON 'error' message) so the
            # *why* of every 4xx/5xx is traced uniformly, for any endpoint.
            if response.is_json:
                try:
                    body = response.get_json(silent=True)
                    if isinstance(body, dict) and body.get('error'):
                        reason = f": {body['error']}"
                except Exception:  # pylint: disable=broad-except
                    pass
        elif request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            level = DebugLevel.info
        else:
            level = DebugLevel.debug
        size = response.content_length
        size_s = f" {size}B" if size is not None else ''
        self._dbg(f"> HTTP >> {request.method} {path} [{request.endpoint}]{in_s} "
                  f"-> {status}{reason} ({ms}){size_s}", level)
        return response

    # ── unhandled exceptions ──────────────────────────────────────────────────
    def _hook_unhandled_error(self, exc):
        """A crash inside a handler must leave a record, and must say something usable.

        Until this existed, it left neither. Flask answered an unhandled exception with its
        own 500, and because ``after_request`` does NOT run on that path, the per-endpoint
        trace line — the one that logs every 4xx/5xx with its reason — never fired either.
        The traceback went to Flask's own logger, which this panel does not wire into its
        debug output or its log file, so on a service or in a container it went nowhere
        anybody looks. Nothing reached the audit, because nothing wrote it there.

        The client fared no better: the body of that 500 is an HTML error page, ``apiPut``
        parses it as JSON, the parse throws, and the ``catch`` returns null — the same null
        it returns when the network is down. Every distinguishing detail was discarded before
        anyone could read it, which is how a save that stored the record showed a bare
        "Error al guardar" with nowhere to go next.

        So: one reference code, in three places at once — the log line, the audit entry, and
        the message on screen. The user reads a short code off the toast and finds the entry;
        the entry names the endpoint and the exception. What the RESPONSE never carries is the
        traceback: an error page is not the place to publish internals to whoever can reach
        the URL, and the reference is what makes that unnecessary rather than merely strict.

        ``HTTPException`` is returned untouched — a 404 or a 403 is an ANSWER, not a fault,
        and auditing every probe for ``/wp-admin`` would bury the real ones.
        """
        if isinstance(exc, HTTPException):
            return exc
        ref = uuid.uuid4().hex[:8]
        self._dbg(f"> HTTP >> {request.method} {request.path} [{request.endpoint}] "
                  f"-> 500 ref={ref}: {type(exc).__name__}: {exc}\n"
                  f"{traceback.format_exc()}", DebugLevel.error)
        # Never let the record-keeping become the thing that fails: _audit_write already
        # rolls back and reports, but an audit that raised HERE would replace a diagnosable
        # crash with an undiagnosable one.
        try:
            self._audit_auto('internal_error', detail={
                'ref': ref,
                'method': request.method,
                'path': request.path,
                'endpoint': request.endpoint or '',
                'exception': type(exc).__name__,
                'message': str(exc)[:500],
            })
        except Exception:  # pylint: disable=broad-except
            pass
        # Debug and pytest keep the raise, so a traceback still lands in the terminal and in
        # the test report — the record above is added to that, never traded for it. Flask's
        # own default when PROPAGATE_EXCEPTIONS is unset, reproduced: registering a handler
        # for Exception takes precedence over it, so not reproducing it would have silently
        # turned every test crash into a 500 response.
        propagate = current_app.config.get('PROPAGATE_EXCEPTIONS')
        if propagate is None:
            propagate = current_app.testing or current_app.debug
        if propagate:
            raise exc
        msg = f"{self._t('internal_error')} (ref: {ref})"
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': msg, 'ref': ref}), 500
        # A browser gets the standard error PAGE with the reference as its description, not a
        # bare string: the page is what states the code, and a 500 that does not say "500"
        # reads like a broken response rather than a reported one.
        return InternalServerError(description=msg)

    # ── teardown_request ──────────────────────────────────────────────────────
    def _hook_close_thread_db(self, _exc=None):  # noqa: ANN001
        """The dev server is threaded=True (a new thread per request), so each request's
        per-thread DB connection would be abandoned when the thread ends — MySQL/MariaDB logs
        that as an 'aborted connection'. Close it cleanly (no-op for SQLite; no reuse lost,
        the thread is short-lived anyway)."""
        for _c in (getattr(self, '_db_connector', None),
                   getattr(self, '_syslog_db_connector', None)):
            if _c is not None:
                _c.close_thread_if_needed()
