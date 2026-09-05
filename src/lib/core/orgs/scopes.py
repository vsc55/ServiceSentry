#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What can belong to a company — declared by whoever owns it, never listed here.

The ownership table spans tables this package has never heard of, so the list of valid scopes
cannot live in it. A list here would be one the core edits every time a package learns to own
something, which is the core naming a domain — the thing the whole discovery mechanism exists to
avoid (`docs/explica-discovery.md`).

A package declares in its ``manifest.py``::

    ORG_SCOPES = (
        {'scope': 'rack', 'label_key': 'orgs_scope_rack', 'chain': dcim_chain},
        {'scope': 'item', 'label_key': 'orgs_scope_item', 'chain': dcim_chain},
    )

``label_key`` names a key in the core language files — this is core UI, so the words are the
core's. ``chain`` is optional and is what makes inheritance work: given the panel and a uid it
returns ``[(scope, uid), …]`` from the thing up to its outermost container, innermost first. A
scope with no chain is a thing that inherits from nothing, which is the honest answer for a
mailbox or a subscription: it belongs to whoever was told, or to nobody.
"""

from __future__ import annotations

#: Resolved once. The declarations are static — they come from manifests read at import time —
#: and a scan per call would walk every package on every permission check.
_CACHE: dict | None = None


def registry() -> dict:
    """``{scope: descriptor}`` for every scope any package declares."""
    global _CACHE                                # pylint: disable=global-statement
    if _CACHE is None:
        from lib.discovery import scan           # noqa: PLC0415
        out: dict = {}
        for pkg, decl in scan('ORG_SCOPES'):
            for spec in (decl if isinstance(decl, (list, tuple)) else [decl]):
                if not isinstance(spec, dict):
                    continue
                name = str(spec.get('scope') or '').strip()
                if name and name not in out:
                    out[name] = dict(spec, scope=name, package=pkg)
        _CACHE = out
    return _CACHE


def forget() -> None:
    """Drop the cache. For tests that install a package mid-run; nothing else needs it."""
    global _CACHE                                # pylint: disable=global-statement
    _CACHE = None


def known(scope: str) -> bool:
    """Whether anything declares this scope. What keeps a typo out of the table."""
    return str(scope or '') in registry()


def chain_of(wa, scope: str, uid: str) -> list[tuple]:
    """``[(scope, uid), …]`` from *uid* outwards, innermost first.

    A scope that declares no chain answers with itself, which is not a degenerate case: it is
    what a thing with no container looks like, and it still resolves — it belongs to whoever was
    told about it.

    A broken chain — a rack whose room was deleted — ends the walk instead of raising: an orphan
    is a real state of the data and the answer for it is "nobody knows", not a 500.
    """
    spec = registry().get(str(scope or ''))
    fn = (spec or {}).get('chain')
    if not callable(fn):
        return [(str(scope or ''), str(uid or ''))] if scope and uid else []
    try:
        return list(fn(wa, str(scope or ''), str(uid or '')) or ())
    except Exception:                            # pylint: disable=broad-except
        return [(str(scope or ''), str(uid or ''))] if scope and uid else []


def owner_of(wa, said: dict, scope: str, uid: str) -> str:
    """The company something belongs to, resolved through its chain.

    For ONE thing. Anything drawing a list resolves the chains itself and calls
    :func:`lib.core.orgs.owners.owner_of` per row off a single read of *said* — this walks the
    containers again on every call, which is the shape that makes a room of forty racks slow.
    """
    from lib.core.orgs import owners             # noqa: PLC0415
    return owners.owner_of(chain_of(wa, scope, uid), said or {})
