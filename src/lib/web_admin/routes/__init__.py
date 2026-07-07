#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Route registration — delegates to sub-modules."""

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
from lib.core.modules.routes import register as _modules
from lib.services.monitoring.routes.checks import register as _checks
from lib.core.users.routes import register as _users
from lib.core.roles.routes import register as _roles
from lib.core.groups.routes import register as _groups
from lib.core.sessions.routes import register as _sessions
from lib.core.audit.routes import register as _audit
from lib.core.config.routes import register as _config
from lib.core.hosts.routes import register as _hosts
from lib.core.credentials.routes import register as _credentials
from lib.core.modules.watchful_routes import register as _watchfuls
from lib.services.monitoring.routes.daemon import register as _daemon
from lib.core.history.routes import register as _history
from lib.services.syslog.routes import register as _syslog
from lib.services.control.routes import register as _services
from lib.services.events.routes import register as _events
from lib.providers.scim.routes import register as _scim
from lib.services.ipban.routes import register as _ipbans
from .util import register as _util
from .ui import register as _ui
from .status import register as _status
from .errors import register as _errors
from lib.core.overview.routes import register as _overview


def register_all(app, wa):
    _auth(app, wa)
    _ui(app, wa)
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
    _entraid(app, wa)
    _users(app, wa)
    _sessions(app, wa)
    _audit(app, wa)
    _roles(app, wa)
    _groups(app, wa)
    _checks(app, wa)
    _watchfuls(app, wa)
    _daemon(app, wa)
    _history(app, wa)
    _syslog(app, wa)
    _services(app, wa)
    _events(app, wa)
    _scim(app, wa)
    _ipbans(app, wa)
    _util(app, wa)
