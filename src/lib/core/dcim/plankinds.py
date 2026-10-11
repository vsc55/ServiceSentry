#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the inventory's plans can hold: the plan editor's catalogue, from this screen.

The inventory registers itself as a screen of the 2D plan editor (:mod:`lib.core.plan2d.kinds`):
which of the base objects it uses —doors, columns, desks, the building's safety, the equipment
on desks, walls and ceilings—, the ones only a data centre has —a contained aisle, a cooling
unit, an electrical panel, a UPS, a cable tray, access control—, and with which permissions it
is read (`dcim_view`) and its own objects created (`dcim_catalog_manage`).

**Where each one is kept is this screen's decision, not the catalogue's.** What is equipment
(`device`) is an item (`dc_item`, `placement = 'room'`, its kind in `role`): it is linked to a
monitored device, its cable is traced, it counts. Everything else is a piece (`dc_feature`, its
kind in `kind`). From here come `FEATURE_KINDS` and `ROOM_ITEM_DEFAULTS`, which the rest of the
inventory has always read; and, with the objects created from the screen, what a request may
place (:func:`feature_kinds`, :func:`device_defaults`).
"""

from __future__ import annotations

from lib.core.plan2d import kinds as p2k

SCREEN = 'dcim'


def _k(label, icon, w, d, h, layer, look, **extra):
    return dict({'label': label, 'icon': icon, 'w': w, 'd': d, 'h': h, 'layer': layer,
                 'look': look}, **extra)


#: What only a data centre's plan has. `layer` is not aesthetics: a contained aisle is drawn
#: UNDER the racks because it is the floor between them, a cable tray OVER them because it runs
#: through the air. `front`: the side it is worked from —a panel, a UPS, a cooling unit, the way
#: one walks through a turnstile—, marked on the plan.
OWN = {
    'aisle':     _k('dcim_kind_aisle', 'bi-distribute-vertical', 4800, 1200, 2200, 'floor',
                    {'fill': 'var(--bs-primary-bg-subtle)', 'line': 'var(--bs-primary)', 'dash': '4 3'}, group='datacenter'),
    # `--bs-secondary-bg`: `--bs-body-secondary-bg` does not exist, and a `fill` with a variable
    # that does not exist is painted black.
    'panel':     _k('dcim_kind_panel', 'bi-lightning-charge', 900, 400, 2000, 'room',
                    {'fill': 'var(--bs-secondary-bg)', 'line': 'var(--bs-body-color)'}, front=True, group='datacenter'),
    'ups':       _k('dcim_kind_ups', 'bi-battery-charging', 1200, 900, 1900, 'room',
                    {'fill': 'var(--bs-secondary-bg)', 'line': 'var(--bs-secondary-color)'}, front=True, group='datacenter'),
    'crac':      _k('dcim_kind_crac', 'bi-snow', 600, 1000, 2000, 'room',
                    {'fill': 'var(--bs-info-bg-subtle)', 'line': 'var(--bs-info)'}, front=True, group='datacenter'),
    'tray':      _k('dcim_kind_tray', 'bi-bezier2', 6000, 300, 140, 'air',
                    {'fill': 'var(--bs-warning-bg-subtle)', 'line': 'var(--bs-warning)', 'dash': '6 3'},
                    base=2720, group='datacenter'),
    # Access control: a turnstile, with its front the side one enters by; and what goes on a
    # wall, a card reader or the gateway the locks connect to, at the height it hangs.
    'turnstile': _k('dcim_kind_turnstile', 'bi-sign-turn-right', 1000, 1600, 1000, 'room',
                    {'fill': 'var(--bs-secondary-bg)', 'line': 'var(--bs-primary)', 'cross': True},
                    front=True, group='access'),
    'reader':    _k('dcim_kind_reader', 'bi-broadcast-pin', 200, 80, 200, 'room',
                    {'fill': 'var(--bs-primary)', 'line': 'var(--bs-primary)', 'dark': True}, base=1300, group='access'),
}

#: The palette's order: the room's own first, the building after, the equipment last.
ORDER = ('aisle', 'zone', 'column', 'wall', 'door', 'panel', 'ups', 'crac', 'bench', 'cabinet',
         'extinguisher', 'tray', 'turnstile', 'reader', 'hose_reel', 'fire_alarm',
         'emergency_light', 'smoke_detector', 'first_aid', 'aed', 'label',
         'pc', 'phone', 'printer', 'ap', 'camera', 'display', 'outlet', 'power_outlet')


def _in_use(wa, key: str) -> int:
    """How many pieces and room items are of kind *key*: what stops its object being deleted."""
    store = getattr(wa, '_dcim_store', None)
    if store is None:
        return 0
    return (len(store.features.list('kind = ?', (str(key),)))
            + len(store.items.list("placement = 'room' AND role = ?", (str(key),))))


p2k.register_screen(SCREEN, base=ORDER, own=OWN, view_perm='dcim_view',
                    manage_perm='dcim_catalog_manage', in_use=_in_use, devices=True)

_CODE = p2k.code_kinds(SCREEN)

#: The pieces the inventory has in code, as it always read them (`w`, `d`, `h`, `base`, `layer`,
#: `front`, and now also how they look).
FEATURE_KINDS = {k: s for k, s in _CODE.items() if not s.get('device')}

#: What a room item measures and where it goes when the row says nothing:
#: ``(width, depth, height, height off the floor, mount)`` in millimetres.
ROOM_ITEM_DEFAULTS = {k: (s['w'], s['d'], s['h'], s.get('base', 0), s.get('mount', 'floor'))
                      for k, s in _CODE.items() if s.get('device')}


def _custom_rows(wa) -> list:
    st = getattr(wa, '_plan2d_kinds', None)
    try:
        return st.of_screen(SCREEN) if st is not None else []
    except Exception:                       # noqa: BLE001 — a catalogue that fails is the code one
        return []


def all_kinds(wa) -> dict:
    """Everything the inventory's plans can hold: in code, and created from the screen."""
    return p2k.kinds(SCREEN, _custom_rows(wa))


def feature_kinds(wa) -> dict:
    """The pieces a request may place: the ones in code and the non-equipment ones created."""
    return {k: s for k, s in all_kinds(wa).items() if not s.get('device')}


def device_defaults(wa) -> dict:
    """`ROOM_ITEM_DEFAULTS` with the equipment created from the screen."""
    out = dict(ROOM_ITEM_DEFAULTS)
    for k, s in all_kinds(wa).items():
        if s.get('device') and k not in out:
            out[k] = (s['w'], s['d'], s['h'], s.get('base', 0), s.get('mount', 'floor'))
    return out


def device_roles(wa) -> tuple:
    """The room-item roles created from the screen (the ones in code are in `ITEM_ROLES`)."""
    return tuple(k for k, s in all_kinds(wa).items() if s.get('device') and s.get('source') == 'custom')
