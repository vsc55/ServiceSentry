#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core SSH helpers shared by the host registry and the watchful modules.

A *host* declared as ``remote`` carries an SSH connection (user + one of
password / key-file path / inline key text) so that modules which need to run
commands on the server (e.g. RAID) or open a tunnel through it (e.g. datastore)
reuse the same credentials defined once on the host.

This lives in the core (not in any watchful module) because SSH reachability is
a property of the *server*, not of a particular check.  ``paramiko`` is an
optional dependency: when absent, :data:`HAS_PARAMIKO` is ``False`` and
:func:`test_connection` returns a friendly install hint instead of raising.
"""

from __future__ import annotations

import io

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:  # pragma: no cover - exercised on hosts without paramiko
    paramiko = None
    HAS_PARAMIKO = False


def pkey_from_string(key_string: str, password: str = ''):
    """Load a paramiko private key from PEM/OpenSSH *text* (any supported type).

    ``password`` is used as the key passphrase when the key is encrypted.
    Raises ``ValueError`` when the text is not a valid/supported key.
    """
    if not HAS_PARAMIKO:
        raise ValueError('paramiko is not installed')
    last_exc = None
    for cls_name in ('Ed25519Key', 'ECDSAKey', 'RSAKey', 'DSSKey'):
        cls = getattr(paramiko, cls_name, None)
        if cls is None:
            continue
        try:
            return cls.from_private_key(io.StringIO(key_string),
                                        password=password or None)
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
    raise ValueError(f'Unsupported or invalid private key: {last_exc}')


def build_connect_kwargs(*, address, port=22, user='', password='',
                         key_path='', key_string='', timeout=10):
    """Return the ``paramiko.SSHClient.connect`` kwargs for a host's SSH config.

    Auth precedence: inline key text > key-file path > password.
    """
    kw = {
        'hostname': str(address or ''),
        'port': int(port or 22),
        'username': str(user or ''),
        'timeout': timeout, 'banner_timeout': timeout, 'auth_timeout': timeout,
    }
    if key_string:
        kw['pkey'] = pkey_from_string(str(key_string), str(password or ''))
    elif key_path:
        kw['key_filename'] = str(key_path)
    elif password:
        kw['password'] = str(password)
    return kw


def connect(*, address, port=22, user='', password='', key_path='',
            key_string='', verify_host=False, timeout=10):
    """Open and return a connected ``paramiko.SSHClient`` (caller must close it).

    When ``verify_host`` is true the server key must already be known
    (MITM-safe, ``RejectPolicy``); otherwise unknown keys are accepted on first
    contact (``AutoAddPolicy``).
    """
    if not HAS_PARAMIKO:
        raise ValueError('paramiko is not installed')
    client = paramiko.SSHClient()
    if verify_host:
        client.load_system_host_keys()
        try:
            import os
            client.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
        except (OSError, IOError):
            pass
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(**build_connect_kwargs(
        address=address, port=port, user=user, password=password,
        key_path=key_path, key_string=key_string, timeout=timeout))
    return client


def run_command(client, cmd: str, timeout: int = 15) -> tuple:
    """Run *cmd* on a connected client; return ``(stdout, stderr, exit_code)``.

    Decodes output as UTF-8 (replacing undecodable bytes).  ``exit_code`` is the
    remote process exit status, or ``-1`` if it could not be obtained.  Never
    raises — transport errors are returned as ``('', <error>, -1)``.
    """
    try:
        _in, out, err = client.exec_command(cmd, timeout=timeout)  # noqa: S601
        stdout = (out.read().decode(errors='replace') or '')
        stderr = (err.read().decode(errors='replace') or '')
        try:
            code = out.channel.recv_exit_status()
        except Exception:  # pylint: disable=broad-except
            code = -1
        return stdout, stderr, code
    except Exception as exc:  # pylint: disable=broad-except
        return '', str(exc), -1


def connect_host(host_ssh: dict, address: str, *, timeout: int = 15):
    """Open a client from a host's resolved SSH fields (see resolve_host).

    *host_ssh* keys: ssh_port, ssh_user, ssh_password, ssh_key, ssh_key_string,
    ssh_verify_host.  *address* is the host address (used as the SSH host).
    """
    return connect(
        address=address,
        port=host_ssh.get('ssh_port') or 22,
        user=host_ssh.get('ssh_user', ''),
        password=host_ssh.get('ssh_password', ''),
        key_path=host_ssh.get('ssh_key', ''),
        key_string=host_ssh.get('ssh_key_string', ''),
        verify_host=bool(host_ssh.get('ssh_verify_host', False)),
        timeout=timeout)


def detect_os(client) -> str:
    """Best-effort canonical OS of a connected host (``uname`` then Windows).

    Returns a token from :data:`lib.os_detect.CANONICAL` (``'other'`` when
    undetermined).  Never raises.
    """
    from lib.os_detect import canonical_os, OS_OTHER  # noqa: PLC0415

    def _run(cmd):
        try:
            _in, out, _err = client.exec_command(cmd, timeout=8)  # noqa: S601
            return (out.read().decode(errors='replace') or '').strip()
        except Exception:  # pylint: disable=broad-except
            return ''

    uname = _run('uname -s')
    if uname:
        return canonical_os(uname)
    # No uname → likely Windows; `ver` prints e.g. "Microsoft Windows [Version …]".
    ver = _run('ver') or _run('cmd /c ver')
    if 'windows' in ver.lower():
        return 'windows'
    return OS_OTHER


def test_connection(*, address, port=22, user='', password='', key_path='',
                    key_string='', verify_host=False, timeout=10,
                    detect=False) -> tuple:
    """Attempt an SSH connection and return ``(ok, message)``.

    When *detect* is true, returns ``(ok, message, os)`` instead — *os* is the
    canonical OS detected over the connection (``''`` on failure).

    Never raises: any failure is reported as ``(False, <reason>)`` so the web
    admin can surface it as a toast.
    """
    if not HAS_PARAMIKO:
        msg = 'paramiko is not installed (pip install paramiko)'
        return (False, msg, '') if detect else (False, msg)
    if not str(address or '').strip():
        msg = 'No address configured'
        return (False, msg, '') if detect else (False, msg)
    client = None
    try:
        client = connect(address=address, port=port, user=user,
                         password=password, key_path=key_path,
                         key_string=key_string, verify_host=verify_host,
                         timeout=timeout)
        os_found = detect_os(client) if detect else ''
        return (True, 'SSH connection successful', os_found) if detect \
            else (True, 'SSH connection successful')
    except Exception as exc:  # pylint: disable=broad-except
        msg = f'SSH error: {exc}'
        return (False, msg, '') if detect else (False, msg)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pylint: disable=broad-except
                pass
