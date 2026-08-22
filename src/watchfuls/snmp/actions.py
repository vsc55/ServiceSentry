#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: what the panel invokes.
#
"""Discovery, and the audit detail that describes every action's outcome.

``discover`` walks a server and reports the OIDs it found, so an admin picks from a list
instead of typing an OID from a vendor PDF. ``audit_detail`` is the other half of an action:
what the audit log should say once one has run.
"""

import concurrent.futures
import logging
import os
import re
import threading
import time
import uuid

from lib.core.snmp import metrics as _metrics
from . import mib_resolver as _mib_resolver
from . import profile_store as _profile_store
from lib.core.snmp import profiles as _profiles
from .client import _HAS_PYSNMP, run_coroutine
from .defaults import _SERVER_DEFAULTS
from .sampler import read_metric as _read_metric

# What every SNMP agent answers, and therefore what identifies a device before anybody has
# decided anything about it. Everything ELSE a detection asks comes from the profiles
# themselves — see `match.probe`.
_OID_SYSOBJECTID = '1.3.6.1.2.1.1.2.0'
_OID_SYSDESCR    = '1.3.6.1.2.1.1.1.0'
_OID_SYSNAME     = '1.3.6.1.2.1.1.5.0'

# A detection is one round trip per profile that declares a probe, against a device somebody is
# waiting on. Generous for a catalogue of a few dozen and finite for an installation that grew
# hundreds; past it the rest are simply not probed, which costs suggestions and not the answer.
_MAX_PROBES = 40

# What a test says out loud while it runs. A diagnostic that only speaks at the end is one
# nobody can tell apart from a hung one, and the interesting part of a slow test is exactly
# WHICH step is slow — so every transition lands in the server log too, where somebody
# watching a dev console can see the shape of it without opening the panel.
_LOG = logging.getLogger(__name__)

# Runs in flight, keyed by the id `test_profiles_start` hands out. Same shape and the same
# GIL-safe write/poll as the MIB compiler's jobs beside it.
_test_jobs: dict = {}

# ── What a test of one device may read ───────────────────────────────────────
#
# The second half of the test is a sweep of the whole device, and a sweep has no natural
# end: a chassis switch answers tens of thousands of OIDs and a NAS with twenty volumes is
# not far behind. Every one of these is a ceiling on somebody's patience rather than on
# correctness — a test that stops early SAYS it stopped early, and what it did read is true.

# Where a device keeps what it has to say: the standard tree and the vendor's own. Between
# them they are every OID any profile in the catalogue names. The rest of the space
# (experimental, and SNMP's own administration) is protocol plumbing, and a list of it under
# "what this device sends that nobody is capturing" would be forty rows of noise at the top
# of the answer.
_SWEEP_ROOTS = ('1.3.6.1.2.1', '1.3.6.1.4.1')

_SWEEP_DEFAULT = 6000        # OIDs one test reads, unless the caller asks for more —
                             # split evenly between the roots below, so three thousand
                             # of mib-2 cannot leave the vendor tree unasked
_SWEEP_MAX     = 20000       # …and the most it may ask for
_TEST_ROWS     = 100         # rows of one table the answer carries
_TEST_SAMPLES  = 3           # example instances shown per uncaptured object
_TEST_CHARS    = 200         # how much of one value travels

# How long the reading half may spend on the device. A metric the device does NOT answer
# costs the full timeout times the retries — five seconds twice, by default — and a group
# like "Synology NAS (everything)" declares a hundred and thirty of them. Assigned to a model
# that serves half, the arithmetic is ten minutes of a button that looks stuck. The scheduler
# can afford that in the background; a person waiting on a dialog cannot. What is past the
# clock is reported as NOT READ rather than quietly missing, which is a different sentence
# from "the device did not answer" and the screen says which one it is.
_TEST_SECONDS = 60

# How many questions one test asks at once. The metrics of one device are independent — each
# is a GET or a walk of its own column — and asking them one after another is what put a
# "Synology NAS (everything)" out of reach: a hundred and fifty-seven metrics, of which the
# ones a given model does not serve cost the full timeout times the retries EACH. Eight is
# the number the module already uses for a server's checks, and for the same reason: it is
# generous against latency and modest against an agent that does not like being crowded.
_TEST_THREADS = 8

# What counts as the object an instance belongs to. Only these are things a device ANSWERS
# — one value, or one per row; everything else in the index is structure (a table, a row, a
# node in the tree). Walking up to the nearest name of ANY kind finds `enterprises` for every
# vendor OID nobody has a MIB for, and collapses the whole interesting half of the report
# into one row called "enterprises".
#
# By suffix, because the class is not always one of the two base ones: pysnmp derives columns
# of its own (`_DHAuthKeyChangeColumn`), and a whitelist of exact names would quietly drop
# them back into the tree above.
_LEAF_TYPES = ('Scalar', 'Column')


class _TestSteps:
    """The checklist a test fills in as it goes.

    Six steps, in the order they happen, each with a state, a counter and a note. It exists
    because "reading" and "walking the device" are minutes apart on a big NAS and look
    identical from outside: a spinner says something is happening, and this says what — which
    is the difference between waiting and wondering whether to press it again.

    Written from the worker threads and read from the polling request, so every mutation
    takes the lock: a counter incremented from eight threads at once is a counter that
    quietly loses ticks, and a progress bar that stops short is worse than none.
    """

    ORDER = ('connect', 'profiles', 'serves', 'read', 'sweep', 'analyse')

    def __init__(self, label: str = ''):
        self._lock = threading.Lock()
        self._label = label
        self._steps = {k: {'key': k, 'state': 'wait', 'n': 0, 'total': 0, 'note': ''}
                       for k in self.ORDER}

    def begin(self, key: str, total: int = 0, note: str = '') -> None:
        with self._lock:
            self._steps[key].update(state='run', total=int(total or 0), note=str(note or ''))
        _LOG.info('SNMP test %s: %s started%s', self._label, key,
                  f' ({total})' if total else '')

    def tick(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._steps[key]['n'] += int(n)

    def end(self, key: str, note: str = '', state: str = 'done') -> None:
        with self._lock:
            step = self._steps[key]
            step['state'] = state
            if note:
                step['note'] = str(note)
            if not step['total']:
                step['total'] = step['n']
            seen = step['n']
        _LOG.info('SNMP test %s: %s %s%s', self._label, key, state,
                  f' — {note}' if note else (f' ({seen})' if seen else ''))

    def snapshot(self) -> list:
        with self._lock:
            return [dict(self._steps[k]) for k in self.ORDER]


class _NoSteps(_TestSteps):
    """The same object for the synchronous action, which has nobody to report to."""

    def begin(self, key: str, total: int = 0, note: str = '') -> None:
        pass

    def tick(self, key: str, n: int = 1) -> None:
        pass

    def end(self, key: str, note: str = '', state: str = 'done') -> None:
        pass


def _oid_key(oid: str) -> tuple:
    """An OID sorted as a tree and not as a string, so `.10` comes after `.9`."""
    out = []
    for part in str(oid or '').split('.'):
        try:
            out.append(int(part))
        except ValueError:
            return tuple(out)
    return tuple(out)


def _covered_by(oid: str, roots: set) -> bool:
    """Is *oid* inside anything the assigned profiles read?

    Prefix containment and not equality: a metric declares a COLUMN
    (`1.3.6.1.2.1.2.2.1.10`) and the device answers one OID per row under it. Comparing the
    two directly would report every interface on the switch as uncaptured while the profile
    charts all of them.
    """
    parts = str(oid or '').split('.')
    for i in range(len(parts), 2, -1):
        if '.'.join(parts[:i]) in roots:
            return True
    return False



class SnmpActions:
    """Operations the UI calls by name (see ``WATCHFUL_ACTIONS``)."""

    @classmethod
    def audit_detail(cls, action: str, result: dict) -> dict | None:
        """Return extra fields for the audit log entry, or None to suppress.

        Returning None skips the audit entry entirely (e.g. intermediate polls).
        The route handler merges the returned dict with {module, action}.
        """
        _done = result.get('done')  # None = regular action; bool = compile job

        # Suppress intermediate compile/import-status polls (job still running).
        if action in ('compile_mibs_status', 'import_mib_from_github_status') and _done is False:
            return None
        # Suppress the GitHub import kickoff — the meaningful audit (ok/failed
        # counts + which files failed) is recorded on the final status read.
        if action == 'import_mib_from_github_start':
            return None

        detail: dict = {'ok': result.get('ok', True)}

        if action == 'compile_mibs_start' and not _done:
            detail['name'] = f'compile started ({result.get("total", 0)} MIBs)'
        elif action == 'import_mib_from_github_status' and _done:
            _imp   = int(result.get('imported', 0) or 0)
            _nfail = int(result.get('failed', 0) or 0)
            _names = list(result.get('failed_names') or [])
            detail['imported'] = _imp
            detail['failed']   = _nfail
            # The audit entry keeps BOTH lists, and the reason for each failure — the
            # only place either can be answered later, since re-running the import to
            # find out costs another few hundred requests against GitHub's 60/h
            # anonymous limit.
            _imported_names = [str(n) for n in (result.get('imported_names') or [])]
            _failed_detail  = [d for d in (result.get('failed_detail') or [])
                               if isinstance(d, dict)]
            if _imported_names:
                detail['imported_names'] = _imported_names
            if _failed_detail:
                detail['failed_detail'] = _failed_detail
            elif _names:
                detail['failed_names'] = _names
            _name = f'GitHub import: {_imp} ok, {_nfail} failed'
            if result.get('truncated'):
                _name += ' (truncated)'
            # The summary line stays a COUNT. It named the first ten failures for a
            # while, which reads well for three and turned into six lines of prose for
            # twelve behind a TLS timeout each — in a table cell, where the row is the
            # index and not the record. Which files, and why, are the structured fields
            # above; the entry opens onto them.
            detail['name'] = _name
        elif _done:
            for _f in ('compiled', 'partial', 'failed', 'result_ok', 'message', 'total'):
                if _f in result:
                    detail[_f] = result[_f]
            _msg  = result.get('message', '')
            _ntot = result.get('total', 0)
            if _msg:
                detail['name'] = _msg
            elif result.get('compiled'):
                detail['name'] = f'{_ntot} MIBs compiled'
            else:
                detail['name'] = 'already up-to-date'
        elif action in ('save_mib_source', 'restore_mib_version'):
            # A MIB is a file the monitor reads: editing one changes what every check that
            # resolves through it sees. The version number is what makes the entry findable
            # afterwards — the content itself is in the history, not in an audit row.
            _vers = result.get('versions') or []
            _v = _vers[0].get('version') if _vers else None
            detail['name'] = f'{result.get("mib", "")} v{_v}' if _v else str(result.get('mib', ''))
            if result.get('unchanged'):
                detail['name'] += ' (no change)'
        elif action == 'build_oid_index':
            detail['name'] = f'{result.get("count", 0)} OIDs'
        elif action == 'clean_library':
            detail['name'] = (f'{result.get("compiled_deleted", 0)} compiled, '
                              f'{result.get("folders_removed", 0)} folder(s)')
        else:
            # WHAT it was done to. The fallback used to repeat the action's own identifier,
            # which the screen already says in words — so the row read "Delete a MIB file"
            # and stopped exactly where the reader's question starts. Every one of these
            # results names its subject; it is a matter of asking in the right order, from
            # the most specific handle to the least.
            _subject = next((result[k] for k in ('filename', 'name', 'mib', 'relpath')
                             if isinstance(result.get(k), str) and result[k]), '')
            if _subject:
                detail['name'] = _subject
        return detail

    # ── Discovery ──────────────────────────────────────────────────────────────

    @classmethod
    def discover(cls, config: dict | None = None) -> list:
        """Walk all enabled servers and return discovered OIDs.

        ``config`` is the full module config dict (sent as POST body by the UI).
        Returns a list of ``{name, display_name, status}`` dicts where:
        - ``name``         — numeric OID string
        - ``display_name`` — current value (truncated, prefixed with server key)
        - ``status``       — SNMP type (e.g. OctetString, Integer32)
        """
        if not _HAS_PYSNMP:
            return []

        cfg     = config or {}
        servers = cfg.get('servers', {})
        if not isinstance(servers, dict):
            return []

        # Determine application data directory injected by the route handler.
        var_dir = str(cfg.get('__var_dir__') or '').strip()

        # Ensure the raw MIB directory exists, then compile the few files that are
        # waiting — and ONLY while they are few.  A discovery used to compile whatever
        # had appeared since the last one, which is fine for a MIB dropped in by hand
        # and is an hour of parsing after a folder import: ~2.7 s per MIB, and a vendor
        # repository brings hundreds.  Past the limit they stay raw and the MIB manager
        # compiles them when asked, with a progress bar and a cancel button.
        if var_dir:
            raw_dir      = os.path.join(var_dir, 'snmp_mibs', 'raw')
            compiled_dir = os.path.join(var_dir, 'snmp_mibs', 'compiled')
            os.makedirs(raw_dir, exist_ok=True)
            _pending = _mib_resolver.pending_raw_mibs(raw_dir, compiled_dir)
            if _pending and len(_pending) <= _mib_resolver.AUTO_COMPILE_LIMIT:
                _mib_resolver.compile_raw_mibs(raw_dir, compiled_dir, mibs_filter=_pending)

        # Build/refresh OID index if missing or older than any compiled MIB.
        # Done once (~0.6 s); subsequent calls load from disk in ~30 ms.
        mib_dirs_raw    = str(cfg.get('mib_dirs') or '').strip()
        mib_dirs_custom = [d.strip() for d in mib_dirs_raw.split(',') if d.strip()]
        if var_dir and _mib_resolver.index_needs_rebuild(var_dir):
            _mib_resolver.build_oid_index(var_dir, mib_dirs_custom)

        # Build resolver: default compiled dir first, then user-specified dirs.
        default_dirs = _mib_resolver.get_default_dirs(var_dir)
        # dict.fromkeys preserves order and removes duplicates
        all_dirs = list(dict.fromkeys(default_dirs + mib_dirs_custom))
        resolver = _mib_resolver.get_resolver(all_dirs, var_dir=var_dir)

        results: list[dict] = []
        per_server = max(1, 300 // max(1, len(servers))) if servers else 300

        for srv_key, srv in servers.items():
            if not isinstance(srv, dict):
                continue
            if not srv.get('enabled', True):
                continue
            host      = str(srv.get('host', '') or '').strip()
            if not host:
                continue
            port      = int(srv.get('port',      _SERVER_DEFAULTS['port'])      or _SERVER_DEFAULTS['port'])
            version   = str(srv.get('version',   _SERVER_DEFAULTS['version'])   or _SERVER_DEFAULTS['version']).strip()
            community = str(srv.get('community', _SERVER_DEFAULTS['community']) or _SERVER_DEFAULTS['community']).strip()
            timeout   = max(1, int(srv.get('timeout',  _SERVER_DEFAULTS['timeout'])  or _SERVER_DEFAULTS['timeout']))
            retries   = max(0, int(srv.get('retries',  _SERVER_DEFAULTS['retries'])  or _SERVER_DEFAULTS['retries']))

            try:
                # The v3 identity travels with the request, exactly as it does for a check.
                # Discovery used to walk with the community string whatever the version, so a
                # v3 server answered nothing and the empty result read as "this device has no
                # OIDs" rather than "nobody asked it properly".
                oids = run_coroutine(cls._snmp_walk(
                    host, port, version, community, timeout, retries,
                    max_oids=per_server,
                    v3_username=str(srv.get('snmpv3_username', '') or ''),
                    v3_auth_key=str(srv.get('snmpv3_auth_key', '') or ''),
                    v3_priv_key=str(srv.get('snmpv3_priv_key', '') or ''),
                    v3_auth_proto=str(srv.get('snmpv3_auth_protocol',
                                              _SERVER_DEFAULTS['snmpv3_auth_protocol'])
                                      or _SERVER_DEFAULTS['snmpv3_auth_protocol']),
                    v3_priv_proto=str(srv.get('snmpv3_priv_protocol',
                                              _SERVER_DEFAULTS['snmpv3_priv_protocol'])
                                      or _SERVER_DEFAULTS['snmpv3_priv_protocol']),
                ))
            except Exception:  # pylint: disable=broad-except
                continue

            # Which server answered, but only when that is a question. The discovery hangs off
            # `checks`, INSIDE one server, so the modal asks one and the prefix repeated the
            # same name down every row while eating the 160 px the value has to live in — and
            # the value is the only thing that says whether an OID is worth adding.
            #
            # The server's NAME when it is shown, never its key: items are rekeyed by uid when
            # stored, so the key is a 36-character UUID and it filled that column on its own.
            srv_label = str(srv.get('label') or '').strip() or srv_key
            prefix = f'[{srv_label}] ' if len(servers) > 1 else ''
            for item in oids:
                mib_info = resolver.resolve(item['name'])
                results.append({
                    'name':         item['name'],
                    'display_name': f'{prefix}{item["display_name"]}',
                    'status':       item['status'],
                    'mib_category': item.get('mib_category', 'unknown'),
                    **mib_info,   # mib_module, mib_name, mib_type
                })

        return results


    # -- Web UI - device profiles -------------------------------------------

    @classmethod
    def list_profiles(cls, config: dict | None = None) -> dict:
        """The whole device-profile catalogue, as the panel needs to show it.

        Both sources in one list, each row saying which it came from: the profiles that ship
        with the product and the ones this installation wrote, where reusing a shipped id
        overrides it. The screen shows that distinction because a profile that answers
        differently from the documented one is the first thing to suspect when a device
        measures wrong, and nothing else would say so.
        """
        cfg = config or {}
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        cdir = _profiles.custom_dir(var_dir)
        catalog = cls._catalog(cfg)

        items = []
        for pid in sorted(catalog):
            prof = catalog[pid]
            metrics = []
            for m in prof.get('metrics') or ():
                row = {'key': m['key'], 'label': m.get('label') or {},
                       'kind': m.get('kind', 'gauge'), 'unit': m.get('unit', ''),
                       'chart': m.get('chart', 'line'),
                       'oid': m.get('oid', ''), 'walk': m.get('walk', '')}
                for opt in ('index_label', 'width', 'scale', 'max_rate', 'role'):
                    if m.get(opt) not in (None, ''):
                        row[opt] = m[opt]
                metrics.append(row)
            row = {
                'id':          pid,
                'label':       prof.get('label') or {},
                'description': prof.get('description') or {},
                'source':      prof.get('source', 'shipped'),
                'match':       (prof.get('match') or {}).get('sysobjectid_prefix', ''),
                # The other half of how a device is recognised. Shown nowhere on the row — a
                # bare OID beside a name says nothing to a reader — but the editor prefills
                # from this list, and a field it cannot read is one that empties itself the
                # first time somebody opens the form to change the name.
                'probe':       (prof.get('match') or {}).get('probe', ''),
                'metrics':     metrics,
            }
            # A group says what it holds AND what that adds up to. Both, because they answer
            # different questions — "which profiles am I assigning" and "how much is this
            # going to measure" — and the second is the one that surprises people.
            if _profiles.is_group(prof):
                resolved = _profiles.expand(catalog, [pid])
                row['includes'] = list(prof.get('includes') or ())
                row['resolved'] = resolved
                row['resolved_metrics'] = sum(
                    len(catalog[m].get('metrics') or ()) for m in resolved)
            items.append(row)
        return {'ok': True, 'items': items, 'dir': cdir}

    # -- Web UI - the catalogue this installation writes ---------------------
    #
    # Three sources reach the catalogue: the profiles that ship, the files under
    # `<var_dir>/snmp_profiles`, and everything written in the panel — which lives in the
    # database, because a deployment with a web container and a worker container shares the
    # database and not the disk. What the panel writes is a *document*, the same shape the
    # shipped files hold, and `profiles.normalise` is the one thing that decides whether it
    # is usable. A group and a profile differ only in what their members are.

    @classmethod
    def _written_store(cls, cfg: dict):
        db = (cfg or {}).get('__connector__')
        return _profile_store.CatalogStore(db) if db is not None else None

    @classmethod
    def _catalog(cls, cfg: dict) -> dict:
        """Everything assignable, as this installation has it: the profiles that ship, the
        files it wrote, and what was written in the panel.

        One assembly point, so a screen and the sampler cannot disagree about what exists.
        """
        var_dir = str((cfg or {}).get('__var_dir__') or '').strip()
        cdir = _profiles.custom_dir(var_dir)
        store = cls._written_store(cfg or {})
        return _profiles.catalog(
            custom=_profiles.load_dir(cdir) if cdir else None,
            written=store.documents() if store is not None else None)

    # ── What every write has to agree about ──────────────────────────────────

    @staticmethod
    def _metric_why(raw) -> str:
        """WHY `normalise_metric` refused one. Asked only after it has refused.

        The verdict is always its own — this only puts a word to a "no" that has already been
        given, so the two cannot drift into disagreeing. A form that answers "not usable" to
        a metric somebody has just typed is a form they have to bisect by hand.
        """
        if not isinstance(raw, dict):
            return 'not a metric'
        if not _profile_store.ID_RE.match(str(raw.get('key') or '').strip().lower()):
            return 'the key is not an identifier'
        oid, walk = str(raw.get('oid') or '').strip(), str(raw.get('walk') or '').strip()
        if not oid and not walk:
            return 'no OID'
        if oid and walk:
            return 'both an OID and a column'
        if not _profiles._OID_RE.match(oid or walk):
            return 'the OID is not a dotted number'
        if str(raw.get('kind') or 'gauge').strip().lower() not in _profiles.KINDS:
            return 'unknown type'
        return 'invalid'

    @classmethod
    def _written_head(cls, cfg: dict) -> tuple:
        """The store, the id and the name — the three things every write needs, checked.

        Everything refused here is refused because of what the id IS downstream: the value a
        server keeps in its ``device_profiles`` field.

        * it has the shape every catalogue id has, because it lands in a JSON key and a chip;
        * it does not name something that already exists, because that entry would shadow it
          and silently unmeasure whatever it used to measure. Overriding a shipped profile is
          a deliberate act, performed by putting a file on the machine;
        * the kind behind an id never changes: a device assigned `mis_linux` when it was a
          group would go on sampling whatever a profile of that name now measures.

        Returns ``(store, pid, label, description, catalog, existing, error)`` — *error* being
        the answer to send back when it is not None.
        """
        store = cls._written_store(cfg)
        if store is None:
            return (None,) * 6 + ({'ok': False, 'message': 'database not available'},)
        pid = str(cfg.get('id') or '').strip().lower()
        label = str(cfg.get('label') or '').strip()[:_profile_store.MAX_LABEL_CHARS]
        desc = str(cfg.get('description') or '').strip()[:_profile_store.MAX_DESC_CHARS]
        if not _profile_store.ID_RE.match(pid):
            return (store, pid) + (None,) * 4 + ({'ok': False, 'message': 'invalid id'},)
        if not label:
            return (store, pid, label) + (None,) * 3 + (
                {'ok': False, 'message': 'a name is required'},)
        catalog = cls._catalog(cfg)
        existing = store.get(pid)
        if existing is None and pid in catalog:
            return (store, pid, label, desc, catalog, existing,
                    {'ok': False, 'message': 'that id already names a profile'})
        return store, pid, label, desc, catalog, existing, None

    @classmethod
    def _written_save(cls, cfg: dict, store, pid: str, body: dict, existing) -> dict:
        """Write it, having agreed it is writable. The row, plus what the screen needs."""
        row = store.save(pid, body, author=str(cfg.get('__user__') or ''))
        out = dict(row)
        out['ok'] = True
        out['created'] = existing is None
        out['name'] = cls._entry_name(body)
        return out

    @staticmethod
    def _entry_name(body) -> str:
        """What to call this entry in a toast and in the audit log.

        The panel writes ONE name — somebody typed it — while a shipped file carries one per
        language. Both are legal in the same field, and `label_of` reads the second shape.
        """
        label = (body or {}).get('label')
        if isinstance(label, str):
            return label
        return _profiles.label_of(body or {}, 'en_EN')

    # ── A group: members that are other entries ──────────────────────────────

    @classmethod
    def save_profile_group(cls, config: dict | None = None) -> dict:
        """Create or update one grouping.

        Beyond what every write agrees about: its members exist (a group of nothing is a chip
        that samples nothing), and it does not end up inside itself. Two groups naming each
        other is a reasonable thing to write by mistake, once, in a form — and it costs a
        recursion error in the middle of a monitoring cycle rather than here.
        """
        cfg = config or {}
        store, pid, label, desc, catalog, existing, err = cls._written_head(cfg)
        if err:
            return err
        if existing is not None and not _profiles.is_group(existing['body']):
            return {'ok': False, 'message': 'that id is a profile, not a group'}

        raw = cfg.get('members')
        if isinstance(raw, str):
            raw = [p for p in re.split(r'[,\s]+', raw) if p]
        members, seen = [], set()
        for m in (raw or ()):
            mid = str(m or '').strip().lower()
            if mid and mid != pid and mid not in seen:
                seen.add(mid)
                members.append(mid)
        members = members[:_profile_store.MAX_MEMBERS]
        if not members:
            return {'ok': False, 'message': 'a group with no profiles measures nothing'}
        unknown = [m for m in members if m not in catalog]
        if unknown:
            return {'ok': False, 'message': 'unknown profiles: ' + ', '.join(unknown)}

        # Asked of the catalogue as it WOULD be and not as it is: the loop a save creates is
        # the one that has to be refused, and it does not exist until the save happens.
        probe = dict(catalog)
        probe[pid] = {'id': pid, 'label': {'*': label}, 'metrics': [], 'includes': members}
        if _profiles.reaches(probe, members, pid):
            return {'ok': False, 'message': 'a group cannot contain itself'}

        body = {'id': pid, 'label': label, 'description': desc, 'includes': members}
        return cls._written_save(cfg, store, pid, body, existing)

    # ── A profile: members that are OIDs ─────────────────────────────────────

    @classmethod
    def save_profile(cls, config: dict | None = None) -> dict:
        """Create or update one profile — the OID matrix itself, written in the panel.

        The metrics are checked **one by one and by name**, because that is the difference
        between a form somebody can correct and one they have to bisect: `normalise` drops
        what it cannot use and keeps the rest, which is exactly right when reading a file
        somebody edited at 3am and exactly wrong when answering a person who is looking at
        the row they just typed.

        A duplicate key is its own refusal rather than a silent drop, for the same reason: two
        metrics under one key are two series filed as one, and which of them survives is not
        something to decide on somebody's behalf.
        """
        cfg = config or {}
        store, pid, label, desc, catalog, existing, err = cls._written_head(cfg)
        if err:
            return err
        if existing is not None and _profiles.is_group(existing['body']):
            return {'ok': False, 'message': 'that id is a group, not a profile'}

        raw = cfg.get('metrics')
        if not isinstance(raw, (list, tuple)) or not raw:
            return {'ok': False, 'message': 'a profile with no metrics measures nothing'}
        if len(raw) > _profile_store.MAX_METRICS:
            return {'ok': False,
                    'message': f'more than {_profile_store.MAX_METRICS} metrics'}
        metrics, seen, bad = [], set(), []
        for i, m in enumerate(raw):
            norm = _profiles.normalise_metric(m)
            name = str((m or {}).get('key') or '').strip() if isinstance(m, dict) else ''
            name = name or f'#{i + 1}'
            if norm is None:
                bad.append(f'{name}: {cls._metric_why(m)}')
                continue
            if norm['key'] in seen:
                bad.append(f'{name}: repeated')
                continue
            seen.add(norm['key'])
            metrics.append(m)
        if bad:
            return {'ok': False, 'message': '; '.join(bad)}

        body = {'id': pid, 'label': label, 'description': desc, 'metrics': metrics}
        # How a device is recognised as one of these. Optional — a profile assigned by hand
        # needs none — and refused rather than dropped when it is there and wrong, because a
        # prefix with a typo is a profile that is never proposed and never says why.
        match = {}
        for key in ('sysobjectid_prefix', 'probe'):
            val = str(cfg.get(key) or '').strip()
            if not val:
                continue
            if not _profiles._OID_RE.match(val):
                return {'ok': False, 'message': f'{key} is not a dotted OID'}
            match[key] = val
        if match:
            body['match'] = match
        # Last: what the panel wrote has to be something the catalogue would accept, and the
        # one authority on that is the same function that reads the shipped files.
        if _profiles.normalise(body) is None:
            return {'ok': False, 'message': 'not a usable profile'}
        return cls._written_save(cfg, store, pid, body, existing)

    # ── Taking one back ──────────────────────────────────────────────────────

    @classmethod
    def _written_delete(cls, cfg: dict, want_group: bool) -> dict:
        """Forget one entry.

        The devices that referenced it keep the id in their field. It stops resolving, exactly
        as a deleted shipped profile does, and shows there as a chip named after itself —
        rewriting other people's configuration because somebody deleted an entry is the larger
        surprise, and the field is where it is visible.
        """
        store = cls._written_store(cfg)
        if store is None:
            return {'ok': False, 'message': 'database not available'}
        pid = str(cfg.get('id') or '').strip().lower()
        row = store.get(pid)
        if row is None:
            return {'ok': False, 'message': 'no such entry'}
        if _profiles.is_group(row['body']) != want_group:
            return {'ok': False, 'message': 'that id is the other kind'}
        store.delete(pid)
        return {'ok': True, 'id': pid, 'name': cls._entry_name(row['body']) or pid}

    @classmethod
    def delete_profile_group(cls, config: dict | None = None) -> dict:
        """Forget one grouping."""
        return cls._written_delete(config or {}, True)

    @classmethod
    def delete_profile(cls, config: dict | None = None) -> dict:
        """Forget one profile written in the panel. The shipped ones are not this
        installation's to delete: a file that a release puts back is not something the panel
        can take away."""
        return cls._written_delete(config or {}, False)

    @staticmethod
    def _conn_of(cfg: dict) -> dict:
        """The kwargs both primitives take, from a server's stored fields.

        The same identity a check travels with, assembled in one place because it was
        assembled in two: an action that reads the community while the server speaks v3 asks
        a question the device does not answer, and reports the silence as a device with
        nothing on it.
        """
        return dict(
            host=str(cfg.get('host', '') or '').strip(),
            port=int(cfg.get('port', _SERVER_DEFAULTS['port']) or _SERVER_DEFAULTS['port']),
            version=str(cfg.get('version', _SERVER_DEFAULTS['version'])
                        or _SERVER_DEFAULTS['version']).strip(),
            community=str(cfg.get('community', _SERVER_DEFAULTS['community'])
                          or _SERVER_DEFAULTS['community']).strip(),
            timeout=max(1, int(cfg.get('timeout', _SERVER_DEFAULTS['timeout'])
                               or _SERVER_DEFAULTS['timeout'])),
            retries=max(0, int(cfg.get('retries', _SERVER_DEFAULTS['retries'])
                               or _SERVER_DEFAULTS['retries'])),
            v3_username=str(cfg.get('snmpv3_username', '') or ''),
            v3_auth_key=str(cfg.get('snmpv3_auth_key', '') or ''),
            v3_priv_key=str(cfg.get('snmpv3_priv_key', '') or ''),
            v3_auth_proto=str(cfg.get('snmpv3_auth_protocol',
                                      _SERVER_DEFAULTS['snmpv3_auth_protocol'])
                              or _SERVER_DEFAULTS['snmpv3_auth_protocol']),
            v3_priv_proto=str(cfg.get('snmpv3_priv_protocol',
                                      _SERVER_DEFAULTS['snmpv3_priv_protocol'])
                              or _SERVER_DEFAULTS['snmpv3_priv_protocol']),
        )

    # -- Web UI - what the assignment actually reads -------------------------

    @classmethod
    def _test_read(cls, catalog: dict, assigned: list, conn: dict, deadline: float = 0,
                   steps=None) -> tuple:
        """Every metric of every assigned profile, read off the device. ``(metrics, roots)``.

        Through `sampler.read_metric`, which is the function the scheduler reads with. The
        point of the whole screen is that what it shows is what will be recorded, and a
        second implementation of "read this metric" would be right until the day it drifted —
        the day the test says the profile works and the graph stays empty.

        In two passes and in parallel, which is what makes a whole NAS answerable at all. The
        naming and scaling columns go first, once each: an interface table with seven metrics
        against one `ifDescr` is one walk and not seven, and pre-filling them is also what
        makes the second pass safe to run wide — nothing writes to the shared cache any more.
        Then every metric at once, up to `_TEST_THREADS`. Sequentially, a device carrying
        "Synology NAS (everything)" could not finish inside its own clock, and most of the
        report came back as *not read* — which is true, and useless.
        """
        todo, roots = [], set()
        for pid in assigned:
            prof = catalog.get(pid) or {}
            for m in prof.get('metrics') or ():
                todo.append((pid, prof, m))
                # Everything the profile READS is covered, and not only what it charts: the
                # column that names the rows and the one that scales them are answers this
                # assignment is already using, and listing them as uncaptured would send
                # somebody to write a metric for a value the profile is holding.
                if m.get('oid'):
                    roots.add(str(m['oid']).strip('.'))
                if m.get('walk'):
                    roots.add(str(m['walk']).strip('.'))
                idx = m.get('index_label') or ''
                for extra in (list(idx) if isinstance(idx, (list, tuple)) else [idx]) \
                        + [m.get('scale_by') or '']:
                    if extra:
                        roots.add(str(extra).strip('.'))
        if not todo:
            return [], roots

        steps = steps or _NoSteps()
        columns: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=_TEST_THREADS) as pool:
            served = cls._test_served(catalog, assigned, conn, pool, steps)
            # The naming and scaling columns, once each — and only for the profiles this
            # device actually has. Pre-filling them is also what makes the metric pass safe
            # to run wide: nothing writes to the shared cache any more.
            extras = []
            for pid, _prof, m in todo:
                if not served.get(pid, True):
                    continue
                idx = m.get('index_label') or ''
                for extra in (list(idx) if isinstance(idx, (list, tuple)) else [idx]) \
                        + [m.get('scale_by') or '']:
                    if extra and extra not in extras:
                        extras.append(extra)
            wanted = sum(1 for t in todo if served.get(t[0], True))
            steps.begin('read', wanted + len(extras))
            for oid, (got, _e) in zip(extras, pool.map(
                    lambda o: cls._snmp_walk_oid(oid=o, **conn), extras)):
                columns[oid] = got or {}
                steps.tick('read')
            # `map` keeps the order it was given, so the report reads in catalogue order
            # however the answers came back.
            out = list(pool.map(
                lambda t: cls._test_metric(t, conn, columns, deadline,
                                           served.get(t[0], True), steps), todo))
        answered = sum(1 for m in out if m['rows'] and not m['error'])
        steps.end('read', f'{answered}/{wanted}')
        return out, roots

    @classmethod
    def _test_served(cls, catalog: dict, assigned: list, conn: dict, pool, steps) -> dict:
        """``{profile id: does this device serve it}``, asked once per profile that says how.

        The cheapest question in the whole screen and the one that saves the most: a profile
        declares `match.probe` precisely to say "this applies to a device that answers THIS",
        and a group called "everything a Synology answers" is assigned whole to a model with
        no GPU, no expansion unit, no SSD cache and no iSCSI. Reading their metrics costs the
        full timeout times the retries FORTY times over; asking their probes costs seven GETs
        at once — and what lands on the screen is better either way: "this device does not
        serve this profile" instead of forty separate "no answer"s, which look like something
        is broken.

        A profile with no probe is always read: it has not claimed anything that could be
        checked, and refusing to read it would be inventing a condition it never declared.
        """
        pairs = []
        for pid in assigned:
            probe = ((catalog.get(pid) or {}).get('match') or {}).get('probe')
            if probe:
                pairs.append((pid, probe))
        steps.begin('serves', len(pairs))
        if not pairs:
            steps.end('serves', state='skip')
            return {}
        # Submitted rather than mapped, so the count moves as the answers arrive: these are
        # the requests that WAIT — a probe for hardware the device has not got costs the whole
        # timeout — and a counter that only jumps at the end is the one somebody is watching.
        futures = {pool.submit(cls._snmp_get, oid=probe, **conn): pid for pid, probe in pairs}
        out = {}
        for fut in concurrent.futures.as_completed(futures):
            value, err = fut.result()
            out[futures[fut]] = not err and value not in (None, '')
            steps.tick('serves')
        absent = sorted(p for p, ok in out.items() if not ok)
        steps.end('serves', f'{len(pairs) - len(absent)}/{len(pairs)}')
        if absent:
            _LOG.info('SNMP test: device does not serve %s', ', '.join(absent))
        return out

    @classmethod
    def _test_metric(cls, task: tuple, conn: dict, columns: dict, deadline: float,
                     served: bool = True, steps=None) -> dict:
        """One metric of one profile, as the report carries it."""
        pid, prof, m = task
        # Past the clock the metric is still LISTED, and listed as unread: what it declares is
        # still what the assignment covers, and a metric that silently vanished from the
        # report would read as a profile with fewer metrics. Same for a profile the device
        # does not serve — and that one is not a failure at all, which is why it says so with
        # a word of its own instead of looking like an OID that went unanswered.
        late = bool(deadline) and time.time() > deadline
        rows, err = ([], '') if (late or not served) else _read_metric(
            m, conn, cls._snmp_get, cls._snmp_walk_oid, columns)
        if steps is not None and served:
            steps.tick('read')
        return {
            'profile': pid,
            'profile_label': prof.get('label') or {},
            'key':   m.get('key', ''),
            'label': m.get('label') or {},
            'kind':  m.get('kind', 'gauge'),
            'unit':  m.get('unit', ''),
            'oid':   m.get('oid', '') or m.get('walk', ''),
            'table': bool(m.get('walk')),
            'rows':  [cls._test_row(m, r) for r in rows[:_TEST_ROWS]],
            'rows_total': len(rows),
            'error': str(err or ''),
            'skipped': late,
            'unserved': not served,
        }

    @staticmethod
    def _test_row(metric: dict, row: dict) -> dict:
        """One reading, as the profile means it — beside the digits the device sent.

        Both, because they answer different questions and the screen exists for the second
        one: 405 is what the agent said, 40.5 °C is what the profile says it means, and a
        profile whose scale is wrong by ten shows a plausible temperature and a raw value
        that gives it away.

        A COUNTER has no value here and that is not a gap: a counter means the difference
        between two readings, there is one, and inventing a rate from it would be the exact
        mistake the profile format exists to prevent. What comes back is the total the
        device is at, which is what says the counter is alive.
        """
        raw = row.get('raw')
        kind = str(metric.get('kind') or 'gauge').lower()
        if kind == 'text':
            value = _metrics.attribute(metric, raw)
        elif kind == 'counter':
            value = None
        else:
            value = _metrics.scale_value(raw, metric.get('scale'))
            if value is not None and row.get('factor', 1) != 1:
                value = _metrics.scale_value(value, row['factor'])
        return {'name': str(row.get('name') or ''), 'index': str(row.get('index') or ''),
                'raw': str('' if raw is None else raw)[:_TEST_CHARS], 'value': value}

    @classmethod
    def _test_sweep(cls, conn: dict, budget: int, steps=None) -> tuple:
        """Walk the device itself. ``(pairs, truncated, error)`` with pairs ``[(oid, value)]``.

        The other half of the question, and the half nobody can answer from the profiles: an
        assignment can only be judged against what the device actually has, and the only
        thing that knows that is the device.
        """
        # A SHARE each, and not one pot the first root drains. Given the whole budget,
        # mib-2 takes it: a NAS answers a routing table, an ARP table and one row per open
        # TCP connection long before the walk reaches `enterprises` — where the vendor's own
        # subjects live, and where the answer somebody opened this screen for actually is.
        # Measured on a real Synology: every one of the three thousand OIDs went to mib-2 and
        # the vendor tree was never asked at all.
        #
        # A floor and not a quota: a root that finishes under its share hands the rest to the
        # ones after it, so a device with little in mib-2 does not waste half the sweep.
        steps = steps or _NoSteps()
        # Which trees, on the step itself: "walking the device" is not a thing anybody can
        # picture, and the two roots are exactly what makes it one — the standard tree and
        # the vendor's, asked whole, which is the only way to learn what a device has that
        # nobody thought to ask it for.
        steps.begin('sweep', budget, note=' + '.join(_SWEEP_ROOTS))
        share = max(1, budget // len(_SWEEP_ROOTS))
        spare = budget - share * len(_SWEEP_ROOTS)
        pairs, truncated, err = [], False, ''
        for root in _SWEEP_ROOTS:
            allow = share + spare
            got, werr = cls._snmp_walk_oid(oid=root, max_rows=allow, **conn)
            if werr and not got:
                err = err or str(werr)
                continue
            for index, value in (got or {}).items():
                pairs.append((f'{root}.{index}', str(value)[:_TEST_CHARS]))
            used = len(got or {})
            steps.tick('sweep', used)
            if used >= allow:
                truncated = True
            spare = max(0, allow - used)
        steps.end('sweep', f'{len(pairs)}' + (' +' if truncated else ''))
        return pairs, truncated, err

    @classmethod
    def _test_uncaptured(cls, pairs: list, roots: set, var_dir: str) -> tuple:
        """What the device sends that nothing reads, gathered under the OBJECT it belongs to.

        ``(groups, n)``. Four hundred rows saying `1.3.6.1.2.1.2.2.1.16.<n>` is the same
        sentence four hundred times: the device has an ifOutOctets column and this assignment
        is not reading it. So the instances collapse into the object they are instances of,
        resolved through the compiled MIBs, and the count is what says how big it is.

        The longest known prefix, not the parent: `.16.3` under a column that the library
        knows resolves to the column; under one it does not, dropping the last component is
        the best guess there is, and an unnamed row still carries its OID and its value —
        which is exactly what somebody writing a profile for an unclaimed box has to work
        from.
        """
        # The library is what turns `1.3.6.1.2.1.2.2.1.16` into a name somebody can act on,
        # and a stale index is the difference between an answer and a column of digits. Built
        # here on the same terms discovery builds it: only when it is missing or older than
        # the compiled MIBs, which is a second the first time and nothing afterwards.
        if var_dir and _mib_resolver.index_needs_rebuild(var_dir):
            try:
                _mib_resolver.build_oid_index(var_dir, [])
            except Exception:  # pylint: disable=broad-except
                pass           # an unnamed object still carries its OID and its value
        index = _mib_resolver.get_oid_index(var_dir) if var_dir else {}
        groups: dict = {}
        total = 0
        for oid, value in pairs:
            if _covered_by(oid, roots):
                continue
            total += 1
            parts = oid.split('.')
            # The longest prefix the library knows as a READABLE object. Its own OID is what
            # the instances under it are instances OF, and the remainder is the index — which
            # is why this is a walk and not a subtraction: an SNMP index is one component on
            # an interface table and four on one keyed by an IP address.
            obj, entry = '.'.join(parts[:-1]), None
            for i in range(len(parts), 2, -1):
                probe = '.'.join(parts[:i])
                found = index.get(probe)
                if found and str(found.get('mib_type') or '').endswith(_LEAF_TYPES):
                    obj, entry = probe, found
                    break
            grp = groups.get(obj)
            if grp is None:
                grp = groups[obj] = {
                    'oid': obj,
                    'name': (entry or {}).get('mib_name', ''),
                    'module': (entry or {}).get('mib_module', ''),
                    'type': (entry or {}).get('mib_type', ''),
                    'count': 0, 'samples': [],
                }
            grp['count'] += 1
            if len(grp['samples']) < _TEST_SAMPLES:
                grp['samples'].append({'oid': oid, 'value': value})
        return sorted(groups.values(), key=lambda g: _oid_key(g['oid'])), total

    @classmethod
    def test_profiles(cls, config: dict | None = None, steps=None) -> dict:
        """Run one device's assignment against the device, and report BOTH gaps.

        An assignment can be wrong in two directions and only one of them is visible from the
        panel. A profile that names an OID the device does not serve leaves an empty chart,
        which somebody eventually notices. A device that serves something no assigned profile
        names is invisible — nothing is missing on any screen, because nothing ever said it
        could be there. That second one is why this action walks the device instead of only
        reading what it was told to read: what is NOT being captured cannot be derived from
        the profiles, only from the box.

        So: every metric of every assigned profile, read exactly as the scheduler reads it,
        with the raw answer beside the value it turns into; and then a sweep of the standard
        and vendor trees, minus everything the assignment already reads, gathered under the
        objects the compiled MIBs name.
        """
        cfg = config or {}
        steps = steps or _NoSteps()
        if not _HAS_PYSNMP:
            return {'ok': False, 'message': 'pysnmp is not installed'}
        host = str(cfg.get('host', '') or '').strip()
        if not host:
            return {'ok': False, 'message': 'no host'}

        conn = cls._conn_of(cfg)
        started = time.time()

        steps.begin('connect', note=f"{host}:{conn['port']} v{conn['version']}")
        sysoid, err = cls._snmp_get(oid=_OID_SYSOBJECTID, **conn)
        if err:
            # The one OID every agent has went unanswered. Everything below would be an empty
            # result about a device nobody is talking to, and "nothing is being captured" is
            # a very different sentence from "the device did not answer".
            steps.end('connect', str(err), state='fail')
            return {'ok': False, 'message': str(err)}
        sysdescr, _e1 = cls._snmp_get(oid=_OID_SYSDESCR, **conn)
        sysname,  _e2 = cls._snmp_get(oid=_OID_SYSNAME,  **conn)
        steps.end('connect', str(sysname or host))

        steps.begin('profiles')
        catalog = cls._catalog(cfg)
        asked = _profiles.assigned(cfg)
        # Through `expand`, which is where a group stops being one: a device carrying
        # "Synology NAS (everything)" is carrying twenty-two profiles, and the test has to
        # read what will be sampled and not what was typed in the field.
        assigned = _profiles.expand(catalog, asked)
        _total = sum(len((catalog.get(p) or {}).get('metrics') or ()) for p in assigned)
        steps.end('profiles', f'{len(assigned)} / {_total}')

        metrics, roots = cls._test_read(catalog, assigned, conn,
                                        deadline=started + _TEST_SECONDS, steps=steps)
        try:
            budget = int(cfg.get('sweep_max') or _SWEEP_DEFAULT)
        except (TypeError, ValueError):
            budget = _SWEEP_DEFAULT
        budget = max(100, min(_SWEEP_MAX, budget))
        pairs, truncated, sweep_err = cls._test_sweep(conn, budget, steps=steps)
        var_dir = str(cfg.get('__var_dir__') or '').strip()
        steps.begin('analyse', len(pairs))
        groups, uncaptured = cls._test_uncaptured(pairs, roots, var_dir)
        steps.end('analyse', f'{uncaptured}')

        return {
            'ok': True,
            'host': host,
            'sysobjectid': str(sysoid or ''),
            'sysdescr':    str(sysdescr or ''),
            'sysname':     str(sysname or ''),
            'asked':       asked,
            'profiles': [{'id': pid,
                          'label': (catalog.get(pid) or {}).get('label') or {},
                          'metrics': len((catalog.get(pid) or {}).get('metrics') or ())}
                         for pid in assigned],
            # An id in the field that the catalogue no longer has. Asked of what was
            # TYPED and not of what came back: `expand` drops what it cannot resolve, so
            # asking it is asking the one list the answer has already been removed from.
            # This is the field of a device pointing at a profile somebody deleted — it
            # measures nothing, for ever, and no other screen would ever say so.
            'missing':  [pid for pid in asked if pid not in catalog],
            'metrics':  metrics,
            'answered': sum(1 for m in metrics if m['rows'] and not m['error']),
            'skipped':  sum(1 for m in metrics if m['skipped']),
            'unserved': sum(1 for m in metrics if m['unserved']),
            'values':   sum(m['rows_total'] for m in metrics),
            'sweep': {
                'walked':     len(pairs),
                'truncated':  truncated,
                'error':      sweep_err,
                'uncaptured': uncaptured,
                'objects':    groups,
            },
            'seconds': round(time.time() - started, 1),
        }

    @classmethod
    def test_profiles_start(cls, config: dict | None = None) -> dict:
        """Run the test in the background and hand back an id to watch it by.

        A test of a NAS is a minute of work on a bad day, and a screen that shows a spinner
        for a minute is one nobody can tell from a hung one — the interesting part of a slow
        test is WHICH step is slow. So the work goes to a thread and the answer is polled: the
        same shape the MIB compiler already has, for the same reason.

        The synchronous action stays exactly as it was. It is the one the tests drive and the
        one anything without a UI would call, and it is now the same code path with nobody
        listening to the steps.
        """
        cfg = config or {}
        if not _HAS_PYSNMP:
            return {'ok': False, 'message': 'pysnmp is not installed'}
        if not str(cfg.get('host', '') or '').strip():
            return {'ok': False, 'message': 'no host'}

        job_id = uuid.uuid4().hex[:12]
        steps = _TestSteps(str(cfg.get('host') or ''))
        _test_jobs[job_id] = {'done': False, 'steps': steps, 'result': None}

        def _run():
            try:
                result = cls.test_profiles(cfg, steps=steps)
            except Exception as exc:      # pylint: disable=broad-except
                # A crash mid-test must end the job, or the screen polls a dead thread for
                # ever. What went wrong travels as the message, which is the only place
                # anybody would look for it.
                _LOG.exception('SNMP test failed')
                result = {'ok': False, 'message': str(exc)}
            job = _test_jobs.get(job_id)
            if job is not None:
                job['result'] = result
                job['done'] = True

        threading.Thread(target=_run, name='snmp-test', daemon=True).start()
        return {'ok': True, 'job_id': job_id, 'done': False,
                'steps': steps.snapshot()}

    @classmethod
    def test_profiles_status(cls, config: dict | None = None) -> dict:
        """Where a running test has got to — and, once, its whole answer.

        Dropped on the first read that finds it finished, like the compile job: the result of
        a test is a picture of one moment and there is nothing to come back to it for.
        """
        job_id = str((config or {}).get('job_id') or '').strip()
        job = _test_jobs.get(job_id)
        if job is None:
            return {'ok': False, 'message': 'Job not found or already collected'}
        snapshot = job['steps'].snapshot()
        if not job['done']:
            return {'ok': True, 'done': False, 'steps': snapshot}
        del _test_jobs[job_id]
        return {'ok': True, 'done': True, 'steps': snapshot, **(job['result'] or {})}

    @classmethod
    def detect_profiles(cls, config: dict | None = None) -> dict:
        """Ask ONE device what it is, and propose the profiles that fit it.

        A proposal and never an assignment: the box in the rack is always the one nobody wrote
        a profile for, and a wrong profile does not fail - it measures numbers that look fine.
        The admin confirms.

        **Which profiles are candidates is declared by the profiles**, not listed here. Each
        says how it is recognised: `match.sysobjectid_prefix` (who made the device) and/or
        `match.probe` (an OID it must answer). This action carried a hardcoded list of "the
        generic ones" for exactly one build, and the profile added in that build was invisible
        to it - which is what a list of module names inside the core always turns into.

        Two kinds of question, because a device answers two different ones about itself: who
        made it, and what it serves. Only the second can answer "does it implement
        HOST-RESOURCES-MIB", and a Synology, a Linux box and a Windows server all do while
        their sysObjectIDs have nothing in common.
        """
        cfg = config or {}
        if not _HAS_PYSNMP:
            return {'ok': False, 'message': 'pysnmp is not installed', 'items': []}

        host = str(cfg.get('host', '') or '').strip()
        if not host:
            return {'ok': False, 'message': 'no host', 'items': []}
        conn = cls._conn_of(cfg)

        sysoid, err = cls._snmp_get(oid=_OID_SYSOBJECTID, **conn)
        if err:
            # The device did not answer the one OID every agent has. Nothing below would mean
            # anything, and "no profile matches" would read as a device with nothing to measure.
            return {'ok': False, 'message': str(err), 'items': []}
        sysdescr, _e1 = cls._snmp_get(oid=_OID_SYSDESCR, **conn)
        sysname,  _e2 = cls._snmp_get(oid=_OID_SYSNAME,  **conn)

        catalog = cls._catalog(cfg)

        # Who made it: every profile whose sysObjectID prefix claims this device. Several,
        # because a vendor's system, disks and volumes are three subjects and three profiles,
        # and they all claim the same tree — proposing one would leave the rest undetected on
        # exactly the hardware they were written for.
        claimed = _profiles.claims_sysobjectid(catalog, str(sysoid or ''))
        matched = claimed[0] if claimed else None

        # What it serves: every profile that names an OID the device has to answer. Probed in
        # catalogue order so the result is the same on every run, and capped so a large
        # catalogue cannot turn one button into a minute of round trips.
        proposed, reasons, probed = [], {}, 0
        for pid in sorted(catalog):
            probe = (catalog[pid].get('match') or {}).get('probe')
            if not probe:
                continue
            if probed >= _MAX_PROBES:
                break
            probed += 1
            value, perr = cls._snmp_get(oid=probe, **conn)
            # Answering at all is the signal: the value itself belongs to the profile's own
            # metrics, and a threshold here would be this action deciding something about a
            # profile it is not supposed to know anything about.
            if perr or value in (None, ''):
                continue
            proposed.append(pid)
            reasons[pid] = 'probe'
        # A vendor's claim proposes only the profiles that do NOT declare a probe. A profile
        # that names one has made a more specific statement about itself — "the device has to
        # answer THIS" — and a model that does not answer it does not have what the profile
        # measures. Proposing it anyway would offer empty charts, and (through supersedes)
        # would displace the generic profile that does work on that model.
        for prof in claimed:
            if (prof.get('match') or {}).get('probe'):
                continue
            if prof['id'] not in proposed:
                proposed.append(prof['id'])
            reasons.setdefault(prof['id'], 'sysobjectid')

        # A vendor profile that measures what a generic one measures wins on that device: the
        # vendor knows its own hardware, and proposing both would chart every disk twice under
        # two sets of names. Only what was PROPOSED supersedes — a profile the device does not
        # serve cannot displace one it does.
        replaced = set()
        for pid in proposed:
            replaced.update((catalog[pid].get('match') or {}).get('supersedes') or ())
        if replaced:
            proposed = [p for p in proposed if p not in replaced]
            reasons = {k: v for k, v in reasons.items() if k not in replaced}

        # Thirteen profiles is a correct answer to a question nobody asked. Where a grouping
        # already holds exactly what was found, the grouping IS the answer: the same profiles
        # are sampled, there is one thing to read in the field, and one thing to change when
        # the family grows a fourteenth. Only a group whose members are ALL present may stand
        # for them — a partial cover would assign profiles this device did not answer, which
        # is the failure this whole flow exists to avoid.
        grouped = _profiles.collapse(catalog, proposed)
        for gid in grouped:
            if gid not in reasons:
                reasons[gid] = 'group'
        reasons = {k: v for k, v in reasons.items() if k in set(grouped)}
        proposed = grouped

        return {
            'ok':          True,
            'items':       proposed,
            'reasons':     reasons,
            'probed':      probed,
            'sysobjectid': str(sysoid or ''),
            'sysdescr':    str(sysdescr or ''),
            'sysname':     str(sysname or ''),
            'matched':     matched['id'] if matched else '',
        }
