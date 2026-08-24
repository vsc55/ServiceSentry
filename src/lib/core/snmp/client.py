#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP watchful: the conversation with the device.
#
"""GET and WALK, and the optional dependency they need.

Everything about speaking SNMP lives here: the pysnmp import guard, the auth/priv protocol
tables, and the two primitives the rest of the module calls. A check decides WHAT to ask and
what the answer means; this decides how to ask it.
"""

import asyncio
import threading

from .mibs import resolver as _mib_resolver


#: The loop every SNMP request runs on, and the thread turning it. One for the process, on
#: purpose: the engine below cannot outlive the loop its socket was opened on, so keeping the
#: engine means keeping the loop.
_LOOP = None
_LOOP_THREAD = None
_LOOP_LOCK = threading.Lock()


def _snmp_loop():
    """The loop, started on first use and left running.

    Checked for a live thread rather than assumed: a loop whose thread has gone is a loop
    nothing will ever run, and every caller would block on it for ever.
    """
    global _LOOP, _LOOP_THREAD           # pylint: disable=global-statement
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed() or not (
                _LOOP_THREAD and _LOOP_THREAD.is_alive()):
            _reset()
            _LOOP = asyncio.new_event_loop()
            _LOOP_THREAD = threading.Thread(target=_LOOP.run_forever, name='snmp-loop',
                                            daemon=True)
            _LOOP_THREAD.start()
        return _LOOP


def run_coroutine(coro):
    """Run *coro* on the SNMP loop and wait for it, from whatever thread called.

    Handed to a loop of our own rather than run on the caller's, which settles a question this
    module used to answer twice: `asyncio.run` **refuses** when the calling thread already has
    one going, and this is called from whatever thread the panel is serving on. Now no caller
    needs a loop and none of them is asked for one.

    Found the hard way, in the version that did use `asyncio.run`. Discovery wraps it in a
    `try/except: continue`, so on a thread with a live loop every server raised, every server
    was skipped, and the empty list read as *this device has no OIDs* — the exact symptom the
    walk had been rewritten to fix, from a different cause. It surfaced in CI because the
    browser tests run Playwright's sync API, which keeps a loop alive in the main thread; the
    reason to fix it is that a request thread is not ours to make assumptions about.

    Nothing already ON the loop may call this — it would wait for itself. Nothing does: what
    runs there are the coroutines below, and they await each other directly.
    """
    return asyncio.run_coroutine_threadsafe(coro, _snmp_loop()).result()


# ── Optional dependency: pysnmp ───────────────────────────────────────────────
# pysnmp 6+/7+ (lextudio fork) moved everything to pysnmp.hlapi.v3arch.asyncio.
_HAS_PYSNMP = False
try:
    from pysnmp.hlapi.v3arch.asyncio import (   # type: ignore[import]
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        UsmUserData,
        bulk_walk_cmd,
        get_cmd,
        walk_cmd,
        usmAesCfb128Protocol,
        usmAesCfb192Protocol,
        usmAesCfb256Protocol,
        usmDESPrivProtocol,
        usmHMACMD5AuthProtocol,
        usmHMACSHAAuthProtocol,
        usmNoAuthProtocol,
        usmNoPrivProtocol,
        usmHMAC128SHA224AuthProtocol,
        usmHMAC192SHA256AuthProtocol,
        usmHMAC256SHA384AuthProtocol,
        usmHMAC384SHA512AuthProtocol,
        usm3DESEDEPrivProtocol,
    )
    _HAS_PYSNMP = True
except ImportError:
    pass


# ── Protocol lookup tables (populated only when pysnmp is available) ──────────
if _HAS_PYSNMP:
    _AUTH_PROTOCOLS: dict = {
        'MD5':     usmHMACMD5AuthProtocol,
        'SHA':     usmHMACSHAAuthProtocol,
        'SHA-224': usmHMAC128SHA224AuthProtocol,
        'SHA-256': usmHMAC192SHA256AuthProtocol,
        'SHA-384': usmHMAC256SHA384AuthProtocol,
        'SHA-512': usmHMAC384SHA512AuthProtocol,
        'none':    usmNoAuthProtocol,
    }
    _PRIV_PROTOCOLS: dict = {
        'DES':     usmDESPrivProtocol,
        '3DES':    usm3DESEDEPrivProtocol,
        'AES-128': usmAesCfb128Protocol,
        'AES-192': usmAesCfb192Protocol,
        'AES-256': usmAesCfb256Protocol,
        'none':    usmNoPrivProtocol,
    }
else:
    _AUTH_PROTOCOLS = {}
    _PRIV_PROTOCOLS = {}


#: The engine every request is sent through, and the transport targets resolved for it.
#:
#: Rebuilt per request — which is what this module did — an ``SnmpEngine`` costs a SECOND.
#: Measured on loopback against a local agent answering instantly, so none of it is the
#: network. Two things happen inside, and pysnmp does both once per engine:
#:
#: * it recompiles thirteen MIB modules from their Python source. `runpy.run_path` compiles
#:   the file every time, so the `.pyc` beside it is never the thing that gets used;
#: * the first OID resolved builds a full LALR parser for the SMI grammar — pysmi's ASN.1
#:   compiler, constructed to look up an OID this module already holds in numbers.
#:
#: Neither is a cost of ASKING; both are costs of BEING an engine. A device carrying the whole
#: catalogue is 348 reads, so the sampling cycle was 365 seconds of which about six were the
#: device. Keeping the engine: 6 seconds. That is the "SNMP collection takes for ever" report,
#: and the "the panel goes slow while it runs" one with it — that second was CPU, held by a
#: sampling thread pool, in a process that also serves pages.
#:
#: Safe to keep. pysnmp is written for it: the LCD configures per target, so one engine serves
#: many devices, and v3 time sync is discovered per device and expires after 300 s, so a device
#: that reboots is re-discovered rather than locked out. Verified against two local agents
#: answering different values, forty walks concurrently — no answer arrived from the wrong one.
_ENGINE = None
_TARGETS: dict = {}
_AUTHS: dict = {}
_TARGET_LOCK = None


def _reset() -> None:
    """Forget the engine and everything resolved for it. For the loop going away, and tests."""
    global _ENGINE, _TARGET_LOCK         # pylint: disable=global-statement
    engine, _ENGINE = _ENGINE, None
    _TARGETS.clear()
    _AUTHS.clear()
    _TARGET_LOCK = None
    if engine is not None:
        try:
            engine.close_dispatcher()
        except Exception:  # pylint: disable=broad-except
            pass


async def _engine():
    """The shared engine, built on the loop thread the first time anything asks.

    On the loop and not in the caller: the dispatcher binds to whatever loop is running when
    the first request opens its socket, and an engine bound to a loop that has gone answers
    nothing, silently.
    """
    global _ENGINE                       # pylint: disable=global-statement
    if _ENGINE is None:
        _ENGINE = SnmpEngine()
    return _ENGINE


async def _target(host: str, port: int, timeout: int, retries: int):
    """The transport for one device, resolved once. A resolve is a DNS lookup."""
    global _TARGET_LOCK                  # pylint: disable=global-statement
    key = (str(host), int(port), int(timeout), int(retries))
    got = _TARGETS.get(key)
    if got is not None:
        return got
    if _TARGET_LOCK is None:
        _TARGET_LOCK = asyncio.Lock()
    # Held across the await so that two metrics of the same device starting together resolve
    # the address once between them rather than once each.
    async with _TARGET_LOCK:
        if key not in _TARGETS:
            _TARGETS[key] = await UdpTransportTarget.create(
                (host, port), timeout=timeout, retries=retries)
        return _TARGETS[key]


class NoAnswer(str):
    """An error from a device that did not answer AT ALL.

    A str subclass, so every caller that logs it, shows it or puts it in a message goes on
    working unchanged — and the one caller that has to tell the two apart can, with
    `isinstance`. The alternative, a third return value, is a change to every call site for a
    fact almost none of them care about.

    The distinction is the whole difference between a device that is off the network and one
    that is talking: `noSuchName` is an ANSWER — this device does not serve that OID, and the
    next profile may well be one it does. A timeout is not an answer, and after a few of them
    the remaining three hundred reads are three hundred timeouts nobody is waiting for.
    """


class SnmpClient:
    """The two SNMP primitives, mixed into ``Watchful``."""

    # ── SNMP GET ───────────────────────────────────────────────────────────────

    @staticmethod
    def _auth_cached(version: str, community: str, *v3) -> object:
        """:meth:`_auth_data`, remembered per credential.

        The same object every time and not merely an equal one: pysnmp's local configuration
        datastore keys on it, so a fresh one per request is a fresh row in the engine's
        configuration per request — the engine grows for the life of the process, and each
        request pays to configure what the one before it configured.
        """
        key = (version, community) + tuple(v3)
        got = _AUTHS.get(key)
        if got is None:
            got = _AUTHS[key] = SnmpClient._auth_data(version, community, *v3)
        return got

    @staticmethod
    def _auth_data(
        version: str,
        community: str,
        v3_username: str = '',
        v3_auth_key: str = '',
        v3_priv_key: str = '',
        v3_auth_proto: str = 'MD5',
        v3_priv_proto: str = 'DES',
    ):
        """How this server proves who it is — for every request the module makes.

        Written once because it was written twice and only one copy learned v3: the check
        path built a ``UsmUserData``, the discovery walk built a ``CommunityData`` and, for
        ``version == '3'``, sent it with ``mpModel=1``. That is a v2c request with a community
        string to a device that answers neither, so a v3 server discovered nothing at all
        while its checks ran fine — and the walk's timeout was swallowed, so the screen said
        only that there was nothing to show.
        """
        if version == '3':
            return UsmUserData(
                v3_username or 'public',
                authKey=v3_auth_key or None,
                privKey=v3_priv_key or None,
                authProtocol=_AUTH_PROTOCOLS.get(v3_auth_proto, usmHMACMD5AuthProtocol),
                privProtocol=_PRIV_PROTOCOLS.get(v3_priv_proto, usmDESPrivProtocol),
            )
        # v1 speaks mpModel 0, v2c speaks 1. Anything else has already been handled above.
        return CommunityData(community, mpModel=0 if version == '1' else 1)

    @staticmethod
    def _snmp_get(
        host: str,
        port: int,
        version: str,
        community: str,
        timeout: int,
        retries: int,
        oid: str,
        v3_username: str = '',
        v3_auth_key: str = '',
        v3_priv_key: str = '',
        v3_auth_proto: str = 'MD5',
        v3_priv_proto: str = 'DES',
    ) -> tuple:
        """Synchronous SNMP GET wrapping the asyncio API."""
        if not _HAS_PYSNMP:
            return None, 'pysnmp is not installed'

        async def _run() -> tuple:
            auth_data = SnmpClient._auth_cached(
                version, community, v3_username, v3_auth_key, v3_priv_key,
                v3_auth_proto, v3_priv_proto,
            )
            transport = await _target(host, port, timeout, retries)
            engine = await _engine()
            error_indication, error_status, error_index, var_binds = await get_cmd(
                engine, auth_data, transport, ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            if error_indication:
                # The engine could not get an answer — a timeout, an unreachable host, a
                # broken credential. Not the device saying no.
                return None, NoAnswer(str(error_indication))
            if error_status:
                idx = int(error_index) - 1
                return None, f'{error_status.prettyPrint()} at index {idx}'
            for _, val in var_binds:
                return str(val), None
            return None, 'no OID data returned'

        try:
            return run_coroutine(_run())
        except Exception as exc:  # pylint: disable=broad-except
            return None, NoAnswer(str(exc))

    # ── SNMP Walk of ONE subtree (used by sampling) ────────────────────────────

    # A table nobody bounded is a cycle nobody bounded: a chassis switch can answer thousands
    # of rows on one column, and the walk that fetches them is the same one that has to finish
    # before the next check runs. The ceiling is generous for real hardware and finite for the
    # rest; a truncated walk says so instead of pretending it saw the whole table.
    WALK_MAX_ROWS = 512

    @staticmethod
    def _snmp_walk_oid(
        host: str,
        port: int,
        version: str,
        community: str,
        timeout: int,
        retries: int,
        oid: str,
        max_rows: int = 0,
        v3_username: str = '',
        v3_auth_key: str = '',
        v3_priv_key: str = '',
        v3_auth_proto: str = 'MD5',
        v3_priv_proto: str = 'DES',
    ) -> tuple:
        """Walk ONE subtree and return ``({index: value}, error)``.

        The discovery walk is a different question and answers it differently: it sweeps two
        fixed subtrees, truncates values to 120 characters and swallows errors, because what it
        produces is a list somebody picks from. A profile metric names its own column, needs the
        value **whole** (a truncated counter is a wrong number, not a shortened one), and needs
        to know when the device did not answer — an empty table and an unreachable device look
        identical otherwise, and they are not the same thing.

        Keys are the OID **suffix** after the walked root, which is the table index: `"3"` for a
        plain table, `"1.3.6.1.4.1"` for one indexed by an OID. Rows come back in the order the
        device sent them.
        """
        if not _HAS_PYSNMP:
            return {}, 'pysnmp is not installed'
        root = str(oid or '').strip().lstrip('.')
        if not root:
            return {}, 'no oid'
        limit = int(max_rows or SnmpClient.WALK_MAX_ROWS)

        async def _run() -> tuple:
            auth_data = SnmpClient._auth_cached(
                version, community, v3_username, v3_auth_key, v3_priv_key,
                v3_auth_proto, v3_priv_proto,
            )
            transport = await _target(host, port, timeout, retries)
            engine  = await _engine()
            context = ContextData()
            target  = ObjectType(ObjectIdentity(root))
            rows: dict = {}
            # GETBULK where the version allows it: a 48-port table is one round trip instead of
            # forty-eight, and the walk happens on every cycle rather than when somebody asks.
            if version != '1':
                cmd = bulk_walk_cmd(engine, auth_data, transport, context, 0, 50, target,
                                    lexicographicMode=False)
            else:
                cmd = walk_cmd(engine, auth_data, transport, context, target,
                               lexicographicMode=False)
            async for err_ind, err_st, err_idx, var_binds in cmd:
                if err_ind:
                    return rows, NoAnswer(str(err_ind))
                if err_st:
                    return rows, f'{err_st.prettyPrint()} at index {int(err_idx) - 1}'
                for vb in var_binds:
                    oid_str = str(vb[0])
                    if oid_str == root:
                        index = '0'              # a scalar walked as if it were a table
                    elif oid_str.startswith(root + '.'):
                        index = oid_str[len(root) + 1:]
                    else:
                        return rows, None        # walked past the subtree: the table is done
                    rows[index] = str(vb[1].prettyPrint())
                    if len(rows) >= limit:
                        return rows, None
            return rows, None

        try:
            return run_coroutine(_run())
        except Exception as exc:  # pylint: disable=broad-except
            return {}, NoAnswer(str(exc))

    # ── SNMP Walk (used by discover) ───────────────────────────────────────────

    @staticmethod
    async def _snmp_walk(
        host: str,
        port: int,
        version: str,
        community: str,
        timeout: int,
        retries: int,
        max_oids: int = 300,
        v3_username: str = '',
        v3_auth_key: str = '',
        v3_priv_key: str = '',
        v3_auth_proto: str = 'MD5',
        v3_priv_proto: str = 'DES',
    ) -> list:
        """Async SNMP walk — mib-2 and enterprises subtrees run in parallel.

        GETBULK (v2c/v3, maxRepetitions=50) reduces round-trips to ~ceil(n/50).
        Both subtrees are walked concurrently via asyncio.gather(), cutting
        wall-clock time roughly in half vs sequential walks.
        Falls back to sequential GETNEXT for SNMPv1.
        """
        auth_data = SnmpClient._auth_cached(
            version, community, v3_username, v3_auth_key, v3_priv_key,
            v3_auth_proto, v3_priv_proto,
        )
        use_bulk  = version != '1'

        async def _walk_subtree(root_oid: str, limit: int) -> list[dict]:
            transport = await _target(host, port, timeout, retries)
            engine  = await _engine()
            context = ContextData()
            root    = ObjectType(ObjectIdentity(root_oid))
            items: list[dict] = []
            if use_bulk:
                cmd = bulk_walk_cmd(
                    engine, auth_data, transport, context,
                    0, 50, root,            # nonRepeaters=0, maxRepetitions=50
                    lexicographicMode=False,
                )
            else:
                cmd = walk_cmd(
                    engine, auth_data, transport, context, root,
                    lexicographicMode=False,
                )
            try:
                async for err_ind, err_st, _, var_binds in cmd:
                    if err_ind or err_st:
                        break
                    for vb in var_binds:
                        oid_str   = str(vb[0])
                        val_obj   = vb[1]
                        val_str   = val_obj.prettyPrint()
                        if len(val_str) > 120:
                            val_str = val_str[:117] + '…'
                        snmp_type = type(val_obj).__name__
                        items.append({
                            'name':         oid_str,
                            'display_name': val_str,
                            'status':       snmp_type,
                            'mib_category': _mib_resolver.get_category(snmp_type),
                        })
                        if len(items) >= limit:
                            break
                    if len(items) >= limit:
                        break
            except Exception:  # pylint: disable=broad-except
                pass
            return items

        per_subtree = max(1, max_oids // 2)
        subtrees    = ['1.3.6.1.2.1', '1.3.6.1.4.1']   # mib-2, enterprises

        if use_bulk:
            # Parallel: both subtrees walk simultaneously
            gathered = await asyncio.gather(
                *[_walk_subtree(oid, per_subtree) for oid in subtrees],
                return_exceptions=True,
            )
            results: list[dict] = []
            for chunk in gathered:
                if isinstance(chunk, list):
                    results.extend(chunk)
        else:
            # SNMPv1: sequential (GETBULK not available)
            results = []
            for oid in subtrees:
                if len(results) >= max_oids:
                    break
                results.extend(await _walk_subtree(oid, max_oids - len(results)))

        return results[:max_oids]
