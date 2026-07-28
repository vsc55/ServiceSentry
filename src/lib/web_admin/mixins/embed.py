#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Being embeddable in somebody else's iframe, without handing them the session.

Allowing an embed is two decisions that must be made together and are easy to make apart:
``frame-ancestors`` says who may frame the panel, and the session cookie's ``SameSite`` says
whether the browser will send the session when they do. Set the first without the second and
the iframe loads an eternally logged-out page; set the second without meaning to and the
cookie travels cross-site everywhere.

They are recomputed together here, after route registration, once the embed profiles are known.
"""

from lib.debug import DebugLevel

class _EmbedMixin:
    """Embed origins, frame-ancestors and the cookie policy that must match them."""

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _register_csrf_exempt(self, *prefixes: str) -> None:
        """Declare CSRF-exempt path prefixes — called by a route module's register() so the
        exempt set is discovered from the modules, not hardcoded. Deduped, order preserved."""
        clean = [p for p in prefixes if p]
        self._csrf_exempt_prefixes = tuple(dict.fromkeys((*self._csrf_exempt_prefixes, *clean)))

    def _register_embed_origins(self, config_attr: str, *origins: str) -> None:
        """Declare iframe-embed origins gated by a bool config attr (e.g. ``_embed_in_teams``),
        so integration-specific frame-ancestors are discovered from the provider rather than
        hardcoded in the core security layer. Recomputes the effective allowlist."""
        prof = (config_attr, tuple(o for o in origins if o))
        self._embed_profiles = (*self._embed_profiles, prof)
        self._recompute_frame_ancestors()

    def _recompute_frame_ancestors(self) -> None:
        """Rebuild the iframe allowlist: admin-configured origins + every registered embed
        profile whose flag attr is currently on. Cheap, called on config change / at startup."""
        try:
            wa_cfg = (self._read_config_file(self._CONFIG_FILE) or {}).get('web_admin') or {}
        except Exception:  # pylint: disable=broad-except
            wa_cfg = {}
        fa = [o for o in str(wa_cfg.get('frame_ancestors') or '').replace(',', ' ').split() if o]
        for attr, origins in self._embed_profiles:
            if getattr(self, attr, False):
                fa = list(dict.fromkeys(fa + list(origins)))
        self._frame_ancestors_list = fa
        _app = getattr(self, '_app', None)   # None at boot (set after _create_app); set on live saves
        if _app is not None:
            self._apply_embed_cookie_policy(_app)

    def _apply_embed_cookie_policy(self, app) -> None:
        """SameSite=None + Secure when the app is embeddable cross-site (any allowed
        frame-ancestors), so the session cookie survives inside the iframe; otherwise the
        stricter Lax. Provider-agnostic — driven by the effective frame-ancestors allowlist.

        **Only on an explicit HTTPS intent**, and that condition is the whole point. Browsers
        refuse a ``SameSite=None`` cookie that is not ``Secure``, and they refuse a ``Secure``
        cookie over plain HTTP — so on an http:// deployment this policy does not enable the
        embed, it just throws the session cookie away. Every login then succeeds and lands
        back on the login page, because the session it created was never stored: an infinite
        redirect, with nothing saying that allowing an iframe origin was what caused it.

        The same reasoning is already applied to ``public_url`` above. A cross-site iframe
        over plain HTTP cannot work in any case, so there is nothing to trade away: the embed
        is impossible either way, and this keeps ordinary login working.
        """
        _https = bool(self._secure_cookies or self._force_https)
        if self._frame_ancestors_list and _https:
            app.config['SESSION_COOKIE_SAMESITE'] = 'None'
            app.config['SESSION_COOKIE_SECURE'] = True
            return
        if self._frame_ancestors_list:
            self._dbg('> Security >> frame-ancestors are allowed but neither secure_cookies '
                      'nor force_https is on: the cross-site iframe cannot work over plain '
                      'HTTP (a SameSite=None cookie must be Secure, and a Secure cookie is '
                      'dropped on http://). Keeping SameSite=Lax so normal login still works.',
                      DebugLevel.warning)
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['SESSION_COOKIE_SECURE'] = _https
