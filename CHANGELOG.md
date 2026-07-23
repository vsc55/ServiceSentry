# Changelog

All notable changes to **ServiceSentry** are documented in this file.

## [Unreleased]

### Added
- **History and Syslog became standalone section pages, like Overview.** They are no longer tabs
  inside the admin panel: `/history` and `/syslog` are whole pages of their own, declared once in
  the `HOME_PAGES` registry with a `standalone` spec (pane, render entry point, required
  permission, navbar icon/label). One generic route factory serves them all, the navbar builds its
  buttons from the same data, and each is selectable as a landing page. A standalone page renders
  **only its own pane** — the admin tab bar and the other sections' markup are not emitted at all,
  rather than shipped and hidden with CSS. `/history` accepts a shareable deep link
  (`?module=&key=`), which is what the "see this check's history" jump from Infrastructure now
  uses. The navbar always shows the same four buttons in the same order (Overview, History, Syslog,
  Admin); the section being viewed stays in place, highlighted, instead of disappearing.
- **Destructive data wipes gathered in Config → General → Maintenance.** *Clear All History*,
  *Clear a Series* and *Clear Syslog Messages* left the toolbars of the very sections they erase —
  pages that stay open all day, one stray click from deleting everything. The Maintenance card has
  no fields of its own and knows nothing about history or syslog: each domain contributes its
  button as a `CONFIG_ACTION` on section `maintenance` (`lib/core/history/manifest.py`,
  `lib/services/syslog/manifest.py`). Two limitations had to go for that to work — generic cards
  now render contributed actions (previously only the bespoke auth renderers did), and a card may
  now exist on actions alone. `CONFIG_ACTIONS` also gained a `perm` key, so a button whose
  permission the user lacks is never drawn (the API still enforces it). Clearing one series is a
  picker modal now, since there is no "current series" outside the History page.
- **Packages can now contribute config-section buttons and their own web UI — no package-specific
  glue left in `web_admin`.** Two self-describing mechanisms (documented as §7b in
  `explica-descubrimiento.md`): (1) `CONFIG_ACTIONS` — a provider/service/module declares its
  buttons as DATA in `<pkg>/config_actions.py` (`section`, `label_key`, `icon`, solid `variant`,
  `order`, the JS `fn` name and a declarative `show_when: {field, not_empty}` gate);
  `discover_config_actions()` scans `lib.providers`/`lib.services`/`lib.core`, `config_layout()`
  attaches them to the matching card, and the generic `_cfgSectionActions()` renders them.
  (2) the existing package **web-assets** discovery (`web/_ui.html` / `_modals.html` /
  `_styles.html`), until now scanned only under `watchfuls/`, now also covers `lib/providers/`
  (referenced as `providers/<name>/…` so a provider can never collide with a watchful of the same
  name, and a package may ship several `*_ui.html`).
  **Migration:** all Entra ID glue moved out of the panel — the OIDC/SAML2/SCIM wizards became
  `lib/providers/entraid/web/{_oidc,_saml,_scim}_ui.html`, the `_entraAppLink` deep-link helper
  moved with them, and the hardcoded Entra buttons in `partials/cfg/auth/_renderers.html` were
  replaced by the generic renderer driven by the provider's `CONFIG_ACTIONS`.
- **Entra ID OIDC client-secret lifecycle: assisted rotation, expiry warning and unattended
  rotation with a margin.** An Entra app secret expires, so three independent, opt-in pieces were
  added. (1) **Assisted rotation** — a *Rotate secret* button on Config → Authentication → OIDC
  runs a device-code sign-in and mints a fresh secret on the EXISTING app registration via Graph
  `addPassword` (new `POST /api/v1/auth/entraid/oidc/secret/device-code` + `…/device-poll`), with
  no re-registration. (2) **Expiry warning** — a new leader-gated background scanner
  (`lib/core/health/secret_scan.py`) emits the routable `secret_expiring` event once per severity
  (expiring → expired), re-arming when the secret is renewed (`oidc|secret_notify_expiry`,
  `oidc|secret_warn_days`, default 30). (3) **Unattended rotation** — with
  `oidc|secret_auto_rotate` on, the scanner mints the replacement once inside the
  `oidc|secret_rotate_days` margin (default 15) by authenticating the app **as itself**
  (client-credentials) and emits `secret_rotated`; if the app may not modify its own registration
  the rotation fails and it degrades to warning only (never silent). Adding a secret does not
  revoke the previous one, so rotation is non-disruptive. New `provisioning.add_app_secret()`
  returns the **expiry Entra actually granted** (the tenant policy may cap the requested lifetime),
  stored in `oidc|secret_expires_at` — an empty value means unknown and disables both checks.
- **Notification recipients: typeahead over users & groups, resolved on send.** The recipient chips
  (Config → Notifications → Email / Microsoft Teams) autocomplete as you type against panel **users**
  and **groups** (new `GET /api/v1/notify/recipients/suggest`, gated by `config_edit`). Picking one
  stores a token — `user:<uid>` (chip: person icon + name) or `group:<uid>` (people icon + name) —
  that a `RecipientResolver` **expands to email(s) at send time**: a user → their current email, a
  group → its enabled members' emails. Built from the shared DB via `router.store('recipients', …)`,
  so it works in both the web-admin test-send and the monitor process. Resolution is against the live
  directory, so a **disabled or deleted** user/group (and a user with no email) is skipped
  automatically — logged and surfaced in the email test result (its chip shows "unknown"). Emails are
  de-duplicated; plain typed addresses still work. Enabled by flagging the field `suggest: 'recipients'`
  in `build_config_schema()` on top of the `multi` chips widget; still stored as a comma-joined string.
- **m365 Overview widgets** (schema `__overview_widget__` + `Watchful.overview_widget`). A module
  can now contribute **several** widgets — `__overview_widget__` accepts a **list** — each with a
  `view`: **`stat`** (a Servers-like stat card: a big count + a coloured badge per state,
  N OK / N Warning / N Error, from a per-state `counts` backend breakdown; auto height, not
  resizable) or **`table`** (a dense listing with a scope selector: all / aggregate / a specific
  check kind). m365 ships both: a stat card fixed to **Service health** (via `scope: "health"`) that
  **clicks through to Microsoft's service-health page** (via `link`; generic
  `_dwIsNavigable`/`_dwNavigate` support for external module-widget links), plus a **table** widget
  with the selector. In the table, rows are always sorted **worst-first** (error → warning → ok), and
  a second **minimum-level** filter (all / ≥ warning / only errors) narrows them down — both applied
  generically to every module table widget. At the **Aggregate** scope a table widget collapses to a
  stat card, so there it behaves like one: **auto (locked) height, not resizable, and the level
  filter is hidden**. The backend `Watchful.overview_widget` returns one entry
  per check KIND (Service health, Licenses, App credentials, Mailboxes, OneDrive, Secure Score, Risky
  users, SharePoint) aggregated across every m365 item — the same data feeds both widgets. Each widget
  is keyed `mw_<module>` (primary) / `mw_<module>_<id>`.
- **Generic Entra ID "check & fix app permissions"** (the Entra provider owns it; modules only
  declare *what* they need). Two credential-editor actions on any credential that declares
  `__entraid_provision__` (m365 is the first):
  - **Check permissions** → `POST /api/v1/auth/entraid/check-permissions`: resolves the required
    application permissions from the module profile, acquires an app-only token and inspects its
    `roles` claim (read-only, no admin), and returns a ✅/❌ report. Backed by the dependency-light
    `lib/providers/entraid/permissions.py` (`token_roles` + `permission_report`). The modal opens
    **immediately** with the required-permission list (known up-front from the action's provision),
    then ticks each ✅/❌ in sequence as the result arrives — no blank wait. When something is
    missing, a **Fix permissions** button appears in the modal footer that launches the fix flow
    (the fix action itself is `toolbar:false` — invokable from the check modal, not shown as its own
    toolbar button). The credential-editor Actions row groups the app-lifecycle buttons together
    (Create app · Open app in Entra ID · Check permissions).
  - **Fix permissions** → the device-code sign-in wizard in a new **ensure** mode: instead of
    creating a new app it grants the MISSING permissions to the **existing** app (by `client_id`) and
    admin-consents them (`provisioning.ensure_app_permissions` → merge `requiredResourceAccess` +
    `appRoleAssignments`), without a new app or a rotated secret, then shows a
    granted/already-present/still-missing report. Idempotent; audited
    (`entra_app_permissions_ensured`/`_failed`).

  The m365 Watchful no longer implements any of this — it only declares its required permissions in
  `__entraid_provision__` and adds the two credential actions. The shared action/link labels live in
  the **core** i18n (`prov_entraid_action_*`), referenced by each action's `label` key, so modules
  don't duplicate them (both the credential editor and item action resolvers honor `action.label`).
- **m365 module — many more Microsoft 365 checks** (beyond SharePoint storage), each an opt-in
  per-item toggle via the same Graph app-only auth: **service health** (`serviceAnnouncement/healthOverviews`
  — degradation warns, interruption is a hard down; optional service filter), **license capacity**
  (`subscribedSkus` — free units below a threshold / exhausted), **app secret/certificate expiry**
  (`applications` — warns N days before this app's own credential expires, avoiding a dead monitor),
  **mailboxes over quota** (reports `getMailboxUsageQuotaStatusMailboxCounts`), **OneDrive tenant
  usage** (reports `getOneDriveUsageStorage`), **Secure Score** (`security/secureScores` — % below a
  minimum) and **risky users** (`identityProtection/riskyUsers`). Each emits under `<item>/<service>`
  so results stay independent. The Entra "Register in Azure" wizard now requests the extra
  application permissions (`ServiceHealth.Read.All`, `Organization.Read.All`, `Application.Read.All`,
  `SecurityEvents.Read.All`, `IdentityRiskyUser.Read.All`) alongside the existing `Sites.Read.All` /
  `Reports.Read.All`. Full en/es i18n and tests for every new check.
- **Clusters list "check" button**: the Infrastructure → Clusters table now has a per-row test
  button (▶, like the Servers list) that runs that multi-bind check once and shows the per-member
  breakdown in the shared results modal (`_clTestRow` → `/api/v1/hosts/test` with an explicit
  single-check payload + `no_ssh`; members resolve from `host_uids`). Gated on edit, mirroring the
  Servers test.
- **Proxmox "Fix permissions" action**: the *Check permissions* modal often showed a missing
  privilege (e.g. `Datastore.Audit (/)`) with no way to fix it. A new `fix_permissions` action
  (button next to *Check permissions*) grants exactly the privileges the item's enabled checks need
  to the identity the credential uses — the token's own user (parsed from `token_id`) plus the token
  itself for a privilege-separated token, or the password user — over SSH (root/sudo), then
  re-verifies over the API and shows the fresh verdict. It reuses a custom role
  (`ServiceSentryMonitor`) and does NOT rotate the token (unlike *Provision token*). The SSH path is
  now a shared `Watchful._provision_ssh` helper (extracted from `provision_token`, keeping the SSRF
  guard in one place). Write action → requires module edit and is audited.
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
- **Row-hover highlight on the notification-routing matrix** (Config → Notifications → Routing): the
  event row under the cursor is tinted so the active line stands out. Implemented with Bootstrap
  `table-hover` + a reusable `.ss-hover-rows` utility class (section sub-headers keep their own
  background).

### Changed
- **Pinned dependency versions for reproducible builds (`requirements.lock`).** Every dependency
  in `requirements.txt` used an open `>=` range and nothing was locked, so each `docker build` /
  `pip install` pulled whatever satisfied the minimum — two builds on different days could ship
  different trees, and a new major (Flask 4, a breaking Werkzeug…) would enter on its own and could
  break the runtime with no repo change (the same class of surprise as the paramiko `.deb` break).
  `requirements.txt` now stays as the intent (ranges) and a new `requirements.lock` carries the
  exact, **tested** versions from the dev venv (the one the 3402-test suite passes on) — 41 pinned
  packages across the full tree, each with **`--hash` digests** so pip verifies integrity in
  `--require-hashes` mode (supply-chain protection). Everything installs from the lock: Docker, the
  `tests` / `db-backends` workflows, and `setup_env.ps1` (so the dev venv matches what deploys, not
  a floating `requirements.txt`); the workflows' pip cache key tracks the lock. Dev tooling is
  layered on top without the lock as a `-c` constraint (a hashed constraints file would force
  `--require-hashes` onto the unhashed dev requirements) — the lock is already installed, so its
  pins hold. Header in both files documents how to regenerate. (`PyJWT` is optional and absent from
  the dev venv, so its lock entry keeps the resolver's version.)
- **Removed the dead `email|notify_on_*` keys (pre-release cleanup).** Superseded by the
  `notifications` routing matrix (`notifications|email_on_*`) and **read by nothing** — they only
  still rendered three no-op switches on the Email card. Dropped the 3 `Cfg` declarations, their
  6 i18n label/hint entries per language, and the doc rows/compat note.
- **`ai-module-guide.md` → `caso-guia-modulo-ia.md`**, bringing the last doc into the naming
  convention (17 inbound references rewritten, including the `watchfuls/*/watchful.py` pointers).
  It stays **deliberately self-contained** rather than deduplicated: its whole purpose is for an
  agent to build a module from that file alone (its frontmatter records the validation), so the
  README now documents it as a conscious exception to the single-source rule — with the caveat
  that changing schema/discovery/guide material means **revalidating it** as well as editing the
  SSOT.
- **One discovery convention for every self-describing feature: `manifest.py` + a single
  scanner.** Each feature used to grow its own near-identical `pkgutil.iter_modules` loop
  importing a differently-named submodule (`permissions.py`, `overview_widget.py`,
  `notify_events.py`, `config_actions.py`, `__init__.py`), so adding a mechanism meant copying a
  scanner and inventing a file name. Now a package declares everything it contributes in its own
  **`manifest.py`**, and the shared `lib/discovery.py` (`scan`/`scan_values`/`scan_flat`) collects
  it. Migrated all five families — `MODULE_PERMISSIONS` (16 packages), `OVERVIEW_WIDGETS` (14),
  `NOTIFY_EVENTS` (6), `CONFIG_ACTIONS` (1) and `EMBEDDED_SERVICE`/`STANDALONE` (4) — and deleted
  the four bespoke scanners. Heavy implementations (a widget's 150-200-line data provider) stay in
  their own module and are imported into the manifest, so it reads as a list of what the package
  offers. Descriptors stay **Python** (not JSON) because they bind live objects — callables like a
  widget's `stat` provider; watchful modules are the opposite case (drop-in plugins with no core
  code) and keep declaring in `schema.json`. Documented as §0 of `explica-descubrimiento.md`.
- **Dropped the legacy `email|lang` fallback (pre-release cleanup).** Since no version has shipped
  there is nothing to migrate, so `notify_lang()` now resolves `notifications|lang` → `web_admin|lang`
  → `''` (the `email|lang` branch is gone). Removed all references — the fallback code + docstrings
  (`formatting.py`, `app.py`, `spec.py` comment), the `test_falls_back_to_legacy_email_lang` test
  (and the precedence test's `email` layer), and the docs (`explica-i18n.md` flow + diagram,
  `explica-notificaciones.md` precedence, `ref-configuracion.md` migration note).
- **i18n sweep: hardcoded user-facing strings routed through i18n** (excluding the standalone
  `overview2.html` dev page). Backend: the four notification channels (`email`/`msteams`/`webhook`/
  `telegram` `notify.py`) now translate their send/test result messages via `translate(lang, key)`
  (lang threaded from `notify_lang(cfg)`, so both the monitor and the "Send test" toast are
  localized); route error bodies use `wa._t(key)` in `modules`, `entraid` (incl. the lone leftover
  **Spanish** literal), `msteams`, email `template_routes`, `hosts` (SSH test), `scim`, `history`,
  `ldap`, plus generic `not_found`/`unauthorized`. Frontend: `msteams_tab.html` (Teams SSO landing),
  the HTML-template editor toolbar/toasts/shortcuts (`_tpl_html.html`), `_utils.html` copy toast,
  `audit/_detail.html` labels, and the group/role name placeholders (`modals/_access.html`) now use
  `t(...)` / `{{ i18n[...] }}`. New keys follow the codebase's per-domain families — channel result
  messages under `email_*` / `webhook_*` / `telegram_*` / `msteams_*` (matching the existing 56
  `msteams_*` / 33 `webhook_*` / … keys), reusing `msteams_url_required` where it already existed;
  the cross-channel recipient chips stay `notif_recipient_*`. en/es parity throughout.
- **i18n: session keys homogenized under `session_*`.** The scattered session labels/messages/actions
  (`active_sessions`, `no_active_sessions`, `sessions_closed`, `current_session`, `revoke_session[_tt]`,
  `revoke_user_sessions`, `confirm_revoke_user_sessions`, `close_all_sessions[_tt]`,
  `confirm_close_all_sessions`) now use the `session_*` prefix (e.g. `session_active`, `session_none`,
  `session_close_all`, `session_revoke_user_confirm`), matching the already-`session_*` audit events.
  The two odd audit events were renamed too (`user_sessions_revoked`→`session_user_revoked`,
  `all_sessions_revoked`→`session_all_revoked`); audit rows written before this show the raw event slug.
  Cross-cutting families left untouched (`col_sessions`, `subtab_sessions`, `overview_sessions`) and the
  `sessions_view`/`sessions_revoke` **permission flags** are unchanged.
- **Notification recipient fields render as removable chips** (Config → Notifications → Email and
  Microsoft Teams). Type an address and press Enter to add it (or paste a comma-separated batch);
  each entry is a chip with an × to remove. Reuses the existing `multi` field widget — just flags
  `email|recipients` / `msteams|recipients` with `multi: true` in `build_config_schema()`; still
  stored as a comma-joined string, so the channels' recipient parsing is unchanged.
- **Auth flow refactor (thin `/login` route + Flask-free resolver, no behaviour change).** The
  `login` route no longer holds the LDAP orchestration: the local-vs-LDAP decision (and the two
  previously-duplicated LDAP branches — known-SSO user vs unknown user) is now one Flask-free
  `_AuthMixin.resolve_login(username, password) -> LoginResult`; the route only maps the result to
  session/audit/flash. The shared post-auth helpers `_establish_session`, `_landing_url` and
  `_auth_method_label` moved from `web_admin/routes/auth.py` onto `_AuthMixin` — so the OIDC/SAML/Teams
  provider routes call `wa._establish_session(...)` / `wa._landing_url(...)` instead of importing them
  from `web_admin.routes.auth` (removes the provider→route layering coupling flagged in the audit). The
  LDAP protocol stays in `providers/ldap`. Verified behaviour-identical: anti-timing/anti-enumeration,
  lockout, LDAP fallback and all SSO paths — 151 auth/LDAP/OIDC/SAML/Teams-SSO/security-regression tests pass.

### Fixed
- **Install aborted on Debian/Ubuntu fetching a dead paramiko `.deb` (affects real installs,
  not just CI).** `dependencies.txt` pinned `python3-paramiko` to a hardcoded pool URL for
  paramiko 2.4.2 (2018); that file is gone from current mirrors, so `wget` returned 404 (exit 8)
  and aborted the install. The pinned version also contradicted `requirements.txt`
  (`paramiko>=3.0`). Now it installs `python3-paramiko` from the distro repo like every other
  dependency (Debian 13 ships paramiko 3.x).
- **CI: install tests aborted on Debian/Ubuntu with `sudo: command not found`.**
  `check_dependencies.sh` called `sudo apt install` unconditionally, but the install-test
  containers run as root with no `sudo` present. It now uses `sudo` only when not already root,
  falls back to running `apt` directly as root, and skips with a clear message when it is neither
  root nor has `sudo` (instead of crashing under `set -e`).
- **CI: three further install-test breakages, surfaced once the `sudo` abort was fixed.**
  (1) The systemd check asserted a `ServiSesentry.timer` that no longer exists — the timer was
  dropped when the monitor became a long-running service; the stale assertion is removed.
  (2) The "monitoring daemon" step ran bare `main.py`, which now starts the **web panel** (the
  default mode) and would hang forever — it runs `main.py --monitor -t 0` (one pass, then exit).
  (3) The web-startup health check used `curl`, installed only on the systemd images, so it would
  fail the Gentoo job — it now probes with `python3` (present on all three images).
  (4) The first-run step asserted `config.json` was created — but no run mode writes it (verified:
  both `--monitor -t 0` and `--web` create only `data.db`). `config.json` is an optional read-only
  bootstrap file, and after the config→DB migration the database is what first run creates; the
  assertion (a leftover from when startup seeded `config.json`, and unmeetable in CI since
  `data/config.json` is gitignored) now checks `data.db` alone.
  (5) The partial-uninstall check asserted `/var/lib` (runtime data + the SQLite DB) was removed,
  but `uninstall.sh` without `-a` deliberately **preserves** it (and `/etc`) so an uninstall can
  never silently destroy the database — the check now asserts that data is kept, matching the
  script's documented safety guarantee.
- **CI: the test workflow installed `pytest-xdist` but ran serially.** Added `-n auto`, so the
  full suite runs in parallel (~13 min) instead of leaving the dependency unused.
- **CI: the Docker workflow logged `test is not a valid semver` twice.** The `type=semver` tag
  patterns tried to parse the `test` build tag as a version. They are now gated with
  `enable=${{ startsWith(github.ref, 'refs/tags/v') }}`, so they apply only to real `v*` release
  tags and stay quiet for the `test` tag.
- **The Overview syslog card was slow and then reported a plausible `0`.** It called
  `SyslogStore.stats()`, which computes four separate `GROUP BY` aggregations over the whole
  message table (host, app, severity, facility) — the card displays only the total and the
  severity split, so three quarters of that work fed nothing, slow enough on a large store to
  look like a hung widget. `stats()` now takes `only=(…)` to compute just the requested
  breakdowns (omitted ones come back as empty lists, never missing keys) and the card asks for
  `severity` alone. Its `except` also swallowed every failure into `0` messages — indistinguishable
  from a genuinely empty store; it still keeps the card alive but now logs a warning.
- **Standalone pages loaded nothing but an endless spinner.** Two top-level
  `document.getElementById('btn-tab-status').addEventListener(...)` calls in
  `partials/init/_wiring.html` lacked the optional chaining every other tab hook uses. Once the
  admin tab bar stopped being rendered on `/overview`, `/history` and `/syslog`, that element no
  longer existed, so the access threw **outside** the init `try/catch` and aborted the entire
  script before any renderer ran — the page arrived intact and simply never initialised. A static
  test now fails on any unguarded access to a panel-only element (`btn-tab-*`, `subtab-*`).
- **Two spinners at once while a standalone page loaded, and a navbar that assembled in two
  steps.** Every tab pane ships a spinner placeholder in the markup, and on a standalone page that
  pane is `show active` from the first paint — so it sat under the `#loading` overlay as a second
  spinner, both visible from the very first frame, before any script ran. The pane placeholder is
  now emitted only for the panel (where panes are inactive at load and it is what a tab switch
  shows first), and the overlay is handed over to the section's own skeleton right as the render
  starts. The overlay itself stays on every page: it dims the page to block interaction while
  booting, not merely to spin. Separately, the *Admin* button rendered visible while the section
  buttons waited for `applyRoleRestrictions()` — it now carries an empty `data-nav-perm` and goes
  through the same single reveal.
- **The browser's "leave site?" dialog fired on every navigation away from a standalone page.**
  `_isDirty()` read `!document.getElementById(id)?.classList.contains('d-none')`, which evaluates
  to `true` when the element is missing — and the dirty badges live in the Modules/Config panes,
  which a standalone page does not render. Every section was therefore permanently "unsaved". It
  now treats an absent badge as clean. Latent since the badges had always existed; moving the
  sections out of the panel exposed it. Leaving the panel with genuinely unsaved changes is now
  intercepted too, reusing the in-app Cancel/Discard/**Save** modal — the browser's own dialog
  cannot offer Save, and both Modules and Config are resolved before the page is left.
- **DB portability — cross-engine schema evolution.** `add_column_if_missing`/`_apply_incremental`
  no longer emit a bare `ADD COLUMN … NOT NULL` with no default (fatal on a non-empty table in every
  engine): a `NOT NULL` constraint is only rendered when the column carries a default, otherwise the
  column is added nullable (and a warning is logged). A `unique=True` column is now enforced with a
  follow-up `CREATE UNIQUE INDEX` (`ux_<table>_<col>`) instead of an inline `UNIQUE` clause, which
  MySQL/SQLite reject on `ALTER TABLE ADD COLUMN`.
- **History bucket downsampling was SQLite-only.** The time-bucket aggregation used integer division
  that silently returned floats (or errored) on MySQL/PostgreSQL; it now truncates with
  `CAST(FLOOR((ts - ?) / ?) AS <int>)` in both the SELECT and GROUP BY, so downsampled history graphs
  render identically across engines.
- **`/history/diag` used a SQLite-only path** (`PRAGMA table_info` + a private `_conn()`); it now goes
  through the portable connector API (`list_columns`, `fetchone`, `KIND`), so the diagnostics endpoint
  works on any backend.
- **Field-value picker / discovery modal could show stale results.** Opening a picker or a discovery
  modal for one field while a slow request for a previous one was still in flight let the late response
  overwrite the current modal. Each open now takes a generation token; a response whose token no longer
  matches the active open is dropped (`_fpGen` in the field picker, `_discoverGen` in discovery).
- **Sessions tab exposed revoke controls to view-only users.** The card/table revoke buttons, the bulk
  bar and the "close all" header button are now gated on `sessions_revoke` client-side (`_canRevokeSessions()`),
  matching the server-side check, so a user with only `sessions_view` no longer sees dead buttons.
- **Group→role mapping listed custom roles by UID.** The role dropdown built custom-role options from
  the role UID instead of its name, so a mapping to a custom role couldn't resolve; it now uses `rd.name`
  (built-ins by key, customs by name), matching `_role_name_to_uid`.
- **Field rename/delete left orphaned entries in the multi-select set.** Renaming or deleting a
  collection item didn't update `_modItemSel`, so a stale `parent|key` selection lingered (and a rename
  lost the selection); both now fix up the set.
- **Config tab could open on a hidden tab / servers "migrate" crashed on a memberless cluster.** The
  active-config-tab fallback now snaps to the first available tab when the remembered one is gone, and
  the migrate modal guards `cluster.members` (`|| []`) at both the `.map` and `.length` sites.
- **`_fmtDateTime` returned "Invalid Date" for unparseable values** instead of echoing the original
  string; it now falls back to the raw input.
- **Built-in Editor role now includes `credentials_view` + `credentials_edit`.** The editor could
  configure modules that use reusable credentials but couldn't see or edit the credentials themselves;
  granted via `roles: ('editor',)` on those two flags in `credentials/permissions.py` (add/delete stay
  admin-only).
- **Overview card hover effects broke at the corners.** Both the `.dw-clickable:hover` outline and the
  "pop" glow box-shadow traced a square-ish box (the outline used the default `--bs-border-radius`; the
  glow used `.dw`'s unset radius), while every card rounds with `.rounded-3` (`--bs-border-radius-lg`),
  so the page background showed through at the rounded corners on hover. `.dw` now carries that radius,
  so both effects hug the card corners. Separately, the stat cards' top **accent bar** now rounds its
  own top corners (`border-radius: …-lg …-lg 0 0`, in both `_dwStatCard` and `_dwMwStatCard`) instead
  of relying on the card's `overflow:hidden` clip: Chromium drops that clip at the corner while an
  ancestor is `transform`-scaled (the hover "pop"), so the square accent corner poked past the card's
  rounded corner. (Verified with a headless-Edge screenshot of the exact markup + CSS.)
- **Overview module stat cards pop by a fixed small amount** (a `dw-module` class). A wide card popped
  with the core's proportional `scale(1.04)` ballooned — overflowing the viewport and overlapping its
  neighbours. `_dwOnGridHover` now sets `--dw-pop = 1 + 8px/width` (capped at 1.04), so a wide card
  grows the same ~8px a narrow one does, and points `transform-origin` at the side with room; the
  neighbours also recede (they did already for core cards), so the popped card has space instead of
  overlapping. Verified with a headless-Edge measurement (cols-8 at the left edge: scale 1.0148,
  8px growth, no overlap, on-screen). Plus glow + a crisp outline; only the stat-card view pops
  (tables don't). Compact core stat cards are unchanged.
- **Stylesheet cache-busting.** `web_admin.css` is now linked with a `?v=<mtime>` query, so an edited
  stylesheet always reaches the browser. The dev watcher doesn't restart on `.css`, and the plain URL
  was cacheable, so earlier CSS-only fixes could silently not take effect until a hard refresh.
- **Overview edit-mode toolbar showed a module widget's raw id** (e.g. `mw_m365:0`) instead of its
  title: the label fell back to the widget id because module widgets have no `lkey`; it now uses
  `_dwLabel(def)` (the module's translated `pretty_name`, e.g. "Microsoft 365").
- **Multicheck modules — live per-check checklist + status reasons.** A module whose item runs
  several sub-checks (m365: SharePoint/tenant/health/licenses/secrets/mailbox/OneDrive/Secure
  Score/risky users) can declare them in the schema (`list.__multicheck__` = `[{toggle, suffix}]`).
  The item's **Check** button then opens a checklist modal **immediately**, lists every enabled
  sub-check with a spinner, and runs each on its own request (`test_connection` honours a `_service`
  suffix → runs just that one), ticking each row ✅/⚠️ with its reason as the result arrives — no
  more waiting for the whole batch before anything shows. The **Status** card now also prints each
  non-OK check's message (the reason) under its name, and the m365 checks' failure paths carry a
  friendly name so a failed sub-check shows e.g. "… · OneDrive (tenant)" instead of the raw
  `<item>/onedrive` key. m365's **service health is now one check per service** (`<item>/health/<svc>`):
  with no filter it auto-surfaces just the **affected** services from Microsoft's API (a single
  aggregate OK row when all are healthy); with a `health_services` filter it shows each chosen
  service (OK or not), and that filter is **discoverable** (`list_services` feeds a multi-select
  picker, so you pick services without knowing their names). Each service's raw Microsoft status
  code (`serviceDegradation`, `serviceInterruption`, `investigating`, …) is now shown as a
  **human-readable label with a ✅/⚠️/🔴 icon** (new `health_states` i18n map, read via a generalised
  `ModuleBase._module_lang_section`) — so a degradation reads warning and an interruption reads
  error, in the Status card *and* in Telegram/email notifications. The live checklist expands a
  sub-check that returns several results (like per-service health) into a row each, and the discover
  picker now **opens immediately with a loading state** instead of freezing the button until data
  arrives. The risky-users check no longer 400s (`$top` capped at the API's 500).
- **Test fix**: `test_wa_hosts::TestApiMigrate::test_preview_and_apply` asserted the migrated SNMP
  `community` by reading `/api/v1/modules`, which now masks it (`community` is `secret: true`) — so
  it read `None`. It now verifies the value survived the migration against the decrypted stored
  config (`_load_modules()`).
- **Monitor now prunes orphan check status**: the monitor only ever *set* status keys, never
  removed them, so a deleted item / disabled sub-check left its last status lingering forever (the
  root cause behind the m365 phantom, and stale rows for removed items generally). Each cycle a
  module's result now prunes the keys it no longer covers: a stale **result** key (carrying a
  `status`) is dropped immediately, while a **bookkeeping-only** key (no `status` — e.g. a bare item
  key holding just `fail_count` while results live under `<item>/site`) is kept as long as any
  sub-key of that item is still reported, so an in-flight failure streak survives. Pruning runs only
  when the module ran and returned a result set, so an errored/timed-out module never wipes its
  last-known state. The Status card also stops counting bookkeeping-only entries as checks.
- **m365 showed a phantom extra check per item**: a single item reported two results (e.g.
  `item_1 · Microsoft 365` Error **and** `item_1 · SharePoint` OK). The check emitted a success under
  a per-service key (`<item>/site`, `<item>/tenant`) but a pre-service failure (no creds / auth)
  under the **bare item key** — and the monitor never prunes keys a module stops emitting, so once
  auth started working the old base-key error lingered forever beside the real result. Failures now
  report under the SAME per-service keys, so a later success overwrites them; and the monitor now
  prunes orphan status (below), so any pre-existing base-key result clears on the next cycle.
- **m365 auth error was unreadable**: a failed token request showed only `Auth: HTTP 400: Bad
  Request`, hiding the cause. `_graph_error` only parsed Graph's `{"error": {"message": …}}` shape,
  but the OAuth token endpoint returns `{"error": "invalid_client", "error_description":
  "AADSTS…"}` (with `error` as a string) — so `('invalid_client').get('message')` threw and the real
  reason was dropped. It now handles both shapes, surfacing the AADSTS code (e.g. *AADSTS7000215:
  Invalid client secret provided* → expired/wrong secret; *AADSTS90002* → wrong tenant) so the test
  says exactly what to fix.
- **Servers "test" results**: two probe fixes. (1) Check messages were shown as their raw i18n key
  (`cpu_ok`, `dns_ok`, `ssl_expiring`…) instead of the translated text, because the probe monitor
  (`lib/core/hosts/probe.py`) left `dir_modules=''`, so `ModuleBase._msg` couldn't load each module's
  `lang/<lang>.json` and fell back to the key. The probe now receives `modules_dir` (to resolve the
  message catalogs) and the global config (`notify_cfg`, so messages use the configured notification
  language + admin text overrides), matching how notifications/Status render them. (2) A per-item
  field that inherits a **module-level** setting (e.g. `ssl_cert` *warning_days*, blank → inherit)
  used the hardcoded default (30) in the test instead of the configured module value, because the
  probe passed only the tested collection's items — not the module-level scalar settings. `_run_checks`
  now merges the saved module-level fields so `get_conf()` resolves them.
- **module config UI**: per-item numeric fields that inherit a module-level setting via
  `placeholder_module` now show the inherited value as the placeholder (they were blank). The
  fallback wrongly used `CONFIG_FIELD_DEFAULTS['modules|<field>']`, but that JS constant only holds a
  few `web_admin|*` keys — never module defaults — so it always resolved to `undefined`. Resolution
  now cascades module-level value → live *Configuration → Modules* value → the module's own
  `__module__` schema default (via a shared `_placeholderModuleValue` helper), and a genuine `0` is
  shown (e.g. datastore *Max connections* → `0` = "no limit"; DNS item *Timeout* → the module default).
  The live placeholder refresh (`_refreshConditionalFields`, on item expand) kept the old broken
  logic — it read only `modulesData[mod][field]` and suppressed `0`, so **expanding an item wiped the
  correct placeholder the render had just set**; it now reuses the same `_placeholderModuleValue`
  cascade so the inherited value survives expand.
- **notifications UI**: the routing matrix no longer repeats a section header. Rows are now grouped
  by source so each subheader (Monitoring / IP ban / Authentication / Service control / …) appears
  once with its events contiguous, even when different sources interleave by `order` (previously the
  header re-emitted on every source change, so *Authentication* and *Service control* showed twice).
- **notifications**: starting/stopping **syslog**, the **event processor** or the internal
  **fail2ban** from the Services tab sent no notification (only an audit entry) — only the monitoring
  scheduler did (`scheduler_started`/`scheduler_stopped`). Added generic operator lifecycle events
  `service_started` / `service_stopped` (source *Service control*), dispatched **synchronously at the
  control point** — in each service's embedded `control()` and in `_control_external` (so a split/
  microservices toggle notifies from the operator's instance immediately, instead of waiting for the
  remote worker's reconcile). Monitoring keeps its own scheduler events (`_LIFECYCLE_NOTIFY = False`
  on `EmbeddedMonitor`, no double-fire). New routing-matrix rows (opt-in, default off) + i18n
  (en_EN/es_ES). The `service_down`/`service_up` (platform health) events are unchanged: those are
  crash detection and still ignore a clean operator start/stop.
- **audit**: two audit events showed their raw key instead of a label in the Audit tab —
  `entra_saml2_graph_secret` (SAML2 provisioning creates the Graph client secret) and
  `notif_text_saved` (unified notification-text editor). Both added to the `audit_events` i18n dict
  (en_EN/es_ES, parity kept). Verified no other emitted audit event is missing a translation.
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
- **Generalised the Entra doc and split out IdP-agnostic SCIM.** `caso-sso-entra.md` →
  `caso-entra-id.md`, broadened from "SSO" to all Entra-specific material (OIDC, SAML2 and the
  Device-Code app-registration wizards for SSO/SCIM/M365-email/Teams). New `caso-scim.md` is the
  single source for **generic SCIM 2.0 provisioning** (IdP-agnostic per RFC 7643/7644): enable +
  token + base URL, JIT-vs-SCIM, configuring Entra/Okta/other IdPs, user/group de-provisioning and
  group soft-delete, badges — pointing to `ref-api.md` (endpoints), `explica-seguridad.md`
  (security) and `caso-entra-id.md` (the Entra auto-registration shortcut). The Entra doc keeps
  only the Entra-specific SCIM registration. All inbound links (docs index/topic map + the 8
  referring docs) rewritten; 0 broken links/anchors verified.
- **Added Mermaid flow/diagram coverage for the requested areas** (all from ground-truth code
  reads): a module **dependency (layer) graph** in `explica-arquitectura.md` (the component,
  start, check-cycle and delivery diagrams already existed); an **authentication flow** section in
  `explica-seguridad.md` (sequence diagrams for local login and SSO OIDC/SAML2/Teams — all
  converging on `_establish_session()` — plus a per-request `_check_session()` flowchart); and an
  **API call flow** section in `ref-api.md` (request-lifecycle sequence with the CSRF/401/403
  branches + a layered call-flow flowchart route→service→store→connector).
- **Added worked examples** alongside the new diagrams: an illustrative `oidc` config block + a
  local-login `curl` in the auth section, and a `PUT /api/v1/config` request/response (200 +
  403-CSRF shapes) in the API section.
- **Removed macOS from the documentation** (not currently supported or tested): platform tables and
  "multiplataforma" claims now read Linux/Windows, macOS-only command rows (`launchctl`,
  `sysctl`/`vm_stat`) and the `darwin` schema examples were dropped across README, `ref-modulos`,
  `explica-arquitectura`, `ref-configuracion`, `ref-schema-json`, `caso-desarrollo`,
  `caso-guia-watchful` and `caso-ssh-hardening` (FreeBSD/BSD kept). The `test_darwin*` rows in
  `ref-tests.md` and the macOS mentions in `ai-module-guide.md` were left untouched — the former
  are real test names (removing them would misrepresent the suite), the latter is exempt from the
  reorg; note the module code still contains `darwin` paths even though macOS is unsupported.
- **Documentation reorganised with a type-prefixed naming convention and a single-source-of-truth
  policy.** Every doc is now prefixed by its type — `ref-` (reference/look-up), `explica-`
  (explanation/how-it-works), `caso-` (case/how-to) — with Spanish stems (e.g. `architecture.md` →
  `explica-arquitectura.md`, `api-reference.md` → `ref-api.md`, `deployment.md` →
  `caso-despliegue.md`; 25 files renamed). `README.md` and `ai-module-guide.md` are exempt. All
  inbound links were rewritten — cross-doc links, the docs index/topic map, and the code-comment
  pointers in `watchfuls/*/watchful.py` and tests — with 0 broken links/anchors verified.
- **Mixed docs split into ref + explica, one SSOT per topic.** New `ref-permisos.md` (the RBAC
  catalog: 63 permission flags, roles, groups, dynamic perms — extracted from web-admin, now the
  single source) and `ref-i18n.md` (tag schemas + `lang/*.json` structure + `_fill` — extracted
  from i18n). The Debug/logging explanation moved out of the config reference into
  `explica-logging.md`. Duplicated topics across docs (concurrency, DB schema/reconcile, service
  topology, REST control-plane, config/env vars, notification grouping, schema.json reference,
  discovery, host model, reverse-proxy) were trimmed to a summary + pointer to their SSOT.
- **Doc/code contradictions reconciled against ground truth.** Permission count corrected 52 → **63**
  (`ref-permisos.md` canonical; the stale table removed from security). Per-module thread pool cap
  documented as `min(len(módulos), 16)` (architecture previously implied unbounded). Action/button
  `variant` examples changed from `outline-*` to solid variants (the actual convention). `info.json`
  `dependencies` documented as **required** (enforced by `test_info_json_has_required_keys`).
  `input_action.result` corrected to `toast|list|field_picker|modal|fields`. The `_DEFAULTS`
  snippet fixed to exclude `__*__` meta-keys (`ModuleBase._schema_defaults`). The misleading global
  "SSH RejectPolicy default" note corrected (only `Exec` uses it; host-aware path defaults to
  `AutoAddPolicy`). Deprecated `@write_required`/`@admin_required` decorators flagged as unused.
- **New reference docs for previously-undocumented areas, all generated from ground-truth code
  reads.** Added `docs/api-reference.md` (complete, authoritative REST inventory: route
  architecture — no blueprints, thin routes + Flask-free service layer —, CSRF/versioning, and
  every endpoint by domain with method/path/permission/purpose + examples), `docs/db-schema.md`
  (the 32 runtime tables with columns/types/indexes, an ER Mermaid diagram, and the
  reconcile/multi-engine portability mechanism), `docs/performance.md` (concurrency model,
  bottlenecks, caches, table row caps, scaling), and `docs/logging.md` (the custom `Debug`
  system + the residual unconfigured stdlib `logging` path). Extended `docs/README.md` with an
  index entry per new doc plus a topic map (documentation-outline → doc).
- **Corrected stale facts across existing docs** found while cross-checking against the code:
  `web-admin.md` REST tables — hosts use the `servers_*` family (not `modules_*`), history
  `test-write`/`diag` require `history_view` (not `history_delete`), Entra ID provisioning
  requires `credentials_add`/`credentials_edit` (not `config_edit`), the IP-ban endpoints use the
  granular `ipban_*` family (not `config_*`), roles/groups paths are `<uid>` (not `<name>`), and
  `/logout` is POST; a pointer to `api-reference.md` as the maintained source was added.
  `configuration.md` — `--verbose`/`SS_VERBOSE` only enables Flask's interactive debugger and does
  NOT change the log level (use `--log-level`). `security.md` — the encrypted-fields table now
  includes `graph_secret`/`idp_cert`/`webhook_url`/`bot_app_password`, and the runtime-transparency
  note reflects that editable config is written encrypted to the DB via `ConfigManager`
  (`_save_config_file` no longer exists on `WebAdmin`). `development.md` — added the missing
  dependencies `jinja2`, `dnspython`, `pysnmp`, `pysmi`, `PyJWT`, and a note that M365/Entra uses
  `requests`+`PyJWT` (not `msal`) and that non-core deps are lazily imported.
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
- **`troubleshooting.md` — nuevo registro de bugs resueltos y trampas conocidas**: documenta
  fallos no evidentes con su causa raíz, solución y lección generalizable (formato de fichas:
  Síntoma / Diagnóstico / Causa raíz / Solución / Lección), separado del changelog. Primera
  entrada: el placeholder heredado (`placeholder_module`) que el render fijaba bien pero
  `_refreshConditionalFields` borraba al expandir el item por usar lógica divergente. Añadido al
  índice de `docs/README.md`.

### Notes
- **Deferred by decision**: `fail2ban` (IP bans) and `events` stay as tabs inside the admin panel
  for now. Both are operational surfaces that would fit the standalone-page treatment Overview,
  History and Syslog now get — the `HOME_PAGES` registry takes them without new machinery (a
  `standalone` spec plus their existing render entry point), so this is a decision, not a
  limitation.
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
