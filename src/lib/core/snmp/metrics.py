#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turning what SNMP returns into something you can put on a chart.

SNMP hands back a number and nothing else. It does not say that ``1.3.6.1.4.1.2021.11.9.0`` is
the CPU, that it is a percentage, or that ``1.3.6.1.2.1.2.2.1.10.3`` is a byte counter that has
to be differentiated before it means anything. That knowledge is the *device profile* — the OID
matrix (see :mod:`watchfuls.snmp.profiles`) — and this module is what applies it.

Three kinds, and the difference is the whole point:

``gauge``
    A value that IS the measurement: a temperature, a percentage, a fan speed. Scaled and
    emitted.

``counter``
    A value that only means something as a DIFFERENCE: octets, packets, errors. Emitted as a
    per-second rate against the previous sample. Charting one raw produces the ramp that every
    first SNMP dashboard has on it — a line that only ever goes up, on which an outage is a
    flat spot nobody notices.

``text``
    Not a measurement at all: a name, a model, a serial. It is what makes the machine
    recognisable, so it travels as an attribute and never as a series.

**Counters wrap, and a device that reboots resets them.** Both look identical — the new value
is smaller than the old one — and the two need opposite treatment: a wrap means "add the
range", a reset means "this sample is meaningless, start again". The rule here uses the width:

* **32-bit** counters wrap constantly (a gigabit interface fills one in ~34 seconds), so a
  backwards step is assumed to be a wrap, and the range is added back. A ceiling can be
  declared (``max_rate``) for the case where the result would be impossible for that link;
* **64-bit** counters do not wrap in any practical sense (~4.6 years at a terabit), so a
  backwards step is a reset, and the sample is dropped rather than turned into a spike that
  reads as the busiest second in the machine's history.

Either way the new baseline is stored. Dropping a sample costs one point on a chart; inventing
one costs the chart.
"""

from __future__ import annotations

# The two widths SNMP actually uses (Counter32 / Counter64). A profile may say which; without
# it, 32 is assumed, because that is what a device that does not implement the 64-bit counters
# is serving — and treating a 32-bit wrap as a reset would drop a sample every few minutes on a
# busy link.
_WIDTHS = (32, 64)
DEFAULT_WIDTH = 32


def scale_value(value, factor):
    """A raw reading in the unit the profile declares.

    ``scale`` is a multiplier and not a formula on purpose: what devices need is almost always
    one (centiseconds → seconds, KB → bytes, tenths of a degree → degrees), and a profile that
    could carry an expression would be a profile that can run one.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    try:
        f = float(factor) if factor not in (None, '') else 1.0
    except (TypeError, ValueError):
        f = 1.0
    out = num * f
    # An integer stays an integer: "41" reads as a reading, "41.0" reads as a computation.
    return int(out) if float(out).is_integer() else out


def counter_rate(current, previous, seconds, *, width=DEFAULT_WIDTH, max_rate=None):
    """The per-second rate between two counter samples, or ``None`` when there is not one.

    ``None`` is an answer this function gives often and on purpose — no previous sample, no
    time between them, a reset, an impossible result. Every one of those is a point a chart is
    better off not having.
    """
    try:
        cur = float(current)
        prev = float(previous)
        dt = float(seconds)
    except (TypeError, ValueError):
        return None
    if dt <= 0:
        return None                     # two samples with no time between them
    w = int(width) if int(width or 0) in _WIDTHS else DEFAULT_WIDTH
    delta = cur - prev
    if delta < 0:
        if w == 64:
            return None                 # a 64-bit counter does not wrap: this is a reboot
        delta += float(2 ** 32)
        if delta < 0:
            return None
    rate = delta / dt
    if max_rate not in (None, ''):
        try:
            if rate > float(max_rate):
                return None             # impossible for this link: a reset that looked like a wrap
        except (TypeError, ValueError):
            pass
    return rate


def sample(metric: dict, raw, previous: dict | None, now: float) -> tuple:
    """Apply one metric declaration to one raw reading.

    Returns ``(value, state)``: the number to record (or ``None`` — see above, and for a
    ``text`` metric, which is not a number at all), and the state to remember for the next
    cycle (``None`` when this kind keeps none).

    *previous* is what this function returned as *state* last time: ``{'v': raw, 't': ts}``.
    """
    kind = str((metric or {}).get('kind') or 'gauge').lower()
    if kind == 'text':
        return None, None
    if kind == 'counter':
        state = {'v': _num(raw), 't': float(now)}
        if state['v'] is None:
            return None, None           # nothing usable to compare against next time either
        if not previous or previous.get('v') is None:
            return None, state          # the first sample of a counter is only a baseline
        rate = counter_rate(state['v'], previous.get('v'), state['t'] - float(previous.get('t') or 0),
                            width=metric.get('width') or DEFAULT_WIDTH,
                            max_rate=metric.get('max_rate'))
        if rate is None:
            return None, state
        return scale_value(rate, metric.get('scale')), state
    return scale_value(raw, metric.get('scale')), None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def attribute(metric: dict, raw):
    """What a ``text`` metric contributes: the string that makes a machine recognisable.

    SNMP will happily return bytes, an OID object or a padded string; this is the one place
    that decides what a name looks like, so a device that answers with trailing whitespace does
    not get a different name from one that does not.
    """
    if raw is None:
        return ''
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8', 'replace')
        except Exception:                       # pylint: disable=broad-except
            raw = str(raw)
    return str(raw).strip()
