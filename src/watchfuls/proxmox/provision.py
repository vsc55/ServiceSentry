#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry - Proxmox VE watchful: setting the cluster up to be monitored.
#
"""Create the monitoring user and its token over SSH, and repair its privileges.

Neither check nor action in the ordinary sense: these WRITE to the Proxmox cluster - they
create a role, a user and an API token, or grant what a fix needs - so they are deliberately
kept out of READ_ONLY_ACTIONS, require module edit rights and are audited.

They run ``pvesh`` over SSH rather than the REST API for a reason: the credential they are
creating is the one the API would have needed.
"""

import json
import re

from .client import _split_hosts

# reads (cluster/ceph/ha status, nodes, network) need Sys.Audit; reading storage
# status (/nodes/{node}/storage) needs Datastore.Audit. Still far tighter than the
# built-in PVEAuditor role.
#
# NOTE: the apt/update LIST endpoint (GET /nodes/{node}/apt/update) is gated behind
# Sys.Modify in Proxmox — even though it's a read — so the *updates* check needs
# Sys.Modify too. It's NOT in the base set (it broadens the token to node-modify);
# provisioning adds it only when the admin opts in (config 'allow_updates').
_MONITOR_PRIVS = 'Sys.Audit, Datastore.Audit'
_UPDATES_PRIV = 'Sys.Modify'

# Extracts "(/path, Priv)" from a Proxmox 403 "Permission check failed (...)" body.
_PERM_RE = re.compile(r'Permission check failed \(([^,]+),\s*([^)\n]+)\)')


def _shq(value: str) -> str:
    """POSIX single-quote a value for safe interpolation into an SSH command."""
    return "'" + str(value).replace("'", "'\\''") + "'"


def _extract_json(text: str):
    """Return the JSON object found in *text* (the ``pveum ... --output-format
    json`` stdout), or None. Tolerates surrounding noise."""
    text = (text or '').strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # pylint: disable=broad-except
        pass
    start, end = text.find('{'), text.rfind('}')
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except Exception:  # pylint: disable=broad-except
            return None
    return None


class ProxmoxProvision:
    """Provisioning flows, mixed into ``Watchful``."""

    @classmethod
    def _provision_ssh(cls, config: dict, cmd: str, *, timeout: int = 30) -> dict:
        """Run *cmd* on a Proxmox node over SSH (root/sudo), reusing the host's SSH
        profile/credential — the shared connection path behind ``provision_token``
        and ``fix_permissions``.

        Resolves the SSH target from the modal fields, falling back to the bound
        host's ``__host__`` SSH context; tries each candidate address in turn behind
        the SSRF guard.  Returns ``{'ok': True, 'out', 'err', 'code'}`` on a
        successful run, else ``{'ok': False, 'message': <reason>}``.
        """
        from lib.core.hosts import ssh_client  # noqa: PLC0415
        from lib.security.net_guard import validate_external_url  # noqa: PLC0415

        # When the check is bound to a host, the route injects the resolved host
        # context (__host__): address + the host's SSH profile (user/port/secret,
        # credential already applied) — the SAME SSH path the host-aware checks
        # use.  Reuse it so provisioning reaches the node on the host's real SSH
        # address/port, not a guessed default.  An explicit modal value still wins.
        host_ctx = config.get('__host__') if isinstance(config.get('__host__'), dict) else {}
        host_ssh = host_ctx.get('ssh') if isinstance(host_ctx.get('ssh'), dict) else {}

        def _conn(key, default=''):
            v = config.get(key)
            if v not in (None, '', 0):
                return v
            v = host_ssh.get(key)
            if v not in (None, '', 0):
                return v
            return default

        host = ((config.get('host') or '').strip()
                or str(host_ctx.get('address') or '').strip()
                or (config.get('_item_key') or '').strip())
        # The host field may list several addresses (comma/space separated) for
        # API failover — provisioning only needs one reachable node, so split and
        # try each in turn rather than handing the whole string to SSH.
        candidates = _split_hosts(host)
        if not candidates:
            return {'ok': False, 'message': 'Host requerido'}
        ssh_user = str(_conn('ssh_user', 'root') or 'root').strip() or 'root'
        ssh_port = int(_conn('ssh_port', 22) or 22)
        ssh_password = config.get('ssh_password') or host_ssh.get('ssh_password') or None
        ssh_key = (config.get('ssh_key') or host_ssh.get('ssh_key') or '').strip() or None  # key file path
        ssh_key_string = config.get('ssh_key_string') or host_ssh.get('ssh_key_string') or None  # inline key
        # Host-key policy: mirror the host-aware checks — default AutoAdd (accept
        # unknown keys on first contact), honouring the host's ssh_verify_host.
        ssh_verify = bool(host_ssh.get('ssh_verify_host', config.get('ssh_verify_host', False)))
        if not ssh_password and not ssh_key and not ssh_key_string:
            return {'ok': False,
                    'message': 'Indica una contraseña o clave SSH (o una credencial SSH) para el aprovisionamiento'}

        if not ssh_client.HAS_PARAMIKO:
            return {'ok': False, 'message': 'paramiko no está instalado (pip install paramiko)'}

        # Connect over SSH via the shared ssh_client (same path as the host-aware
        # checks): it accepts an inline key text directly and honours the host-key
        # policy.  Try each candidate node until one connects.
        out = err = ''
        code = None
        connected = False
        last_err = None
        for cand in candidates:
            reason = validate_external_url(f'https://{cand}:{ssh_port}')
            if reason:
                last_err = f'{cand}: bloqueado ({reason})'
                continue
            client = None
            try:
                client = ssh_client.connect(
                    address=cand, port=ssh_port, user=ssh_user,
                    password=ssh_password or '', key_path=ssh_key or '',
                    key_string=ssh_key_string or '', verify_host=ssh_verify, timeout=timeout)
                out, err, code = ssh_client.run_command(client, cmd, timeout=timeout)
                connected = True
                break
            except Exception as exc:  # pylint: disable=broad-except
                last_err = f'{cand}:{ssh_port} → {exc}'
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # pylint: disable=broad-except
                        pass
        if not connected:
            hint = ''
            if last_err and 'known_hosts' in last_err:
                hint = (' La clave del host no está en known_hosts y el perfil SSH del host '
                        'tiene la verificación activada: desactívala o añade la clave.')
            return {'ok': False,
                    'message': (f'SSH: {last_err or "ningún host alcanzable"}.{hint} '
                                f'La acción conecta por SSH (puerto {ssh_port}) '
                                f'al nodo Proxmox, no a la API (8006): revisa que el puerto SSH, '
                                f'la dirección de gestión y el firewall sean correctos.')}
        return {'ok': True, 'out': (out or '').strip(), 'err': (err or '').strip(), 'code': code}

    @classmethod
    def provision_token(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/proxmox/provision_token

        Connects to the Proxmox node over **SSH** (root or a sudo-capable user)
        and provisions an API token, then returns the generated token id + secret
        so the UI fills the form (result mode ``fields``).

        Two modes (``mode`` input):
          * ``create`` (default) — idempotently create a read-only monitoring user
            and grant the ``PVEAuditor`` role at ``/``, then (re)create the token.
          * ``renew`` — only rotate the token secret (remove + add); assumes the
            user and role already exist (lighter, for secret rotation).

        Returns {"ok": bool, "message": str, "fields": {auth_method, token_id,
        token_secret}}.
        """
        user = (config.get('prov_user') or 'servicesentry@pve').strip()
        token = (config.get('prov_token') or 'monitoring').strip()
        role = (config.get('prov_role') or 'ServiceSentryMonitor').strip()
        mode = (config.get('mode') or 'create').strip().lower()

        # Opt-in: the updates check needs Sys.Modify (Proxmox gates apt/update list
        # behind it). Off by default to keep the token least-privilege.
        allow_updates = str(config.get('allow_updates', '')).lower() in ('1', 'true', 'yes', 'on')
        privs = f'{_MONITOR_PRIVS}, {_UPDATES_PRIV}' if allow_updates else _MONITOR_PRIVS
        qu, qt, qr, qp = _shq(user), _shq(token), _shq(role), _shq(privs)
        token_cmd = (
            f"pveum user token remove {qu} {qt} 2>/dev/null; "
            f"pveum user token add {qu} {qt} --privsep 0 "
            f"--comment 'ServiceSentry' --output-format json"
        )
        if mode == 'renew':
            # Rotate the secret only: assumes the user + role already exist.
            cmd = token_cmd
        else:
            # Idempotent, least-privilege: create a custom role with exactly the
            # privileges the checks need (modify keeps it in sync if it existed),
            # create the user (ignore "already exists"), grant that role at / (it
            # propagates), then (re)create the token for a fresh secret.
            cmd = (
                f"pveum role add {qr} -privs {qp} 2>/dev/null; "
                f"pveum role modify {qr} -privs {qp}; "
                f"pveum user add {qu} --comment 'ServiceSentry monitoring (read-only)' 2>/dev/null; "
                f"pveum acl modify / --users {qu} --roles {qr} && "
                + token_cmd
            )

        res = cls._provision_ssh(config, cmd)
        if not res.get('ok'):
            return {'ok': False, 'message': res.get('message', 'SSH: error')}
        out, err, code = res.get('out', ''), res.get('err', ''), res.get('code')
        data = _extract_json(out)
        secret = (data or {}).get('value')
        full_id = (data or {}).get('full-tokenid') or f'{user}!{token}'
        if not secret:
            detail = (err or out or f'exit {code}')[:300]
            return {'ok': False, 'message': f'No se pudo crear el token: {detail}'}

        if mode == 'renew':
            message = (f'Secreto del token «{full_id}» renovado. '
                       f'Credenciales rellenadas — guarda el módulo.')
        else:
            message = (f'Usuario «{user}» y token «{full_id}» creados con el rol «{role}» '
                       f'(privilegios: {privs}). Credenciales rellenadas — guarda el módulo.')
        return {
            'ok': True,
            'message': message,
            'fields': {
                'auth_method': 'token',
                'token_id': full_id,
                'token_secret': secret,
            },
        }

    @classmethod
    def fix_permissions(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/proxmox/fix_permissions

        Grant the privileges the item's *enabled* checks need to the identity the
        configured credential already uses, over **SSH** (root/sudo) — the same path
        as ``provision_token`` but WITHOUT rotating the token, so an existing token
        keeps working with more privileges.

        Ensures a custom role (``prov_role``, default ``ServiceSentryMonitor``) holds
        exactly the required privileges (``Sys.Audit``; ``Datastore.Audit`` for the
        storage check; ``Sys.Modify`` for the updates check) and grants it at ``/``
        to the token's own user — and to the token itself, covering a
        privilege-separated token.  Then re-verifies over the API and returns the
        fresh per-privilege verdict (same shape as ``test_permissions``).

        Returns {"ok": bool, "all_ok": bool, "message": str, "variant": str,
                 "info": [[label, ✅/❌], …]}.
        """
        auth_method = str(config.get('auth_method') or 'token').strip().lower()
        role = (config.get('prov_role') or 'ServiceSentryMonitor').strip()
        # Exactly the privileges the enabled checks need (deduped, order preserved).
        privs = list(dict.fromkeys(p for p, _path, _f in cls._required_privs(config)))
        if not privs:
            return {'ok': False, 'message': 'No hay privilegios que conceder'}

        # Grant to the identity the credential uses: the token's own user (parsed
        # from token_id 'user@realm!tokenname'), else the password user.  A privsep
        # token has its own ACLs, so also grant on the token itself for token auth.
        token_id = str(config.get('token_id') or '').strip()
        token_grant = ''
        if auth_method == 'token':
            if not token_id:
                return {'ok': False, 'message': 'Falta token_id para conceder permisos'}
            user = token_id.split('!', 1)[0]
            token_grant = f"pveum acl modify / --tokens {_shq(token_id)} --roles {_shq(role)}; "
        else:
            user = str(config.get('username') or '').strip()
            if not user:
                return {'ok': False, 'message': 'Falta el usuario para conceder permisos'}

        qu, qr, qp = _shq(user), _shq(role), _shq(', '.join(privs))
        # Idempotent: create the role if absent, sync its privileges, grant it at /
        # (propagates) to the user and — for a privsep token — to the token too.
        cmd = (
            f"pveum role add {qr} -privs {qp} 2>/dev/null; "
            f"pveum role modify {qr} -privs {qp}; "
            f"pveum acl modify / --users {qu} --roles {qr}; "
            + token_grant
        ).rstrip('; ')

        res = cls._provision_ssh(config, cmd)
        if not res.get('ok'):
            return {'ok': False, 'message': res.get('message', 'SSH: error')}

        # Re-verify over the API so the result modal shows the updated verdict.
        note = f'Permisos concedidos a «{user}» (rol «{role}»: {", ".join(privs)}). '
        verify = cls.test_permissions(config)
        if isinstance(verify, dict) and verify.get('ok'):
            verify = dict(verify)
            verify['message'] = note + str(verify.get('message', ''))
            return verify
        return {'ok': True, 'all_ok': False, 'variant': 'warning',
                'message': note + 'No se pudo re-verificar por API: '
                                  + str((verify or {}).get('message', ''))}
