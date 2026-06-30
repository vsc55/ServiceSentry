"""Mixin classes for WebAdmin — internal use only.

The background services (monitoring / syslog / events) are no longer mixins: the
WebAdmin composes one embedded object per service (``lib.services.*.embedded``),
discovered and controlled by :class:`_ServicesMixin`.
"""
from .users import _UsersMixin
from .roles import _RolesMixin
from .groups import _GroupsMixin
from .permissions import _PermissionsMixin
from .sessions import _SessionsMixin
from .audit import _AuditMixin
from .checks import _ChecksMixin
from .services import _ServicesMixin

__all__ = [
    '_UsersMixin',
    '_RolesMixin',
    '_GroupsMixin',
    '_PermissionsMixin',
    '_SessionsMixin',
    '_AuditMixin',
    '_ChecksMixin',
    '_ServicesMixin',
]
