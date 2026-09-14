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

A watchful item either carries its own connection details or points at a device by uid, and
from there the answers have to be resolved: which address, which protocol profile, whose
credential, what operating system, and therefore which command. Multi-bind modules ask the
same question once per device and get a list back.

None of that is what a check MEANS, which is why it is no longer in the same file as the
loop that runs one. Mixed into ``ModuleBase``: every watchful calls ``self.device_exec`` and
``self.device_cmd_for`` as its own methods, and they are — the class composes them.
"""

from lib.core.devices.resolve import device_profile_specs, reported_os, resolve_os
from lib.util import os_detect


class HostBinding:
    """Resolving an item's device, its credential and how to run a command on it."""

    def _reported_os(self, uid) -> str:
        """What the fleet's recorded state says this machine runs, or ``''``.

        Read from the state the monitor is already holding rather than from a store: this runs
        once per check, and a query per check for a fact that changes when a machine is
        reinstalled would be a query nobody needs.
        """
        status = getattr(getattr(self, '_monitor', None), 'status', None)
        data = getattr(status, 'data', None)
        if not isinstance(data, dict) or not uid:
            return ''
        try:
            return reported_os(data, uid)
        except Exception:  # pylint: disable=broad-except
            return ''      # a platform we could not work out is the same as one nobody said

    def resolve_device(self, item: dict) -> dict:
        """Merge a referenced device's connection over a check item.

        Device-centric config: an item (or, for SNMP, a server) may carry a
        ``device_uid`` instead of inline connection fields.  When it does, this
        looks the device up in the monitor's device registry and returns a NEW dict
        = the item with the device's address + the relevant per-protocol
        credential profile(s) merged in (device values win, since the UI hides the
        inline connection fields when a device is bound).  Items without a
        ``device_uid`` — the classic inline config — are returned unchanged, so
        the two styles coexist.

        Which fields come from the device is declared by the module's
        ``__device_profile__`` in schema.json::

            "__device_profile__": {"key": "snmp", "address_field": "host",
                                 "fields": ["host","port","community", ...]}

        ``__device_profile__`` may also be a LIST of such specs for modules that
        need several protocols (e.g. datastore: an ``ssh`` tunnel + a ``db``
        profile).  Only specs with an ``address_field`` receive the device
        address; the rest contribute their profile fields only.
        """
        if not isinstance(item, dict):
            return item
        # Multi-device binding (``__device_multiple_bind__`` modules, e.g. proxmox): a
        # single check references several devices via ``device_uids`` — its address
        # field becomes the failover list of all member addresses.
        device_uids = item.get('device_uids')
        if isinstance(device_uids, list):
            uids = [str(u).strip() for u in device_uids if str(u).strip()]
            if uids:
                return self._resolve_bound_hosts(item, uids, multi=True)
        device_uid = str(item.get('device_uid') or '').strip()
        if not device_uid:
            # Inline check (no device): still honour a referenced named credential.
            cred_uid = str(item.get('cred_uid') or '').strip()
            return self._apply_cred(item, cred_uid) if cred_uid else item
        return self._resolve_bound_hosts(item, [device_uid])

    def _resolve_bound_hosts(self, item: dict, uids: list, multi: bool = False) -> dict:
        """Merge one or more referenced devices onto a check (see resolve_device).

        The FIRST resolved device is the primary: it supplies the per-protocol
        profile fields, the SSH credential, OS and maintenance state.  The
        address field is filled with the space-joined addresses of ALL bound
        devices, so a multi-device (cluster) check fails over across its nodes.

        For a *multi*-device (cluster) binding, the member roster is exposed as
        ``__cluster_members__`` (uid/name/address/maintenance + the manually
        assigned ``node`` name from the device's profile), so the module can map
        each API node to its device; and a member in maintenance does NOT disable
        the whole check (the module skips just that node).
        """
        store = getattr(self._monitor, '_devices_store', None)
        if store is None:
            return item
        devices = []
        for u in uids:
            try:
                h = store.get(u)
            except Exception:  # pylint: disable=broad-except
                h = None
            if h:
                devices.append(h)
        if not devices:
            return item
        primary = devices[0]

        specs = device_profile_specs(
            (getattr(self, 'ITEM_SCHEMA', None) or {}).get('__device_profile__'))
        if not specs:
            return item

        # Failover address list across every bound device (a cluster spans nodes).
        addresses = [str(h.get('address')).strip() for h in devices
                     if str(h.get('address') or '').strip()]
        address_value = ' '.join(addresses)

        profiles = primary.get('profiles') or {}
        is_remote = str(primary.get('kind') or 'local').strip().lower() == 'remote'
        conn: dict = {}
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            # The SSH connection only applies to a remote device; a local device is
            # reached directly, so its (stale) ssh profile must not activate a
            # tunnel / command-bridge.
            if spec.get('key') == 'ssh' and not is_remote:
                continue
            addr_field = spec.get('address_field')
            # The device address fills the address_field ONLY when the check does
            # not already carry its own value.  A visible address_field (e.g.
            # web's 'server') can thus be overridden per check — needed when one
            # device (a reverse proxy) serves several FQDNs — while hidden ones
            # (snmp 'host', ssh 'ssh_host') stay blank and always take the host.
            if (addr_field and address_value
                    and not str(item.get(addr_field) or '').strip()):
                conn[addr_field] = address_value
            prof = profiles.get(spec.get('key')) or {}
            if isinstance(prof, dict):
                # Only non-empty values of fields the schema DECLARES as
                # device-owned override the item.  Stale profile keys (left over
                # after a schema evolution moved a field back to the check —
                # e.g. ssl_cert's port) must not clobber per-check values.
                declared = set(spec.get('fields') or [])
                conn.update({k: v for k, v in prof.items()
                             if k in declared and k != addr_field and v not in (None, '')})
        resolved = {**item, **conn}
        # A named credential supplies the identity, overlaying the inline fields.
        # The check's own cred_uid (any type, e.g. web auth) applies regardless of
        # device kind; the device's ssh-profile cred_uid is the SSH identity, so it
        # only applies to a remote device.
        cred_uid = str(item.get('cred_uid') or '').strip()
        if not cred_uid:
            # The device's own identity for the protocol, when the check names none. A device
            # carries its credential the way it carries its address — one place, reused by
            # every check bound to it — so this is not an SSH privilege: SSH is merely the
            # protocol that is skipped on a LOCAL device, because a local device is not reached
            # over it. Any other protocol (an SNMP community, an API token) applies whatever
            # the device's kind.
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
        # Expose the device's OS so modules that run OS-specific commands can branch on it.
        #
        # `auto` asks the DEVICE first, out of what a module has already recorded about it —
        # see `reported_os`. Then the old ladder: this process's platform on a local device, and
        # on a remote one `'auto'`, resolved over SSH by the consumer when needed.
        resolved['device_os'] = resolve_os(
            primary.get('os'), is_remote, reported=self._reported_os(primary.get('uid')))
        # The kind ITSELF and not a two-way flag: `device_exec` has three answers to give
        # now (over SSH, here, nowhere), and collapsing them to remote/local is what made a
        # device with no connection run its commands on the panel.
        resolved['device_kind'] = str(primary.get('kind') or 'none').strip().lower()
        if multi:
            # Cluster roster: each member's identity + its per-node datum, read from
            # THIS module's device profile (``profiles[<module>]`` — the key the UI
            # writes to).  The datum is either the legacy ``node`` name (proxmox,
            # correlating API nodes with devices) or the schema-declared
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
            for h in devices:
                hp = (h.get('profiles') or {}).get(pkey) or {}
                hp = hp if isinstance(hp, dict) else {}
                member = {
                    'device_uid':    h.get('uid', ''),
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
            # Single-device check: a device in maintenance skips every check bound to
            # it this cycle (disabled; modules already skip disabled items).
            resolved['enabled'] = False
            resolved['_device_maintenance'] = True
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

    # ── Device-aware command execution ─────────────────────────────────────────
    def device_os(self, item: dict) -> str:
        """Canonical OS for an item: the bound device's OS, else this machine's."""
        if isinstance(item, dict) and item.get('device_os'):
            return str(item['device_os']).strip().lower()
        return os_detect.local_os()

    @staticmethod
    def device_cmd_for(item: dict, cmds: dict, default_os: str = 'linux') -> str:
        """Pick the command for the item's OS from ``{os: cmd}`` (falls back to
        the *default_os* entry, then any).  Returns '' when *cmds* is empty."""
        os_ = str((item or {}).get('device_os') or os_detect.local_os()).lower()
        return cmds.get(os_) or cmds.get(default_os) or next(iter(cmds.values()), '')

    def device_exec(self, item: dict, cmd: str, *, timeout: int = 15) -> tuple:
        """Run *cmd* for a check item and return ``(stdout, stderr, exit_code)``.

        Where it runs depends on the item's bound device (set by
        :meth:`resolve_device`):

          * ``device_kind == 'remote'`` → over SSH on the device, reusing the device's
            stored SSH connection (``ssh_*`` fields merged into the item);
          * otherwise (a local device or a classic inline item) → locally.

        Never raises; transport/exec failures come back as
        ``('', <error>, -1)``.
        """
        if not isinstance(item, dict) or not cmd:
            return '', 'invalid item or command', -1
        # …and nowhere, for a device that runs nothing. See `devices/runner.py::run` — the
        # same rule, because the two are the same decision reached from two sides.
        if str(item.get('device_kind') or '').strip().lower() == 'none':
            from lib.core.devices.runner import NO_EXEC   # noqa: PLC0415
            return '', NO_EXEC, -1
        if str(item.get('device_kind') or '').strip().lower() == 'remote':
            from lib.core.devices import ssh_client  # noqa: PLC0415
            if not ssh_client.HAS_PARAMIKO:
                return '', 'paramiko is not installed', -1
            address = str(item.get('ssh_host') or '').strip()
            if not address:
                return '', 'remote device has no address', -1
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
