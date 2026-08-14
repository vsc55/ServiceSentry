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

from . import mib_resolver as _mib_resolver


def run_coroutine(coro):
    """Run *coro* to completion from synchronous code — running loop in this thread or not.

    `asyncio.run` **refuses** when the calling thread already has one going, and this module is
    called from whatever thread the panel is serving on. Where a loop is already there the work
    goes to a thread of its own with its own loop: what is being awaited here talks to a UDP
    socket and belongs to no particular loop.

    Found the hard way. Discovery is `asyncio.run` inside a `try/except: continue`, so on a
    thread with a live loop every server raised, every server was skipped, and the empty list
    read as *this device has no OIDs* — the exact symptom the walk was rewritten to fix, from a
    different cause. It showed up in CI because the browser tests run Playwright's sync API,
    which keeps a loop alive in the main thread; but the reason to fix it is that a request
    thread is not ours to make assumptions about.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)               # the ordinary case: nothing running here
    box: dict = {}

    def _worker():
        try:
            box['value'] = asyncio.run(coro)
        except BaseException as exc:           # noqa: BLE001  (re-raised in the caller)
            box['error'] = exc

    thread = threading.Thread(target=_worker, name='snmp-sync', daemon=True)
    thread.start()
    thread.join()
    if 'error' in box:
        raise box['error']
    return box['value']


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


class SnmpClient:
    """The two SNMP primitives, mixed into ``Watchful``."""

    # ── SNMP GET ───────────────────────────────────────────────────────────────

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
            auth_data = SnmpClient._auth_data(
                version, community, v3_username, v3_auth_key, v3_priv_key,
                v3_auth_proto, v3_priv_proto,
            )

            transport = await UdpTransportTarget.create(
                (host, port), timeout=timeout, retries=retries
            )
            engine = SnmpEngine()
            try:
                error_indication, error_status, error_index, var_binds = await get_cmd(
                    engine, auth_data, transport, ContextData(),
                    ObjectType(ObjectIdentity(oid)),
                )
                if error_indication:
                    return None, str(error_indication)
                if error_status:
                    idx = int(error_index) - 1
                    return None, f'{error_status.prettyPrint()} at index {idx}'
                for _, val in var_binds:
                    return str(val), None
                return None, 'no OID data returned'
            finally:
                try:
                    engine.close_dispatcher()
                except Exception:  # pylint: disable=broad-except
                    pass

        try:
            return run_coroutine(_run())
        except Exception as exc:  # pylint: disable=broad-except
            return None, str(exc)

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
        auth_data = SnmpClient._auth_data(
            version, community, v3_username, v3_auth_key, v3_priv_key,
            v3_auth_proto, v3_priv_proto,
        )
        use_bulk  = version != '1'

        async def _walk_subtree(root_oid: str, limit: int) -> list[dict]:
            transport = await UdpTransportTarget.create(
                (host, port), timeout=timeout, retries=retries
            )
            engine  = SnmpEngine()
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
            finally:
                try:
                    engine.close_dispatcher()
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
