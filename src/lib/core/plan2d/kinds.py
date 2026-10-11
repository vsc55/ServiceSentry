#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What can be put on a plan: the objects, their size and their look, in one catalogue.

Three layers, from the most shared to the most local:

* **The base** (:data:`BASE`) — objects any plan of a building may hold: a door, a column, a
  desk, an extinguisher, a PC, a camera. Their size is the usual one, their look is the one every
  plan draws them with, and their name is ``plan2d_kind_<id>``.
* **A screen's own** — each screen that edits a plan registers itself
  (:func:`register_screen`) saying which base objects it uses and adding the ones that only make
  sense there: the inventory adds a contained aisle, a cooling unit or a cable tray.
* **The ones somebody creates** — from the screen itself, kept in ``plan2d_kind``
  (:mod:`lib.core.plan2d.store`), one list per screen. Their key starts ``u-`` and can never
  collide with one written here.

An object says what it IS and how it LOOKS, never where it is stored: ``device`` marks the ones
that are equipment (they can be linked to a monitored device, and a cable can be traced to
them), and it is the screen that decides what that means for its tables.

Each object is a dict:

``label``  the i18n key of its name (an object created from the screen carries ``name``)
``icon``   a Bootstrap icon
``w``, ``d``, ``h``  width, depth and height in millimetres; ``base``: how high it starts
``layer``  ``floor`` (drawn under everything), ``room`` or ``air`` (drawn over everything)
``front``  it has a front side, marked on the plan
``mount``  where equipment usually goes: ``desk``, ``wall``, ``ceiling`` or ``floor``
``device`` it is equipment (see above)
``look``   how it is drawn: ``fill``, ``line``, ``dash``, ``cross``, ``dark`` (dark text),
           ``abbr`` (the letters drawn on it)
``group``  the palette group it is looked for in (:data:`GROUPS`); one created from a screen
           goes to ``other``
"""

from __future__ import annotations

import re

#: The layers, bottom to top. The order IS the data: whoever draws walks this and invents none.
LAYERS = ('floor', 'room', 'air')
#: Where equipment can be mounted.
MOUNTS = ('desk', 'wall', 'ceiling', 'floor')
#: What an object created from a screen starts with: its key, so it never meets one of these.
CUSTOM_PREFIX = 'u-'
#: The palette's groups, in order, with their icon: what an object is FOR, which is how a person
#: looks for it. Thirty icons in one strip were told apart only by hovering each. The name of a
#: group is ``plan2d_pal_<id>``. Whatever a screen creates goes to ``other``.
GROUPS = (('structure', 'bi-bricks'), ('furniture', 'bi-lamp'), ('datacenter', 'bi-hdd-stack'),
          ('safety', 'bi-shield-check'), ('access', 'bi-key'), ('sockets', 'bi-outlet'),
          ('equipment', 'bi-pc-display'), ('other', 'bi-boxes'))
GROUP_IDS = tuple(g for g, _icon in GROUPS)


def _k(icon, w, d, h, layer, look, **extra):
    return dict({'icon': icon, 'w': w, 'd': d, 'h': h, 'layer': layer, 'look': look}, **extra)


#: Objects of a building that any plan may use. The colours are theme variables, not literals:
#: the panel is read in light and dark, and a plan in the greys of one theme over the background
#: of the other cannot be read. The equipment's colours are fixed and none is red: red is «down».
BASE = {
    'zone':      _k('bi-bounding-box', 2000, 2000, 20, 'floor',
                    {'fill': 'var(--bs-body-bg)', 'line': 'var(--bs-secondary-color)', 'dash': '3 3'}),
    'column':    _k('bi-x-diamond', 500, 500, 3000, 'room',
                    {'fill': 'var(--bs-secondary-bg)', 'line': 'var(--bs-body-color)', 'cross': True}),
    'wall':      _k('bi-square-half', 4000, 100, 2700, 'room',
                    {'fill': 'var(--bs-info-bg-subtle)', 'line': 'var(--bs-info)'}),
    'door':      _k('bi-door-open', 1000, 120, 2100, 'room',
                    {'fill': 'var(--bs-warning)', 'line': 'var(--bs-warning)', 'dark': True}),
    'bench':     _k('bi-table', 1600, 800, 750, 'room',
                    {'fill': 'var(--bs-tertiary-bg)', 'line': 'var(--bs-secondary-color)'}, front=True),
    'cabinet':   _k('bi-archive', 1000, 500, 2000, 'room',
                    {'fill': 'var(--bs-secondary-bg)', 'line': 'var(--bs-body-color)'}, front=True),
    'extinguisher': _k('bi-fire', 300, 300, 900, 'room',
                       {'fill': 'var(--bs-danger)', 'line': 'var(--bs-danger)', 'dark': True}),
    'hose_reel':  _k('bi-droplet-half', 700, 250, 700, 'room',
                     {'fill': 'var(--bs-danger-bg-subtle)', 'line': 'var(--bs-danger)'}, base=900, front=True),
    'fire_alarm': _k('bi-bell', 120, 60, 120, 'room',
                     {'fill': 'var(--bs-danger)', 'line': 'var(--bs-danger)', 'dark': True}, base=1400, front=True),
    'emergency_light': _k('bi-lightbulb', 350, 80, 120, 'room',
                          {'fill': 'var(--bs-success-bg-subtle)', 'line': 'var(--bs-success)'},
                          base=2200, front=True),
    'smoke_detector':  _k('bi-record-circle', 120, 120, 60, 'air',
                          {'fill': 'var(--bs-body-bg)', 'line': 'var(--bs-secondary-color)'}, base=2940),
    'first_aid':  _k('bi-bandaid', 400, 150, 500, 'room',
                     {'fill': 'var(--bs-success)', 'line': 'var(--bs-success)', 'dark': True}, base=1200, front=True),
    'aed':        _k('bi-heart-pulse', 450, 200, 450, 'room',
                     {'fill': 'var(--bs-success)', 'line': 'var(--bs-success)', 'dark': True}, base=1200, front=True),
    'label':     _k('bi-tag', 1600, 400, 10, 'air', {'fill': 'none', 'line': 'none'}),
    # Equipment: what is on a desk, a wall or a ceiling and answers on the network.
    'pc':      _k('bi-pc-display', 180, 300, 330, 'room', {'fill': '#3b82f6', 'abbr': 'PC'},
                  base=750, mount='desk', device=True),
    'phone':   _k('bi-telephone', 190, 200, 110, 'room', {'fill': '#14b8a6', 'abbr': 'Tel'},
                  base=750, mount='desk', device=True),
    'printer': _k('bi-printer', 520, 480, 420, 'room', {'fill': '#a855f7', 'abbr': 'Imp'},
                  base=0, mount='floor', device=True),
    'ap':      _k('bi-wifi', 230, 230, 45, 'room', {'fill': '#f59e0b', 'abbr': 'AP'},
                  base=2950, mount='ceiling', device=True),
    'camera':  _k('bi-camera-video', 130, 130, 120, 'room', {'fill': '#6366f1', 'abbr': 'Cam'},
                  base=2750, mount='wall', device=True),
    'display': _k('bi-tv', 1450, 90, 830, 'room', {'fill': '#64748b', 'abbr': 'TV'},
                  base=900, mount='wall', device=True),
    'outlet':  _k('bi-ethernet', 86, 45, 86, 'room', {'fill': '#94a3b8', 'abbr': ''},
                  base=300, mount='wall', device=True),
    # A wall power socket. Not red, which is «down»: what it hangs from is said by its letters.
    'power_outlet': _k('bi-plug', 86, 45, 86, 'room', {'fill': '#64748b', 'abbr': ''},
                       base=300, mount='wall', device=True),
}
#: Each base object's palette group.
_BASE_GROUP = {
    'zone': 'structure', 'column': 'structure', 'wall': 'structure', 'door': 'structure',
    'label': 'structure', 'bench': 'furniture', 'cabinet': 'furniture',
    'extinguisher': 'safety', 'hose_reel': 'safety', 'fire_alarm': 'safety',
    'emergency_light': 'safety', 'smoke_detector': 'safety', 'first_aid': 'safety', 'aed': 'safety',
    'pc': 'equipment', 'phone': 'equipment', 'printer': 'equipment', 'ap': 'equipment',
    'camera': 'equipment', 'display': 'equipment', 'outlet': 'sockets', 'power_outlet': 'sockets',
}
for _id, _spec in BASE.items():
    _spec['label'] = 'plan2d_kind_' + _id
    _spec['group'] = _BASE_GROUP[_id]

#: The icons an object created from a screen may take: a closed list, so a name typed into a
#: form can never become a class of somebody else's markup.
ICONS = (
    'bi-square', 'bi-circle', 'bi-triangle', 'bi-hexagon', 'bi-box', 'bi-boxes', 'bi-archive',
    'bi-bookshelf', 'bi-table', 'bi-door-open', 'bi-door-closed', 'bi-window', 'bi-lamp',
    'bi-lightbulb', 'bi-plug', 'bi-outlet', 'bi-lightning-charge', 'bi-battery-charging',
    'bi-fan', 'bi-snow', 'bi-thermometer-half', 'bi-droplet', 'bi-fire', 'bi-bell',
    'bi-shield-check', 'bi-lock', 'bi-key', 'bi-camera-video', 'bi-webcam', 'bi-printer',
    'bi-pc-display', 'bi-laptop', 'bi-display', 'bi-tv', 'bi-phone', 'bi-telephone',
    'bi-headset', 'bi-router', 'bi-hdd-network', 'bi-hdd-stack', 'bi-wifi', 'bi-broadcast',
    'bi-ethernet', 'bi-usb-symbol', 'bi-cpu', 'bi-speaker', 'bi-mic', 'bi-tag', 'bi-signpost',
    'bi-flag', 'bi-star', 'bi-heart-pulse', 'bi-bandaid', 'bi-trash', 'bi-recycle', 'bi-cup-hot',
    'bi-person', 'bi-people', 'bi-car-front', 'bi-bicycle', 'bi-tree', 'bi-flower1',
)

# ── Screens ───────────────────────────────────────────────────────────────────

_SCREENS: dict[str, dict] = {}


def register_screen(name: str, *, base, own=None, view_perm: str, manage_perm: str,
                    in_use=None, devices: bool = True) -> None:
    """Declare a screen that edits a plan.

    *base*: the ids of :data:`BASE` it uses, in the order its palette shows them, mixed with its
    own; *own*: ``{id: spec}`` objects only it has (their ``label`` is the screen's own key).
    *view_perm* lets a viewer read its catalogue, *manage_perm* create objects of its own from the
    screen. *in_use(wa, key)* says how many things of that kind the screen holds, which is what
    stops an object in use from being deleted. *devices*: whether the screen keeps equipment, and
    so whether an object created there may be one.
    """
    # An object of its own with no group goes to `other`, like one created from the screen.
    own = {k: dict({'group': 'other'}, **v) for k, v in (own or {}).items()}
    orden = list(base)
    for k in own:
        if k not in orden:
            orden.append(k)
    for k in orden:
        if k not in BASE and k not in own:
            raise ValueError(f'{name}: {k} is neither a base object nor one of its own')
        if k.startswith(CUSTOM_PREFIX):
            raise ValueError(f'{name}: {k} looks like an object created from a screen')
        if (own.get(k) or BASE.get(k) or {}).get('group') not in GROUP_IDS:
            raise ValueError(f'{name}: {k} has no palette group')
    _SCREENS[name] = {'order': orden, 'own': own, 'view_perm': view_perm,
                      'manage_perm': manage_perm, 'in_use': in_use, 'devices': devices}


def screen(name: str) -> dict | None:
    return _SCREENS.get(str(name or ''))


def code_kinds(name: str) -> dict:
    """The objects a screen has in code —its base ones and its own—, in its order, each with
    ``source``: ``base`` or ``screen``."""
    s = _SCREENS[name]
    out = {}
    for k in s['order']:
        if k in s['own']:
            out[k] = dict(s['own'][k], source='screen')
        else:
            out[k] = dict(BASE[k], look=dict(BASE[k]['look']), source='base')
    return out


def custom_spec(row: dict) -> dict:
    """An object created from a screen, as the catalogue gives it."""
    look = {'fill': row.get('fill') or '#94a3b8'}
    if row.get('line'):
        look['line'] = row['line']
    if row.get('dash'):
        look['dash'] = row['dash']
    if row.get('abbr'):
        look['abbr'] = row['abbr']
    spec = {'name': row.get('name') or '', 'icon': row.get('icon') or 'bi-square',
            'w': int(row.get('w_mm') or 600), 'd': int(row.get('d_mm') or 600),
            'h': int(row.get('h_mm') or 1000), 'layer': row.get('layer') or 'room',
            'look': look, 'source': 'custom', 'uid': row.get('uid') or '', 'group': 'other'}
    if int(row.get('base_mm') or 0):
        spec['base'] = int(row['base_mm'])
    if int(row.get('front') or 0):
        spec['front'] = True
    if int(row.get('device') or 0):
        spec['device'] = True
        spec['mount'] = row.get('mount') or 'floor'
    return spec


def kinds(name: str, rows=()) -> dict:
    """Everything a screen offers: its objects in code, then the ones created from it (*rows*,
    from the store), in the order they were created."""
    out = code_kinds(name)
    for r in rows or ():
        if str(r.get('key') or '').startswith(CUSTOM_PREFIX):
            out[r['key']] = custom_spec(r)
    return out


def groups() -> list:
    """The palette's groups, in order: ``[{id, icon, label}]``."""
    return [{'id': g, 'icon': icon, 'label': 'plan2d_pal_' + g} for g, icon in GROUPS]


# ── An object created from a screen: what it may say ──────────────────────────

_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
_DASH = re.compile(r'^(\d{1,2}( \d{1,2})?)?$')
#: The limits of a size, in millimetres: from a socket to a hall.
_SIZE = {'w_mm': (10, 100000), 'd_mm': (10, 100000), 'h_mm': (1, 20000), 'base_mm': (0, 20000)}


def custom_bad(data: dict, devices: bool = True) -> str:
    """Why *data* cannot describe an object, as an i18n key, or ``''``. Every field is checked
    whether or not it was sent: what is not sent takes its default before this runs."""
    name = data.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        return 'plan2d_kind_bad_name'
    if data.get('icon') not in ICONS:
        return 'plan2d_kind_bad_icon'
    for campo, (lo, hi) in _SIZE.items():
        v = data.get(campo)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not lo <= v <= hi:
            return 'plan2d_kind_bad_size'
    if data.get('layer') not in LAYERS:
        return 'plan2d_kind_bad_layer'
    if not (isinstance(data.get('fill'), str) and _COLOR.match(data['fill'])):
        return 'plan2d_kind_bad_color'
    if data.get('line') and not (isinstance(data['line'], str) and _COLOR.match(data['line'])):
        return 'plan2d_kind_bad_color'
    if not (isinstance(data.get('dash'), str) and _DASH.match(data['dash'])):
        return 'plan2d_kind_bad_dash'
    abbr = data.get('abbr')
    if not isinstance(abbr, str) or len(abbr) > 4:
        return 'plan2d_kind_bad_abbr'
    if data.get('device') and not devices:
        return 'plan2d_kind_no_devices'
    if data.get('device') and data.get('mount') not in MOUNTS:
        return 'plan2d_kind_bad_mount'
    return ''


#: What an object created from a screen starts with, field by field.
CUSTOM_DEFAULTS = {'name': '', 'icon': 'bi-square', 'device': 0, 'mount': 'floor',
                   'w_mm': 600, 'd_mm': 600, 'h_mm': 1000, 'base_mm': 0, 'layer': 'room',
                   'front': 0, 'fill': '#94a3b8', 'line': '', 'dash': '', 'abbr': ''}


def custom_clean(data: dict, current: dict | None = None) -> dict:
    """*data* over *current* (or the defaults), with only the fields an object has, numbers as
    numbers and flags as 0/1. What :func:`custom_bad` then judges."""
    out = dict(CUSTOM_DEFAULTS)
    if current:
        out.update({k: current.get(k, v) for k, v in CUSTOM_DEFAULTS.items()})
    for k in CUSTOM_DEFAULTS:
        if k in (data or {}):
            out[k] = data[k]
    for k in ('device', 'front'):
        out[k] = 1 if out[k] in (True, 1, '1', 'true', 'on') else 0
    for k in _SIZE:
        v = out[k]
        if isinstance(v, str) and v.strip().lstrip('-').isdigit():
            out[k] = int(v)
    if isinstance(out.get('name'), str):
        out['name'] = out['name'].strip()
    return out
