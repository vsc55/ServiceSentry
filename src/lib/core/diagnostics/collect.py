#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this install actually is, collected from the process it runs in.

The questions this answers are the ones asked in a support thread, in this order: *what
version is it, what is it running on, is anything missing, and where does it write*. Every one
of them was answerable before — by reading a log, opening a shell in the container, or knowing
which library turns which feature on. That is three people's afternoon per question.

**Everything here is a pure function of the process and the filesystem.** No Flask, no
database, no network — the update check lives next door in :mod:`update` precisely because it
is the one thing that reaches outside, and mixing it in here would make a page that renders in
milliseconds wait on a socket.

**Nothing here raises.** A diagnostics screen that fails is the one screen whose failure you
cannot diagnose, so every collector answers a dict with what it could find and says what it
could not. A missing `platform.freedesktop_os_release`, an unreadable mount, a package with no
metadata: each is a field that reads "unknown", never a 500.

**Nothing here reports a secret.** The values are versions, paths, counts and flags. Paths are
the one judgement call — they name directories, which is what "where does it write" means, and
they are already visible in the config screen to anybody who can read this one.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
import time

# When this process started, near enough. Read at import — the module is imported once, during
# start-up, so the drift is the import order and not a number that grows every reload.
_STARTED = time.time()

UNKNOWN = 'unknown'


def _safe(fn, default=UNKNOWN):
    """Call *fn*, answering *default* if it raises for any reason.

    Broad on purpose: the callers are `platform` and `os` functions that fail differently on
    every OS — `OSError` on a missing mount, `AttributeError` for a function that only exists
    on Linux, `PermissionError` inside a hardened container. What matters is that one unknown
    field never costs the other forty.
    """
    try:
        value = fn()
    except Exception:      # pylint: disable=broad-except
        return default
    return default if value in (None, '') else value


def _in_container() -> bool:
    """Is this a container? Worth knowing before anything else on the page.

    It changes what every other answer means: a path that "exists" is inside an image that may
    be recreated tomorrow, and free disk is the layer's, not the host's. Two signals, because
    neither is universal — Docker's marker file, and a cgroup line naming a container runtime.
    """
    if os.path.exists('/.dockerenv'):
        return True
    try:
        with open('/proc/1/cgroup', encoding='utf-8') as fh:
            blob = fh.read()
        return any(k in blob for k in ('docker', 'kubepods', 'containerd', 'lxc'))
    except OSError:
        return False


def system_info() -> dict:
    """The machine and the interpreter underneath it."""
    return {
        'os': _safe(platform.system),
        'os_release': _safe(platform.release),
        'os_version': _safe(platform.version),
        # A friendly name where the OS publishes one ('Debian GNU/Linux 12'), because
        # 'Linux 6.1.0-18-amd64' answers a different question than the one being asked.
        'distribution': _distribution(),
        'arch': _safe(platform.machine),
        'hostname': _safe(platform.node),
        'container': _in_container(),
        'cpu_count': os.cpu_count() or 0,
        'python': _safe(platform.python_version),
        'python_impl': _safe(platform.python_implementation),
        'python_exe': sys.executable or UNKNOWN,
        'pid': os.getpid(),
        # Not `time.tzname[0]`: that is the name of standard time, so a panel running in
        # summer reports the wrong one. The offset is what a timestamp mismatch is read
        # against, and it is the reason this field exists at all.
        'timezone': _safe(lambda: time.strftime('%Z')),
        'utc_offset': _safe(lambda: time.strftime('%z')),
        'now': time.strftime('%Y-%m-%d %H:%M:%S'),
        'uptime_seconds': int(time.time() - _STARTED),
    }


def _distribution() -> str:
    """The distribution's own name for itself, where it publishes one."""
    reader = getattr(platform, 'freedesktop_os_release', None)     # Python 3.10+, Linux only
    if reader is not None:
        data = _safe(reader, default={})
        if isinstance(data, dict) and data.get('PRETTY_NAME'):
            return data['PRETTY_NAME']
    if platform.system() == 'Windows':
        return ' '.join(x for x in (_safe(platform.system, ''), _safe(platform.release, '')) if x)
    return UNKNOWN


# ── Dependencies ─────────────────────────────────────────────────────────────
#
# Read from the LOCK file and not from `pip freeze`: the lock is what the install was built
# from, so "installed 3.1 where the lock says 3.4" is a fact about this deployment and not a
# list of everything that happens to be importable. The comparison is by string equality on
# purpose — this reports a difference, it does not judge whether the difference is safe.

def _parse_lock(path: str) -> list:
    """`[(name, pinned_version)]` from a `pip` requirements file.

    Hand-parsed rather than with `packaging`: the lock is `name==version` a few dozen times,
    and a diagnostics page that needs a parser dependency to report on dependencies has a
    problem it cannot report on.
    """
    out = []
    try:
        with open(path, encoding='utf-8') as fh:
            lines = fh.readlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.split('#', 1)[0].strip()
        # `--hash=…` continuation lines, and any other flag. They belong to the requirement
        # above them and are not requirements themselves.
        if not line or line.startswith('-'):
            continue
        line = line.split(';', 1)[0].strip()        # drop environment markers
        # The line CONTINUES: `pip-compile --generate-hashes` writes `name==1.7.2 \` with the
        # hashes underneath, and a version carrying that backslash matches nothing. Every
        # pinned package then reported as "a different version installed" — forty-one of them,
        # all of them correct, which is the kind of wrong answer that costs an afternoon before
        # anybody doubts the screen rather than the deployment.
        line = line.rstrip('\\').strip()
        if '==' in line:
            name, _sep, version = line.partition('==')
            out.append((name.strip(), version.strip()))
        elif line:
            out.append((line.strip(), ''))
    return out


def _installed(name: str) -> str:
    from importlib import metadata                  # noqa: PLC0415  (stdlib, imported lazily)
    try:
        return metadata.version(name)
    except Exception:      # pylint: disable=broad-except
        return ''


def dependencies(lock_path: str) -> dict:
    """Every pinned requirement, with what is actually installed beside it.

    Three verdicts and no fourth: `ok`, `missing` (nothing provides it) and `mismatch` (a
    different version than the lock pinned). "Newer" is deliberately not a verdict — a
    deployment that drifted upward drifted, and calling that fine is how a support thread
    starts by ruling out the true cause.
    """
    rows = []
    for name, pinned in _parse_lock(lock_path):
        have = _installed(name)
        if not have:
            status = 'missing'
        elif pinned and have != pinned:
            status = 'mismatch'
        else:
            status = 'ok'
        rows.append({'name': name, 'required': pinned, 'installed': have, 'status': status})
    rows.sort(key=lambda r: ({'missing': 0, 'mismatch': 1, 'ok': 2}[r['status']], r['name']))
    return {
        'source': lock_path,
        'found': bool(rows),
        'rows': rows,
        'missing': sum(1 for r in rows if r['status'] == 'missing'),
        'mismatch': sum(1 for r in rows if r['status'] == 'mismatch'),
    }


# The same package spelled two ways. `pip` writes `charset-normalizer` in a lock and the
# distribution on disk may call itself `charset_normalizer`; comparing the two literally puts
# one package on both sides of "is this pinned".
_CANON_RE = re.compile(r'[-_.]+')


def canonical_name(name: str) -> str:
    """A package name as PEP 503 compares them: lowercase, every run of `-_.` a single dash."""
    return _CANON_RE.sub('-', str(name or '').strip()).lower()


def installed_outside_lock(lock_path: str) -> list:
    """What is installed in this environment that the lock does NOT pin.

    The lock is the deployment's contract and the table above is about keeping it; this is the
    rest of the environment — `pip` and `setuptools` in a container built from that lock, plus
    the test and tooling packages in a development checkout. They are not a drift to fix, which
    is why they are not a fourth status in :func:`dependencies` and never appear as a problem.

    They exist here for exactly one reason: **they are code that runs on the machine, so they
    can carry an advisory.** A table that reported "no known vulnerabilities" while `pip` had
    one would be answering a narrower question than the one being read off the screen.

    Rows are shaped like the pinned ones — name, required (empty, nothing pinned it), installed,
    status — so the remote check consumes one list and does not learn a second row format.
    """
    from importlib import metadata                  # noqa: PLC0415  (stdlib, imported lazily)
    pinned = {canonical_name(n) for n, _v in _parse_lock(lock_path)}
    out, seen = [], set()
    try:
        dists = list(metadata.distributions())
    except Exception:      # pylint: disable=broad-except
        return out
    for dist in dists:
        try:
            name = str((dist.metadata or {}).get('Name') or '')
            version = str(dist.version or '')
        except Exception:      # pylint: disable=broad-except
            # A half-written `.dist-info` in a shared image. One unreadable package is one row
            # missing, never a page that fails.
            continue
        key = canonical_name(name)
        # The same distribution twice — two `site-packages` on the path, a vendored copy. The
        # first one wins because the first one is the one that gets imported.
        if not key or key in pinned or key in seen:
            continue
        seen.add(key)
        out.append({'name': name, 'required': '', 'installed': version, 'status': 'unpinned'})
    out.sort(key=lambda r: canonical_name(r['name']))
    return out


_ENV_CACHE: dict = {}


def environment(lock_path: str) -> dict:
    """What this PROCESS is running on, small enough to publish beside a heartbeat.

    Computed once and kept. Unlike everything else on this page — which is recomputed on every
    call on purpose, because a diagnostics screen served from a cache describes the problem you
    had before — none of this can change while the process lives: a package cannot be installed
    into a running interpreter's view of itself, and the lock is read from the source tree. It
    is a full walk of every installed distribution, and it now runs on every render of the page
    (to compare against the other containers) as well as once at start-up.

    The diagnostics page describes the process that served the request. On a single-container
    install that is the whole installation; split across containers it is the web admin and
    nothing else — the worker, the syslog receiver and the event processor are invisible from
    every screen, and "is that pod on the same build?" is exactly the question a support
    thread opens with.

    So each process publishes this once and the panel reads it from the shared database. Once,
    because none of it can change without a restart, and a restart is a new instance row.

    Deliberately smaller than :func:`dependencies` and friends: names and versions, no
    verdicts. Whoever reads it compares against their own — the comparison belongs where both
    sides are in hand, not baked into each half separately.
    """
    cached = _ENV_CACHE.get(lock_path)
    if cached is not None:
        return cached
    info = system_info()
    out = {
        'python': info.get('python', ''),
        'python_impl': info.get('python_impl', ''),
        'os': info.get('distribution') or info.get('os', ''),
        'arch': info.get('arch', ''),
        'container': info.get('container', False),
        'lock': [{'name': r['name'], 'required': r['required'], 'installed': r['installed']}
                 for r in (dependencies(lock_path).get('rows') or [])],
        'extra': [{'name': r['name'], 'installed': r['installed']}
                  for r in installed_outside_lock(lock_path)],
        # Which optional libraries this process has. A worker without `paramiko` runs every
        # SSH check as "skipped", and nothing on any screen said so.
        'features': sorted(f['module'] for f in optional_features() if f.get('available')),
    }
    _ENV_CACHE[lock_path] = out
    return out


# ── Optional features ────────────────────────────────────────────────────────
#
# The list that answers most of the questions this page exists for. A panel where the SSO
# button never appears, or SNMP checks are all skipped, is almost never misconfigured: the
# library is not installed, the feature switched itself off, and nothing on screen said which.
#
# Declared as data — import name, what it is for — so a feature that grows a dependency adds a
# row here instead of a paragraph in a support answer.

OPTIONAL_FEATURES = (
    {'module': 'ldap3',       'feature': 'diag_feat_ldap'},
    {'module': 'pysnmp',      'feature': 'diag_feat_snmp'},
    {'module': 'paramiko',    'feature': 'diag_feat_ssh'},
    {'module': 'authlib',     'feature': 'diag_feat_oidc'},
    {'module': 'onelogin',    'feature': 'diag_feat_saml'},
    {'module': 'jwt',         'feature': 'diag_feat_msteams_bot'},
    {'module': 'cryptography', 'feature': 'diag_feat_secrets'},
    {'module': 'psycopg',     'feature': 'diag_feat_postgres'},
    {'module': 'pymysql',     'feature': 'diag_feat_mysql'},
)


def optional_features() -> list:
    """Which optional libraries are importable, and what each one turns on.

    `find_spec` and not `import`: importing to find out costs the import — pysnmp alone is
    seconds and a pile of memory — on a page whose whole job is to be readable at a glance.
    """
    from importlib.util import find_spec            # noqa: PLC0415
    out = []
    for spec in OPTIONAL_FEATURES:
        name = spec['module']
        try:
            present = find_spec(name) is not None
        except (ImportError, ValueError):
            # A namespace package that half-exists raises rather than answering False, and a
            # broken install is exactly the case this page is for: report it as absent.
            present = False
        out.append({'module': name, 'feature_key': spec['feature'], 'available': present,
                    'version': _installed(name) if present else ''})
    return out


# ── Storage ──────────────────────────────────────────────────────────────────

def storage(paths: dict) -> list:
    """For each named directory: is it there, can we write to it, how much room is left.

    Writability is tested by ASKING the OS (`os.access`), not by writing a file: a diagnostics
    page must not create anything, least of all in the directory somebody is looking at
    because it is behaving strangely.
    """
    out = []
    for key, path in (paths or {}).items():
        path = str(path or '')
        row = {'key': key, 'path': path, 'exists': False, 'writable': False,
               'free_bytes': 0, 'total_bytes': 0}
        if path:
            row['exists'] = os.path.isdir(path)
            row['writable'] = bool(row['exists'] and os.access(path, os.W_OK))
            usage = _safe(lambda p=path: shutil.disk_usage(p), default=None)
            if usage is not None:
                row['free_bytes'] = int(usage.free)
                row['total_bytes'] = int(usage.total)
        out.append(row)
    return out
