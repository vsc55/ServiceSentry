#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free diagnostics helpers extracted from :mod:`lib.core.diagnostics.routes`.

Everything here takes the web admin (`wa`) and reads what it already holds — the connector, the
paths, the embedded services, the config. It imports no Flask and touches no request: the route
layer is left with three route declarations, a permission and an audit line, which is all a
route layer should be.

The split is by *what the answer depends on*, not by file size. :mod:`collect` is a function of
the process and the disk and needs nothing; this is a function of the running panel; and
:mod:`report` is a function of what those two returned. Only the middle one can be wrong in a
way that depends on how the install is deployed, which is the part worth being able to read on
its own.
"""

from __future__ import annotations

import os

from lib import __version__
from lib.config.spec import cfg_default
from lib.core.diagnostics import collect


def lock_path() -> str:
    """`src/requirements.lock`, from this file's own position in the tree.

    Walked up from `__file__` rather than read off the app or the working directory: the
    process may have been started from anywhere, and a diagnostics page that reports "no
    dependency information" because somebody `cd`'d is worse than none.
    """
    here = os.path.dirname(os.path.abspath(__file__))          # …/src/lib/core/diagnostics
    src = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(src, 'requirements.lock')


def database(wa) -> dict:
    """Which engine, which driver, and where.

    Read from the connector the panel is already using — asking the config would report what it
    was *told*, and the interesting case is exactly when those two differ.
    """
    conn = getattr(wa, '_db_connector', None)
    syslog = getattr(wa, '_syslog_db_connector', None)
    out = {'engine': getattr(conn, 'KIND', collect.UNKNOWN) if conn else collect.UNKNOWN,
           'path': str(getattr(conn, '_path', '') or ''),
           'separate_syslog_db': bool(syslog is not None and syslog is not conn)}
    if syslog is not None and syslog is not conn:
        out['syslog_engine'] = getattr(syslog, 'KIND', collect.UNKNOWN)
    return out


def runtime(wa) -> dict:
    """How this process is deployed — the answer that reframes every other one.

    Whether the scheduler runs HERE decides where to look for a check that did not run, and on
    a multi-container install that is a different container from the one serving this page.
    """
    # `global|log_level`, read the way `_apply_log_level` reads it. There is no attribute
    # mirroring it on the instance — it is applied to the shared debug printer and not held —
    # and asking for one answered an empty string, so the field said "—" on every install. A
    # diagnostics page reporting a blank where a value exists is worse than not showing the
    # row: it reads as "this is not set".
    section = wa._config_section('global') if hasattr(wa, '_config_section') else {}
    level = (section or {}).get('log_level', cfg_default('global|log_level'))
    return {
        'version': __version__,
        # `_startup_id`, which is what this process actually has: a uuid minted at start-up and
        # the thing the browser watches to notice the panel restarted. There is no
        # `_instance_id` on the web admin — asking for one answered '' and the field said "—"
        # everywhere, which reads as "this install has no identity" rather than "this page
        # asked the wrong question".
        'startup_id': str(getattr(wa, '_startup_id', '') or ''),
        'embedded_services': sorted(getattr(wa, '_embedded_services', {}) or {}),
        'log_level': str(level or ''),
        'var_dir': str(getattr(wa, '_var_dir', '') or ''),
        'config_dir': str(getattr(wa, '_config_dir', '') or ''),
    }


def network(wa, seen: dict | None = None) -> dict:
    """How this request reached the panel, and whether that answer can be believed.

    The panel never terminates TLS itself — there is no `ssl_context` anywhere in it, on
    purpose: something in front does that. So "are we on HTTPS" is not a property of this
    process. It is a CLAIM made by a proxy, and the only honest report says three things apart
    from each other: what the panel concluded, what the proxy actually sent, and whether the
    panel was configured to believe it.

    That third one is the failure this block exists for. ``X-Forwarded-Proto`` is read only
    when `web_admin|proxy_count` is above zero — that setting is what mounts ProxyFix at all —
    so with it left at 0 behind a proxy the panel serves an install that IS on https while
    believing it is on http. Then `secure_cookies` makes the browser drop the session cookie
    over what it has been told is an insecure connection, and the result is a login that
    silently loops. The panel already knows how to say this (`_hook_csrf` logs it) but only at
    the moment it breaks, and only to whoever is reading the log.

    *seen* is what the REQUEST observed, handed in by the route: this module stays Flask-free,
    and half of this answer only exists while a request is being served.
    """
    seen = seen or {}
    proxies = int(getattr(wa, '_PROXY_COUNT', 0) or 0)
    trusted = proxies > 0
    declared = str(seen.get('forwarded_proto') or '')
    secure = bool(seen.get('secure'))
    out = {
        # What the panel concluded — already through ProxyFix when it is mounted.
        'scheme': str(seen.get('scheme') or ''),
        'secure': secure,
        'host': str(seen.get('host') or ''),
        'client_ip': str(seen.get('client_ip') or ''),
        # What the proxy said, trusted or not. Reported RAW because the interesting case is
        # precisely the one where the panel is ignoring it.
        'forwarded_proto': declared,
        'forwarded_for': str(seen.get('forwarded_for') or ''),
        'forwarded_host': str(seen.get('forwarded_host') or ''),
        'proxy_count': proxies,
        'trusting_proxy_headers': trusted,
        # The panel's own socket, as a constant and not a probe: no code path gives it a TLS
        # context, and phrasing it as a question invites somebody to hunt for the setting that
        # would answer it.
        'tls_terminated_here': False,
        'force_https': bool(getattr(wa, '_FORCE_HTTPS', False)),
        'secure_cookies': bool(getattr(wa, '_SECURE_COOKIES', False)),
        'public_url': str(getattr(wa, '_PUBLIC_URL', '') or ''),
    }
    # One word for the row a person actually reads. `ignored` is not a worse `http`: it means
    # the install is on https and the panel does not know, which is a different problem with a
    # different fix (set `proxy_count`), and the two look identical in every other field.
    out['verdict'] = ('ignored' if (declared and not trusted)
                      else 'https' if secure else 'http')
    # The login loop, named before it happens: a Secure cookie cannot survive a connection the
    # panel believes is plain, whoever is right about that.
    out['cookie_trap'] = bool(out['secure_cookies'] and not secure)
    return out


def storage_paths(wa) -> dict:
    """The three directories worth reporting on, resolved the way their owners resolve them."""
    var_dir = str(getattr(wa, '_var_dir', '') or '')
    return {
        'var_dir': var_dir,
        'config_dir': str(getattr(wa, '_config_dir', '') or ''),
        # Empty `backup_dir` means `<var_dir>/backups`, and the page has to report where copies
        # ACTUALLY land — not the setting, which is blank on most installs.
        'backup_dir': (str(getattr(wa, '_BACKUP_DIR', '') or '')
                       or os.path.join(var_dir, 'backups')),
    }


def update_url(wa) -> str:
    """Where to ask about new releases. Configurable so a fork — or an install behind an
    internal mirror — points somewhere else without a code change; empty means the built-in
    default in :mod:`lib.core.diagnostics.update`."""
    section = wa._config_section('web_admin') if hasattr(wa, '_config_section') else {}
    return str((section or {}).get('update_check_url') or '')


def dependency_rows(wa) -> list:
    """The packages the remote check asks about: what the lock pins, as installed here.

    Read from the same collector the page draws, so the two halves of that table cannot
    disagree about which packages exist — and read on the SERVER, because the alternative is a
    client that gets to choose which names this panel sends to an outside service.
    """
    return list((collect.dependencies(lock_path()) or {}).get('rows') or [])


def unpinned_rows(wa) -> list:
    """Everything else installed here — the environment the lock does not describe.

    Asked about for advisories and nothing more. They are not drift and they are not a finding
    on their own: a container built from the lock still carries `pip` and `setuptools`, and a
    checkout carries the test tooling as well. But they are code on the machine, and a screen
    that said "no known vulnerabilities" while `pip` had one would have answered a narrower
    question than the one somebody read.
    """
    return list(collect.installed_outside_lock(lock_path()) or [])


def elsewhere_rows(wa) -> list:
    """Packages the OTHER processes run that this one does not, or runs at another version.

    So the remote check covers the whole installation while still being **one** round of
    requests. The alternative — each container asking PyPI and OSV about its own list — is
    four processes reaching the internet to ask nearly the same question, in precisely the
    deployment where that is least welcome.

    Only what is new is added. Four containers from one image contribute nothing here, which
    is the common case and costs nothing to confirm.
    """
    # By name AND version. The same package at two versions is two questions for the advisory
    # service, and answering one of them for both is how a container gets reported clean
    # because a different one is.
    here = {(collect.canonical_name(r.get('name')), str(r.get('installed') or ''))
            for r in dependency_rows(wa) + unpinned_rows(wa)}
    extra = set()
    for inst in instances(wa):
        if inst.get('is_self'):
            continue
        for row in (inst.get('packages') or []):
            pin = (collect.canonical_name(row.get('name')), str(row.get('version') or ''))
            if pin[1] and pin not in here:
                extra.add(pin)
    return [{'name': name, 'required': '', 'installed': version, 'status': 'elsewhere'}
            for name, version in sorted(extra)]


def packages_of(env: dict) -> list:
    """Everything one process runs, by name and version, saying which its lock pins.

    Sorted, because it is read as a list. `pinned` is carried rather than left to be inferred
    from a second lookup: over there `pip` is not drift and `flask` is, and that distinction is
    the same one the local table draws — a reader should not have to hold two screens at once
    to make it.
    """
    out = []
    for row in list((env or {}).get('lock') or []):
        out.append({'name': str(row.get('name') or ''),
                    'version': str(row.get('installed') or ''), 'pinned': True})
    for row in list((env or {}).get('extra') or []):
        out.append({'name': str(row.get('name') or ''),
                    'version': str(row.get('installed') or ''), 'pinned': False})
    out.sort(key=lambda r: collect.canonical_name(r['name']))
    return out


def _versions(env: dict) -> dict:
    """`{canonical name: version}` for everything one process reports installed."""
    out = {}
    for row in list((env or {}).get('lock') or []) + list((env or {}).get('extra') or []):
        name = collect.canonical_name(row.get('name'))
        if name:
            out[name] = str(row.get('installed') or '')
    return out


def compare_environments(mine: dict, theirs: dict) -> dict:
    """What differs between two processes' packages, and nothing that does not.

    The answer is the DIFFERENCE on purpose. Four containers built from one image carry four
    identical lists, and printing them four times is a screen nobody reads to find the one row
    that matters — while "same as this process" is the whole answer when it is true.
    """
    a, b = _versions(mine), _versions(theirs)
    diff = []
    for name in sorted(set(a) | set(b)):
        here, there = a.get(name), b.get(name)
        if here == there:
            continue
        diff.append({'name': name, 'here': here or '', 'there': there or '',
                     'kind': 'missing_there' if there is None
                             else 'missing_here' if here is None else 'version'})
    return {'same': not diff, 'rows': diff, 'count': len(diff)}


def instances(wa) -> list:
    """Every background service process, with what it runs on and how it differs from here.

    Read from the heartbeat registry — the shared database the control plane already treats as
    its source of truth — and not over HTTP: the standalone services answer no HTTP unless
    `SS_CONTROL_TOKEN` is set, which is not the default, and a diagnostics screen that works
    only on the installs that opted into a token is a diagnostics screen for somebody else.

    Empty on a single-process install: there is nothing to compare, and a table of one row
    that says "same as this process" is a table that exists to be dismissed.
    """
    store = getattr(wa, '_service_instances_store', None)
    lister = getattr(wa, '_service_instances_list', None)
    if store is None:
        return []
    try:
        rows = lister(None) if callable(lister) else store.list_instances()
    except Exception:      # pylint: disable=broad-except
        return []
    mine = collect.environment(lock_path())
    out = []
    for row in rows:
        env = row.get('env') or {}
        out.append({
            'service': row.get('service_key') or '',
            'mode': row.get('mode') or '',
            'host': row.get('host') or '',
            'pid': row.get('pid'),
            'version': row.get('version') or '',
            'state': row.get('derived_state') or ('alive' if row.get('running') else 'down'),
            'is_self': bool(row.get('is_self')),
            'last_seen': row.get('last_seen'),
            'python': str(env.get('python') or ''),
            'os': str(env.get('os') or ''),
            'arch': str(env.get('arch') or ''),
            'features': list(env.get('features') or []),
            # Everything that process runs, by name and version, saying which of them its
            # lock pins. One shape for both readers: the screen lists them when somebody asks
            # what "the same 42" actually are, and the remote check reads the same rows to
            # work out the union — a second, flatter copy alongside is how the two come to
            # disagree about what is installed over there.
            'packages': packages_of(env),
            # An instance that has not published yet — an older build, or one whose first
            # beat landed before this column existed. Said, never guessed at.
            'known': bool(env),
            'diff': compare_environments(mine, env) if env else None,
        })
    return out


def payload(wa, seen: dict | None = None) -> dict:
    """Everything answerable without leaving the machine.

    Computed on every call and never cached: a diagnostics page served from a cache describes
    the problem you had before.

    *seen* is what the request observed — the scheme, the client address and the forwarded
    headers. Passed in rather than read here, because this module is Flask-free and that half
    of the answer exists only while a request is being served.
    """
    return {
        'runtime': runtime(wa),
        'system': collect.system_info(),
        'network': network(wa, seen),
        'database': database(wa),
        'storage': collect.storage(storage_paths(wa)),
        'dependencies': collect.dependencies(lock_path()),
        'features': collect.optional_features(),
        # The other processes of this installation. Empty unless there are any: everything
        # above describes THIS process, which on a single container is the whole answer.
        'instances': instances(wa),
    }
