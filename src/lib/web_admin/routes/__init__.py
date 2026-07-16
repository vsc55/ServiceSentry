#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central route registration — ``register_all(app, wa)`` wires every route module.

Routes live with the thing they serve (each domain/service/provider registers its own from
its package).  This docstring is the index of the whole URL surface and where each part is
registered; every listed file's own header lists its exact per-endpoint routes.

── core domains — lib/core/<d>/routes.py ────────────────────────────────────────────
    users            /api/v1/users*
    roles            /api/v1/roles*
    groups           /api/v1/groups*
    sessions         /api/v1/sessions*
    audit            /api/v1/audit*
    config           /api/v1/config*            (+ /config/versions, /config/layout, /config/schema)
    credentials      /api/v1/credentials*
    history          /api/v1/history*
    hosts            /api/v1/hosts*             (perm group 'servers')
    modules          /api/v1/modules*           (+ /modules/checks/run, /modules/watchfuls/<mod>/<action>)
    overview         /api/v1/overview*
    notify/email     /api/v1/notify/email/test  (+ template_routes: /notify/templates*, /notify/html-templates*)
    notify/telegram  /api/v1/notify/telegram/test
    notify/webhook   /api/v1/notify/webhooks*   (+ test_routes: /notify/webhook/test)
    notify/msteams   /api/v1/notify/msteams*    (Teams channels CRUD + user test; bot inbound at /auth/msteams/messages)

── background services — lib/services/<svc>/routes.py ───────────────────────────────
    manager          /api/v1/services*          (service control plane; folder lib/services/manager)
    monitoring       /api/v1/monitoring*        (scheduler; the on-demand run is /api/v1/modules/checks/run, in modules)
    syslog           /api/v1/syslog*            (+ /syslog/drops*)
    events           /api/v1/event/rules*, /api/v1/event/notifications
    ipban            /api/v1/ipbans*

── auth providers — lib/providers/<x>/routes.py ─────────────────────────────────────
    ldap             /api/v1/auth/ldap/*        (JSON: connection test / group lookup)
    entraid          /api/v1/auth/entraid/*     (JSON: Entra app-registration + SCIM-provisioning device-code)
    entraid (sso)    /auth/msteams/tab, /auth/msteams/sso   (Microsoft Teams personal-tab SSO sign-in)
    oidc             /auth/oidc/*               (browser OAuth redirect flow — login/callback, NOT /api/v1)
    saml             /auth/saml2/*              (browser SAML flow — login/acs/metadata, NOT /api/v1)
    scim             /scim/v2/*                 (IETF RFC 7643/7644 standard — outside /api/v1; external IdPs call it)

── web — lib/web_admin/routes/*.py ──────────────────────────────────────────────────
    auth             /login, /logout            (local login; oidc/saml/ldap providers above)
    pages            /, /admin, /overview       (rendered HTML views)
    overview2        /overview2                 (experimental Alpine.js Overview — real widgets + data)
    ui               /lang/<code> (navigation), /api/v1/me, /api/v1/health
    status           /status                    (public status page, no auth)
    util             /api/v1/util/*
    errors           (Flask error handlers — no URL routes)

── path convention ──────────────────────────────────────────────────────────────────
    Internal JSON APIs the frontend calls → ``/api/v1/<domain>/*`` (session + CSRF).
    Endpoints hit by EXTERNAL systems or an embedding host (IdP callbacks, embedded pages,
    provider webhooks) → ``/auth/<provider>/*`` (+ the IETF-mandated ``/scim/v2/*``): these are
    CSRF-exempt (each module self-declares its prefixes via ``wa._register_csrf_exempt`` in its
    register(), discovered — not hardcoded) and authenticated by their own protocol/token, not
    the session. Teams external endpoints: ``/auth/msteams/{tab,sso,messages}``.
"""

from .auth import register as _auth
from lib.providers.ldap.routes import register as _ldap
from lib.providers.oidc.routes import register as _oidc
from lib.providers.saml.routes import register as _saml
from lib.providers.entraid.routes import register as _entraid
from lib.core.notify.telegram.routes import register as _telegram
from lib.core.notify.email.routes import register as _email
from lib.core.notify.webhook.test_routes import register as _webhook
from lib.core.notify.email.template_routes import register as _notif_templates
from lib.core.notify.webhook.routes import register as _webhooks
from lib.core.notify.msteams.routes import register as _msteams
from lib.core.modules.routes import register as _modules
from lib.services.monitoring.routes import register as _monitoring
from lib.core.users.routes import register as _users
from lib.core.roles.routes import register as _roles
from lib.core.groups.routes import register as _groups
from lib.core.sessions.routes import register as _sessions
from lib.core.audit.routes import register as _audit
from lib.core.config.routes import register as _config
from lib.core.hosts.routes import register as _hosts
from lib.core.credentials.routes import register as _credentials
from lib.core.history.routes import register as _history
from lib.services.syslog.routes import register as _syslog
from lib.services.manager.routes import register as _services
from lib.services.events.routes import register as _events
from lib.providers.scim.routes import register as _scim
from lib.services.ipban.routes import register as _ipbans
from .util import register as _util
from .ui import register as _ui
from .pages import register as _pages
from .overview2 import register as _overview2   # experimental Alpine Overview (/overview2)
from lib.providers.entraid.sso_routes import register as _msteams_sso   # Teams personal-tab SSO
from .status import register as _status
from .errors import register as _errors
from lib.core.overview.routes import register as _overview


def register_all(app, wa):
    _auth(app, wa)
    _ui(app, wa)
    _pages(app, wa)
    _overview2(app, wa)
    _msteams_sso(app, wa)
    _status(app, wa)
    _errors(app, wa)
    _modules(app, wa)
    _overview(app, wa)
    _config(app, wa)
    _hosts(app, wa)
    _credentials(app, wa)
    _telegram(app, wa)
    _ldap(app, wa)
    _oidc(app, wa)
    _saml(app, wa)
    _email(app, wa)
    _webhook(app, wa)
    _notif_templates(app, wa)
    _webhooks(app, wa)
    _msteams(app, wa)
    _entraid(app, wa)
    _users(app, wa)
    _sessions(app, wa)
    _audit(app, wa)
    _roles(app, wa)
    _groups(app, wa)
    _monitoring(app, wa)
    _history(app, wa)
    _syslog(app, wa)
    _services(app, wa)
    _events(app, wa)
    _scim(app, wa)
    _ipbans(app, wa)
    _util(app, wa)
