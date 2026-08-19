#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Who this installation makes carry a second factor, and where a security key would live.

Split from :mod:`.mixin` because the two halves answer different kinds of question. This one
**decides**: it reads the configuration, the account and its groups and says yes or no. The
other one **remembers**: it keeps the half-finished sign-in in the Flask cookie. Nothing here
touches a request, a cookie or a template, which is what makes every rule below reachable from
a test that does not stand up an app — and these are the rules that hurt most when they are
wrong, because they decide who gets shut out.

**The property to preserve above all: switching a policy on must never lock anybody out.** It
is why :meth:`_MfaPolicyMixin._mfa_must_enrol` exists and answers "send them to enrol" rather
than "refuse them". The day that becomes "refuse", the first person locked out is the last
administrator of an install that just turned the setting on.

Composed onto :class:`~lib.web_admin.WebAdmin` beside ``_MfaMixin``, and it leans on two things
that mixin provides — ``_mfa_enrolled`` and the store behind it. Two mixins on one object, so
the call is a plain ``self.``; the split is about what a reader (and a test) has to carry, not
about severing the two.
"""

from __future__ import annotations

from lib.debug import DebugLevel


class _MfaPolicyMixin:
    """Second-factor POLICY on the WebAdmin — no Flask, no request, no session."""

    def _mfa_policy(self) -> str:
        """`'off'`, `'admins'` or `'all'` — who this installation makes carry a second factor.

        **Fails safe, and that is the whole reason this is a method.** A policy that demanded a
        factor on an install where secrets cannot be encrypted would demand something nobody
        can enrol: `MfaStore` refuses to write a seed it cannot protect, so every account that
        had not already enrolled would be shut out, including the last administrator. Read as
        `off` in that case whatever the config says, and said out loud — the alternative is an
        installation nobody can open and a setting that looks correct.

        Read from the config each time rather than mirrored on an attribute: it is consulted
        once per sign-in, and an attribute would be a second copy every save has to refresh.
        """
        from lib.config.spec import cfg_default        # noqa: PLC0415
        section = self._config_section('web_admin') if hasattr(self, '_config_section') else {}
        want = str((section or {}).get('mfa_required')
                   or cfg_default('web_admin|mfa_required') or 'off')
        if want not in ('off', 'admins', 'all'):
            return 'off'
        if want != 'off' and getattr(self, '_mfa_store', None) is not None \
                and self._mfa_store._fernet is None:
            self._dbg('> MFA >> `mfa_required` is set but secrets cannot be encrypted on this '
                      'install — the policy is being ignored, because enforcing it would lock '
                      'out every account that has not already enrolled', DebugLevel.warning)
            return 'off'
        return want

    def _mfa_policy_applies(self, username: str) -> bool:
        """Does the installation's policy cover THIS account?

        `admins` means an administrator however they became one — by their own role or through
        a group carrying it. Asking only the account's own role is the bug the August audit
        found in four other guards, and repeating it here would leave the accounts the policy
        exists to protect as the ones it skipped.
        """
        policy = self._mfa_policy()
        if policy == 'all':
            return True
        if policy != 'admins':
            return False
        from lib.core.users import service as users_svc   # noqa: PLC0415
        user = self._users.get(str(username or '')) or {}
        return bool(user) and users_svc.user_is_admin(user, self._groups)

    # Which config section backs which sign-in source. Only the three that HAVE one: a Teams
    # tab sign-in (`entraid`) has no section of its own, so it is never trusted — the safe
    # direction, and the panel asks for what it can verify itself.
    _TRUSTED_SECTIONS = {'ldap': 'ldap', 'oidc': 'oidc', 'saml2': 'saml2'}

    def _mfa_provider_trusted(self, source: str) -> bool:
        """Has the operator said this directory already asks for a second factor?

        When it has, asking again is friction with no gain: the account proved two things
        before the panel ever saw it. It skips BOTH halves — the code step and the forced
        enrolment — because both exist to establish the same fact and the IdP established it.

        A local sign-in is never trusted, whatever any provider says. Trusting a provider is a
        statement about that DOOR, not about the account: somebody who also has a password
        here still meets the panel's own policy when they use it.
        """
        section = self._TRUSTED_SECTIONS.get(str(source or ''))
        if not section:
            return False
        cfg = self._config_section(section) if hasattr(self, '_config_section') else {}
        return bool((cfg or {}).get('mfa_trusted'))

    def _mfa_must_enrol(self, username: str, source: str = 'local') -> bool:
        """The policy covers this account and it has no factor — enrol on the way in.

        Not "refuse the sign-in": that would mean switching the policy on locks out everybody
        who has not enrolled yet, which on a fresh policy is everybody. The forced enrolment IS
        the way in, and it is what makes this safe to turn on.
        """
        if self._mfa_provider_trusted(source):
            return False
        return self._mfa_policy_applies(username) and not self._mfa_enrolled(username)

    def _mfa_required(self, username: str, source: str = 'local') -> bool:
        """Does this sign-in owe a second factor — either verifying one or setting one up?

        An account with a factor always verifies it, whatever the policy says: turning the
        policy off must not silently stop honouring the ones people already set up.

        Unless the sign-in came through a directory the operator has marked as already asking
        for one. That is a switch per provider and not a rule written here, because "does this
        IdP enforce MFA" is a fact about somebody else's system that only they can state.
        """
        if self._mfa_provider_trusted(source):
            return False
        return self._mfa_enrolled(username) or self._mfa_must_enrol(username, source)

    # ── Where security keys are registered ───────────────────────────────────

    def _webauthn_scope(self) -> dict:
        """`{'ok', 'rp_id', 'origin', 'reason'}` — can this install offer a security key?

        Three things have to be true, and when one is not the answer is **do not offer it**
        rather than try: a credential is scoped by the browser to the RP ID and CANNOT be
        moved, so registering one against a guess produces a key that silently never works
        again and nothing on screen that says why.

        * `public_url` (or the `webauthn_rp_id` escape) names a domain. An IP address is not a
          registrable domain and neither is an empty setting.
        * the origin is **https**. The browser refuses a ceremony outside a secure context, and
          refusing here instead means an explanation instead of an opaque browser error.
        `proxy_warning` comes back beside them for the case that bites behind a reverse proxy
        terminating TLS: with `proxy_count` at 0 the panel never reads `X-Forwarded-Proto`, so
        it serves an install that IS on https while believing it is not — the state the
        diagnostics network block calls `ignored`. It is a warning and not a refusal, because
        the ceremony would work; what breaks first is the session cookie, and naming WebAuthn
        as the problem would send somebody to the wrong setting.
        """
        from lib.core.mfa import webauthn                # noqa: PLC0415
        section = self._config_section('web_admin') if hasattr(self, '_config_section') else {}
        section = section or {}
        public_url = str(section.get('public_url') or getattr(self, '_PUBLIC_URL', '') or '')
        override = str(section.get('webauthn_rp_id') or '').strip().lower()
        rp_id = override or webauthn.rp_id_from(public_url)
        origin = webauthn.origin_from(public_url)
        if not rp_id:
            return {'ok': False, 'rp_id': '', 'origin': '', 'reason': 'no_public_url'}
        if not origin.startswith('https://'):
            return {'ok': False, 'rp_id': rp_id, 'origin': origin, 'reason': 'not_https'}
        # An override that the origin does not sit under would be rejected by the browser,
        # which is a worse place to find out. The RP ID must be the origin's host or a parent
        # of it — `example.com` for a panel on `panel.example.com`, never the other way round.
        host = origin.split('://', 1)[1].split(':', 1)[0]
        if host != rp_id and not host.endswith('.' + rp_id):
            return {'ok': False, 'rp_id': rp_id, 'origin': origin, 'reason': 'rp_id_mismatch'}
        # A WARNING and not a refusal. `public_url` says https, so the browser will reach a
        # secure context and the ceremony will work — but with `proxy_count` at 0 behind a
        # proxy that terminates TLS the panel believes it is serving plain http, and that
        # breaks the SESSION (a Secure cookie the panel will not set) long before WebAuthn is
        # reached. Blocking here would name the wrong problem; saying it is the useful part.
        trusting = int(getattr(self, '_PROXY_COUNT', 0) or 0) > 0
        return {'ok': True, 'rp_id': rp_id, 'origin': origin, 'reason': '',
                'proxy_warning': not trusting}

