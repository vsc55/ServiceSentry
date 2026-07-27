#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — the device-code sign-in flow, once.

Every "Register in Azure" / "Rotate secret" button is the same conversation: ask Entra for
a code, park what the operation will need, and poll until the admin has signed in on
another device.  Six buttons meant that conversation was written six times, and its rules
— how long a parked flow lives, that ``slow_down`` raises the interval, that a flow is
consumed on any terminal answer — were six copies that had to be kept in step by hand.

They live here instead.  A route is left with what is actually its own: which permission
guards it, what it stashes, and what it does once the token arrives.

The parked flow is a plain dict so a caller can stash anything it needs.  Five keys are
this module's and must not be reused for something else:

    device_code   the code being polled
    expires_at    wall-clock deadline (epoch seconds)
    interval      seconds between polls, raised by Entra's ``slow_down``
    kind          what the flow is for — the poll refuses a token of another kind
    client_id     the app the flow was started with (SCIM needs a different one, and the
                  poll MUST redeem with the same client that issued the code)

Where the flows are kept is the caller's business (WebAdmin holds a dict on itself,
process-local on purpose: a device code that only one worker can complete is better than
one shared across a restart).
"""

from __future__ import annotations

import secrets
import time

from lib.providers.entraid import auth

# How long a parked flow is honoured when Entra doesn't say. Entra's own device codes last
# ~15 min; this is the fallback for a response without ``expires_in``.
DEFAULT_TTL = 900

# Entra asks for a slower poll with ``slow_down``; each one adds this, up to the cap. The
# cap exists so a misbehaving tenant cannot stretch the poll past the code's own lifetime.
SLOW_DOWN_STEP = 5
MAX_INTERVAL = 30


def start(flows: dict, kind: str, *, scope: str | None = None,
          client_id: str | None = None, **stash) -> tuple[str, dict]:
    """Begin a device-code sign-in, park it in *flows* and return ``(token, payload)``.

    *payload* is the JSON body the wizard needs to show the code — the same shape for
    every button, ``verification_uri_complete`` included: it is the URL with the code
    already in it, so the admin lands on the consent screen with nothing to type.

    Anything in *stash* is kept on the flow for the poll to read.  Raises whatever
    :func:`auth.device_code_start` raises — the caller owns the message, because "the
    wizard could not start" reads differently in each of them.
    """
    kwargs = {}
    if scope:
        kwargs['scope'] = scope
    if client_id:
        kwargs['client_id'] = client_id
    d = auth.device_code_start(**kwargs)

    flow_token = secrets.token_urlsafe(16)
    flows[flow_token] = {
        'device_code': d['device_code'],
        'expires_at':  time.time() + int(d.get('expires_in', DEFAULT_TTL)),
        'interval':    int(d.get('interval', 5)),
        'kind':        kind,
        # Only when the flow was started with a non-default client: the poll passes it
        # back, and an absent key means "whatever auth defaults to".
        **({'client_id': client_id} if client_id else {}),
        **stash,
    }
    return flow_token, {
        'flow_token':       flow_token,
        'user_code':        d['user_code'],
        'verification_uri': d['verification_uri'],
        'verification_uri_complete': d.get('verification_uri_complete', ''),
        'expires_in':       d.get('expires_in', DEFAULT_TTL),
        'interval':         d.get('interval', 5),
    }


def poll(flows: dict, flow_token, kind: str, *, on_error=None) -> tuple[dict, dict, dict]:
    """Advance one parked flow.  Returns ``(flow, token_body, response)``.

    Exactly one of the last two is meaningful:

    * *response* set → hand it back verbatim (``pending`` / ``expired`` / ``error``).  The
      flow has been dropped unless the answer was ``pending``.
    * *response* ``None`` → the admin signed in.  *flow* is what the start route stashed
      and *token_body* the token response.  **The flow is already gone**: a completed
      sign-in is single-use, and leaving it parked while the caller does the slow part
      would let a second poll redeem the same code twice.

    A flow of another *kind* answers ``expired`` rather than "wrong kind": a token that
    doesn't match is either stale or forged, and neither deserves a description.

    *on_error*, if given, is called ``(kind, message)`` on every terminal failure —
    expiry, decline, Entra error — so a wizard failure is auditable instead of living only
    in a toast the admin has already dismissed.
    """
    def _fail(message):
        flows.pop(flow_token, None)
        if on_error:
            on_error(kind, message)

    flow = flows.get(flow_token)
    if not flow or flow.get('kind') != kind:
        return {}, {}, {'status': 'expired'}
    if time.time() > flow['expires_at']:
        _fail('sign-in expired')
        return flow, {}, {'status': 'expired'}

    body = auth.device_code_poll(
        flow['device_code'],
        **({'client_id': flow['client_id']} if flow.get('client_id') else {}))
    error = body.get('error', '')
    if error == 'authorization_pending':
        return flow, {}, {'status': 'pending'}
    if error == 'slow_down':
        flow['interval'] = min(flow['interval'] + SLOW_DOWN_STEP, MAX_INTERVAL)
        return flow, {}, {'status': 'pending', 'interval': flow['interval']}
    if error:
        message = body.get('error_description', error)
        _fail(message)
        return flow, {}, {'status': 'error', 'message': message}

    flows.pop(flow_token, None)
    return flow, body, None


def park(flows: dict, *, ttl: int = DEFAULT_TTL, **stash) -> str:
    """Park a follow-up flow that is NOT a device-code sign-in and return its token.

    Used by the Azure RBAC step: the provisioning poll already holds an ARM token, so
    letting the admin pick a subscription afterwards must not cost a second sign-in.  The
    token is held for *ttl* seconds — deliberately shorter than its own ~1 h lifetime, so
    an abandoned picker doesn't keep one alive for the full hour.
    """
    flow_token = secrets.token_urlsafe(16)
    flows[flow_token] = {'expires_at': time.time() + ttl, **stash}
    return flow_token


def take(flows: dict, flow_token, kind: str):
    """A parked follow-up flow, or ``None`` if it is unknown, of another kind or expired.

    Does NOT consume it: the caller drops it with :func:`drop` once it has decided the
    request is worth spending it on, so a request that fails validation can be retried
    instead of burning a token the admin would have to earn again with a second sign-in.
    """
    flow = flows.get(flow_token)
    if not flow or flow.get('kind') != kind:
        return None
    if time.time() > flow['expires_at']:
        flows.pop(flow_token, None)
        return None
    return flow


def drop(flows: dict, flow_token) -> None:
    """Consume a flow. The ARM token a follow-up flow carries must not be replayable."""
    flows.pop(flow_token, None)
