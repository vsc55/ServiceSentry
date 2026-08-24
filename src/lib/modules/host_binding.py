#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Javier Pastor (aka VSC55)
# <jpastor at cerebelum dot net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""How a check reaches the machine it is about.

A watchful item either carries its own connection details or points at a host by uid, and
from there the answers have to be resolved: which address, which protocol profile, whose
credential, what operating system, and therefore which command. Multi-bind modules ask the
same question once per host and get a list back.

None of that is what a check MEANS, which is why it is no longer in the same file as the
loop that runs one. Mixed into ``ModuleBase``: every watchful calls ``self.host_exec`` and
``self.host_cmd_for`` as its own methods, and they are — the class composes them.
"""

from lib.core.hosts.resolve import host_profile_specs, resolve_os
from lib.util import os_detect


class HostBinding:
    """Resolving an item's host, its credential and how to run a command on it."""

    def resolve_host(self, item: dict) -> dict:
        """Merge a referenced host's connection over a check item.

        Host-centric config: an item (or, for SNMP, a server) may carry a
        ``host_uid`` instead of inline connection fields.  When it does, this
        looks the host up in the monitor's host registry and returns a NEW dict
        = the item with the host's address + the relevant per-protocol
        credential profile(s) merged in (host values win, since the UI hides the
        inline connection fields when a host is bound).  Items without a
        ``host_uid`` — the classic inline config — are returned unchanged, so
        the two styles coexist.

        Which fields come from the host is declared by the module's
        ``__host_profile__`` in schema.json::

            "__host_profile__": {"key": "snmp", "address_field": "host",
                                 "fields": ["host","port","community", ...]}

        ``__host_profile__`` may also be a LIST of such specs for modules that
        need several protocols (e.g. datastore: an ``ssh`` tunnel + a ``db``
        profile).  Only specs with an ``address_field`` receive the host
        address; the rest contribute their profile fields only.
        """
        if not isinstance(item, dict):
            return item
        # Multi-host binding (``__host_multiple_bind__`` modules, e.g. proxmox): a
        # single check references several hosts via ``host_uids`` — its address
        # field becomes the failover list of all member addresses.
        host_uids = item.get('host_uids')
        if isinstance(host_uids, list):
            uids = [str(u).strip() for u in host_uids if str(u).strip()]
            if uids:
                return self._resolve_bound_hosts(item, uids, multi=True)
        host_uid = str(item.get('host_uid') or '').strip()
        if not host_uid:
            # Inline check (no host): still honour a referenced named credential.
            cred_uid = str(item.get('cred_uid') or '').strip()
            return self._apply_cred(item, cred_uid) if cred_uid else item
        return self._resolve_bound_hosts(item, [host_uid])

    def _resolve_bound_hosts(self, item: dict, uids: list, multi: bool = False) -> dict:
        """Merge one or more referenced hosts onto a check (see resolve_host).

        The FIRST resolved host is the primary: it supplies the per-protocol
        profile fields, the SSH credential, OS and maintenance state.  The
        address field is filled with the space-joined addresses of ALL bound
        hosts, so a multi-host (cluster) check fails over across its nodes.

        For a *multi*-host (cluster) binding, the member roster is exposed as
        ``__cluster_members__`` (uid/name/address/maintenance + the manually
        assigned ``node`` name from the host's profile), so the module can map
        each API node to its host; and a member in maintenance does NOT disable
        the whole check (the module skips just that node).
        """
        store = getattr(self._monitor, '_hosts_store', None)
        if store is None:
            return item
        hosts = []
        for u in uids:
            try:
                h = store.get(u)
            except Exception:  # pylint: disable=broad-except
                h = None
            if h:
                hosts.append(h)
        if not hosts:
            return item
        primary = hosts[0]

        specs = host_profile_specs(
            (getattr(self, 'ITEM_SCHEMA', None) or {}).get('__host_profile__'))
        if not specs:
            return item

        # Failover address list across every bound host (a cluster spans nodes).
        addresses = [str(h.get('address')).strip() for h in hosts
                     if str(h.get('address') or '').strip()]
        address_value = ' '.join(addresses)

        profiles = primary.get('profiles') or {}
        is_remote = str(primary.get('kind') or 'local').strip().lower() == 'remote'
        conn: dict = {}
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            # The SSH connection only applies to a remote host; a local host is
            # reached directly, so its (stale) ssh profile must not activate a
            # tunnel / command-bridge.
            if spec.get('key') == 'ssh' and not is_remote:
                continue
            addr_field = spec.get('address_field')
            # The host address fills the address_field ONLY when the check does
            # not already carry its own value.  A visible address_field (e.g.
            # web's 'server') can thus be overridden per check — needed when one
            # host (a reverse proxy) serves several FQDNs — while hidden ones
            # (snmp 'host', ssh 'ssh_host') stay blank and always take the host.
            if (addr_field and address_value
                    and not str(item.get(addr_field) or '').strip()):
                conn[addr_field] = address_value
            prof = profiles.get(spec.get('key')) or {}
            if isinstance(prof, dict):
                # Only non-empty values of fields the schema DECLARES as
                # host-owned override the item.  Stale profile keys (left over
                # after a schema evolution moved a field back to the check —
                # e.g. ssl_cert's port) must not clobber per-check values.
                declared = set(spec.get('fields') or [])
                conn.update({k: v for k, v in prof.items()
                             if k in declared and k != addr_field and v not in (None, '')})
        resolved = {**item, **conn}
        # A named credential supplies the identity, overlaying the inline fields.
        # The check's own cred_uid (any type, e.g. web auth) applies regardless of
        # host kind; the host's ssh-profile cred_uid is the SSH identity, so it
        # only applies to a remote host.
        cred_uid = str(item.get('cred_uid') or '').strip()
        if not cred_uid:
            # The host's own identity for the protocol, when the check names none. A device
            # carries its credential the way it carries its address — one place, reused by
            # every check bound to it — so this is not an SSH privilege: SSH is merely the
            # protocol that is skipped on a LOCAL host, because a local host is not reached
            # over it. Any other protocol (an SNMP community, an API token) applies whatever
            # the host's kind.
            for spec in specs:
                key = spec.get('key') if isinstance(spec, dict) else None
                if not key or (key == 'ssh' and not is_remote):
                    continue
                prof = profiles.get(key)
                if not isinstance(prof, dict):
                    continue
                cred_uid = str(prof.get('cred_uid') or '').strip()
                if cred_uid:
                    break
        if cred_uid:
            resolved = self._apply_cred(resolved, cred_uid)
        # Expose the host's OS so modules that run OS-specific commands can
        # branch on it.  'auto' on a LOCAL host resolves to this process's
        # platform; on a remote host it stays 'auto' (resolved over SSH by the
        # consumer when needed).
        # 'auto' on a local host resolves to this process's platform; on a remote
        # host it stays 'auto' (resolved over SSH by the consumer when needed).
        resolved['host_os'] = resolve_os(primary.get('os'), is_remote)
        # The kind ITSELF and not a two-way flag: `host_exec` has three answers to give
        # now (over SSH, here, nowhere), and collapsing them to remote/local is what made a
        # device with no connection run its commands on the panel.
        resolved['host_kind'] = str(primary.get('kind') or 'none').strip().lower()
        if multi:
            # Cluster roster: each member's identity + its per-node datum, read from
            # THIS module's host profile (``profiles[<module>]`` — the key the UI
            # writes to).  The datum is either the legacy ``node`` name (proxmox,
            # correlating API nodes with hosts) or the schema-declared
            # ``__member_field__`` value (e.g. keepalived's ``priority``); both are
            # exposed on the roster so a module reads its member value without a
            # second resolve.  No module-specific field name is assumed.
            pkey = (self.name_module or '').split('.')[-1]
            mf_key = None
            for _coll in (getattr(self, 'ITEM_SCHEMA', None) or {}).values():
                if isinstance(_coll, dict) and isinstance(_coll.get('__member_field__'), dict):
                    mf_key = _coll['__member_field__'].get('key')
                    break
            members = []
            for h in hosts:
                hp = (h.get('profiles') or {}).get(pkey) or {}
                hp = hp if isinstance(hp, dict) else {}
                member = {
                    'host_uid':    h.get('uid', ''),
                    'name':        h.get('name', ''),
                    'address':     h.get('address', ''),
                    'maintenance': bool(h.get('maintenance')),
                    'node':        str(hp.get('node') or '').strip(),
                }
                if mf_key:
                    member[mf_key] = hp.get(mf_key)
                members.append(member)
            resolved['__cluster_members__'] = members
            # A member in maintenance must NOT disable the whole cluster check —
            # the module skips just that node (via the roster).
        elif primary.get('maintenance'):
            # Single-host check: a host in maintenance skips every check bound to
            # it this cycle (disabled; modules already skip disabled items).
            resolved['enabled'] = False
            resolved['_host_maintenance'] = True
        return resolved

    def _apply_cred(self, target: dict, cred_uid: str) -> dict:
        """Overlay a named credential's SSH identity onto *target* (by cred_uid).

        Returns *target* unchanged if there is no credentials store, the uid is
        unknown, or lookup fails — so a dangling reference never breaks a check.
        """
        cstore = getattr(self._monitor, '_credentials_store', None)
        if cstore is None:
            return target
        try:
            cred = cstore.get(cred_uid)
        except Exception:  # pylint: disable=broad-except
            return target
        if not cred:
            return target
        from lib.core.credentials.store import apply_credential  # noqa: PLC0415
        return apply_credential(target, cred)

    # ── Host-aware command execution ─────────────────────────────────────────
    def host_os(self, item: dict) -> str:
        """Canonical OS for an item: the bound host's OS, else this machine's."""
        if isinstance(item, dict) and item.get('host_os'):
            return str(item['host_os']).strip().lower()
        return os_detect.local_os()

    @staticmethod
    def host_cmd_for(item: dict, cmds: dict, default_os: str = 'linux') -> str:
        """Pick the command for the item's OS from ``{os: cmd}`` (falls back to
        the *default_os* entry, then any).  Returns '' when *cmds* is empty."""
        os_ = str((item or {}).get('host_os') or os_detect.local_os()).lower()
        return cmds.get(os_) or cmds.get(default_os) or next(iter(cmds.values()), '')

    def host_exec(self, item: dict, cmd: str, *, timeout: int = 15) -> tuple:
        """Run *cmd* for a check item and return ``(stdout, stderr, exit_code)``.

        Where it runs depends on the item's bound host (set by
        :meth:`resolve_host`):

          * ``host_kind == 'remote'`` → over SSH on the host, reusing the host's
            stored SSH connection (``ssh_*`` fields merged into the item);
          * otherwise (a local host or a classic inline item) → locally.

        Never raises; transport/exec failures come back as
        ``('', <error>, -1)``.
        """
        if not isinstance(item, dict) or not cmd:
            return '', 'invalid item or command', -1
        # …and nowhere, for a device that runs nothing. See `hosts/runner.py::run` — the
        # same rule, because the two are the same decision reached from two sides.
        if str(item.get('host_kind') or '').strip().lower() == 'none':
            from lib.core.hosts.runner import NO_EXEC   # noqa: PLC0415
            return '', NO_EXEC, -1
        if str(item.get('host_kind') or '').strip().lower() == 'remote':
            from lib.core.hosts import ssh_client  # noqa: PLC0415
            if not ssh_client.HAS_PARAMIKO:
                return '', 'paramiko is not installed', -1
            address = str(item.get('ssh_host') or '').strip()
            if not address:
                return '', 'remote host has no address', -1
            client = None
            try:
                client = ssh_client.connect_host(item, address, timeout=timeout)
                return ssh_client.run_command(client, cmd, timeout=timeout)
            except Exception as exc:  # pylint: disable=broad-except
                return '', f'SSH error: {exc}', -1
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # pylint: disable=broad-except
                        pass
        # Local / inline — run through the shell so pipes, globs and ';' behave
        # the same as on the remote SSH path (the local Exec helper uses
        # shlex.split, which would not interpret them).  The command is built
        # from module code/schema (never raw user input), so shell=True is safe.
        import subprocess  # noqa: PLC0415
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True,  # noqa: S602
                                 text=True, timeout=timeout)
            return (res.stdout or ''), (res.stderr or ''), res.returncode
        except Exception as exc:  # pylint: disable=broad-except
            return '', str(exc), -1
