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
import time

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
    from pyasn1.type import univ as _univ           # type: ignore[import]
    from pysnmp.proto import rfc1902 as _rfc1902    # type: ignore[import]
    from pysnmp.proto import rfc1905 as _rfc1905    # type: ignore[import]
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

#: Engines of their own, for the v3 credentials the shared one cannot hold at the same time.
#:
#: pysnmp's local configuration keys a USM user by its NAME. Two devices that both use the v3
#: user `monitor` with DIFFERENT keys are therefore one row in the shared engine, and every
#: request rewrites that row with its own keys — while the other device's request is still in
#: flight on the same loop. What arrives is an authentication failure (or a wrong-key decrypt)
#: that reads like the device, and which device gets it depends on timing. A `securityName` of
#: our own does not separate them: pysnmp indexes the user table by it but looks the row up by
#: `userName`, so the second row is never found.
#:
#: So the first credential seen under a user name keeps the shared engine — the common case,
#: one credential per user name, still costs exactly one engine — and any OTHER credential
#: under that same name gets an engine of its own, keyed by the whole credential.
_ENGINES: dict = {}
_V3_OWNERS: dict = {}

#: How long a resolved transport is trusted. `UdpTransportTarget.create` is a DNS lookup, and
#: a lookup kept for the life of the process is a device that changed address being polled at
#: the old one until somebody restarts the panel. Five minutes is a handful of resolves per
#: device per hour; a read that gets no answer at all forgets it at once (`_forget_target`).
_TARGET_TTL = 300.0


def _reset() -> None:
    """Forget the engine and everything resolved for it. For the loop going away, and tests."""
    global _ENGINE, _TARGET_LOCK         # pylint: disable=global-statement
    engines = [e for e in [_ENGINE, *_ENGINES.values()] if e is not None]
    _ENGINE = None
    _ENGINES.clear()
    _V3_OWNERS.clear()
    _TARGETS.clear()
    _AUTHS.clear()
    _TARGET_LOCK = None
    for engine in engines:
        try:
            engine.close_dispatcher()
        except Exception:  # pylint: disable=broad-except
            pass


def _engine_slot(v3) -> tuple | None:
    """Which engine a credential is sent through: ``None`` for the shared one.

    *v3* is ``(user, auth key, priv key, auth proto, priv proto)`` for a v3 request and empty
    for anything else — a community string has no per-user row to collide on.
    """
    if not v3:
        return None
    cred = tuple(str(p or '') for p in v3)
    user = cred[0] or 'public'
    owner = _V3_OWNERS.setdefault(user, cred)
    return None if owner == cred else cred


def _v3_of(version, *v3) -> tuple:
    """The credential `_engine` separates on — empty for anything that is not v3."""
    return tuple(v3) if str(version) == '3' else ()


async def _engine(v3=None):
    """The engine for one request, built on the loop thread the first time anything asks.

    On the loop and not in the caller: the dispatcher binds to whatever loop is running when
    the first request opens its socket, and an engine bound to a loop that has gone answers
    nothing, silently.

    The shared one for everything but a v3 credential whose user name another credential
    already holds in it — see `_ENGINES`.
    """
    global _ENGINE                       # pylint: disable=global-statement
    slot = _engine_slot(v3)
    engine = _ENGINE if slot is None else _ENGINES.get(slot)
    if engine is None:
        engine = SnmpEngine()
        if slot is None:
            _ENGINE = engine
        else:
            _ENGINES[slot] = engine
    return engine


def _target_key(host, port, timeout, retries) -> tuple:
    return (str(host), int(port), int(timeout), int(retries))


def _forget_target(host, port, timeout, retries) -> None:
    """Drop one resolved transport, so the next request resolves the name again.

    Called when a device did not answer at all: the commonest reason a name that used to
    answer stops answering is that it now points somewhere else.
    """
    _TARGETS.pop(_target_key(host, port, timeout, retries), None)


async def _target(host: str, port: int, timeout: int, retries: int):
    """The transport for one device, resolved once per `_TARGET_TTL`. A resolve is a DNS
    lookup."""
    global _TARGET_LOCK                  # pylint: disable=global-statement
    key = _target_key(host, port, timeout, retries)

    def _fresh():
        got = _TARGETS.get(key)
        if got is not None and time.monotonic() - got[1] < _TARGET_TTL:
            return got[0]
        return None

    found = _fresh()
    if found is not None:
        return found
    if _TARGET_LOCK is None:
        _TARGET_LOCK = asyncio.Lock()
    # Held across the await so that two metrics of the same device starting together resolve
    # the address once between them rather than once each.
    async with _TARGET_LOCK:
        found = _fresh()
        if found is None:
            found = await UdpTransportTarget.create(
                (host, port), timeout=timeout, retries=retries)
            _TARGETS[key] = (found, time.monotonic())
        return found


def _absent(val) -> str:
    """The name of an SNMPv2 exception value (``noSuchObject`` …), or ``''`` for a reading.

    v2c and v3 do not answer a missing OID with an error status: the PDU comes back with
    status 0 and the variable binding carries one of these in place of a value. They are
    `Null`s underneath, so ``str()`` of one is ``''`` — and an empty string read as the value
    is an OID that "answers" for ever.
    """
    if not _HAS_PYSNMP:
        return ''
    if isinstance(val, (_rfc1905.NoSuchObject, _rfc1905.NoSuchInstance,
                        _rfc1905.EndOfMibView)):
        name = type(val).__name__
        return name[:1].lower() + name[1:]
    return ''


def _utf8_text(val) -> str | None:
    """An OctetString that is UTF-8 text with non-ASCII in it, as that text — else ``None``.

    pyasn1 prints any octet outside printable ASCII as ``0x…`` hex, so an interface alias
    "Oficina Señor" or a storage called "Memoria física" came back from a walk as a string of
    digits, and from a GET decoded as Latin-1 ("SeÃ±or"). Only what decodes CLEANLY and is
    printable throughout counts as text; anything else keeps the spelling it had — the hex is
    what `metrics.attribute` turns into a MAC, and binary is what it is.

    Six octets are left alone on purpose: that is the length of a MAC, and a MAC whose bytes
    happen to be valid UTF-8, read as a few accented letters, would be a forwarding-table entry
    nothing can match again. A six-byte accented name keeps the spelling it had before.
    """
    if not _HAS_PYSNMP or not isinstance(val, _univ.OctetString):
        return None
    if isinstance(val, (_univ.Null, _rfc1902.IpAddress, _rfc1902.Opaque, _rfc1902.Bits)):
        return None
    try:
        raw = bytes(val.asOctets())
    except Exception:  # pylint: disable=broad-except
        return None
    if not raw or len(raw) == 6 or all(b < 0x80 for b in raw):
        return None                      # empty, MAC-shaped, or ASCII: the old path is right
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return None
    return text if text.isprintable() else None


class Truncated(str):
    """A walk that stopped at its row ceiling with more rows still to come.

    A str subclass for the same reason as `NoAnswer`: the rows that were read are real, and
    every caller that shows or logs the error goes on working. The caller that must not treat
    a partial table as the whole one — the sightings store, which REPLACES what it held — can
    tell, with `isinstance`.
    """


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
            engine = await _engine(_v3_of(version, v3_username, v3_auth_key, v3_priv_key,
                                          v3_auth_proto, v3_priv_proto))
            error_indication, error_status, error_index, var_binds = await get_cmd(
                engine, auth_data, transport, ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            if error_indication:
                # The engine could not get an answer — a timeout, an unreachable host, a
                # broken credential. Not the device saying no.
                _forget_target(host, port, timeout, retries)
                return None, NoAnswer(str(error_indication))
            if error_status:
                idx = int(error_index) - 1
                return None, f'{error_status.prettyPrint()} at index {idx}'
            for _, val in var_binds:
                # v2c/v3 say "not here" INSIDE a successful PDU. An answer, so a plain string
                # and not `NoAnswer`: the device is on the network and the sampler must not
                # count this towards giving up on it.
                missing = _absent(val)
                if missing:
                    return None, f'{missing} at {oid}'
                text = _utf8_text(val)
                return (text if text is not None else str(val)), None
            return None, 'no OID data returned'

        try:
            return run_coroutine(_run())
        except Exception as exc:  # pylint: disable=broad-except
            _forget_target(host, port, timeout, retries)
            return None, NoAnswer(str(exc))

    # ── SNMP Walk of ONE subtree (used by sampling) ────────────────────────────

    # A table nobody bounded is a cycle nobody bounded: a chassis switch can answer thousands
    # of rows on one column, and the walk that fetches them is the same one that has to finish
    # before the next check runs. The ceiling is generous for real hardware and finite for the
    # rest; a truncated walk says so instead of pretending it saw the whole table — with a
    # `Truncated` error beside the rows it did read.
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

        A table longer than *max_rows* comes back as its first *max_rows* rows and a
        `Truncated` error. It used to come back with no error at all, and a partial table read
        as the whole one — which a store that REPLACES what it held turns into data loss.
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
            engine  = await _engine(_v3_of(version, v3_username, v3_auth_key, v3_priv_key,
                                           v3_auth_proto, v3_priv_proto))
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
                    if not rows:
                        _forget_target(host, port, timeout, retries)
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
                    if _absent(vb[1]):
                        continue                 # endOfMibView / noSuch*: not a row
                    # Text as text: prettyPrint spells any octet outside ASCII as hex.
                    text = _utf8_text(vb[1])
                    rows[index] = text if text is not None else str(vb[1].prettyPrint())
                    # One row PAST the ceiling is how a full table is told from a cut one.
                    if len(rows) > limit:
                        del rows[index]
                        return rows, Truncated(
                            f'more than {limit} rows; only the first {limit} were read')
            return rows, None

        try:
            return run_coroutine(_run())
        except Exception as exc:  # pylint: disable=broad-except
            _forget_target(host, port, timeout, retries)
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
            engine  = await _engine(_v3_of(version, v3_username, v3_auth_key, v3_priv_key,
                                           v3_auth_proto, v3_priv_proto))
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
