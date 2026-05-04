#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Route registration — delegates to sub-modules."""

from .auth import register as _auth
from .ui import register as _ui
from .modules import register as _modules
from .config import register as _config
from .telegram import register as _telegram
from .users import register as _users
from .sessions import register as _sessions
from .audit import register as _audit
from .roles import register as _roles
from .groups import register as _groups
from .checks import register as _checks


def register_all(app, wa):
    _auth(app, wa)
    _ui(app, wa)
    _modules(app, wa)
    _config(app, wa)
    _telegram(app, wa)
    _users(app, wa)
    _sessions(app, wa)
    _audit(app, wa)
    _roles(app, wa)
    _groups(app, wa)
    _checks(app, wa)
