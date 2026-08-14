#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Everything the templates are handed, in one place.

Every page renders from the same dictionary: the current language and theme, the permission
catalog, the landing destinations, the config registry's defaults and layout, which auth
providers are available and what their buttons should say, and the ~25 ``wa_*`` values the
frontend reads as constants instead of re-deriving.

It lived inside ``_create_app`` — ninety-odd lines in the middle of a method that also
configured Flask, wired the request hooks and discovered module assets. Adding one constant for
a template meant opening the file that owns the request lifecycle, which is a poor place to be
browsing when the errand is "the panel needs to know the audit page size".

Nothing here touches the request cycle: it is read-only, per-render, and the only reason it is
a mixin rather than a function is that every value comes off the instance.
"""

import os

from flask import session

from lib import APP_NAME
from lib.config.layout import config_layout
from lib.config.spec import registry_defaults
from lib.core.audit.events import audit_severity as _audit_severity
from lib.core.constants import BUILTIN_ROLE_UIDS, ROLES
from lib.core.permissions import PERMISSIONS, PERMISSION_GROUPS
from lib.i18n import DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS
from lib.providers.entraid.declarations import (
    DEFAULT_APP_NAME as _ENTRA_APP_DEFAULT,
    OIDC_APP_NAME as _ENTRA_APP_OIDC,
    SAML2_APP_NAME as _ENTRA_APP_SAML2,
    SCIM_APP_NAME as _ENTRA_APP_SCIM,
    EMAIL_APP_NAME as _ENTRA_APP_EMAIL,
    TEAMS_APP_NAME as _ENTRA_APP_TEAMS)
from lib.providers.ldap import auth as _ldap_auth
from lib.providers.oidc import auth as _oidc_auth
from lib.providers.saml import auth as _saml_auth

from ..constants import landing_options


class _ContextMixin:
    """The template context — what every page is rendered with."""

    def _asset_version(self, app) -> int:
        """Cache-buster for the stylesheet: its mtime.

        The dev watcher does not restart on a ``.css`` edit and the ``<link>`` is otherwise a
        plain cacheable URL, so without this an edited stylesheet reaches the browser whenever
        the browser feels like it. Unreadable → 0, which is a cache-buster that busts nothing
        rather than a page that fails to render.
        """
        try:
            return int(os.path.getmtime(os.path.join(app.static_folder, 'css', 'web_admin.css')))
        except OSError:
            return 0

    def _auth_provider_context(self) -> dict:
        """Which sign-in providers exist, are switched on, and what their buttons say.

        `available` and `enabled` are different questions and the login page asks both: a
        provider whose library is missing cannot be offered at all, while one that is merely
        turned off still has its configuration on screen.
        """
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        ldap_cfg = cfg.get('ldap') or {}
        oidc_cfg = cfg.get('oidc') or {}
        saml2_cfg = cfg.get('saml2') or {}
        provider_url = (oidc_cfg.get('provider_url') or '').lower()
        idp_sso_url = (saml2_cfg.get('idp_sso_url') or '').lower()
        return {
            'ldap_enabled':       _ldap_auth.is_available() and bool(ldap_cfg.get('enabled')),
            'ldap_button_label':  (ldap_cfg.get('button_label') or '').strip(),
            'oidc_enabled':       _oidc_auth.is_available() and bool(oidc_cfg.get('enabled')),
            'saml2_enabled':      _saml_auth.is_available() and bool(saml2_cfg.get('enabled')),
            'oidc_button_label':  (oidc_cfg.get('button_label') or '').strip(),
            'saml2_button_label': (saml2_cfg.get('button_label') or '').strip(),
            # The icon follows the IdP the URL points at, so the button looks like the thing
            # it opens rather than like a generic "sign in elsewhere".
            'oidc_button_icon': (
                'bi-microsoft' if 'microsoftonline.com' in provider_url
                else 'bi-google' if 'accounts.google.com' in provider_url
                else 'bi-box-arrow-in-right'
            ),
            'saml2_button_icon': (
                'bi-microsoft' if any(kw in idp_sso_url
                                      for kw in ('microsoftonline.com', 'microsoft.com', 'azure'))
                else 'bi-shield-lock'
            ),
            'ldap_available':  _ldap_auth.is_available(),
            'oidc_available':  _oidc_auth.is_available(),
            'saml2_available': _saml_auth.is_available(),
        }

    def _template_context(self, app) -> dict:
        """The dictionary every template renders with.

        Registered as Flask's context processor by ``_create_app``; *app* is passed rather than
        read off ``self`` because this runs while the app is still being built, before
        ``self._app`` exists.
        """
        lang = session.get('lang', self._DEFAULT_LANG)
        dark_mode = session.get('dark_mode', self._DEFAULT_DARK_MODE)
        return {
            'asset_v': self._asset_version(app),
            # The product's name, from its one home in `lib/__init__.py`. Every page that signs
            # itself — the title, the sidebar head, the boot screen, the status page — reads it
            # from here rather than spelling it out, so the name lives in exactly one place.
            'app_name': APP_NAME,
            'lang': lang,
            'default_lang': self._DEFAULT_LANG,
            'dark_mode': dark_mode,
            'i18n': TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG]),
            'supported_langs': SUPPORTED_LANGS,
            'current_session_token': session.get('session_id', ''),
            'permissions_list': list(PERMISSIONS),
            'permissions_groups': PERMISSION_GROUPS,
            # Landing destinations for the three selects that offer them (config, user,
            # group), labelled server-side: a module section names itself in the module's
            # own lang file, so a frontend resolving `t(label_key)` had nothing to look up
            # and printed the raw id. Core pages AND module sections, one entry per view.
            'home_pages': landing_options(lang, self._DEFAULT_LANG),
            # Notification routing matrix, registry-driven: rows = discovered event kinds
            # (lib/core/notify/events.py), columns = registered channels (registry.py).
            'notify_matrix_events': self._notify_matrix_events(),
            'notify_channels': self._notify_channel_cols(),
            'wa_builtin_roles': [BUILTIN_ROLE_UIDS[r] for r in ROLES if r in BUILTIN_ROLE_UIDS],
            'wa_sensitive_fields': sorted(self._sensitive_fields),
            'wa_remember_me_days': self._REMEMBER_ME_DAYS,
            'wa_audit_max_entries': self._AUDIT_MAX_ENTRIES,
            'wa_audit_detail_max_items': self._AUDIT_DETAIL_MAX_ITEMS,
            # What each audit event MEANS, declared by the package that writes it
            # (manifest.py :: AUDIT_EVENTS). The badge used to be guessed from the event
            # NAME, which made the colour depend on the noun somebody picked.
            'audit_severity': _audit_severity(),
            'wa_secure_cookies': self._SECURE_COOKIES,
            'wa_pw_min_len': self._PW_MIN_LEN,
            'wa_pw_max_len': self._PW_MAX_LEN,
            'wa_pw_require_upper': self._PW_REQUIRE_UPPER,
            'wa_pw_require_digit': self._PW_REQUIRE_DIGIT,
            'wa_pw_require_symbol': self._PW_REQUIRE_SYMBOL,
            'wa_public_status': self._PUBLIC_STATUS,
            'wa_public_status_detail': self._PUBLIC_STATUS_DETAIL,
            'wa_status_refresh_secs': self._STATUS_REFRESH_SECS,
            'wa_status_lang': self._STATUS_LANG,
            'wa_web_port': self._PORT,
            'wa_env_locked_fields': sorted(self._env_locked),
            'wa_file_locked_fields': sorted(getattr(self, '_file_locked', frozenset())),
            'wa_proxy_count': self._PROXY_COUNT,
            'wa_public_url': self._PUBLIC_URL,
            'csrf_token': self._csrf_token(),
            # Effective base URL (config override → else proxy-aware auto-detect),
            # injected so the JS never re-derives it. See public_base_url().
            'wa_base_url': self.public_base_url(),
            'wa_force_https': self._FORCE_HTTPS,
            'wa_force_fqdn':  self._FORCE_FQDN,
            'wa_startup_id':  self._startup_id,
            'wa_default_dark_mode': self._DEFAULT_DARK_MODE,
            'config_registry_defaults': registry_defaults(),
            'config_layout': config_layout(),
            **self._auth_provider_context(),
            # Default Entra ID app display names (single source: providers.entraid),
            # injected into the JS wizards via core/_constants.html.
            'entra_app_name_default': _ENTRA_APP_DEFAULT,
            'entra_app_name_oidc':    _ENTRA_APP_OIDC,
            'entra_app_name_saml2':   _ENTRA_APP_SAML2,
            'entra_app_name_scim':    _ENTRA_APP_SCIM,
            'entra_app_name_email':   _ENTRA_APP_EMAIL,
            'entra_app_name_teams':   _ENTRA_APP_TEAMS,
            'module_web_styles': self._module_web_styles,
            'module_web_ui':     self._module_web_ui,
            'module_web_modals': self._module_web_modals,
        }
