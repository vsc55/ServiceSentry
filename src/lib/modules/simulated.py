#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulated check items: answered by a scenario they carry, never probed.

A check item may carry a ``simulated`` block instead of a reachable target::

    "simulated": {
        "source": "demo",
        "results": [
            {"suffix": "", "status": "ok", "message": "Ping: srv-01 🔼",
             "metrics": {"latency_ms": [0.8, 0.3, 2]}},
            {"suffix": "_swap", "status": "warning", "message": "…",
             "metrics": {"used": [91, 2, 1]}}
        ]
    }

Such an item is **not handed to its watchful** (:meth:`ModuleBase.get_conf` leaves it out of
the collection the module enumerates), so nothing ever opens a socket, runs a command or sends
a packet for it. Instead the monitor adds what the scenario says to the module's result
(:func:`merge_into`, called by ``Monitor.check_module``) — and from there it is an ordinary
result: the same change detection, the same ``check_state`` row, the same history sample, the
same alert. That is the point: the screens that show it cannot tell, because they read the
same tables a real check writes.

Two things can tell, on purpose:

* every result carries ``_simulated: <source>`` in its ``other_data`` — an underscore field,
  which the history keeps as the series' identity and never as a measurement;
* the alert it raises is marked as simulated, and the notifier drops it before any channel
  (:class:`lib.core.notify.monitor_notifier.MonitorNotifier`). A demonstration must never page
  anybody, whatever Telegram, Teams, e-mail or webhooks the installation has configured.

The metrics are ``[base, spread, decimals]``: each reading is ``base`` moved by up to
``spread`` either way, the same for every caller within a five-minute window, so two screens
asking at the same moment see the same number and a chart over days is a believable line and
not a flat one.

Generic: nothing here knows which module, which demo or which device. The one that writes the
scenarios is :mod:`lib.core.dcim.demo_monitor`.
"""

from __future__ import annotations

import random
import time

#: The item field that holds the scenario.
SIM_KEY = 'simulated'
#: The ``other_data`` field that marks a result as simulated (its value is the source).
MARK = '_simulated'
#: The states a scenario result may be in.
STATES = ('ok', 'warning', 'error')
#: How long one reading of a metric lasts: within this window every caller sees the same.
_WINDOW = 300
#: The syslog MSGID a simulated log line carries: shown like any other, kept from the event
#: rules (`lib.services.events.manager`) so it never fires a notification, and found by it to
#: be removed.
SYSLOG_MSGID = 'ss-simulated'


def is_simulated(item) -> bool:
    """Whether *item* is answered by its scenario instead of being probed."""
    sim = item.get(SIM_KEY) if isinstance(item, dict) else None
    return isinstance(sim, dict) and isinstance(sim.get('results'), list)


def without_simulated(items):
    """*items* (a collection dict) minus the simulated ones; anything else unchanged."""
    if not isinstance(items, dict):
        return items
    return {k: v for k, v in items.items() if not is_simulated(v)}


def metric(key: str, name: str, spec, now: float | None = None) -> float | None:
    """One reading of a metric ``[base, spread, decimals]`` at *now* (see the module doc)."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    try:
        base = float(spec[0])
        spread = float(spec[1]) if len(spec) > 1 else 0.0
        decimals = int(spec[2]) if len(spec) > 2 else 1
    except (TypeError, ValueError):
        return None
    ventana = int((time.time() if now is None else float(now)) // _WINDOW)
    rnd = random.Random(f'{key}|{name}|{ventana}')
    return round(max(0.0, base + rnd.uniform(-spread, spread)), max(0, decimals))


def results(module_cfg, *, device_scope: str = '', now: float | None = None) -> list[dict]:
    """What the simulated items of one module's configuration answer now.

    ``[{key, status, severity, message, other_data, name, item_uid}]``, one per scenario
    result. Disabled items answer nothing — as a disabled real check — and *device_scope*
    narrows it to the items bound to that device, as a «collect this device» run does.
    """
    out: list[dict] = []
    if not isinstance(module_cfg, dict):
        return out
    for coll, items in module_cfg.items():
        if str(coll).startswith('__') or not isinstance(items, dict):
            continue
        for key, item in items.items():
            if not is_simulated(item) or item.get('enabled') is False:
                continue
            if device_scope and str(item.get('device_uid') or '').strip() != device_scope:
                continue
            sim = item[SIM_KEY]
            source = str(sim.get('source') or 'simulated')
            name = str(item.get('label') or key)
            for res in sim['results']:
                if not isinstance(res, dict):
                    continue
                estado = str(res.get('status') or 'ok')
                if estado not in STATES:
                    estado = 'error'
                rkey = f"{key}{str(res.get('suffix') or '')}"
                datos = {m: v for m, v in ((m, metric(rkey, m, s, now))
                                           for m, s in (res.get('metrics') or {}).items())
                         if v is not None}
                datos.update({k: v for k, v in (res.get('data') or {}).items()})
                datos[MARK] = source
                out.append({'key': rkey, 'status': estado == 'ok',
                            'severity': '' if estado == 'ok' else estado,
                            'message': str(res.get('message') or ''),
                            'other_data': datos, 'name': name, 'item_uid': str(key)})
    return out


def merge_into(result_data, module_cfg, *, device_scope: str = '',
               now: float | None = None) -> int:
    """Add the simulated answers to a module's :class:`ReturnModuleCheck`. How many."""
    n = 0
    for r in results(module_cfg, device_scope=device_scope, now=now):
        # send_msg=True: the monitor's own change detection announces it — a watchful's
        # `_emit` sends its own and passes False, but a scenario has no module behind it.
        result_data.set(r['key'], r['status'], r['message'], True, r['other_data'],
                        r['severity'] or None, name=r['name'])
        n += 1
    return n


def is_simulated_result(other_data) -> bool:
    """Whether a result's ``other_data`` says it came from a scenario."""
    return isinstance(other_data, dict) and bool(other_data.get(MARK))
