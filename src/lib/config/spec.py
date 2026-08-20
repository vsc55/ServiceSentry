#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central registry of configuration fields — single source of truth.

Every option that lives in ``config.json`` is declared here once, with its
type, default value, validation range, the ``WebAdmin`` instance attribute it
maps to (when any), its environment-variable override, whether it is admin-only,
and so on.  Changing a default means editing exactly one line in this file.

Two distinct things are centralised here:

* **Schema** of the ``web_admin`` section — the validated rule dicts
  (``int_rules`` / ``bool_rules`` / ``json_dict_fields``), the env-var map
  (``env_field_specs``) and the admin-only set (``admin_only_fields``) are all
  *derived* from the entries below.  Only fields with ``no_rule=False`` feed
  those rule dicts; everything else is excluded so the web_admin config-save
  validation keeps working exactly as before (e.g. array sections like
  ``webhooks`` must never be iterated as ``data[section][field]``).

* **Defaults** of *all* sections — ``cfg_default(path)`` returns the canonical
  default for any field, so point-of-use reads across the core (monitor, db,
  auth, email, webhooks, …) pull their fallback from here instead of hardcoding
  it.

This module is intentionally dependency-free (no Flask, no web_admin imports)
so it can be imported from the core (``lib.services.monitoring.monitor``, ``lib.db.*``) without any
circular-import or heavyweight side effects.

Notes
-----
* ``attr`` is the ``WebAdmin`` instance attribute mirroring the value at
  runtime.  ``None`` means the field is not held on the instance — its default
  is read at the point of use via :func:`cfg_default`.
* ``no_rule=True`` excludes a field from the derived ``int_rules`` /
  ``bool_rules`` / ``json_dict_fields`` (used for fields handled by dedicated
  code, read only at the point of use, or belonging to array/non-web_admin
  sections).  It does NOT affect :func:`cfg_default`.
* Per-module watchful settings (the module config ``list[item]`` fields) are
  deliberately NOT here: each watchful owns its own declarative defaults in its
  ``schema.json`` / module ``DEFAULTS`` to keep modules independent of the core.
* ``database|port`` has no single default — it is driver-specific (3306 for
  MySQL, 5432 for PostgreSQL) and resolved in the driver modules.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import timedelta

from lib import APP_NAME

# Default UI language.  Inlined (not imported from web_admin) to keep this
# module dependency-free; lib.i18n.DEFAULT_LANG carries the same value.
_DEFAULT_LANG = 'en_EN'


@dataclass(frozen=True)
class Cfg:
    """Schema for one ``section|field`` configuration option."""
    path: str                         # "section|field"
    type: type                        # bool | int | str | dict | list
    default: object = None            # value when config.json lacks the key
    attr: str | None = None           # WebAdmin instance attribute (None = not mirrored)
    min: int | None = None            # int range (inclusive)
    max: int | None = None
    env: str | None = None            # environment-variable override
    admin_only: bool = False          # only admins may modify it
    flask_cfg: tuple | None = None    # (app.config key, transform) to sync Flask
    no_rule: bool = False             # exclude from the derived web_admin rule dicts
    no_seed: bool = False             # exclude from default materialisation (creds only)
                                      # (first-run-only credentials)
    nullable: bool = False            # blank/null is valid (= "use the default")
    card: str | None = None           # config-UI card (category) this option renders in;
                                      # the layout groups fields by this. None = the field
                                      # belongs to a bespoke `renderer` card (auth/db/…) that
                                      # draws it itself, or is not shown as a scalar field.


# ── The registry ────────────────────────────────────────────────────────────
# Order is irrelevant (everything is keyed by ``path``).  Fields with
# ``no_rule=False`` participate in the web_admin validation rule dicts; all the
# rest are documentation + point-of-use defaults (no_rule=True).
CONFIG_FIELDS: tuple[Cfg, ...] = (
    # ══ web_admin: instance-backed runtime options (feed the rule dicts) ═════
    # `default_`, because that is what they are: the language and theme a user gets
    # BEFORE choosing their own (each account keeps its own preference). Named `lang`
    # and `dark_mode`, the attribute that follows from them read as "the language" in
    # chains like `session['lang'] or wa._DEFAULT_LANG or DEFAULT_LANG`, where it is the middle
    # term that is the default. The env var stays `SS_LANG`: it is a published surface.
    # (`_DEFAULT_LANG` appears twice below and means two things: the module constant at the
    # top of this file, and the name of the WebAdmin attribute. They agree on purpose.)
    Cfg('web_admin|default_lang', str, _DEFAULT_LANG, attr='_DEFAULT_LANG',
        env='SS_LANG', card='global'),           # default UI language → General card
    Cfg('web_admin|default_dark_mode', bool, False, attr='_DEFAULT_DARK_MODE',
        env='SS_DARK_MODE', no_rule=True, card='global'),   # default theme → General card
    Cfg('web_admin|landing_page', str, 'admin', attr='_LANDING_PAGE',
        no_rule=True, card='global'),   # default landing page (admin/status/…) → General card
    Cfg('web_admin|remember_me_days', int, 30, attr='_REMEMBER_ME_DAYS',
        min=1, max=365, env='SS_REMEMBER_ME_DAYS', admin_only=True,
        flask_cfg=('PERMANENT_SESSION_LIFETIME', lambda v: timedelta(days=v)),
        card='login_security'),
    Cfg('web_admin|api_token_log_enabled', bool, True, attr='_API_TOKEN_LOG_ENABLED',
        # WHETHER to record at all. Separate from the ceiling below, because "no limit" and
        # "no rows" are opposite answers and one number cannot carry both — it used to, and
        # `0` meant the second while the same `0` in `audit_max_entries` and `syslog|max_rows`
        # means the first. Somebody zeroing every cap to mean "keep everything" switched two
        # of them off instead.
        env='SS_API_TOKEN_LOG_ENABLED', card='api_tokens'),
    Cfg('web_admin|api_token_log_max', int, 200, attr='_API_TOKEN_LOG_MAX',
        # How many recent calls are kept PER TOKEN. A ring, not a log: the questions it answers
        # ("what has this been doing", "where is it calling from") are about the recent past,
        # and a table that grows with API traffic is the one thing an API's own bookkeeping
        # must not be. Per token rather than globally, so a chatty token cannot evict the
        # history of a quiet one — and the quiet one is where a single unexpected call is the
        # whole signal.
        # 0 = NO CEILING: the ring becomes a log and the table grows with API traffic,
        # which is a deliberate choice and not the default. Switching the recording off is
        # the option above.
        min=0, max=10000, env='SS_API_TOKEN_LOG_MAX', card='api_tokens'),
    Cfg('web_admin|audit_max_entries', int, 500, attr='_AUDIT_MAX_ENTRIES',
        # The 'audit' card is bespoke, so this has no `card=` to be placed by; the card draws
        # it explicitly. It said the same thing before and the card did not — an option nobody
        # could see, env-lockable and all.
        min=0, max=10000, env='SS_AUDIT_MAX_ENTRIES'),
    Cfg('web_admin|audit_detail_max_items', int, 100, attr='_AUDIT_DETAIL_MAX_ITEMS',
        # How many names a single audit entry lists per outcome before it says "and N more".
        # The detail is stored as JSON in one row and painted whole when opened, and the
        # number of tables is NOT bounded by anything — modules create their own at runtime
        # (lib/db/module_tables.py). Without a ceiling, one maintenance run on a large
        # install writes hundreds of names into one entry, and on a broken database hundreds
        # of error strings with them: that stops being a record and starts being an obstacle
        # to whoever is reading the log, exactly when reading it matters most.
        # 0 = NO CEILING, like every other ceiling here: every name is listed. It meant the
        # opposite until somebody zeroed all four caps in this panel meaning "keep
        # everything" and silently lost two logs and these names.
        min=0, max=10000, env='SS_AUDIT_DETAIL_MAX_ITEMS'),
    Cfg('web_admin|backup_dir', str, '', attr='_BACKUP_DIR',
        # Where copies are written. Empty means `<var_dir>/backups`, which is the sane
        # default and the wrong place to leave it: a copy on the same disk as the data it
        # copies survives a mistake and nothing else. Point it at a mount that is not this
        # machine and the same button starts producing a backup worth the name.
        # Read at every call rather than cached: changing it must not need a restart, and an
        # operator who moves it mid-day would otherwise write the next copy to the old path
        # and not find it there.
        env='SS_BACKUP_DIR', card='backup'),
    Cfg('web_admin|backup_every_hours', int, 0, attr='_BACKUP_EVERY_HOURS',
        # 0 = off. An INTERVAL and not a time of day, because a panel that was down at 03:00
        # must still take its daily copy when it comes back at 09:00: "how long since the last
        # one" stays true until one is taken, where "is it 03:00 now" is false 1439 minutes out
        # of 1440 and misses the window entirely if the process was not up for it. 24 = daily,
        # 168 = weekly. The cost is drift — a copy lands a few minutes later each time — which
        # is the side to be wrong on.
        min=0, max=8760, env='SS_BACKUP_EVERY_HOURS', card='backup'),
    Cfg('web_admin|backup_keep', int, 7, attr='_BACKUP_KEEP',
        # Retention is not decoration: without it the folder grows until the disk is full, and
        # a full disk stops the panel — a backup feature that takes the install down is worse
        # than none. 0 keeps everything, for an operator who prunes elsewhere. Only automatic
        # copies are counted; one somebody took by hand before an upgrade is never pruned.
        min=0, max=365, env='SS_BACKUP_KEEP', card='backup'),
    Cfg('web_admin|backup_auto_secrets', bool, True, attr='_BACKUP_AUTO_SECRETS',
        # Defaults to ON, unlike a hand-made copy where somebody is standing there to decide:
        # an unattended copy that silently holds no credentials is discovered at restore time,
        # which is the worst moment to discover anything.
        env='SS_BACKUP_AUTO_SECRETS', card='backup'),
    Cfg('web_admin|update_check_url', str,
        'https://api.github.com/repos/vsc55/ServiceSentry/releases/latest',
        no_rule=True, card='diagnostics',
        # Where Diagnostics asks whether a newer release exists. The address lives HERE and not
        # as a constant in `lib/core/diagnostics/update.py` — that module reads it from this
        # registry — so the config screen can show it greyed behind an empty box like every
        # other option, "restore default" has something to restore to, and the one address this
        # panel is willing to contact is visible to whoever is deciding whether it may reach
        # the internet at all. Left as a constant, the box was blank with nothing behind it.
        # A field and not a fixed value so a fork, or an install that may only reach an
        # internal mirror, points it elsewhere without a code change.
        # The check NEVER runs on its own: no poll, nothing at boot, nothing while a page
        # paints. It happens when somebody presses the button, which is why there is no
        # separate on/off switch — a URL nobody clicks is already off.
        env='SS_UPDATE_CHECK_URL'),
    Cfg('web_admin|pw_min_len', int, 8, attr='_PW_MIN_LEN',
        min=1, max=128, admin_only=True, card='pw_policy'),
    Cfg('web_admin|pw_max_len', int, 128, attr='_PW_MAX_LEN',
        min=8, max=256, admin_only=True, card='pw_policy'),
    Cfg('web_admin|pw_require_upper', bool, True, attr='_PW_REQUIRE_UPPER',
        admin_only=True, card='pw_policy'),
    Cfg('web_admin|pw_require_digit', bool, True, attr='_PW_REQUIRE_DIGIT',
        admin_only=True, card='pw_policy'),
    Cfg('web_admin|pw_require_symbol', bool, False, attr='_PW_REQUIRE_SYMBOL',
        admin_only=True, card='pw_policy'),
    Cfg('web_admin|public_status', bool, False, attr='_PUBLIC_STATUS',
        env='SS_PUBLIC_STATUS', admin_only=True),        # rendered by the 'pub_status' card
    Cfg('web_admin|public_status_detail', bool, False, attr='_PUBLIC_STATUS_DETAIL',
        env='SS_PUBLIC_STATUS_DETAIL', admin_only=True),
    Cfg('web_admin|status_refresh_secs', int, 60, attr='_STATUS_REFRESH_SECS',
        min=10, max=3600, env='SS_STATUS_REFRESH_SECS'),
    Cfg('web_admin|status_lang', str, '', attr='_STATUS_LANG',
        env='SS_STATUS_LANG'),
    # ── External Access card (order = host → port → public URL → proxy → HTTPS) ──
    Cfg('web_admin|host', str, '0.0.0.0', no_rule=True, card='proxy'),  # bind addr
    Cfg('web_admin|port', int, 8080, attr='_PORT',
        min=1, max=65535, env='SS_PORT', card='proxy'),
    Cfg('web_admin|public_url', str, '', attr='_PUBLIC_URL',
        env='SS_PUBLIC_URL', admin_only=True, card='proxy'),
    Cfg('web_admin|proxy_count', int, 0, attr='_PROXY_COUNT',
        min=0, max=10, env='SS_PROXY_COUNT', admin_only=True, card='proxy'),
    Cfg('web_admin|force_https', bool, False, attr='_FORCE_HTTPS',
        env='SS_FORCE_HTTPS', admin_only=True, card='proxy'),
    # Framing allowlist: origins permitted to embed the panel in an iframe (CSP
    # frame-ancestors). Empty = framing blocked (default). embed_in_teams adds the
    # Microsoft Teams/Outlook/M365 origins so the Teams personal tab can render.
    Cfg('web_admin|frame_ancestors', str, '', admin_only=True, no_rule=True, card='proxy'),
    Cfg('web_admin|embed_in_teams', bool, False, attr='_EMBED_IN_TEAMS',
        admin_only=True, card='proxy'),
    Cfg('web_admin|force_fqdn', bool, False, attr='_FORCE_FQDN',
        env='SS_FORCE_FQDN', admin_only=True, card='proxy'),
    Cfg('web_admin|secure_cookies', bool, False, attr='_SECURE_COOKIES',
        env='SS_SECURE_COOKIES', admin_only=True, no_rule=True, card='proxy'),
    # How many records a table paginates by. `table_rows_options` is the list its per-table
    # chooser offers and `table_rows_default` is the one it opens on — the second is expressed
    # in the vocabulary of the first, which is why they are named as a pair.
    # They were `table_rows_default` / `table_rows_options`: "page size" reads as something about the
    # size of the page, and says nothing about tables or records.
    # The list lives HERE, in the registry, so its default has one home and reaches the panel
    # through CONFIG_REGISTRY_DEFAULTS like every other default. It used to be a literal in
    # three files. `no_rule`: it is a list, so the int/bool rule dicts have nothing to say
    # about it. `0` means "all".
    Cfg('web_admin|table_rows_default', int, 25, attr='_TABLE_ROWS_DEFAULT',
        min=0, max=200),                                 # rendered by the 'tables' card
    Cfg('web_admin|table_rows_options', list, [15, 25, 50, 100, 200, 0], no_rule=True),
    Cfg('web_admin|config_poll_secs', int, 30, attr='_CONFIG_POLL_SECS',
        min=10, max=300),
    Cfg('web_admin|config_update_banner_secs', int, 8, attr='_CONFIG_UPDATE_BANNER_SECS',
        min=0, max=60),
    Cfg('web_admin|lockout_max_attempts', int, 5, attr='_LOCKOUT_MAX_ATTEMPTS',
        min=0, max=100, admin_only=True, card='login_security'),
    Cfg('web_admin|lockout_duration_secs', int, 900, attr='_LOCKOUT_DURATION_SECS',
        min=60, max=86400, admin_only=True, card='login_security'),
    Cfg('web_admin|session_check_secs', int, 20, attr='_SESSION_CHECK_SECS',
        min=5, max=300),
    # Client-side connectivity heartbeat: how often the browser pings the server to detect a
    # lost connection (and raise the "No connection" overlay). Shown in Interface → Connection.
    Cfg('web_admin|conn_check_secs', int, 6, attr='_CONN_CHECK_SECS',
        min=2, max=120, card='connection'),
    Cfg('web_admin|session_idle_minutes', int, 720, attr='_SESSION_IDLE_MINUTES',
        min=0, max=43200, admin_only=True, card='login_security'),  # idle timeout (0=off)
    Cfg('web_admin|session_log_enabled', bool, True, attr='_SESSION_LOG_ENABLED',
        # The same pair as the API-token ring, and for the same reason: whether to record is
        # a switch, how much to keep is a number, and 0 in that number means "no ceiling".
        admin_only=True, env='SS_SESSION_LOG_ENABLED', card='login_security'),
    Cfg('web_admin|session_log_max', int, 200, attr='_SESSION_LOG_MAX',
        # How many recent requests are kept PER SESSION, so "what has this sign-in been doing"
        # has an answer at all. The twin of `api_token_log_max`, and a ring for the same
        # reason — but NOT of everything: only the acts (POST/PUT/PATCH/DELETE) and the
        # refusals (>= 400) are written, because the panel polls itself and a ring of
        # heartbeats answers nothing. 0 = no ceiling; the switch above is how it stops.
        min=0, max=10000, env='SS_SESSION_LOG_MAX', admin_only=True, card='login_security'),
    # Brute-force throttles (per client IP). 0 = disabled.
    Cfg('web_admin|login_ratelimit_max', int, 15, attr='_LOGIN_RATELIMIT_MAX',
        min=0, max=1000, admin_only=True, card='login_security'),
    Cfg('web_admin|login_ratelimit_window_secs', int, 300, attr='_LOGIN_RATELIMIT_WINDOW_SECS',
        min=10, max=3600, admin_only=True, card='login_security'),
    # Who has to carry a second factor. Three values and not a switch, because "everybody"
    # and "the accounts that can change everything" are different decisions with different
    # costs: `admins` is the one most installs actually want, and offering only on/off means
    # the answer to "protect the dangerous accounts" is "make forty people enrol".
    #
    # `off` is the default and stays it: turning this on is a policy an operator chooses, not
    # something an upgrade does to an installation overnight. Somebody who must have one and
    # does not is not locked out — they enrol on the way in, which is what makes it safe to
    # switch on with everybody already signed up to nothing.
    #
    # Read at the point of use rather than mirrored on an attribute: it is consulted once per
    # sign-in, and an attribute is a second copy that a save has to remember to refresh.
    Cfg('web_admin|mfa_required', str, 'off', env='SS_MFA_REQUIRED',
        admin_only=True, no_rule=True, card='login_security'),
    # How long a sign-in that owes a second factor stays parked between the password and the
    # code — long enough to unlock a phone and find the app, short enough that a password
    # typed on a shared machine does not stay half-usable for the afternoon.
    #
    # A setting because the right answer depends on the room: a shared terminal in a hospital
    # wants sixty seconds, and somebody whose key lives in a drawer wants more than five
    # minutes. Nothing outside the panel ever sees this number, so unlike the TOTP parameters
    # (period, digits, algorithm — fixed on purpose, see lib/core/mfa/totp.py) changing it
    # cannot produce an install where enrolment silently fails on somebody's phone.
    #
    # The floor is 30 seconds, which is one TOTP step: below that the code on screen can
    # expire before the hold does, and the failure looks like a wrong code.
    Cfg('web_admin|mfa_hold_secs', int, 300, env='SS_MFA_HOLD_SECS',
        min=30, max=3600, admin_only=True, card='login_security'),
    # The domain security keys are registered against. Normally derived from `public_url` and
    # left empty here — this is the escape for a deployment where the two differ: several
    # names in front of one panel, or a public URL on a subdomain of the domain the keys
    # should be scoped to.
    #
    # It is worth being blunt about the cost of changing it: a credential is scoped to this by
    # the BROWSER and cannot be moved. Change it and every key already registered stops
    # working, with nothing on screen to say why — which is also why it is not derived from
    # the request, where a reverse proxy gets to decide it per call.
    Cfg('web_admin|webauthn_rp_id', str, '', env='SS_WEBAUTHN_RP_ID',
        admin_only=True, no_rule=True, card='login_security'),
    # Internal fail2ban — progressive per-IP jail shared by every exposed service
    # (web + syslog). Offenses accumulate per IP; crossing a threshold jails the IP
    # for an escalating term. Two tracks: 'auth' (anonymous/login/CSRF/SCIM/401/anon-403)
    # and 'authz' (an authenticated session hitting forbidden sections — higher, more
    # tolerant threshold). 0 in a threshold disables that track.
    Cfg('web_admin|ipban_enabled', bool, True, attr='_IPBAN_ENABLED',
        env='SS_IPBAN_ENABLED', admin_only=True, no_rule=True, card='ipban'),
    Cfg('web_admin|ipban_auth_threshold', int, 10, attr='_IPBAN_AUTH_THRESHOLD',
        min=0, max=1000, admin_only=True, card='ipban'),
    Cfg('web_admin|ipban_auth_window_secs', int, 600, attr='_IPBAN_AUTH_WINDOW_SECS',
        min=10, max=86400, admin_only=True, card='ipban'),
    Cfg('web_admin|ipban_authz_threshold', int, 30, attr='_IPBAN_AUTHZ_THRESHOLD',
        min=0, max=1000, admin_only=True, card='ipban'),
    Cfg('web_admin|ipban_authz_window_secs', int, 600, attr='_IPBAN_AUTHZ_WINDOW_SECS',
        min=10, max=86400, admin_only=True, card='ipban'),
    Cfg('web_admin|ipban_durations', str, '900,3600,21600,86400', attr='_IPBAN_DURATIONS',
        admin_only=True, no_rule=True, card='ipban'),   # escalating ban terms (s), CSV
    Cfg('web_admin|ipban_permanent_after', int, 4, attr='_IPBAN_PERMANENT_AFTER',
        min=0, max=100, admin_only=True, card='ipban'),  # ban level past which = permanent (0=never)
    # (The per-service block action lives in the fail2ban service registry — see
    #  lib/services/ipban/exposed.py — persisted in the ip_service_action table,
    #  not as a single global config field.)
    # Env/programmatic never-ban CSV (also an escape hatch: SS_IPBAN_WHITELIST=<ip>
    # lets a locked-out admin whitelist their address and get back in). The UI-managed
    # whitelist with descriptions lives in its own store and is merged on top; this
    # field has no config-UI card.
    Cfg('web_admin|ipban_whitelist', str, '', attr='_IPBAN_WHITELIST',
        env='SS_IPBAN_WHITELIST', admin_only=True, no_rule=True),
    Cfg('web_admin|scim_ratelimit_max', int, 20, attr='_SCIM_RATELIMIT_MAX',
        min=0, max=1000, admin_only=True, card='scim'),
    Cfg('web_admin|scim_ratelimit_window_secs', int, 300, attr='_SCIM_RATELIMIT_WINDOW_SECS',
        min=10, max=3600, admin_only=True, card='scim'),
    Cfg('web_admin|scim_min_token_len', int, 16, attr='_SCIM_MIN_TOKEN_LEN',
        min=8, max=256, admin_only=True, card='scim'),   # bearer token entropy floor
    Cfg('web_admin|scim_max_members', int, 2000, attr='_SCIM_MAX_MEMBERS',
        min=1, max=100000, admin_only=True, card='scim'),  # members per group write
    Cfg('web_admin|session_revoke_redirect_secs', int, 3,
        attr='_SESSION_REVOKE_REDIRECT_SECS', min=0, max=30),
    Cfg('web_admin|access_poll_secs', int, 30, attr='_ACCESS_POLL_SECS',
        min=5, max=300),
    # Roles, users and groups are held in memory; this is how long this process may keep
    # serving them without asking the database whether another writer changed them.
    # 0 = ask on every request (immediate, one tiny aggregate query per table).
    Cfg('web_admin|cache_reload_secs', int, 5, attr='_CACHE_RELOAD_SECS',
        min=0, max=300, admin_only=True),
    # When the backend restarts (startup_id changes), the page-reload banner is
    # shown. With force-reload on, the banner also counts down and auto-reloads.
    Cfg('web_admin|force_reload_on_update', bool, False,
        attr='_FORCE_RELOAD_ON_UPDATE'),
    Cfg('web_admin|force_reload_secs', int, 10, attr='_FORCE_RELOAD_SECS',
        min=1, max=300),
    # web_admin first-run credentials (read in main.py) — bootstrap only, NOT editable
    # config (the admin account is managed in the Users UI), so no config-UI card.
    Cfg('web_admin|username', str, 'admin', no_rule=True, no_seed=True),
    Cfg('web_admin|password', str, 'admin', no_rule=True, no_seed=True),

    # ══ telegram (env-overridable; not mirrored on the instance) ═════════════
    Cfg('telegram|token', str, '', env='SS_TELEGRAM_TOKEN', no_rule=True),
    Cfg('telegram|chat_id', str, '', env='SS_TELEGRAM_CHAT_ID', no_rule=True),
    Cfg('telegram|group_messages', bool, False, env='SS_TELEGRAM_GROUP_MESSAGES',
        no_rule=True),

    # ══ monitoring (the service monitor) ═════════════════════════════════════
    # Like syslog: a simple on/off ``enabled`` flag; whether this process hosts it
    # (embedded) or a standalone ``--monitor`` process / worker container owns it
    # is decided by the SS_MONITORING_EMBEDDED env, not a config field.
    # ``enabled`` is the master switch (off ⇒ the service is off, not even
    # startable); ``autostart`` decides whether the EMBEDDED monitor launches
    # automatically when the web admin process boots — a standalone ``--monitor``
    # process ignores it (it always runs when enabled).  enabled=on + autostart=off
    # ⇒ boots stopped but startable from the Services tab.
    Cfg('monitoring|enabled', bool, True, env='SS_MONITORING_ENABLED', card='monitoring'),
    Cfg('monitoring|autostart', bool, True, env='SS_MONITORING_AUTOSTART', card='monitoring'),
    Cfg('monitoring|timer_check', int, 300, min=10, max=86400, env='SS_CHECK_INTERVAL',
        card='monitoring'),
    # ── Platform self-monitoring (lib/core/health) — NOT the monitoring service ──
    # Service-health notifications: alert when a background service (monitor/syslog/events
    # worker) stops beating (crashed/unreachable) and when it recovers.  Off by default.
    Cfg('services|notify_down', bool, False, admin_only=True, card='health'),
    Cfg('services|down_after_secs', int, 60, min=15, max=86400, admin_only=True,
        card='health'),
    Cfg('services|health_poll_secs', int, 30, min=5, max=3600, admin_only=True,
        card='health'),
    # Certificate-expiry notifications: a periodic scan of every ssl_cert check emits
    # ``cert_expiring`` when a cert is within warn_days of expiry (once per severity).
    Cfg('certs|notify_expiry', bool, False, admin_only=True, card='health'),
    Cfg('certs|warn_days', int, 21, min=1, max=3650, admin_only=True, card='health'),
    Cfg('certs|scan_every_secs', int, 86400, min=3600, max=604800, admin_only=True,
        card='health'),

    # ══ modules: global defaults inherited by every watchful module ══════════
    # Last link of the item → module → global resolution chain.  'threads' also
    # sets how many modules the monitor checks in parallel.
    Cfg('modules|threads', int, 5,  min=1, max=100, card='modules'),
    Cfg('modules|timeout', int, 15, min=1, max=600, card='modules'),
    # Role assigned to newly-created users (a role UID). Empty means "unset" and
    # resolves to the built-in 'none' role — the consumers own that fallback
    # (web_admin uses BUILTIN_ROLE_UIDS['none']) so the canonical UID is never
    # duplicated here. Also used when the configured role was deleted.
    # Both default-role options share one "Default roles" card in the Auth tab
    # (role assignment is an authorization concern, not a General one).
    Cfg('users|default_role', str, '', no_rule=True, admin_only=True, card='default_roles'),
    # Role pre-selected for newly-created groups (same scheme/fallback as users).
    Cfg('groups|default_role', str, '', no_rule=True, admin_only=True, card='default_roles'),

    # ══ global ═══════════════════════════════════════════════════════════════
    # Log verbosity: 'off' disables debug output; otherwise a DebugLevel name
    # ('debug'/'info'/'warning'/'error') used as the minimum level shown.
    Cfg('global|log_level', str, 'off', no_rule=True, card='global'),

    # ══ database (port is driver-specific → no single default) ═══════════════
    # Bootstrap section: read before the DB connector exists, so the env vars are
    # overlaid at connector-build time (see lib.config.bootstrap_database_cfg),
    # not through the usual web-layer override path.
    Cfg('database|driver', str, 'sqlite', env='SS_DB_DRIVER', no_rule=True),
    Cfg('database|path', str, '', env='SS_DB_PATH', no_rule=True),  # '' → default_sqlite_path
    Cfg('database|host', str, 'localhost', env='SS_DB_HOST', no_rule=True),
    Cfg('database|port', int, None, env='SS_DB_PORT', no_rule=True, nullable=True),  # 3306 MySQL / 5432 PostgreSQL
    Cfg('database|name', str, 'servicesentry', env='SS_DB_NAME', no_rule=True),
    Cfg('database|user', str, '', env='SS_DB_USER', no_rule=True),
    Cfg('database|password', str, '', env='SS_DB_PASSWORD', no_rule=True),

    # ══ LDAP ═════════════════════════════════════════════════════════════════
    Cfg('ldap|enabled', bool, False),
    Cfg('ldap|use_ssl', bool, False),
    Cfg('ldap|ssl_verify', bool, True),   # validate the LDAPS server certificate (MITM guard)
    Cfg('ldap|fallback_to_local', bool, True),
    # Does this directory already ask for a second factor of its own? When it does, asking
    # again here is friction with no gain — the account proved two things before the panel
    # ever saw it. Default False, which is the conservative direction: the panel keeps asking
    # for what it can verify itself until an operator says the IdP is doing it.
    #
    # It skips BOTH halves for sign-ins through this provider — the code step and the forced
    # enrolment — because both exist to establish the same fact, and the IdP has established
    # it. A factor the account enrolled here stays enrolled and is still asked for on a LOCAL
    # sign-in; trusting a provider is a statement about that door, not about the account.
    Cfg('ldap|mfa_trusted', bool, False, admin_only=True, no_rule=True),
    Cfg('ldap|allow_email_login', bool, False),
    Cfg('ldap|port', int, 389, min=1, max=65535),
    Cfg('ldap|timeout', int, 5, min=1, max=60),
    Cfg('ldap|group_role_map', dict, '{}'),
    Cfg('ldap|group_display_names', dict),
    # LDAP string fields (defaults read at point of use)
    Cfg('ldap|server', str, '', no_rule=True),
    Cfg('ldap|bind_dn', str, '', no_rule=True),
    Cfg('ldap|bind_password', str, '', no_rule=True),
    Cfg('ldap|base_dn', str, '', no_rule=True),
    Cfg('ldap|user_filter', str, '(sAMAccountName={username})', no_rule=True),
    Cfg('ldap|email_attr', str, 'mail', no_rule=True),
    Cfg('ldap|name_attr', str, 'displayName', no_rule=True),
    Cfg('ldap|username_attr', str, '', no_rule=True),
    Cfg('ldap|group_attr', str, 'memberOf', no_rule=True),
    Cfg('ldap|default_role', str, '', no_rule=True),

    # ══ OIDC ═════════════════════════════════════════════════════════════════
    Cfg('oidc|enabled', bool, False),
    Cfg('oidc|auto_create_users', bool, True),
    Cfg('oidc|mfa_trusted', bool, False, admin_only=True, no_rule=True),
    Cfg('oidc|group_role_map', dict, '{}'),
    Cfg('oidc|group_display_names', dict),
    Cfg('oidc|provider_url', str, '', no_rule=True),
    Cfg('oidc|client_id', str, '', no_rule=True),
    Cfg('oidc|client_secret', str, '', no_rule=True),
    Cfg('oidc|scopes', str, 'openid email profile', no_rule=True),
    Cfg('oidc|username_claim', str, 'preferred_username', no_rule=True),
    Cfg('oidc|email_claim', str, 'email', no_rule=True),
    Cfg('oidc|name_claim', str, 'name', no_rule=True),
    Cfg('oidc|groups_claim', str, 'groups', no_rule=True),
    Cfg('oidc|default_role', str, '', no_rule=True),
    # Client-secret lifecycle. ``secret_expires_at`` is written by the app (the expiry Entra
    # actually granted when the secret was minted), not typed by the admin. The scanner in
    # lib.core.health.secret_scan warns at ``secret_warn_days`` and — only if
    # ``secret_auto_rotate`` is on — mints a replacement at ``secret_rotate_days``.
    Cfg('oidc|secret_expires_at', str, '', no_rule=True),
    Cfg('oidc|secret_notify_expiry', bool, False, admin_only=True),
    Cfg('oidc|secret_warn_days', int, 30, min=1, max=3650, admin_only=True),
    Cfg('oidc|secret_auto_rotate', bool, False, admin_only=True),
    Cfg('oidc|secret_rotate_days', int, 15, min=1, max=3650, admin_only=True),

    # ══ SAML2 ════════════════════════════════════════════════════════════════
    Cfg('saml2|enabled', bool, False),
    Cfg('saml2|auto_create_users', bool, True),
    Cfg('saml2|mfa_trusted', bool, False, admin_only=True, no_rule=True),
    Cfg('saml2|group_role_map', dict, '{}'),
    Cfg('saml2|group_display_names', dict),
    Cfg('saml2|sp_entity_id', str, '', no_rule=True),
    Cfg('saml2|sp_acs_url', str, '', no_rule=True),
    Cfg('saml2|sp_app_id', str, '', no_rule=True),      # Entra app (client) id, for the "open in Entra ID" link
    Cfg('saml2|sp_object_id', str, '', no_rule=True),   # Entra servicePrincipal objectId, for the SSO-blade deep link
    Cfg('saml2|graph_secret', str, '', no_rule=True),   # client secret for the group→role mapping (Graph reads)
    Cfg('saml2|sp_cert', str, '', no_rule=True),
    Cfg('saml2|sp_key', str, '', no_rule=True),
    Cfg('saml2|idp_entity_id', str, '', no_rule=True),
    Cfg('saml2|idp_sso_url', str, '', no_rule=True),
    Cfg('saml2|idp_cert', str, '', no_rule=True),
    Cfg('saml2|username_attr', str, '', no_rule=True),
    Cfg('saml2|email_attr', str, 'email', no_rule=True),
    Cfg('saml2|name_attr', str, 'displayName', no_rule=True),
    Cfg('saml2|groups_attr', str, 'groups', no_rule=True),
    Cfg('saml2|default_role', str, '', no_rule=True),

    # ══ SCIM 2.0 (aprovisionamiento proactivo desde el IdP) ═══════════════════
    Cfg('scim|enabled', bool, False),
    Cfg('scim|token', str, '', no_rule=True),          # bearer token que envía el IdP (cifrado)
    Cfg('scim|default_role', str, '', no_rule=True),   # rol para usuarios aprovisionados (vacío = none)
    Cfg('scim|auto_disable', bool, True),              # active=false del IdP → deshabilita el usuario
    Cfg('scim|sp_app_id', str, '', no_rule=True),      # appId de la app SCIM en Entra (deep link)
    Cfg('scim|sp_object_id', str, '', no_rule=True),   # objectId del SP (deep link a Provisioning)

    # ══ Email ════════════════════════════════════════════════════════════════
    Cfg('email|enabled', bool, False),
    Cfg('email|smtp_use_tls', bool, True),
    Cfg('email|smtp_use_ssl', bool, False),
    Cfg('email|smtp_port', int, 587, min=1, max=65535),
    # Email string fields (defaults read at point of use)
    Cfg('email|provider', str, 'smtp', no_rule=True),
    Cfg('email|recipients', str, '', no_rule=True),
    Cfg('email|subject_prefix', str, '', no_rule=True),  # alerts use '[ServiceSentry]'
    Cfg('email|smtp_host', str, '', no_rule=True),
    Cfg('email|smtp_username', str, '', no_rule=True),
    Cfg('email|smtp_password', str, '', no_rule=True),
    Cfg('email|from_email', str, '', no_rule=True),
    Cfg('email|from_name', str, APP_NAME, no_rule=True),
    # Global language for ALL notification content (Telegram/Email/Teams/webhook), resolved by
    # lib.core.notify.formatting.notify_lang.
    Cfg('notifications|lang', str, '', no_rule=True),
    Cfg('email|ms365_tenant_id', str, '', no_rule=True),
    Cfg('email|ms365_client_id', str, '', no_rule=True),
    Cfg('email|ms365_client_secret', str, '', no_rule=True),
    Cfg('email|gmail_client_id', str, '', no_rule=True),
    Cfg('email|gmail_client_secret', str, '', no_rule=True),
    Cfg('email|gmail_refresh_token', str, '', no_rule=True),

    # ══ Notification routing matrix ═════════════════════════════════════════
    # NOT declared here — the matrix keys ``notifications|{channel}_on_{kind}`` are
    # fully DYNAMIC: the kinds come from the notify-event registry (each domain's
    # ``notify_events.py`` — monitoring/syslog/ipban/auth/health/… — discovered at
    # runtime) × the registered channels.  A cell is stored in the DB ``config`` table
    # only when the admin ticks it (default off; dispatch reads ``notif.get(k, False)``).
    # Declaring them here would duplicate the registry — the single source of truth.

    # ══ Syslog receiver ═════════════════════════════════════════════════════
    # Built-in syslog server: receive RFC 3164/5424 events from external hosts
    # over UDP/TCP(+TLS), store them (lib/services/syslog/store) and optionally alert.
    Cfg('syslog|enabled',         bool, True, admin_only=True, card='syslog_conn'),
    # autostart: launch the EMBEDDED listener at web-admin boot (a standalone
    # ``--syslog`` process ignores it).  enabled=on + autostart=off ⇒ boots stopped
    # but startable from the Services tab.
    Cfg('syslog|autostart',       bool, True, admin_only=True, env='SS_SYSLOG_AUTOSTART',
        card='syslog_conn'),
    Cfg('syslog|bind_host',       str, '0.0.0.0, ::', admin_only=True, card='syslog_conn'),
    Cfg('syslog|udp_port',        int, 514, min=0, max=65535, admin_only=True, nullable=True,
        card='syslog_conn'),
    Cfg('syslog|tcp_port',        int, 514, min=0, max=65535, admin_only=True, nullable=True,
        card='syslog_conn'),
    # Standard syslog-over-TLS port. Only actually bound when a cert + key are set
    # (the listener stays off, silently, without them — see server.start()).
    Cfg('syslog|tls_port',        int, 6514, min=0, max=65535, admin_only=True, nullable=True,
        card='syslog_conn'),
    Cfg('syslog|tls_cert',        str, '', admin_only=True, card='syslog_security'),
    Cfg('syslog|tls_key',         str, '', admin_only=True, card='syslog_security'),
    Cfg('syslog|allowed_sources', str, '', admin_only=True, card='syslog_security'),  # IPs/CIDRs
    Cfg('syslog|retention_days',  int, 30, min=0, max=3650, admin_only=True, nullable=True,
        card='syslog_retention'),
    # The ceiling is a typo guard, not a product limit: 0 already means "no cap", so anyone
    # wanting unlimited has a way to say it, and a stray digit on 500000 would otherwise ask
    # the pruner to keep five billion rows. A hundred million is roughly 20 GB of syslog —
    # far past any real retention and still short of "the disk fills before you notice".
    Cfg('syslog|max_messages',    int, 500000, min=0, max=100000000, admin_only=True,
        nullable=True, card='syslog_retention'),
    # Syslog→notification routing is handled by the Event-rules manager (Events
    # tab), not a built-in alert here — one place owns event→notification.

    # ── Events (event-rules manager) ──────────────────────────────────────────
    # Global default cooldown (s) inherited by any event rule that leaves its own
    # Cooldown field blank.  0 = notify on every match.
    Cfg('events|cooldown',        int, 0, min=0, max=86400),
    # Decoupled event worker (rule evaluation). Uniform with monitoring/syslog:
    # ``enabled`` is the on/off master switch; whether it runs HERE (embedded) or a
    # dedicated ``--events`` container owns it is the SS_EVENTS_EMBEDDED env, not a
    # config field.  poll_secs: how often the worker drains new syslog/audit rows.
    # (Legacy ``events|mode`` — embedded/external/off — is read for backward compat
    # in _EventsMixin._events_enabled: off ⇒ disabled, else enabled.)
    Cfg('events|enabled',         bool, True),
    # autostart: launch the EMBEDDED worker at web-admin boot (a standalone
    # ``--events`` process ignores it).  enabled + autostart=off ⇒ boots stopped but
    # startable from the Services tab.
    Cfg('events|autostart',       bool, True, env='SS_EVENTS_AUTOSTART'),
    Cfg('events|poll_secs',       int, 2, min=1, max=3600),

    # ── Syslog dedicated database (optional) ──────────────────────────────────
    # When enabled, syslog messages are stored in their own database (isolating
    # high-volume ingestion from the system DB).  Otherwise they share it.
    # Mirrors the ``database`` section's fields; the password is encrypted at rest.
    Cfg('syslog_db|enabled',  bool, False, admin_only=True, env='SS_SYSLOG_DB_ENABLED'),
    Cfg('syslog_db|driver',   str, 'sqlite', admin_only=True, no_rule=True, env='SS_SYSLOG_DB_DRIVER'),
    Cfg('syslog_db|path',     str, '', admin_only=True, no_rule=True, env='SS_SYSLOG_DB_PATH'),
    Cfg('syslog_db|host',     str, 'localhost', admin_only=True, no_rule=True, env='SS_SYSLOG_DB_HOST'),
    Cfg('syslog_db|port',     int, None, admin_only=True, no_rule=True, env='SS_SYSLOG_DB_PORT', nullable=True),
    Cfg('syslog_db|name',     str, 'servicesentry_syslog', admin_only=True, no_rule=True, env='SS_SYSLOG_DB_NAME'),
    Cfg('syslog_db|user',     str, '', admin_only=True, no_rule=True, env='SS_SYSLOG_DB_USER'),
    Cfg('syslog_db|password', str, '', admin_only=True, no_rule=True, env='SS_SYSLOG_DB_PASSWORD'),

    # ══ Webhooks (editor schema only) ═══════════════════════════════════════
    # These are the per-webhook FORM field defaults (type/default for the editor
    # via frontend_schema).  Webhooks are stored as records in their own table
    # (lib/core/notify/webhook/store.py), NOT as singleton config — so they are no_seed:
    # never materialised as ``webhooks|*`` rows in the config table.
    Cfg('webhooks|enabled', bool, False, no_rule=True, no_seed=True),
    Cfg('webhooks|url', str, '', no_rule=True, no_seed=True),
    Cfg('webhooks|method', str, 'POST', no_rule=True, no_seed=True),
    Cfg('webhooks|timeout', int, 10, no_rule=True, no_seed=True),
    Cfg('webhooks|secret', str, '', no_rule=True, no_seed=True),
    Cfg('webhooks|secret_header', str, 'X-Hub-Signature-256', no_rule=True, no_seed=True),
    Cfg('webhooks|headers', str, '', no_rule=True, no_seed=True),
    # body_template default lives in webhook_notify._DEFAULT_BODY_TPL (a large
    # JSON template); documented here but not duplicated.
    Cfg('webhooks|body_template', str, None, no_rule=True, no_seed=True),

    # ══ Microsoft Teams (msteams) ═══════════════════════════════════════════
    # Teams is ONE logical channel with two destination kinds:
    #  (a) channels — Incoming Webhook URLs, stored as records in their own table
    #      (lib/core/notify/msteams/store.py); the ``msteams_channels|*`` entries
    #      below are editor form-field defaults only (no_seed, never materialised).
    #  (b) users — direct-to-user delivery via the ``msteams`` singleton section
    #      below (a real, seeded section): pick a delivery mechanism and recipients.
    Cfg('msteams_channels|enabled', bool, True, no_rule=True, no_seed=True),
    Cfg('msteams_channels|name', str, '', no_rule=True, no_seed=True),
    Cfg('msteams_channels|webhook_url', str, '', no_rule=True, no_seed=True),
    # User-mode (singleton section): send directly to users. delivery ∈
    # {'activity_feed' (Graph TeamsActivity.Send — outbound only), 'bot'
    # (Bot Framework proactive 1:1 chat — needs a public messaging endpoint)}.
    Cfg('msteams|user_enabled', bool, False, no_rule=True),
    Cfg('msteams|delivery', str, 'activity_feed', no_rule=True),   # 'activity_feed' | 'bot'
    Cfg('msteams|notify_panel_users', bool, False, no_rule=True),  # target panel users by their email/UPN
    Cfg('msteams|recipients', str, '', no_rule=True),              # extra UPN/email list (comma/semicolon)
    # Graph client-credentials app (activity_feed): needs the TeamsActivity.Send
    # application permission; the Entra wizard can register it.
    Cfg('msteams|tenant_id', str, '', no_rule=True),
    Cfg('msteams|client_id', str, '', no_rule=True),
    Cfg('msteams|client_secret', str, '', no_rule=True),
    # Bot Framework app (bot): the Azure Bot's Microsoft App (id + secret + tenant).
    Cfg('msteams|bot_app_id', str, '', no_rule=True),
    Cfg('msteams|bot_app_password', str, '', no_rule=True),
    Cfg('msteams|bot_tenant_id', str, '', no_rule=True),
)

CFG_BY_PATH: dict[str, Cfg] = {f.path: f for f in CONFIG_FIELDS}

# Config paths removed from the registry but possibly still stored from older
# versions.  They are stripped on read (so the UI never shows them) and the next
# save prunes their DB rows.  Add a path here when you delete a Cfg above.
OBSOLETE_CONFIG_PATHS: frozenset[str] = frozenset({
    'syslog|alert_enabled',        # built-in syslog alert → replaced by Event rules
    'syslog|alert_severity_max',
    'syslog|alert_regex',
})


# ── Default accessor ──────────────────────────────────────────────────────────

def cfg_default(path: str):
    """Canonical default value of a config field, from the registry.

    Single source of truth for every option's default.  Point-of-use reads
    across the app pass this as their fallback instead of hardcoding a literal.
    """
    return CFG_BY_PATH[path].default


def cfg_meta(path: str) -> dict:
    """UI metadata (``{type, default[, min, max]}``) for a config field, from the
    registry — for fields the config schema endpoint exposes outside the
    auto-derived web_admin set (e.g. the ``modules`` section).  Empty if unknown."""
    f = CFG_BY_PATH.get(path)
    if f is None:
        return {}
    if f.type is bool:
        return {'type': 'bool', 'default': f.default}
    if f.type is int:
        m = {'type': 'int', 'default': f.default, 'min': f.min, 'max': f.max}
        if f.nullable:
            m['nullable'] = True
        return m
    return {'type': 'str', 'default': f.default}


def cfg_get(section_data: dict, path: str, *, falsy: bool = False):
    """Read ``path``'s field from an already-loaded *section_data* dict, applying
    the registry default and coercing to the field's type.

    ``path`` is the full ``'section|field'`` registry key; the field name is read
    from *section_data* (which is that section's sub-dict).  Collapses the
    repeated ``int(cfg.get('x', cfg_default('sec|x')))`` / ``cfg.get('x') or
    cfg_default(...)`` idioms into one schema-aware call.

    falsy=False — fall back to the default only when the key is missing
                  (the ``cfg.get(k, default)`` semantic).
    falsy=True  — also fall back when present-but-empty/zero
                  (the ``cfg.get(k) or default`` semantic).

    int/bool/str fields are coerced to their type; dict/list values pass through.
    """
    spec = CFG_BY_PATH.get(path)
    field = path.split('|', 1)[1] if '|' in path else path
    raw = (section_data or {}).get(field)
    if raw is None or (falsy and not raw):
        raw = spec.default if spec else None
    if spec is None or raw is None:
        return raw
    if spec.type is int:
        return int(raw)
    if spec.type is bool:
        return bool(raw)
    if spec.type is str:
        return str(raw)
    return raw  # dict / list: as-is


def cfg_validate(path: str, value) -> tuple[bool, str | None]:
    """Validate a raw config value against the registry rule for *path*.

    Returns ``(ok, error)`` where *error* is ``None`` on success or a short kind
    the caller turns into a message: ``'type'`` (wrong type), ``'range'`` (int
    out of [min, max]) or ``'json'`` (not a JSON object). Fields the registry
    does not constrain (and unknown paths) pass through as valid.

    Shared by the config PUT route and the env-override path so the int-range /
    json-object checks live in one place next to the schema.
    """
    spec = CFG_BY_PATH.get(path)
    if spec is None:
        return True, None
    if spec.type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            return False, 'type'
        if spec.min is not None and value < spec.min:
            return False, 'range'
        if spec.max is not None and value > spec.max:
            return False, 'range'
        return True, None
    if spec.type is dict:
        if value is None or value == '':
            return True, None
        if isinstance(value, dict):
            return True, None
        if isinstance(value, str):
            try:
                parsed = _json.loads(value)
            except (ValueError, TypeError):
                return False, 'json'
            return (True, None) if isinstance(parsed, dict) else (False, 'json')
        return False, 'json'
    return True, None


def normalize_url(value) -> str:
    """Canonical "store form" of a base URL: trimmed, scheme-stripped, no
    trailing slash.  e.g. ``' https://Host/ '`` → ``'Host'``.

    Used for ``web_admin|public_url`` (stored without scheme; the scheme is
    re-applied at render time from ``force_https``).  Single home for what was
    duplicated across app.py / routes.config / monitor.
    """
    s = str(value or '').strip().rstrip('/')
    if '://' in s:
        s = s.split('://', 1)[1]
    return s


# ── Derived views (web_admin schema; consumed by routes.config and app) ───────

def int_rules() -> dict:
    """``{path: {min, max, attr[, flask_cfg]}}`` for every web_admin int field."""
    out: dict = {}
    for f in CONFIG_FIELDS:
        if f.type is int and not f.no_rule:
            rule = {'min': f.min, 'max': f.max, 'attr': f.attr}
            if f.flask_cfg:
                rule['flask_cfg'] = f.flask_cfg
            out[f.path] = rule
    return out


def bool_rules() -> dict:
    """``{path: attr}`` for every boolean rule field (``attr`` may be ``None``)."""
    return {f.path: f.attr for f in CONFIG_FIELDS
            if f.type is bool and not f.no_rule}


def json_dict_fields() -> set:
    """Set of paths whose value must parse as a JSON object."""
    return {f.path for f in CONFIG_FIELDS if f.type is dict and not f.no_rule}


def env_field_specs() -> dict:
    """``{ENV_VAR: (path, type)}`` for every env-overridable field."""
    return {f.env: (f.path, f.type) for f in CONFIG_FIELDS if f.env}


def admin_only_fields() -> set:
    """Set of web_admin field paths only admins may modify."""
    return {f.path for f in CONFIG_FIELDS if f.admin_only}


def registry_defaults() -> dict:
    """``{path: default}`` for every registry field eligible for UI seeding.

    The config UI pre-populates each section so its card renders before the
    option has ever been saved.  Those initial values come from here — the
    central registry — instead of being hardcoded in the template, so the
    frontend can never drift from the source of truth.  ``no_seed`` fields
    (webhooks/credentials, stored as records elsewhere) are excluded; a
    JSON-object field with no default seeds an empty object string.
    """
    out: dict = {}
    for f in CONFIG_FIELDS:
        if f.no_seed:
            continue
        default = f.default
        if f.type is dict and default is None:
            default = '{}'
        out[f.path] = default
    return out


def section_defaults(section: str) -> dict:
    """Registry defaults for one section as ``{field: default}``.

    Defaults are resolved lazily (never materialised in the DB), so a section
    read back from the effective config only contains the fields a user has
    actually saved.  Consumers that need a *complete* section (e.g. the syslog
    listener, which must see its ports even when only ``enabled`` was saved)
    merge these defaults underneath the saved values.
    """
    prefix = section + '|'
    return {p[len(prefix):]: d for p, d in registry_defaults().items()
            if p.startswith(prefix)}


def frontend_schema() -> dict:
    """Per-field metadata for the config UI, built from the registry.

    ``{path: {type, default[, min, max]}}`` for every instance-backed web_admin
    field (``attr`` set).  The config route merges UI-only extras on top (option
    lists, numeric-string flags, etc.).  Single source so the frontend's
    "Restore default" values come from the registry, not hardcoded literals.
    """
    out: dict = {}
    for f in CONFIG_FIELDS:
        if f.attr is None:
            continue
        if f.type is bool:
            out[f.path] = {'type': 'bool', 'default': f.default}
        elif f.type is int:
            out[f.path] = {'min': f.min, 'max': f.max, 'default': f.default}
    return out
