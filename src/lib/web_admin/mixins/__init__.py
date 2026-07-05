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
from .auth import _AuthMixin
from .checks import _ChecksMixin
from .services import _ServicesMixin
from .ipban import _IpBanMixin

__all__ = [
    '_UsersMixin',
    '_RolesMixin',
    '_GroupsMixin',
    '_PermissionsMixin',
    '_SessionsMixin',
    '_AuditMixin',
    '_AuthMixin',
    '_ChecksMixin',
    '_ServicesMixin',
    '_IpBanMixin',
]
