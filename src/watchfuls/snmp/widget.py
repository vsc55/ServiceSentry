#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Overview widget: every device this module reads, at a glance.

**Why this is not a chart.** SNMP does not measure one thing. It measures whatever the
profiles installed say it measures — a temperature on a MikroTik, a battery on a UPS, the
throughput of a switch, ninety disks on a NAS — so a widget that picked a measurement by name
would be a widget that knows what a NAS is. What every device HAS in common is a state and a
handful of figures its own profile called worth reading first (``headline``), and that is what
this shows: one row per device, its worst state, and its own headline.

The core renders it and never learns any of this: the shape it consumes is
``{entries: [...], aggregate: {...}}`` and every word in it — the labels, the units, the
meaning of an enumeration — comes from the profiles, already translated.
"""

from __future__ import annotations

from lib.core.snmp import profiles as _profiles

#: The order the figures read in when a device answers more than fits. Not alphabetical: the
#: first question about a box is whether it is well (a state), the second how hard it is
#: working, the third how hot it is. A unit is a good enough proxy for "what kind of question
#: is this", and it is the module's to decide — this file is the one that knows what SNMP
#: measures.
_UNIT_ORDER = ('', '%', '°C', 'B/s', 'W', 'V', 'rpm', 'ms', 's')

#: One figure per KIND. A RouterOS box answers four temperatures; four temperatures on one row
#: is the same question answered four times, and the traffic — the other thing anybody opens
#: this for — falls off the end. The per-device view below still lists every one of them.
_CHIPS = 4

#: How many of a device's own rows travel. A switch serves a row per port, and this payload is
#: rebuilt on every refresh of a dashboard somebody leaves open: eleven hundred ports is not a
#: summary, it is the reason a dashboard gets closed.
_ROWS_MAX = 40

#: Bytes per second, in the words a person reads. The catalogue says `B/s`; nobody reads
#: 12897431 B/s.
_SCALE = ((1024 ** 3, 'GB/s'), (1024 ** 2, 'MB/s'), (1024, 'kB/s'))

#: The name the HISTORY files this module's series under, which is what a chart is fetched by.
#: The module's own name, spelled by the module — the core still holds no string naming one.
_MODULE = 'snmp'


class SnmpWidget:
    """``Watchful.overview_widget`` — mixed into the module class."""

    # ── Formatting ───────────────────────────────────────────────────────────────────────
    @staticmethod
    def _fmt(value, unit: str) -> str:
        """One figure, in the unit the profile declared and in words."""
        try:
            num = float(value)
        except (TypeError, ValueError):
            return str(value)
        if unit == 'B/s':
            for step, name in _SCALE:
                if abs(num) >= step:
                    return f'{num / step:.2f} {name}'
            return f'{num:.0f} B/s'
        if unit == 's':
            # A machine's uptime and a UPS's remaining runtime are both seconds and neither is
            # read as one. Days for the first, minutes for the second — the same rule reads
            # both, because the size of the number IS which of the two it is.
            if abs(num) >= 86400:
                return f'{num / 86400:.1f} d'
            if abs(num) >= 3600:
                return f'{num / 3600:.1f} h'
            return f'{num / 60:.0f} min'
        text = f'{num:.0f}' if abs(num) >= 10 or num == int(num) else f'{num:.2f}'
        return f'{text} {unit}'.strip()

    # ── What every profile says is worth reading first ───────────────────────────────────
    @classmethod
    def _proportions(cls, lang: str, var_dir: str = '') -> dict:
        """``{field: {role, label, unit, source}}`` — the halves of a proportion.

        A store answers as a SIZE and an AMOUNT USED, and two numbers side by side is
        arithmetic left to the reader when the answer is "83 %". Which of the two is which
        cannot be guessed from a label that says "Usado" in one profile and "In use" in the
        next, so the profile says it: `headline: "used"` / `"total"` / `"free"`.

        Charted as a LINE those two are a pair of parallel lines nobody reads. Asked for from
        the screen — "uso de disco… eso igual es mejor queso" — and the ring the panel already
        draws elsewhere is the answer.
        """
        cdir = _profiles.custom_dir(var_dir)
        catalog = _profiles.catalog(custom=_profiles.load_dir(cdir) if cdir else None)
        out: dict = {}
        for prof in catalog.values():
            for field, meta in _profiles.history_fields(prof, lang).items():
                role = meta.get('headline')
                if role in ('used', 'total', 'free') and field not in out:
                    out[field] = {'role': role, 'label': meta.get('label') or field,
                                  'unit': str(meta.get('unit') or ''),
                                  # The name of the THING, not the title of the profile:
                                  # "Almacenamiento", not "Almacenamiento (HOST-RESOURCES-MIB)".
                                  # The MIB belongs on the catalogue where somebody is choosing
                                  # a profile; here they are reading one machine.
                                  'source': str(meta.get('source_short')
                                                or meta.get('source_label')
                                                or meta.get('source') or '')}
        return out

    @classmethod
    def _rings(cls, results: dict, dev: str, pairs: dict) -> list:
        """Every proportion a device answered, device-level and per row.

        Per row because that is where they live: one filesystem per row, one volume per row.
        A machine has a handful; the interface table — the one that would flood this — has no
        proportion in it at all, so no cap is needed and none is invented.
        """
        out = []
        for key, res in sorted(results.items()):
            data = res.get('other_data') if isinstance(res.get('other_data'), dict) else {}
            if not data:
                continue
            found: dict = {}
            for field, value in data.items():
                spec = pairs.get(field)
                if spec and isinstance(value, (int, float)):
                    found.setdefault(spec['source'], {})[spec['role']] = (field, value, spec)
            row = str(data.get('_row') or '')
            for source, half in found.items():
                total = half.get('total')
                other = half.get('used') or half.get('free')
                if not total or not other or not (total[1] > 0):
                    continue
                used = other[1] if other[0] == (half.get('used') or (None,))[0] \
                    else max(0.0, total[1] - other[1])
                pct = max(0.0, min(100.0, used * 100.0 / total[1]))
                out.append({
                    'kind':  'ring',
                    # The field is what identifies this pick across a redraw, and a
                    # proportion's is the pair rather than either half of it.
                    'field': f'{total[0]}~{other[0]}',
                    'label': f'{source} — {row}' if row else source,
                    'unit':  total[2]['unit'],
                    'row':   row,
                    'key':   key,
                    'chart': {'used': used, 'total': total[1], 'pct': round(pct, 1)},
                })
        return out

    @classmethod
    def _headline_fields(cls, lang: str, var_dir: str = '') -> dict:
        """``{field: {label, unit, states}}`` — every figure a profile called ``headline``.

        The union of the catalogue and not of the profiles assigned: which figures a field
        answers does not depend on which device happens to serve it, and working out the
        assignments would mean reading the module configuration from a function that does not
        need it.
        """
        cdir = _profiles.custom_dir(var_dir)
        catalog = _profiles.catalog(custom=_profiles.load_dir(cdir) if cdir else None)
        out: dict = {}
        for prof in catalog.values():
            for field, meta in _profiles.history_fields(prof, lang).items():
                # `True` only: a `used`/`total` role is one HALF of a proportion, and half of a
                # fraction on a row of chips is a number with no question behind it.
                if meta.get('headline') is True and field not in out:
                    out[field] = {'label': meta.get('label') or field,
                                  'unit': str(meta.get('unit') or ''),
                                  'states': meta.get('states') or {}}
        return out

    @classmethod
    def _figures(cls, data: dict, heads: dict) -> list:
        """The figures ONE device answered, worst-question first — see `_UNIT_ORDER`."""
        found = []
        for rank, (field, meta) in enumerate(heads.items()):
            if field not in (data or {}):
                continue
            value = data[field]
            if value is None or isinstance(value, (dict, list)):
                continue
            said = (meta['states'] or {}).get(str(value))
            found.append({
                'field': field,
                'label': meta['label'],
                # A state answers with a WORD ("Normal", "Failed") and the MIB it came from is
                # what says so; a figure answers with itself.
                'value': str((said or {}).get('label') or cls._fmt(value, meta['unit'])),
                'state': cls._level(said),
                'unit':  meta['unit'],
                'rank':  rank,
                # Not a number: an enumeration. "Normal" has no shape over time, and a chart
                # of one would be a flat line at 1 with a legend nobody can read.
                'plot':  not said and isinstance(value, (int, float)),
            })
        # Within a kind, the order the PROFILE declared them in — which is a decision somebody
        # made about that equipment. Alphabetically by key, a RouterOS box led with
        # `mt_board_temp` and the plain "Temperatura" it declares first came fourth: the keys
        # are internal names and their alphabet is not a fact about a switch.
        order = {u: i for i, u in enumerate(_UNIT_ORDER)}
        found.sort(key=lambda f: (order.get(f['unit'], len(order)), f['rank']))
        return found

    @staticmethod
    def _level(said) -> str:
        """A profile's level for one reading, in the words the core's renderer paints."""
        level = str((said or {}).get('level') or '').lower()
        return {'bad': 'error', 'warn': 'warn', 'ok': 'ok'}.get(level, 'none')

    # ── The hook ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def overview_widget(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """One entry per DEVICE: what it is called, how it is, and what it says about itself.

        Built from the recorded state and not from the configuration, because that is where
        the answer is: a device the registry says is one is sampled with no check behind it, so
        it appears in the status under a key of its own and in no item list. *items* is read
        only for a nicer name.
        """
        heads = cls._headline_fields(lang)
        pairs = cls._proportions(lang)
        by_device: dict = {}
        for key, res in (status or {}).items():
            if not isinstance(res, dict):
                continue
            by_device.setdefault(str(key).split('/', 1)[0], {})[str(key)] = res
        entries = []
        for dev, results in sorted(by_device.items()):
            own = results.get(f'{dev}/metrics') or {}
            data = own.get('other_data') if isinstance(own.get('other_data'), dict) else {}
            figures = cls._figures(data, heads)
            counts = {'ok': 0, 'warn': 0, 'error': 0, 'total': 0}
            rows = []
            for key, res in sorted(results.items()):
                state = cls._state_of(res)
                counts['total'] += 1
                counts[state] = counts.get(state, 0) + 1
                # Only what is NOT well, and capped. A switch serves a row per port; a
                # dashboard is a summary and eleven hundred rows is not one. The figures below
                # are what a device that is fine has to say.
                if state in ('warn', 'error') and len(rows) < _ROWS_MAX:
                    rows.append({'name': str(res.get('name') or key.split('/', 1)[-1]),
                                 'state': state,
                                 'detail': str(res.get('message') or '')[:160]})
            rows += [{'name': f['label'], 'state': f['state'], 'detail': f['value']}
                     for f in figures]
            entries.append({
                'id':    dev,
                'name':  cls._name_of(dev, own, items),
                'state': cls._worst(counts),
                'ok':    counts['error'] == 0 and counts['warn'] == 0,
                'stats': [{'label': f['label'], 'value': f['value'], 'state': f['state']}
                          for f in cls._one_per_kind(figures)],
                # …and WHERE each of those figures is kept, so a screen can draw its shape
                # over time without knowing anything about SNMP. The coordinates are the ones
                # the history already files it under, which is what makes this a chart of the
                # same numbers and not of a second reading taken a different way.
                'charts': [{'field': f['field'], 'label': f['label'], 'unit': f['unit'],
                            'kind': 'line',
                            'series': {'module': _MODULE, 'key': f'{dev}/metrics',
                                       'field': f['field']}}
                           for f in figures if f['plot']]
                          + cls._rings(results, dev, pairs),
                'rows':  rows,
                'counts': counts,
            })
        agg = {'ok': 0, 'warn': 0, 'error': 0, 'total': len(entries)}
        for e in entries:
            agg[e['state']] = agg.get(e['state'], 0) + 1
        return {'entries': entries, 'aggregate': {'counts': agg}}

    @staticmethod
    def _one_per_kind(figures: list) -> list:
        """At most one figure of each kind, and at most `_CHIPS` of them."""
        out, seen = [], set()
        for f in figures:
            if f['unit'] in seen:
                continue
            seen.add(f['unit'])
            out.append(f)
            if len(out) >= _CHIPS:
                break
        return out

    @staticmethod
    def _name_of(dev: str, own: dict, items: dict) -> str:
        """What to call a device — and the answer is not the key.

        Reported from the screen as `host.0598ae99-8ccf-4e67-…` across the top of a chart. The
        `name` a result is emitted with lives in memory for one cycle: `check_state` has no
        column for it, so the state read back later has the key and nothing else. Every screen
        that shows a name rebuilds it from the CONFIGURATION — and a device sampled because the
        REGISTRY says it is one has no entry there to rebuild it from.

        So it is asked. A device answering SNMP has told us its name (`sysName`, RFC 1213, on
        every agent alive) and it is recorded like any other fact about the box, under a role
        the core already names. Read by ROLE and not by module, so nothing here knows which
        profile answered.
        """
        data = own.get('other_data') if isinstance(own.get('other_data'), dict) else {}
        for facts in (data.get('_attrs') or {}).values():
            said = str((facts or {}).get('name') or '').strip() if isinstance(facts, dict) else ''
            if said:
                return said
        label = str(((items or {}).get(dev) or {}).get('label') or '').strip()
        # Last: the key with its convention stripped. A uid is not a name, but it is what the
        # screen has, and a blank would read as a device with no identity at all.
        return str(own.get('name') or label or dev.split('.', 1)[-1] or dev)

    @staticmethod
    def _state_of(res: dict) -> str:
        """One result, as the renderer's three words.

        A warning is not a failure — the same distinction the fleet list draws, and the reason
        `severity` travels with a result at all.
        """
        if res.get('status') is not False:
            return 'ok'
        return 'warn' if str(res.get('severity') or '') == 'warning' else 'error'

    @staticmethod
    def _worst(counts: dict) -> str:
        if counts.get('error'):
            return 'error'
        if counts.get('warn'):
            return 'warn'
        return 'ok' if counts.get('total') else 'none'
