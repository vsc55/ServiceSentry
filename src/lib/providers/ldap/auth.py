#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LDAP / Active Directory authentication for web_admin.

Requires the optional ``ldap3`` package (``pip install ldap3``).
If not installed, ``is_available()`` returns False and all auth attempts
raise ``LdapUnavailableError``.
"""

import json
import ssl
import uuid

from lib.config.spec import cfg_default, cfg_get
from lib.debug import DebugLevel

_HAS_LDAP3 = False
try:
    from ldap3 import NONE, SUBTREE, Connection, Server, Tls
    from ldap3.core.exceptions import LDAPException
    _HAS_LDAP3 = True
except Exception:
    Server = Connection = NONE = SUBTREE = Tls = None
    LDAPException = Exception


class LdapUnavailableError(RuntimeError):
    """Raised when ldap3 is not installed."""


def is_available() -> bool:
    """Return True when the optional ``ldap3`` package is installed; when False,
    LDAP auth is disabled and :func:`authenticate` fails with ``ldap_unavailable``."""
    return _HAS_LDAP3


# ── Config helpers ──────────────────────────────────────────────────────────

def _get_config(wa) -> dict:
    return wa._config_section('ldap')


def _get_group_role_map(cfg: dict) -> dict:
    raw = cfg.get('group_role_map') or cfg_default('ldap|group_role_map')
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Role/group mapping ───────────────────────────────────────────────────────

def _map_role(group_vals: list, group_role_map: dict) -> str:
    """Return the best-matching app role from LDAP group list.

    Priority order: admin > editor > viewer (first match wins for each tier).
    Falls back to '' (no role) if nothing matches.
    """
    priority = ['admin', 'editor', 'viewer']
    matched: dict[str, str] = {}  # role_name → first matching group

    for group_val in group_vals:
        gv = str(group_val)
        # Exact-match candidates: the raw value AND, when it is a DN (AD `memberOf` returns
        # full DNs), its first RDN value (the CN). This lets a short-name pattern ("Admins")
        # match `CN=Admins,OU=…` WITHOUT the substring escalation that would also match
        # "Admins-ReadOnly" (whose CN is "admins-readonly", a distinct exact token).
        candidates = {gv.lower()}
        first_rdn = gv.split(',', 1)[0]
        if '=' in first_rdn:
            candidates.add(first_rdn.split('=', 1)[1].strip().lower())
        for pattern, role in group_role_map.items():
            if pattern.lower() in candidates and role not in matched:
                matched[role] = group_val

    for role in priority:
        if role in matched:
            return role

    # Any custom role that matched
    for role in matched:
        return role

    return ''


# ── Core authenticate ────────────────────────────────────────────────────────

def authenticate(wa, username: str, password: str) -> tuple:
    """Try to authenticate *username*/*password* against the configured LDAP.

    Returns:
        (attrs_dict, None)   — success; attrs_dict has display_name, email, groups
        (None, reason_str)   — failure; reason is one of:
            'ldap_unavailable', 'ldap_disabled', 'ldap_connection_error',
            'ldap_user_not_found', 'ldap_invalid_credentials'
    """
    wa._dbg(f"> Auth/LDAP >> authenticate user={username!r}", DebugLevel.info)
    if not _HAS_LDAP3:
        return None, 'ldap_unavailable'

    # Reject empty password up front: many LDAP/AD servers treat a bind with a
    # valid DN and an empty password as an *unauthenticated bind* that succeeds
    # (RFC 4513), which would be an authentication bypass.
    if not password:
        return None, 'ldap_invalid_credentials'

    cfg = _get_config(wa)
    if not cfg.get('enabled'):
        return None, 'ldap_disabled'

    server_host = cfg.get('server', '')
    port        = cfg_get(cfg, 'ldap|port')
    use_ssl     = cfg_get(cfg, 'ldap|use_ssl')
    ssl_verify  = cfg_get(cfg, 'ldap|ssl_verify')
    timeout     = cfg_get(cfg, 'ldap|timeout')
    bind_dn     = cfg.get('bind_dn', '')
    bind_pass   = cfg.get('bind_password', '')
    base_dn     = cfg.get('base_dn', '')
    user_filter   = cfg_get(cfg, 'ldap|user_filter')
    email_attr    = cfg_get(cfg, 'ldap|email_attr', falsy=True)
    name_attr     = cfg_get(cfg, 'ldap|name_attr', falsy=True)
    username_attr = cfg.get('username_attr', '') or ''
    group_attr    = cfg_get(cfg, 'ldap|group_attr', falsy=True)
    allow_email   = cfg_get(cfg, 'ldap|allow_email_login')

    search_filter = user_filter.replace('{username}', _ldap_escape(username))
    # If email login is enabled and username looks like an email, also try email attribute
    if allow_email and '@' in username:
        email_attr_filter = f'({email_attr}={_ldap_escape(username)})'
        base_filter = user_filter.replace('{username}', _ldap_escape(username.split('@')[0]))
        search_filter = f'(|{base_filter}{email_attr_filter})'
    # 'dn' is not a valid LDAP attribute — it is always available as entry.entry_dn
    attrs = [email_attr, name_attr, group_attr]
    if username_attr:
        attrs.append(username_attr)

    wa._dbg(f"> Auth/LDAP >> bind+search server={server_host}:{port} ssl={use_ssl} base={base_dn!r}",
            DebugLevel.debug)
    try:
        # LDAPS: validate the server certificate by default (ssl_verify) — without an
        # explicit Tls, ldap3 defaults to CERT_NONE, which lets a network attacker MITM the
        # connection and capture the bind credentials. Admins can disable it (self-signed labs).
        tls = Tls(validate=ssl.CERT_REQUIRED if ssl_verify else ssl.CERT_NONE) if use_ssl else None
        srv  = Server(server_host, port=port, use_ssl=use_ssl, tls=tls,
                      get_info=NONE, connect_timeout=timeout)
        conn = Connection(srv, user=bind_dn or None, password=bind_pass or None,
                          auto_bind=True, receive_timeout=timeout)
    except Exception as exc:
        wa._dbg(f"> Auth/LDAP >> connection/bind failed: {exc}", DebugLevel.warning)
        return None, 'ldap_connection_error'

    try:
        conn.search(base_dn, search_filter, search_scope=SUBTREE, attributes=attrs)
    except Exception as exc:
        conn.unbind()
        wa._dbg(f"> Auth/LDAP >> search failed: {exc}", DebugLevel.warning)
        return None, 'ldap_connection_error'

    if not conn.entries:
        conn.unbind()
        wa._dbg(f"> Auth/LDAP >> user {username!r} not found", DebugLevel.info)
        return None, 'ldap_user_not_found'

    entry    = conn.entries[0]
    user_dn  = str(entry.entry_dn)

    # Verify user's password by binding as that user
    try:
        user_conn = Connection(srv, user=user_dn, password=password,
                               auto_bind=True, receive_timeout=timeout)
        user_conn.unbind()
    except Exception:
        conn.unbind()
        wa._dbg(f"> Auth/LDAP >> invalid credentials for {username!r}", DebugLevel.info)
        return None, 'ldap_invalid_credentials'

    def _val(attr_name):
        try:
            v = getattr(entry, attr_name)
            if v and hasattr(v, 'values') and v.values:
                return str(v.values[0])
        except Exception:
            pass
        return ''

    def _vals(attr_name):
        try:
            v = getattr(entry, attr_name)
            if v and hasattr(v, 'values'):
                return [str(x) for x in v.values]
        except Exception:
            pass
        return []

    # Primary groups: memberOf attribute (AD / overlay)
    primary_groups = _vals(group_attr)

    # Secondary search: groups that list the user via memberUid/member/uniqueMember.
    # This covers posixGroup and groupOfNames topologies where the user entry
    # has no memberOf attribute — membership is stored on the group object instead.
    _gf = (f'(|(memberUid={_ldap_escape(username)})'
           f'(member={_ldap_escape(user_dn)})'
           f'(uniqueMember={_ldap_escape(user_dn)}))')
    secondary_groups: list[str] = []
    try:
        conn.search(base_dn, _gf, search_scope=SUBTREE, attributes=['cn'])
        for ge in conn.entries:
            secondary_groups.append(str(ge.entry_dn))
            try:
                for cv in ge.cn.values:
                    secondary_groups.append(str(cv))
            except Exception:
                pass
    except Exception:
        pass

    # Deduplicate while preserving order; primary (memberOf) takes precedence
    seen: set[str] = set()
    all_groups: list[str] = []
    for g in primary_groups + secondary_groups:
        gl = g.lower()
        if gl not in seen:
            seen.add(gl)
            all_groups.append(g)

    result = {
        'dn':           user_dn,
        'display_name': _val(name_attr),
        'email':        _val(email_attr),
        'groups':       all_groups,
    }
    if username_attr:
        result['username'] = _val(username_attr)

    conn.unbind()
    wa._dbg(f"> Auth/LDAP >> success user={username!r} groups={len(all_groups)}", DebugLevel.info)
    return result, None


def _ldap_escape(s: str) -> str:
    """Escape special LDAP filter characters."""
    for ch, esc in (('\\', '\\5c'), ('*', '\\2a'), ('(', '\\28'),
                    (')', '\\29'), ('\x00', '\\00')):
        s = s.replace(ch, esc)
    return s


# ── User sync ────────────────────────────────────────────────────────────────

def sync_user(wa, username: str, attrs: dict) -> "dict | None":
    """Create or update a user entry in wa._users from LDAP attributes.

    Returns ``None`` when the username collides with an existing LOCAL account (the caller
    must reject the login — do not convert a local account to SSO). Always re-syncs role
    from group mapping (called on every login).
    Returns the user dict.
    """
    cfg            = _get_config(wa)
    group_role_map = _get_group_role_map(cfg)
    role_name      = _map_role(attrs.get('groups', []), group_role_map)
    _dr = cfg.get('default_role', '')
    default_role_uid = _dr if wa._is_uid(_dr) else (wa._role_name_to_uid(_dr or 'none') or wa._role_name_to_uid('none'))
    role_uid       = wa._role_name_to_uid(role_name) or default_role_uid

    existing = wa._users.get(username)
    if existing is None:
        user = {
            'uid':            str(uuid.uuid4()),
            'auth_source':    'ldap',
            'auth_source_id': attrs.get('dn', ''),
            'display_name':   attrs.get('display_name', ''),
            'email':          attrs.get('email', ''),
            'role':           role_uid,
            'groups':         [],
            'enabled':        True,
            'lang':           '',
        }
        wa._users[username] = user
    else:
        # Never auto-convert a LOCAL (or unmarked) account to SSO on a username collision
        # (account-takeover guard — see the OIDC provider for the rationale). SCIM/other
        # SSO accounts still re-link.
        if existing.get('auth_source', 'local') in ('', 'local'):
            wa._dbg(f"> Auth/LDAP >> username {username!r} collides with a local account; "
                    f"refusing auto-conversion to SSO", DebugLevel.warning)
            return None
        user = existing
        user['auth_source']    = 'ldap'
        user['auth_source_id'] = attrs.get('dn', '')
        user['display_name']   = attrs.get('display_name', '') or user.get('display_name', '')
        user['email']          = attrs.get('email', '') or user.get('email', '')
        user['role']           = role_uid  # re-sync on every login

    wa._persist_users()
    return user
