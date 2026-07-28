#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Service status watchful: listing what is there to monitor.
#
"""Discovery: ask the box which services it has, so nobody types unit names from memory.

Every init system answers differently - systemd, OpenRC, SysV, launchd, Windows SC - so there
is one command and one parser per family, and the dispatch picks by platform. It runs locally
or over SSH when the item is bound to a host, because the list is a property of that machine
and not of the one running the panel.
"""



import os
import subprocess

import psutil


class ServiceDiscovery:
    """The ``discover`` action and its per-init parsers. Mixed into ``Watchful``."""

    # ── Discover (local autocomplete, or over SSH for a remote host) ──────────
    @classmethod
    def discover(cls, config=None) -> list:
        """Return [{name, display_name, status}] for the host's services.

        With a remote host context (``config['__host__']``, injected by the route
        for the Servers modal) the list is read over SSH; otherwise from THIS
        machine.
        """
        from lib.core.hosts import runner as host_runner  # noqa: PLC0415
        host = (config or {}).get('__host__') if isinstance(config, dict) else None
        if host_runner.is_remote(host):
            return cls._discover_remote(host, str(host.get('os') or 'linux'))
        if cls._PLATFORM == 'windows':
            return cls._discover_windows()
        if cls._INIT_SYSTEM == 'openrc':
            return cls._discover_openrc()
        if cls._INIT_SYSTEM == 'sysv':
            return cls._discover_sysv()
        try:
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--all',
                 '--no-pager', '--no-legend', '--plain'],
                capture_output=True, text=True, timeout=10,
            )
            return cls._parse_systemd_list(result.stdout)
        except Exception:
            return []

    # ── Remote discovery (over SSH) ──────────────────────────────────────────
    _DISCOVER_CMDS = {
        'linux':   'systemctl list-units --type=service --all --no-pager --no-legend --plain',
        'windows': 'sc query state= all',
        'darwin':  'launchctl list',
        'freebsd': 'service -e',
    }

    @classmethod
    def _discover_remote(cls, host, os_: str) -> list:
        from lib.core.hosts import runner as host_runner  # noqa: PLC0415
        cmd = cls._DISCOVER_CMDS.get(os_) or cls._DISCOVER_CMDS['linux']
        out, _err, code = host_runner.run(host, cmd, timeout=15)
        if code != 0 and not out:
            return []
        if os_ == 'windows':
            return cls._parse_sc_query(out)
        if os_ == 'darwin':
            return cls._parse_launchctl(out)
        if os_ == 'freebsd':
            return cls._parse_service_e(out)
        return cls._parse_systemd_list(out)

    @staticmethod
    def _parse_systemd_list(stdout: str) -> list:
        services = []
        for line in (stdout or '').split('\n'):
            cols = line.split()
            if len(cols) < 4:
                continue
            raw_name = cols[0]
            if not raw_name.endswith('.service'):
                continue
            name = raw_name[:-len('.service')]
            status = cols[3]
            display = ' '.join(cols[4:]) if len(cols) > 4 else ''
            services.append({'name': name, 'display_name': display, 'status': status})
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _parse_sc_query(stdout: str) -> list:
        """Parse `sc query state= all` blocks (SERVICE_NAME / STATE …RUNNING)."""
        services, name = [], None
        for line in (stdout or '').splitlines():
            s = line.strip()
            if s.upper().startswith('SERVICE_NAME:'):
                name = s.split(':', 1)[1].strip()
            elif 'STATE' in s.upper() and name:
                up = s.upper()
                status = 'running' if 'RUNNING' in up else ('stopped' if 'STOPPED' in up else 'unknown')
                services.append({'name': name, 'display_name': name, 'status': status})
                name = None
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _parse_launchctl(stdout: str) -> list:
        """Parse `launchctl list` lines: <PID>\t<status>\t<label>."""
        services = []
        for line in (stdout or '').splitlines()[1:]:   # skip header
            cols = line.split('\t') if '\t' in line else line.split()
            if len(cols) < 3:
                continue
            pid, label = cols[0].strip(), cols[-1].strip()
            if not label:
                continue
            status = 'running' if pid not in ('-', '') and pid.lstrip('-').isdigit() else 'stopped'
            services.append({'name': label, 'display_name': label, 'status': status})
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _parse_service_e(stdout: str) -> list:
        """Parse FreeBSD `service -e` (paths to enabled rc scripts)."""
        services = []
        for line in (stdout or '').splitlines():
            path = line.strip()
            if not path:
                continue
            name = path.rsplit('/', 1)[-1]
            services.append({'name': name, 'display_name': name, 'status': 'unknown'})
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _discover_openrc() -> list:
        try:
            result = subprocess.run(
                ['rc-status', '--all', '--nocolor'],
                capture_output=True, text=True, timeout=10,
            )
            services, seen = [], set()
            for line in result.stdout.split('\n'):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith('Runlevel:') or stripped.startswith('Dynamic'):
                    continue
                if '[' not in stripped or ']' not in stripped:
                    continue
                name = stripped.split()[0]
                raw_st = stripped[stripped.index('[') + 1:stripped.index(']')].strip()
                status = 'running' if raw_st.lower() == 'started' else raw_st.lower()
                if name not in seen:
                    seen.add(name)
                    services.append({'name': name, 'display_name': name, 'status': status})
            return sorted(services, key=lambda x: x['name'].lower())
        except Exception:
            return []

    @staticmethod
    def _discover_sysv() -> list:
        try:
            init_dir = '/etc/init.d'
            if not os.path.isdir(init_dir):
                return []
            skip = {'README', 'functions', 'rc', 'rc.local', 'rcS', 'skeleton',
                    'halt', 'reboot', 'single', 'killprocs', 'sendsigs'}
            services = []
            for name in sorted(os.listdir(init_dir)):
                if name.startswith('.') or name in skip or name.startswith('_'):
                    continue
                path = os.path.join(init_dir, name)
                if not os.access(path, os.X_OK) or os.path.isdir(path):
                    continue
                services.append({'name': name, 'display_name': name, 'status': 'unknown'})
            return services
        except Exception:
            return []

    @staticmethod
    def _discover_windows() -> list:
        try:
            services = [
                {'name': svc.name(), 'display_name': svc.display_name(), 'status': svc.status()}
                for svc in psutil.win_service_iter()
            ]
            return sorted(services, key=lambda x: x['name'].lower())
        except Exception:
            return []

    @staticmethod
    def _clear_str(text: str) -> str:
        if text:
            return str(text).strip().replace("(", "").replace(")", "")
        return ''
