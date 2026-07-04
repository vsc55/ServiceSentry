#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Route registration — delegates to sub-modules."""

from .auth import register as _auth
from .auth.ldap import register as _ldap
from .auth.entraid import register as _entraid
from .notify.telegram import register as _telegram
from .notify.email import register as _email
from .notify.webhook_test import register as _webhook
from .notify.templates import register as _notif_templates
from .notify.webhooks import register as _webhooks
from .modules import register as _modules
from .modules.checks import register as _checks
from .users import register as _users
from .users.roles import register as _roles
from .users.groups import register as _groups
from .sessions import register as _sessions
from .sessions.audit import register as _audit
from .config import register as _config
from .hosts import register as _hosts
from .credentials import register as _credentials
from .watchfuls import register as _watchfuls
from .daemon import register as _daemon
from .history import register as _history
from .syslog import register as _syslog
from .services import register as _services
from .events import register as _events
from .scim import register as _scim
from .util import register as _util
from .ui import register as _ui
from .status import register as _status
from .errors import register as _errors


def register_all(app, wa):
    _auth(app, wa)
    _ui(app, wa)
    _status(app, wa)
    _errors(app, wa)
    _modules(app, wa)
    _config(app, wa)
    _hosts(app, wa)
    _credentials(app, wa)
    _telegram(app, wa)
    _ldap(app, wa)
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
    _util(app, wa)
