"""Mixin classes for WebAdmin — internal use only.

The background services (monitoring / syslog / events) are no longer mixins: the
WebAdmin composes one embedded object per service (``lib.services.*.embedded``),
discovered and controlled by :class:`_ServicesMixin`.  Core domains (users, roles,
groups, sessions, permissions, …) carry their own mixin inside their
``lib.core.<domain>`` package and are imported directly by :mod:`lib.web_admin.app`.

What is left here is the glue that belongs to no domain: ``auth`` (the login/session
lifecycle of the panel itself) and ``services`` (which discovers and controls the
embedded services rather than owning one).
"""
from .auth import _AuthMixin
from .services import _ServicesMixin

__all__ = [
    '_AuthMixin',
    '_ServicesMixin',
]
