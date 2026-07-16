# Changelog

All notable changes to **ServiceSentry** are documented in this file.

## [Unreleased]

### Added
- **Web admin panel** (Flask + Jinja2 + Bootstrap 5) with card views, an advanced configuration
  panel, navigation reorg and a generic table CSS.
- **Host-centric model**: a host registry with per-protocol profiles (SSH/SNMP/DB/HTTP…),
  host-aware execution (local/SSH) and reusable credentials.
- **Watchful modules**, schema-driven and core-agnostic (ping, web, dns, datastore, raid,
  ram_swap, filesystemusage, process, service_status, temperature, snmp, ssl_cert, keepalived
  VIP, Microsoft 365, proxmox…).
- **Notifications**, multi-channel and grouped per cycle (Telegram / Email / Webhook / Microsoft
  Teams) with a central dispatcher; multiple webhooks.
- **Microsoft Teams** notification channel with two destination kinds under one routing column:
  **channels** (multiple Incoming Webhook URLs, own store + CRUD, delivered as Adaptive/Message
  cards; the URL is encrypted at rest) and **direct-to-user** delivery with a selectable
  mechanism — *activity feed* (Graph `TeamsActivity.Send`, provisioned by the same Entra
  "Register in Azure" wizard) or *bot 1:1 chat* (Bot Framework proactive messaging via a public
  `/api/teams/messages` endpoint — optional, gated on PyJWT for Bot Framework JWT validation, and
  documented as requiring a registered Azure Bot + a public endpoint). Recipients are the configured
  UPN/email list and/or panel users. Wired into the routing matrix, per-cycle monitor grouping, and
  event rules. For the activity-feed path, a **"Download Teams app"** button generates the required
  Teams app package (`manifest.json` + icons, zipped; `webApplicationInfo.id` wired to the app
  registration) — pure-stdlib, no image library — so the admin can upload/sideload and install it
  for recipients (Teams requires an installed app to accept `sendActivityNotification`). The
  Teams "Register in Azure" wizard also configures the app's SSO surface (`expose_api`: Application
  ID URI `api://<clientId>` + an `access_as_user` scope + the Teams web/desktop clients
  preauthorized) so the generated Teams app can be **admin-installed** (a unified-store install
  validates SSO and otherwise fails); the personal tab that makes the app installable is included
  in the package.
- **Notification-event discovery** (`lib/core/notify/events.py`): the core now discovers *what*
  can be notified, symmetric to channel discovery. Each domain that publishes notifications
  declares a `notify_events.py` with a `NOTIFY_EVENTS` list (monitoring → `down`/`recovery`/`warn`,
  syslog → `syslog`, events → `event`); `events()` scans `lib.core.*`/`lib.services.*`/`lib.providers.*`
  (same self-describing pattern as `MODULE_PERMISSIONS`/`OVERVIEW_WIDGETS`) and `register_event()`
  adds one manually. `matrix_events()` are the auto-routing kinds (`matrix=True`); a rule-driven
  kind like `event` is a known source with no matrix columns. The config routing-matrix keys
  (`notifications|{channel}_on_{kind}`) are **fully dynamic — a single source of truth**: they are
  NOT declared in `lib/config/spec.py` (that duplicated the registry). A cell is stored in the DB
  `config` table only when the admin ticks it; dispatch reads `notif.get(key, False)`, so absent =
  off. (Generating them into `spec.py` at import was tried and reverted: `spec.py` is foundational,
  so discovering domains at its import time perturbs the other domain-discovery passes.) The
  **routing-matrix UI** is registry-driven at request time: its rows
  (event kinds) and columns (channels) are injected from the backend (`NOTIFY_MATRIX_EVENTS` /
  `NOTIFY_CHANNELS` in `core/_constants.html`) instead of being hardcoded in the renderer, so a new
  source kind or channel appears in the grid with no frontend edit. An event may set `ui=False` to
  stay hidden from the grid (used for the legacy `syslog` kind, which has no active dispatcher).
- **Services now emit their own notification events** (routable rows, opt-in per channel):
  the internal fail2ban emits `ipban_banned` / `ipban_unbanned` (from the ban lifecycle), and
  auth emits `auth_login` / `auth_login_failed` / `auth_account_locked` (from the login flow,
  covering local + LDAP + SSO). Each domain declares its events (`notify_events.py`, or
  `register_event(...)` for auth which lives outside the discovery roots) and dispatches them
  through the router; the matrix keys are dynamic (runtime), so they need no `spec.py` entry and
  default off. They appear as rows in the routing grid automatically.
- **Certificate-expiry notifications**: a background scanner (`lib/core/health/cert_scan.py`)
  periodically checks the certificate of every configured `ssl_cert` check (resolving a bound
  host's address) and emits `cert_expiring` when one is within `certs|warn_days` of expiry —
  **once per severity** (expiring → expired), re-arming when a cert is renewed; leader-gated.
  Configurable via `certs|notify_expiry` (off by default), `certs|warn_days` (21),
  `certs|scan_every_secs` (86400 = daily). Routable as the *Certificate expiring* row.
- **Service-health notifications**: a background evaluator (`lib/core/health/health.py`)
  watches the heartbeat registry and emits `service_down` / `service_up` **once per transition**
  when a background worker (monitor/syslog/events) stops beating (crash/unreachable) or recovers —
  leader-gated so replicas don't double-alert, seeded silently at boot (no startup noise), and a
  clean operator stop is treated as idle (never alerted). Configurable via `services|notify_down`
  (off by default), `services|down_after_secs` (60), `services|health_poll_secs` (30).
- Both the service-health and cert-expiry evaluators live in a new **`lib/core/health`** domain
  (platform self-monitoring — is my own stack alive, are my certs valid — a core concern
  *below* the monitoring service, which monitors external targets). Their config is a dedicated
  **Platform health** card in the General tab, not mixed into the Monitoring service card.
- **Manual-run notification event** (`manual_run`): an on-demand *Run all* / *Run select* from the
  Status tab now routes as its own single event (one routing row, grouped under a *Manual* source),
  separate from the daemon's per-kind `down`/`recovery`/`warn`. The whole batch is forwarded to the
  channels that have `notifications|{channel}_on_manual_run` ticked — regardless of each check's real
  kind (the digest still shows the real states) — so an admin can send interactive runs to a
  dedicated channel (or silence them) without touching the daemon routing. The transient monitor
  built for the run carries a cycle notifier pinned to this event (`MonitorNotifier(route_kind=…)`),
  so *Run all* notifies exactly like the daemon does, just under its own row.
- **SSO / provisioning**: OIDC and SAML2 (assisted Entra ID registration), SCIM 2.0 with
  before/after auditing, LDAP/Active Directory.
- **Internal fail2ban** (service-level IP bans) + an extracted security layer.
- **Self-describing Overview** (per-domain/service widgets) with its own `/overview` page,
  configurable landing and AJAX refresh; an integrated **syslog server** (RFC 3164/5424,
  UDP/TCP/TLS); a **connection-lost overlay**.
- **Management CLI** (users/groups/status/reload) on the same core logic as the web.
- **`ldap|ssl_verify`** (enabled by default) to validate the LDAPS server certificate.
- **Microsoft Teams personal-tab SSO** (`lib/providers/entraid/sso_routes.py`, alongside the
  OIDC/SAML providers): the Teams tab signs in via the Teams JS SDK (`getAuthToken`) instead of a
  redirect (Microsoft's login can't be iframed). `GET /auth/msteams/tab` loads the SDK and posts
  the token to `POST /auth/msteams/sso`, which validates it (PyJWT — JWKS, audience
  `api://<clientId>`, issuer) and establishes a session, mapping the AAD identity to an existing
  user by UPN/email with the same anti-account-takeover guard as OIDC. Enabling `embed_in_teams`
  also sets the session cookie `SameSite=None; Secure` (required for the cross-site iframe). Added
  **PyJWT** as an optional dependency (also used by the bot endpoint).
- **Route path convention + discovered CSRF-exempt list**: documented the convention (internal
  frontend APIs `/api/v1/<domain>/*` with session+CSRF vs external/host-facing
  `/auth/<provider>/*` + `/scim/v2/*`, CSRF-exempt and protocol/token-authenticated). The
  CSRF-exempt prefixes are no longer hardcoded — each route module self-declares them via
  `wa._register_csrf_exempt(...)` in its `register()`, so the set is discovered. Teams external
  endpoints are `/auth/msteams/{tab,sso,messages}`.
- **Configurable iframe allowlist** (`web_admin|frame_ancestors` + `web_admin|embed_in_teams`):
  the panel blocks framing by default (CSP `frame-ancestors 'none'` + `X-Frame-Options: DENY`),
  but an admin can now allow specific origins to embed it — and one toggle adds the Microsoft
  Teams/Outlook/M365 hosts so the **Teams personal tab renders ServiceSentry**. When an allowlist
  is set, `X-Frame-Options` is dropped (it can't express an allowlist), CSP `frame-ancestors`
  governs, and the session cookie switches to `SameSite=None; Secure` (so it survives in a
  cross-site iframe). The core security layer stays provider-agnostic: integration-specific
  embed origins (the Teams hosts) are declared by the provider via `wa._register_embed_origins()`
  and discovered — not hardcoded in `lib/security/headers.py`.
- **`BaseConnector.last_insert_id()`** (portable) + a per-connector `KIND` tag (sqlite/mysql/postgresql).
- **Email → Microsoft 365 "Register in Azure" wizard**: the M365 (Graph) email-notification
  provider now offers the same assisted Device Code Flow as SSO — it reuses the shared generic
  Entra wizard (`showEntraIdProvisionWizard`) to register an app with the `Mail.Send` application
  permission and auto-fill `ms365_tenant_id`/`ms365_client_id`/`ms365_client_secret` (secret
  stored encrypted). No new backend routes — it passes an inline `app_roles: ['Mail.Send']` spec
  to the existing `/api/v1/auth/entraid/provision/*` endpoints. An **"Open in Entra ID"** button
  (shared `_entraAppLink`) opens the registered app in the Azure portal in a new tab.
- **Syslog listener load/concurrency tests** (`TestLoad` in `tests/test_syslog_server.py`): 1000
  simultaneous TCP connections streaming 5000 messages arrive with zero loss/duplication, a
  single connection with 3000 octet-counted frames is fully received, and a UDP burst is
  asserted best-effort (the receiver survives and delivers the bulk).
- **Scheduler lifecycle notifications** (`scheduler_started` / `scheduler_stopped`): starting or
  stopping the background check scheduler now emits a routable notification event (opt-in per
  channel in the matrix, default off), so operators can be alerted when the daemon is turned on/off
  — distinct from the health domain's crash detection, which deliberately ignores a clean start/stop.
- **Editable notification texts (custom text layer over i18n), for every channel and module.**
  The Notifications → Templates editor now covers **all** notification strings, not just email: an
  admin can override any text per language, and the resolution is *custom → i18n default*. Texts are
  discovered as **packages** (`/api/v1/notify/text-packages`): Core themes (**Events / Messages /
  Statuses**), **Email** strings, and **one package per watchful module** (its `messages` section).
  Each entry shows its i18n default as the template; a blank field reverts to i18n. Overrides live in
  `notif_text_overrides` (`{lang: {'core:<key>'|'mod:<mod>:<key>': text}}`), resolved by
  `formatting.notify_text` / `ModuleBase._msg` / `event_title`; email keeps its own `notif_templates`
  store, unified into the same editor. Backend: `lib/core/notify/text_catalog.py`.
  - **Reorderable, named placeholders.** Templates take `{}` (sequential) **and** `{0}`/`{1}`… (by
    index), so a custom text can *reorder* the inserted values. Each message declares a **schema of
    its placeholders** (name per position) — core via `_CORE_VARS` (i18n `notif_var_*`), modules via
    an optional `messages_vars` section in their lang file — surfaced in the editor as clickable tag
    chips (`{0} user · {1} reason · {2} IP`) that insert the placeholder at the cursor. instead of English-only — both the
  **titles** and the framework-generated **bodies/statuses**. A notification has no user context but
  a *system* one, so the title (reusing the SAME i18n keys the routing grid shows, `notif_event_*`,
  so title and grid row can't drift) and the body are translated with the configured notification
  language. Framework event bodies now come from i18n templates with placeholders (`notif_msg_*` /
  `notif_status_*`, filled via `lib.i18n.translate`): login (*admin inició sesión vía LDAP desde …*),
  failed login, IP ban/unban, scheduler start/stop, service down/up and certificate expiring/expired.
  `formatting.event_title(kind, lang)` replaces the old hardcoded English `EVENT_TITLE` map, and the
  login method label (Local / LDAP / SSO …) is now i18n too (`notif_auth_*`).
- **Watchful check messages are localised via each module's own lang file.** New `ModuleBase._msg(key,
  *args)` reads a `messages` section from the module's `lang/<lang>.json` (in the system notification
  language, `en_EN` filling gaps, `{}` placeholders filled positionally) — so a module's digest text
  (e.g. *CPU (srv) uso excesivo 99.8%*) is translated where its labels/hints already live. **All 19
  watchful modules** are converted (cpu, ram_swap, filesystemusage, temperature, ntp, ssl_cert,
  hddtemp, datastore, process, dns, ups, ping, web, raid, service_status, keepalived, snmp, proxmox,
  m365) — each with a `messages` section in its `en_EN`/`es_ES` lang file.
- **Unified language selector** in the config UI: `lang`, `status_lang` and the new `notif_lang`
  fields all render through one template (`_field_render.html`) — each shows the language's native
  name (English / Español…, never the raw `es_ES` code) and, where a blank is allowed, a translated
  **Default** option (`— Default (system language) —` for the notification language). Replaces three
  near-duplicate per-field blocks.
- **Notification language is now a single global setting** (`notifications|lang`) that applies to
  **every** channel (Telegram / Email / Teams / webhooks), moved out of the *Email* provider into a
  **Notification settings** card at the top of the Notifications → Routing tab. A shared
  `formatting.notify_lang(cfg)` resolves it — preferring `notifications|lang`, then the legacy
  `email|lang` (kept for back-compat), then the panel language — and the email channel and the
  Telegram digest/single-event all use it. Existing `email|lang` values keep working via the
  fallback.
- **Telegram messages are now sent as HTML** with a designed layout instead of flat plain text,
  across both paths:
  - *Single-event* alerts: an event-kind **icon + bold title** (e.g. 🔓 *Sign-in*, ⛔ *IP banned*,
    📜 *Certificate expiring*), the target as inline `code`, the body as a **quote block** and a
    dimmed timestamp.
  - *Grouped monitor digest*: **bold section headers** (⚠️ *Issues (n)* / ✅ *Recovered (n)*), and
    each alert rendered as its own **quote-block card** — a bold header (status icon + item) with the
    message on the line below, blank-line-separated for breathing room instead of one crammed run-on
    line per alert — plus a summary line whose status URL is a real clickable `<a>` link.
  HTML is robust — every dynamic field is HTML-escaped (`& < >`), so module text with `_`/`*`/`<>`
  renders safely (the old plain path existed precisely to dodge Markdown breakage). Icons/titles per
  kind live in `lib/core/notify/formatting.py` (`event_icon`/`event_title`).
- **Login notifications now state the auth method** (Local / LDAP / SSO (OIDC/SAML/Entra ID)…):
  `_establish_session` derives it from the user's `auth_source` and includes it in both the alert
  status and message (e.g. *"admin signed in via SSO (OIDC) from 192.168.0.1"*), so an alert says
  *how* the user authenticated, not just that they did.
- **Notification Routing matrix**: rows are now **grouped by their source domain** — a subheader
  (Monitoring / IP ban / Authentication / Platform health / Certificates …) precedes each group so
  it's clear where every event comes from. The `source` is carried from the discovered descriptor to
  the grid (`NOTIFY_MATRIX_EVENTS`), labelled by `notif_source_<domain>`.
- **monitoring notification kinds** (`down`/`recovery`/`warn`) are now declared once in the
  monitoring domain's discovered `notify_events.py` (as `KIND_*` constants) and referenced by the
  emitter (`Monitor._alert_kind`), so the routing registry and the emitter can't drift apart. Removed
  the dead duplicate `KINDS` tuple from `monitor_notifier.py`.
- **Notification Routing matrix**: each channel column header now has a **select-all / deselect-all**
  checkbox that toggles every event row for that channel (tri-state: indeterminate when partial),
  driving the individual cells.
- **Allowed iframe origins** (`web_admin|frame_ancestors`) is now a **removable-chips input** —
  each origin is added on Enter and removed with its ×, instead of one free-text field (reuses the
  existing `multi` field control, like `syslog|allowed_sources`). Stored space-separated as before.
- Reorganization into **`lib/core` (foundational layer) / `lib/services` / `lib/providers`** with
  self-describing modules; thin HTTP routes + a Flask-free service layer per package; unified
  routing (one `routes.py` per domain) and central registration.
- Editable configuration migrated to the database (single read/write flow); registry-driven
  configuration layout.
- Notifications → Providers sub-tab reordered to a fixed sequence: **Event rules → Telegram →
  Email → Webhooks**.
- **Notification routing moved into a core-owned `NotificationRouter`**
  (`lib/core/notify/router.py`), built from an explicit `NotifyContext`
  (`lib/core/notify/context.py`) — DB connector, config reader, cipher, debug/audit sinks,
  public-URL/panel-user callables — so routing is independent of the web admin and Flask. The
  router *owns* every channel store (webhooks + Teams channels + the Teams bot reference store)
  and does the fan-out; each host (web admin, monitor/events/syslog workers) builds one and
  sends through it. `notification_dispatcher.dispatch()` and `MonitorNotifier` are now thin
  entry points that route through the host's router. Removed the per-service channel-store
  wiring and `_load_webhooks`/`_load_msteams`/`_msteams_bot_refs` duplicated on the syslog/events
  services and the embedded context; the standalone monitor now reaches webhook/Teams channels
  too (it previously had no channel stores).
- **Notification channels are now self-registering and own their stores** (`lib/core/notify/registry.py`):
  each channel is a `Channel` descriptor (`send` + grouped-`flush`) declared in its own
  `lib/core/notify/<channel>/channel.py`, which registers itself with the core registry on import.
  The registry **discovers** those `channel.py` modules (no central channel list). The router's
  dispatch and the monitor's per-cycle notifier iterate the registry instead of hard-coding the
  channel list / per-channel `if` blocks and `_flush_*` methods. The `NotificationRouter` is now
  **channel-agnostic**: it names no concrete store — a channel that needs persistence owns its
  store and builds it via `router.store(key, factory)` from the context; the webhook/Teams store
  code lives in each channel package (`webhook/channel.py`, `msteams/channel.py`), not in the
  router. Adding a channel is a new `channel.py` with no change to the router or the monitor.
  Removed the web admin's channel-store aliases and `_load_webhooks`/`_load_msteams`/`_msteams_bot_refs`
  shims; routes and the config bundle reach a channel's store through its `channel.get_store(wa._notify)`.

### Fixed
- **uninstall**: `uninstall.sh` no longer destroys runtime data by default. It now removes only the
  program code (`/opt/ServiSesentry`) and **preserves** both the config (`/etc/ServiSesentry`) and the
  runtime data (`/var/lib/ServiSesentry`, which may hold the SQLite database) — `--all` is required to
  remove those too. Previously a plain uninstall silently deleted `/var/lib` (potential DB loss).
- **install**: `check_dependencies.sh` actually installs missing OS packages now. Every `apt`/`wget`
  command was prefixed with `echo` (and the script ran under `bash -x`), so it only *printed* the
  install commands — the dependency check sourced by `install.sh`/`update.sh` was a no-op. Removed the
  `echo`/`-x`, and guarded it to warn-and-skip (not abort under `set -e`) on non-apt systems. (Note:
  `dependencies.txt` remains an incomplete OS-package subset — several runtime deps are pip-only.)
- **notifications**: the notification-text editor's **messages** Core package is no longer empty /
  frozen. The `notif_msg_vars` meta key (a dict of placeholder names) shares the `notif_msg_` prefix
  and was being swept into the package as a bogus entry with a non-string default, which crashed the
  client render when switching to that package. Discovery now keeps only real string entries.
- **monitoring**: a first-seen passing check no longer announces a spurious **recovery**. A
  `recovery` needs a prior problem state, so an OK item observed for the first time (no recorded
  baseline) is not a recovery — this stops a first daemon cycle / manual "Run all" over 100+
  passing checks from blasting 100+ recovery alerts (and a digest email listing them all).
  First-seen DOWN/WARN checks still announce (real problems), and genuine DOWN → UP transitions
  still notify; the working state is still recorded either way.
- **monitoring**: an on-demand **Run all** (Status tab → `POST /api/v1/modules/checks/run`) now
  sends notifications like the background daemon. Its transient monitor got no cycle notifier, so a
  state change detected during a manual run was never routed to Telegram/Email/etc.; it now gets a
  `MonitorNotifier` routed through the host's core notification router. It behaves exactly like a
  daemon cycle — state-change based (the shared `check_state` is the baseline), routed by the
  notifications matrix — so which channels receive what is controlled per-channel there.
- **monitoring**: resource sensors that breach a **soft threshold** now alert as a **warning**
  instead of a **down**. High CPU, RAM/SWAP, filesystem usage, temperature, HDD temperature, a
  near-expiry TLS certificate, a datastore connection-count breach and an NTP offset over the limit
  are all conditions where the host is reachable — they now carry `severity='warning'` so the
  monitor routes them to the `warn` kind. Genuinely hard failures (unreachable host, parse/connect
  error, an **already-expired** certificate) stay `down`. Also threads `severity` through the
  `send_message` bridge (ModuleBase → Monitor) so ad-hoc module alerts (ssl_cert, hddtemp, datastore,
  ntp) route correctly too, not only the reference `dict_return` path. The **Status tab** and the
  **Overview checks widget** now render this: a soft-threshold check shows an **amber "Warning"**
  badge (not red "Error"), a card whose only problems are warnings reads amber, and the Overview
  badge tallies warnings apart from errors (showing both when a module has each). The Overview
  **CHECKS stat card** likewise counts warnings apart from errors — a warning-only state reads amber
  with a "N warning(s)" badge, a mixed state shows both an error and a warning badge. The Overview
  **modules and servers table widgets gain a "Warning" filter** option, and their filter dropdowns
  are now **generated from the descriptor** (`view.filter.options` in each domain's
  `overview_widget.py`) instead of a hardcoded per-widget `<select>` in `_layout.html` — so adding a
  filter option is a backend-only change, and the two per-widget change handlers collapse into one
  generic `_dwSetTableFilter`. The servers `error`/`warning` filters now **exclude hosts in
  maintenance** (maintenance is its own bucket, as in the servers stat), so a maintenance host —
  whose skipped checks read "warning" (pending) — no longer leaks into the warning filter.
- **Overview severity filter with a =/≥ operator + maintenance union**: the modules and servers
  table widgets' error/warning filter is now a **compound control** — a level (Warning/Error) with
  an operator (**exactly `=`** or **that level or higher `≥`**, since error outranks warning), and
  on servers a **"+ maintenance" checkbox** that unions in hosts in maintenance. So "≥ Warning"
  shows warnings *and* errors, "= Warning" only warnings. The compound state is one opaque value
  (`<op>_<level>[+m]`, parsed by `lib/core/overview/filters.py`), so it rides the existing single-
  value filter plumbing; legacy saved filters (`error`/`warn`/`maint`/`errmaint`) map onto it. The
  control (level select + operator + maintenance check) is built from the descriptor
  (`view.filter.kind:'severity'` + `levels`), so a new level stays a backend-only change.
- **monitoring**: scheduler start/stop was **audited twice** (once as the request user `admin`, once
  as `system`) because both the HTTP route and the scheduler wrote a `daemon_started`/`daemon_stopped`
  row. The route-level audit is removed; the scheduler is the single source and writes **one**
  actor-aware row via a new `_audit_auto` — the request user for a manual action, `system` for an
  autostart/background one.
- **events**: the worker *tick* is now serialized (`_event_tick_lock`) so the periodic loop
  and a `run_now` command can't drain the cursor at the same time → no duplicate notifications.
- **syslog**: the listener prunes finished per-connection threads (TCP/TLS) → no unbounded
  memory growth.
- **heartbeat**: can restart after `stop_heartbeat()` (the thread handle is reset and the
  stop event is captured in the loop).
- **ipban**: `web_admin|ipban_enabled` is applied at boot (a persisted "disabled" survives a
  restart); the housekeeping DELETEs (bans/history/offense_counters/offense_log) run inside a
  transaction → deterministic on PostgreSQL/MySQL.
- **ipban**: `parse_manual_ban` rejects a negative duration (previously → a silent permanent ban).
- **MySQL / PostgreSQL portability** (production runs on both, via Docker; only SQLite was
  exercised by the tests, so these were invisible): the raw runtime SQL now quotes
  reserved-word identifiers (dialect-aware `quote_ident`) — the `key` column (check_state,
  history), the `virtual` column (hosts), the `groups` table (groups store) on MySQL, and the
  `user` column (audit) on PostgreSQL (which otherwise errored on INSERT and returned
  `CURRENT_USER` instead of the column). Without this, whole features were broken on the
  production engines: check state (`/status`, overview, monitor change-detection/alerts),
  history, host CRUD, group/role & SSO-group mapping, and the audit log. Verified end-to-end
  against real **MariaDB 11.8** and **PostgreSQL 18** instances (all fixed operations
  round-trip correctly on both).
  Regression guards: `tests/test_db_portability.py` (offline — asserts the raw SQL quotes
  reserved words) and `tests/test_db_portability_live.py` (opt-in — runs the stores against a
  real MySQL/PostgreSQL when `SS_TEST_MYSQL_HOST` / `SS_TEST_PG_HOST` are set, skipped otherwise).
- **history**: dialect-aware string concatenation for the group key (`CONCAT` on MySQL, `||`
  on SQLite/PostgreSQL); `get_stats` extracts JSON fields per engine (no `json_extract` on
  PostgreSQL); the down-sampling query uses `CAST(… AS SIGNED)` on MySQL and aggregates the
  `data` column (`MAX(data)`) so PostgreSQL's strict `GROUP BY` accepts it — previously the
  bare non-grouped `data` errored on PostgreSQL (swallowed → empty chart). The per-field
  aggregate (`min`/`max`/`avg`) is isolated in its own try/except, so a non-numeric field value
  (which makes PostgreSQL's numeric `CAST` raise; SQLite/MySQL degrade to NULL) only drops those
  three keys instead of losing the whole stats result.
- **events**: the MySQL connection reports MATCHED rows from `UPDATE` (`CLIENT.FOUND_ROWS`),
  so the cursor/cooldown upsert (`UPDATE; if rowcount == 0: INSERT`) no longer hits a UNIQUE
  violation when re-writing an unchanged value on MySQL.
- **schema migrations (MySQL)**: table rebuilds are now atomic — MySQL auto-commits DDL, so the
  base create-copy-drop-rename (transactional on SQLite/PostgreSQL) could lose data if it failed
  mid-way; MySQL now swaps the rebuilt table in with a single atomic `RENAME TABLE old→backup,
  new→old` and drops the backup only after the swap. Verified data-preserving on real MariaDB.
- **schema introspection (PostgreSQL)**: `information_schema`/`pg_class` lookups are scoped to
  `current_schema()`, so a same-named table in another schema no longer causes spurious rebuilds
  or column mix-ups in multi-schema deployments.
- **services (manager)**: `commands.enqueue()` returns its own INSERT's id (`last_insert_id`),
  not a race-prone `SELECT MAX`.
- **config**: a change to the `database` section or to `web_admin|host` (bind address) now flags
  a pending restart (previously only port/proxy/`syslog_db` did).
- **security (secrets)**: `restore_sensitive` now recurses into **lists** too (like
  `mask_sensitive`) → a secret nested inside a list of dicts is no longer erased on save.
- **watchfuls**: `datastore` — the SSH tunnel now serves **multiple** connections (InfluxDB 1.x /
  MongoDB over SSH are no longer reported down); integer coercion of thresholds in `web`/`ping`.
- **audit**: editing a user no longer records a spurious role change (compares uid to uid).
- **UI**: bulk enable/disable reflects the real state; on a failed module save `modulesData` is
  re-synced from the server; role reassignments check each result (no misleading "success").
- **config (email)**: the notification **provider** selector now persists — it registered a
  dirty *section* but not the `email|provider` field path, so `saveConfig()` (which sends only
  dirty field paths) never saved it and it reverted to `smtp` on reload. Now uses `updateField`.
- **MySQL**: `READ COMMITTED` so cross-process config changes are visible.
- The daemon no longer leaks a Telegram sender thread on every start/stop cycle.
- Correct *running* state for active-active external services.

### Security
- **SNMP community string is now a secret** (`watchfuls/snmp/schema.json`): marked `secret: true`, so
  it is encrypted at rest and masked in the API like the SNMPv3 auth/priv keys (previously stored in
  clear). Also gated with `show_when: version ∈ {1, 2c}` (it does not apply to SNMPv3).
- **Outgoing webhooks now pass through the SSRF guard** (`lib.security.net_guard.validate_external_url`
  in `webhook/notify._dispatch`) — the only server-side fetcher that previously skipped it. Rejects
  non-HTTP(S) schemes (`file://`, …) and the link-local / cloud-metadata range (169.254.x); private/
  internal endpoints stay allowed (a legitimate webhook target for a monitoring tool). Regression tests
  added (`test_wa_webhook.py::TestWebhookDispatch::test_ssrf_*`).
- **Non-root deployment, per role.** The Docker image now creates a fixed-uid non-root user
  `ssentry` (uid/gid **1000**) owning `/app`, `/etc/ServiSesentry` and `/var/lib/ServiSesentry`, and
  the deployments run each role as the least privilege it can:
  - **Compose** (microservices / traefik / test / ha-test): `web`, `events` and `syslog` run as
    `user: ssentry`; `syslog` gets `sysctls: net.ipv4.ip_unprivileged_port_start=0` so the non-root
    process can bind :514.
  - **Helm**: the `web` and `events` Deployments get a non-root `securityContext`
    (`runAsNonRoot`/`runAsUser: 1000`/`fsGroup: 1000`, `capabilities: drop [ALL]`, seccomp
    `RuntimeDefault`); the `netRaw` capability block was removed from `web.yaml` (web runs no
    in-process checks, `*_EMBEDDED=0`).
  - **Stay root** (documented in-file): the `worker` role and the **monolithic** web container,
    because the `ping` module uses `pythonping` (raw ICMP) which needs `CAP_NET_RAW` as an *ambient*
    capability — not grantable to a non-root process via `cap_add`/K8s `capabilities.add`.
  - **Upgrade note**: existing (root-owned) named volumes must be chowned once to uid 1000
    (`docker run --rm -v <vol>:/d alpine chown -R 1000:1000 /d`); fresh volumes inherit it from the image.
- **LDAPS validates the server certificate** by default (previously `CERT_NONE` → man-in-the-middle
  risk and theft of the bind credentials).
- **LDAPS validates the server certificate** by default (previously `CERT_NONE` → man-in-the-middle
  risk and theft of the bind credentials).
- **`/api/v1/overview/widget/<id>` requires a session** (`@login_required`) — it was previously
  readable anonymously (a session-less request resolved to `viewer` permissions).
- **Privilege escalation** in role assignment: a unified `_role_grantable` guard (a non-admin can
  never assign the built-in admin role, and a *custom* role only if its permissions are a subset
  of their own) on user/group create and update — **including group membership** (`_groups_grantable`),
  so a non-admin can't escalate by adding a user to a group that carries a higher-privilege role
  (e.g. the built-in Administrators group).
- **SSO account takeover**: OIDC/SAML/LDAP no longer convert a **local** account to SSO on a
  username collision (all three login callers reject cleanly — no 500).
- **LDAP group→role mapping is exact** (was a substring match: `Admins` matched `Admins-ReadOnly`);
  a short-name pattern still matches the CN of a full-DN `memberOf` value so Active Directory keeps
  working.
- **`saml2|graph_secret`** is now encrypted at rest and masked to the client (it was sent in cleartext).
- **`POST /api/v1/credentials/test` hardened**: requires a credentials permission
  (`credentials_view/edit/add`) — `servers_edit` was dropped, which let a server editor test a
  stored credential (decrypted secret) against an arbitrary address and exfiltrate it.
- **CSRF**: the `fetch` wrapper no longer attaches the token to protocol-relative URLs (`//host/…`).
- **watchfuls (Windows)**: `service_status`/`dns` quote the argument for `cmd.exe` (prevents
  injection from configuration values).

### Docs
- **Doc filenames standardised to kebab-case** (lowercase, hyphen-separated — the URL/slug-friendly
  convention; `README.md` stays the conventional exception). Renamed `ai_module_guide.md` →
  `ai-module-guide.md`, `watchful_guide.md` → `watchful-guide.md`, `web_admin.md` → `web-admin.md`,
  and updated every inbound reference (cross-doc links, the docs index, the root README, and the
  `watchfuls/*/watchful.py` comment pointers). 0 broken links/anchors.
- **Public-API docstrings filled in** for the three lowest-coverage areas surfaced by the audit
  (Google-style, English, no behaviour change): 62 docstrings across `lib/cli` (the `cmd_*` handlers +
  `context` helpers), `lib/db` (backend-specific `describe_table`/`list_indexes`/`vacuum` overrides),
  and `lib/providers` (LDAP/OIDC/SAML `is_available` + route handlers, the full SCIM `ScimService`
  CRUD, and the Entra device-code/SSO/tab handlers). Already-documented symbols were left untouched.
- **`schema.md` — nueva referencia del esquema de base de datos**: además del
  `schema.json` de configuración de módulos, el documento ahora incluye una sección
  «Esquema de base de datos (tablas relacionales)» que cataloga las **32 tablas fijas**
  (16 del núcleo `lib/core/*`, 14 de servicios `lib/services/*`, 2 de syslog) —PK,
  columnas clave, índices, JSON blobs y store de origen, verificadas contra cada
  `TableSpec`— más las tablas dinámicas por módulo (`mod_<módulo>_<name>`) y un diagrama
  ER Mermaid de las relaciones lógicas por `uid`. Documenta el motor conectable
  (SQLite/MySQL/PostgreSQL), la ausencia de FKs físicas y la capa editable en la tabla
  `config`; enlaza a `configuration.md` y `architecture.md`.
- **New test coverage for audit-identified gaps**: `test_ratelimit.py` (the sliding-window rate
  limiter — under/over limit, window slide, per-key isolation, `peek` vs `hit`, reset, GC, with a
  controllable clock) and `test_ha_failover.py` (end-to-end leader-gating: a single-owner service runs
  on exactly one replica, fails over to a standby on lease expiry / clean release, and an active-active
  service runs on every replica).
- **Corrected stale in-code docstrings** surfaced by the code/doc audit (comment-only, no
  behaviour change): the monitoring scheduler docstrings/comments no longer claim a Telegram
  sender thread / `pool_run` is closed on dispose (`monitoring/manager.py` ×4 — notifications are
  synchronous via `MonitorNotifier`); `telegram/notify.py` no longer references a queued Telegram
  client; `events/manager.py` now describes the cursor-based worker instead of a syslog "per-message
  hook"; `hosts/__init__.py` calls `routes` a module (not a package); `entraid/__init__.py` lists the
  real Graph submodules (client/auth/directory/mail/teams/provisioning) instead of a non-existent
  `graph` module; `users/store.py` schema comment fixed (`uid` PK, `username` UNIQUE).
- **`notifications.md` rewritten** to match the current delivery layer end-to-end: the
  `NotifyContext` → `NotificationRouter` → channel-registry / event-registry architecture (Flask-
  and web_admin-independent); the self-registering `Channel(send, flush)` model and the discovered
  `NOTIFY_EVENTS` kinds with `matrix`/`ui` flags; the dynamic routing matrix; the grouped-per-cycle
  `MonitorNotifier`; the WARNING severity; per-channel specifics (Telegram now **HTML**, not
  plain/Markdown; Email SMTP/M365/Gmail; Webhook HMAC; Microsoft Teams); and a detailed **notification-
  text system** section — the custom→i18n resolution layer (`formatting.py`), how the editable
  listings are generated (`text_catalog.py` packages), the **tag schemas** (`notif_msg_vars` /
  `notif_email_vars` / `messages_vars`), and the editor UI + endpoints. Removed the obsolete
  "central dispatcher / plain-text Telegram / queued-thread" descriptions.
- `discovery.md`: added the two new self-describing systems — the **notification-channel registry**
  (`register_channel`/`Channel`, discovered from `lib/core/notify/<name>/channel.py`) and the
  **notification-event registry** (`NOTIFY_EVENTS` in each domain's `notify_events.py`) — with their
  flow diagrams and two rows in the "how to add each thing" summary.
- `architecture.md` synced with the `lib/core/notify` reorg: rewrote the `core/notify/` directory
  tree (context/router/registry/events/monitor_notifier/formatting/text_catalog + per-channel
  `channel.py`, incl. the whole `msteams/` package; `notification_dispatcher.py` marked a legacy
  shim), added `lib/core/health/` (platform self-monitoring → `service_down/up`, `cert_expiring`),
  corrected the concurrency model (synchronous flush, no Telegram queue/thread), the component and
  check-cycle diagrams (accumulate-then-flush, multichannel), and the `lib/__init__` export note.
- `README.md` (docs index): the notifications/i18n rows and the overview now name the router/registry
  architecture, all four channels (incl. Microsoft Teams), the WARNING severity and the notification-
  text/tags system.
- Fixed stale cross-doc anchors surfaced during the sync (control-plane / high-availability links
  now point to `services.md`; the notifications-matrix and permissions anchors).
- `i18n.md` synced with the notification-text code: reframed the two-layer architecture to add the
  third concern (notification texts, reusing both layers); documented the module file's new
  `messages` / `messages_vars` keys; catalogued the core notification key families
  (`notif_event_*` / `notif_msg_*` / `notif_status_*` / `notif_auth_*` / `notif_source_*` and the
  `notif_tpl_*` editor keys); documented the `email_tpl` overlay flow (`_DEFAULT_STRINGS` base +
  per-language overlay + admin overrides); documented the three tag schemas (`notif_msg_vars`,
  `notif_email_vars`, `messages_vars`); `ModuleBase._msg()` precedence; admin overrides
  (`core:` / `mod:` scoped keys); and indexed `{0}`/`{1}` placeholders for reordering. Editor
  detail links to `notifications.md`.
- `configuration.md` synced with the notifications code: the `notifications` routing matrix is
  now documented as **dynamic** (keys generated from the discovered notify-event registry, not a
  fixed 4×4 table), with the real `matrix=True` kinds and their sources, `syslog` flagged as
  compat-only (`ui=False`, no active dispatcher) and `event` as non-matrix; new global
  `notifications.lang`; removed the obsolete `email.lang` (migration note) and `msteams.app_id`;
  webhooks relocated from `config.json` to their own DB table (`FILE_ONLY_SECTIONS` = `database`
  only); rewrote the Telegram section (synchronous HTML send, `(ok, status_code, info)` — no
  background queue, no `-1/-2/-3` codes); documented the `notif_text_overrides` / `notif_templates`
  / `notif_html_templates` feature-data stores. Deep detail links to `notifications.md`.
- Documentation aligned with the routing refactor (architecture, web_admin, cli, services,
  discovery, security, SSO); a note that the `/scim/v2/*` routes are an IETF standard and can't
  be renamed.
- Documented the multi-engine DB portability: `architecture.md` (connector layer — `quote_ident`,
  `KIND`, atomic MySQL rebuild), `configuration.md` (`ldap.ssl_verify`; exact LDAP group→role
  matching), and `tests.md` (§81 — the security-regression and offline/live DB-portability tests,
  with the `SS_TEST_MYSQL_*` / `SS_TEST_PG_*` env vars — auto-loaded suite-wide from a
  gitignored `src/tests/.env.test` by `src/conftest.py` — to run against real
  MySQL/PostgreSQL; the live harness self-skips under `-n auto` and must run with `-n0`).
- Documented the syslog receiver's measured resource footprint under load (`tests.md` §49) and
  a sizing rule of thumb — thread-per-connection, ≈47 KB RAM per live TCP/TLS connection — with
  deployment guidance in `docker.md` (isolate the `syslog` container / set `mem_limit` for very
  high persistent-connection counts) and a pointer from `deployment.md`.
- `web-admin.md` synced with the notifications UI/endpoints: documented the Notifications config
  tab's four sub-tabs (General / Routing / Providers / Templates) and the General sub-tab's global
  `notif_lang`; added the unified "Notification Texts" editor and the `text-packages`
  GET/PUT endpoints (Core/Email/per-module discovery; legacy `templates/<lang>` PUT no longer
  invoked by the UI); added the Microsoft Teams channel endpoints (channel CRUD + channel/user
  test + app-package); corrected the built-in/preview HTML-template endpoints to `config_view`;
  added the `notif_text_saved` audit event and the `summary` HTML-type "preview-only" caveat.
  Deep detail links to `notifications.md`.
- `modules.md`, `watchful-guide.md` and `services.md` synced with the WARNING severity, the
  `_msg()` + `messages`/`messages_vars` module-i18n helper, and the monitor's grouped-per-cycle
  notification. `modules.md`: `ReturnModuleCheck` now documents `severity`/`name` and multi-channel
  plain-text delivery (the OK/DOWN model is no longer binary), plus a per-module note on the 11
  soft-threshold modules that emit `warning` (`ssl_cert`: near-expiry = `warn`, expired/handshake
  failure = `down`). `watchful-guide.md`: fixed the `send_message(self, message, status=None,
  item='', severity='')` signature (three kinds recovery/down/warn), added a `_msg(key, *args)`
  subsection (admin override → module `messages` → key; positional `{}` + indexed `{0}`/`{1}`),
  replaced the hardcoded inline-Markdown messages in the minimal template and the tcp_check example
  with `self._msg(...)` + `messages`/`messages_vars`, added those two keys to the lang-file table,
  and added checklist steps. `services.md`: the monitoring row/notes now describe `MonitorNotifier`
  grouped-per-cycle multichannel dispatch (one synchronous flush, no background thread), the `warn`
  severity and the `manual_run` kind. Canonical detail links to `notifications.md`.
- **`modules.md` aligned with the host-aware system-module model** (no `psutil` in the check): the
  system modules (`cpu`, `ram_swap`, `temperature`, `filesystemusage`, `process`, `service_status`,
  `raid`) run OS commands via `ModuleBase.host_exec` local/SSH on the bound host — `psutil` is used
  only in local `discover()`. Corrected each module's flow and platform: `cpu` (`_cpu_cmd`:
  `/proc/stat`/`kern.cp_time`/`top`/`wmic`), `ram_swap` (`_MEM_CMDS`; emits `<key>_ram`/`<key>_swap`,
  added the `list`/host example), `temperature` (**Linux-only** `/sys/class/thermal` via `grep`),
  `filesystemusage` (`df -P -k`/`wmic logicaldisk`) and `process` (`ps`/`tasklist`). `service_status`:
  the check **always** uses `systemctl is-active` on Linux (init detection is `discover()`-only),
  documented auto-remediation and the SSH/host-aware mode. `ssl_cert`: parsed with the `cryptography`
  library (`x509.load_der_x509_certificate`), documented the dependency and the OK/warn/down states
  (expired or handshake failure = `down`). `web`: example updated to the host-centric
  `scheme`/`server`/`port`/`path` schema (`url` is compat). Added a cross-cutting note on host-aware
  system modules, and per-module `severity='warning'` (amber) on soft-threshold breaches. Fixed the
  "via psutil" description in `cpu`/`filesystemusage`/`process` `info.json`.

### Notes
- **`/overview2`**: an internal proof-of-concept to evaluate **Alpine.js** against the current
  Overview (same widgets/API/design; edit mode persisted to the account; a route-scoped CSP with
  `'unsafe-eval'`). Not a product feature — parked.
- **Accepted risk**: `POST /api/v1/hosts/test_ssh` lets a `servers_edit` holder test a stored
  credential against an arbitrary address (exfiltration/SSRF); hardening it would break the
  editor's legitimate flow, so it stays audited and documented. Future option: bind the target to
  a registered host.
- Remaining **deferred** items (verified-harmless / latent): the leader-election
  INSERT-conflict fallback is dead code on PostgreSQL, but the SELECT-first design means the
  common path never reaches it and acquire/renew/steal are correct (verified on real
  PostgreSQL) — the loser of a first-acquire race just retries next cycle; incremental
  `ADD COLUMN` requires a default for a `NOT NULL` column (the current convention — a
  default-less `NOT NULL` or `UNIQUE` add would fail, but no schema does that); the
  `/history/diag` endpoint is SQLite-only (returns an error on MySQL/PostgreSQL). Plus frontend
  low-severity items (discovery-modal races, client-side gating of session revocation,
  invalid-date formatting, escaping hardening).
