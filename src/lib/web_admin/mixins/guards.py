#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Who may call a route, and where a refusal sends them.

Four decorators that all begin the same way — *is there a session at all?* — and then differ
only in what they check next. That opening was written out four times, and the important part
of it is not the check but the ANSWER: an API caller gets 401 JSON, a browser gets sent to the
login page. Reply the wrong way and a fetch() renders a login page into a table, or a browser
is handed a JSON error it cannot act on.

Written once here, so the four cannot drift into three answers.

``_admin_required`` and ``_write_required`` are shims kept for routes not yet migrated; new
routes name the permission they need with :meth:`_perm_required`, which is the only one of the
four that says out loud what it is protecting.
"""

import functools
from urllib.parse import urlparse

from flask import jsonify, redirect, request, url_for


class _GuardsMixin:
    """Route guards: authentication, permissions, and safe redirects."""

    def _deny_unauthenticated(self):
        """``None`` when a session is present, otherwise the refusal to return.

        The shape of the refusal is the whole point: an API caller cannot act on a login page
        and a browser cannot act on a JSON error, so the answer follows the caller.
        """
        if self._check_session():
            return None
        if request.path.startswith('/api/'):
            return jsonify({'error': self._t('unauthorized')}), 401
        return redirect(url_for('login'))

    def _perm_required(self, *perms):
        """Return a decorator that requires ANY of the listed permissions."""
        def decorator(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                denied = self._deny_unauthenticated()
                if denied is not None:
                    return denied
                if not any(p in self._get_session_permissions() for p in perms):
                    return jsonify({'error': self._t('access_denied')}), 403
                return f(*args, **kwargs)
            return wrapper
        return decorator

    def _login_required(self, f):
        """Decorator that redirects unauthenticated requests to ``/login``."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            denied = self._deny_unauthenticated()
            if denied is not None:
                return denied
            return f(*args, **kwargs)
        return wrapper

    def _admin_required(self, f):
        """Deprecated shim — prefer _perm_required(). Checks users_view."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            denied = self._deny_unauthenticated()
            if denied is not None:
                return denied
            if 'users_view' not in self._get_session_permissions():
                return jsonify({'error': self._t('access_denied')}), 403
            return f(*args, **kwargs)
        return wrapper

    def _write_required(self, f):
        """Deprecated shim — prefer _perm_required(). Checks modules_edit or config_edit."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            denied = self._deny_unauthenticated()
            if denied is not None:
                return denied
            perms = self._get_session_permissions()
            if not ('modules_edit' in perms or 'config_edit' in perms):
                return jsonify({'error': self._t('read_only_access')}), 403
            return f(*args, **kwargs)
        return wrapper

    @staticmethod
    def _safe_referrer(fallback: str = 'login') -> str:
        """Return the Referer URL only when it belongs to the same origin.

        Prevents open-redirect attacks where an attacker-controlled
        ``Referer`` header could redirect users to an external site.
        """
        ref = request.referrer
        if ref:
            parsed = urlparse(ref)
            own = urlparse(request.host_url)
            if parsed.scheme == own.scheme and parsed.netloc == own.netloc:
                return ref
        return url_for(fallback)
