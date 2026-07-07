"""Mixin classes for WebAdmin — internal use only.

The background services (monitoring / syslog / events) are no longer mixins: the
WebAdmin composes one embedded object per service (``lib.services.*.embedded``),
discovered and controlled by :class:`_ServicesMixin`.  Core domains (users, roles,
groups, sessions, …) carry their own mixin inside their ``lib.core.<domain>``
package and are imported directly by :mod:`lib.web_admin.app`.
"""
from .permissions import _PermissionsMixin
from .auth import _AuthMixin
from .services import _ServicesMixin

__all__ = [
    '_PermissionsMixin',
    '_AuthMixin',
    '_ServicesMixin',
]
