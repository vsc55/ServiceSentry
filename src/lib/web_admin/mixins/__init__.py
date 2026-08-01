"""Mixin classes for WebAdmin — internal use only.

The background services (monitoring / syslog / events) are no longer mixins: the
WebAdmin composes one embedded object per service (``lib.services.*.embedded``),
discovered and controlled by :class:`_ServicesMixin`.  Core domains (users, roles,
groups, sessions, permissions, …) carry their own mixin inside their
``lib.core.<domain>`` package and are imported directly by :mod:`lib.web_admin.app`.

What is left here is the glue that belongs to no domain, and four of these were carved out of
``app.py`` — which had grown to 1119 lines with a single 372-line method inside it:

* ``context``   the dictionary every template renders with;
* ``hooks``     what runs around every request, in a DECLARED order (Flask takes it from
                registration order, so it used to be the order of five decorators);
* ``guards``    who may call a route, and the shape of the refusal;
* ``server``    binding the interfaces and serving, fail-soft per interface, fail-hard overall.

The rest were already here: ``auth`` (the login/session lifecycle of the panel itself),
``services`` (which discovers and controls the embedded services rather than owning one),
``stores``, ``scanners``, ``embed`` and ``freshness`` (the same three lines that keep roles,
users and groups from going stale when this process is not the only writer).

What stayed in ``app.py`` is what it is for: the class, ``__init__`` composing the object in an
order its own comments explain, and ``_create_app`` assembling the Flask app from the pieces
above.
"""
from .auth import _AuthMixin
from .context import _ContextMixin
from .embed import _EmbedMixin
from .freshness import _FreshnessMixin
from .guards import _GuardsMixin
from .hooks import _HooksMixin
from .scanners import _ScannersMixin
from .server import _ServerMixin
from .services import _ServicesMixin
from .stores import _StoresMixin

__all__ = [
    '_AuthMixin',
    '_ContextMixin',
    '_EmbedMixin',
    '_FreshnessMixin',
    '_GuardsMixin',
    '_HooksMixin',
    '_ScannersMixin',
    '_ServerMixin',
    '_ServicesMixin',
    '_StoresMixin',
]
