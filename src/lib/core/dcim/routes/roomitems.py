#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What is in a room and not in a rack: ``/api/v1/dcim/rooms/<uid>/items`` and its kin

    GET    /api/v1/dcim/rooms/<uid>/items    the room's items (PCs, phones, printers, access
                                             points, cameras, displays, wall outlets), with
                                             their state and their box
    POST   /api/v1/dcim/rooms/<uid>/items    put one in the room
    PUT    /api/v1/dcim/room-items/<uid>     move it, turn it, rename it, link its device; a wall
                                             outlet or power socket, its jacks (a connector and
                                             how many, per type) and (a socket) the power source
                                             it hangs from
    GET    /api/v1/dcim/room-items/jacks     what the jack of a wall outlet and of a power
                                             socket can be, from the connector catalogue
    GET    /api/v1/dcim/items/<uid>/trace    follow an item's cables, through the passive ones
                                             (patch panels, outlets), to where each one ends

Removing one is ``DELETE /api/v1/dcim/items/<uid>``, the same as any item: it takes its cables
with it, and whose it is follows the room (`DcimStore.chain_of`).

A room item is a ``dc_item`` with ``placement = 'room'``, no rack and a room: where it stands is
measured like a piece of the plan. Its own routes and not the rack ones because everything
those check —a free U, a face, a tray to hang from— is about a cabinet, and a desk has none.
"""

from __future__ import annotations

from flask import jsonify, request

from lib.core.dcim import owners as dcim_owners
from lib.core.dcim import service as dcim_svc
from lib.core.dcim.routes._common import SERVER_COLS, _fresh, _without, group_bad
from lib.core.dcim import plankinds as dcim_plankinds
from lib.core.dcim import connectors as dcim_connectors
import json

from lib.core.dcim.store import ITEM_ROLES, JACK_ROLES, JACK_TYPES_MAX, JACKS_SANE, MOUNTS, room_item_box

#: What a request may write on a room item. Not its rack, its U or its placement: a room item
#: is in a room, and putting it in a rack is placing it there with the rack's routes.
_EDITABLE = ('label', 'role', 'type_uid', 'device_uid', 'serial', 'asset', 'description',
             'pos_x', 'pos_y', 'rotation', 'base_mm', 'mount', 'depth_mm', 'room_uid',
             'purchased_at', 'warranty_until', 'supplier', 'group_uid',
             'jacks', 'source_uid')


def register(app, wa, C):

    def _room_writable(store, room_uid):
        room = store.rooms.get(str(room_uid or '')) if store else None
        if not room:
            return None
        return room if C.may_write(store, store.owners_map(), C.seen(), 'room', room['uid']) else False

    def _bad(store, data):
        """Why *data* cannot describe a room item, as an error key, or ``''``."""
        # Las de código y el equipo creado desde la pantalla del plano (`plankinds`).
        if 'role' in data and str(data.get('role') or '') not in ITEM_ROLES + dcim_plankinds.device_roles(wa) + ('',):
            return 'dcim_role_unknown'
        if str(data.get('mount') or '') not in MOUNTS + ('',):
            return 'dcim_mount_unknown'
        if group_bad(data):
            return 'dcim_group_bad'
        for campo in ('pos_x', 'pos_y', 'rotation', 'base_mm', 'depth_mm'):
            if campo in data and data[campo] not in (None, ''):
                try:
                    v = float(data[campo])
                except (TypeError, ValueError, OverflowError):
                    return 'dcim_bad_number'
                if v != v or abs(v) > 1e7:                  # NaN, Infinity, nonsense
                    return 'dcim_bad_number'
        if data.get('type_uid') and not (getattr(wa, '_dcim_catalog', None)
                                         and wa._dcim_catalog.get(str(data['type_uid']))):
            return 'dcim_not_found'
        return ''

    def _bad_jack(store, data, item, room_uid) -> str:
        """Why the jacks or the source of a wall item cannot be *data*, or ``''``. Its role is the
        new one if it changes, else the item's; its site, its room's. The jacks are a list —two
        RJ45, a fibre and an HDMI on one plate—: each a connector of its role's kind and how many,
        a whole number from 1 with no maximum. Empty (`''`, `null`, `[]`) is «not said». The
        same connector twice is one entry, its counts added. Leaves the list as stored JSON."""
        role = str(data.get('role', (item or {}).get('role')) or '')
        # Otra clase: lo que era de la anterior se va —una roseta que pasa a ser un PC no tiene
        # bocas ni cuelga de un SAI; una toma que pasa a roseta no tiene Schuko—, salvo lo que la
        # misma petición diga de nuevo, que se comprueba abajo contra la clase nueva.
        if item is not None and 'role' in data and role != str(item.get('role') or ''):
            data.setdefault('jacks', '')
            if role != 'power_outlet':
                data.setdefault('source_uid', '')
        if 'jacks' in data:
            v = data['jacks']
            if v in (None, '', []):
                data['jacks'] = ''
            else:
                if role not in JACK_ROLES or not isinstance(v, list) or len(v) > JACK_TYPES_MAX:
                    return 'dcim_jacks_bad'
                ids = {c['id'] for c in dcim_connectors.jacks(role, '', C.conns())}
                limpio, donde = [], {}
                for b in v:
                    if not isinstance(b, dict):
                        return 'dcim_jacks_bad'
                    cid = str(b.get('connector') or '').strip()
                    if cid not in ids:
                        return 'dcim_jack_connector_bad'
                    n = b.get('n', 1)
                    try:
                        f = float(n) if not isinstance(n, bool) else float('nan')
                    except (TypeError, ValueError, OverflowError):
                        return 'dcim_bad_number'
                    if f != f or abs(f) > JACKS_SANE:
                        return 'dcim_bad_number'
                    if f < 1 or f != int(f):
                        return 'dcim_jacks_bad'
                    if cid in donde:
                        limpio[donde[cid]]['n'] = min(JACKS_SANE, limpio[donde[cid]]['n'] + int(f))
                    else:
                        donde[cid] = len(limpio)
                        limpio.append({'connector': cid, 'n': int(f)})
                data['jacks'] = json.dumps(limpio, separators=(',', ':'))
        if data.get('source_uid'):
            src = store.sources.get(str(data['source_uid']))
            room = store.rooms.get(str(room_uid or '')) or {}
            if role != 'power_outlet' or not src \
                    or str(src.get('site_uid') or '') != str(room.get('site_uid') or ''):
                return 'dcim_jack_source_bad'
        return ''

    def _out(store, item, estados, cajas) -> dict:
        return dict(item, state=dcim_svc.item_state(item, estados), box=room_item_box(item, cajas),
                    **dcim_svc.jack_brief(store, item, C.conns()))

    @app.route('/api/v1/dcim/room-items/jacks', methods=['GET'])
    @C.view_req
    def api_dcim_room_item_jacks():
        """What each jack of a wall item can be: ``{role: [{id, name, abbr, shape}]}``, from the
        connector catalogue — copper, fibre and video for an outlet, power for a socket."""
        return jsonify({'connectors': {r: dcim_connectors.jacks(r, wa._lang(), C.conns())
                                       for r in JACK_ROLES}})

    @app.route('/api/v1/dcim/rooms/<uid>/items', methods=['GET'])
    @C.view_req
    def api_dcim_room_items(uid):
        """The room's items —what is in it and not in a rack— with their state and box (where it
        is and how big, in millimetres, its role's defaults filling what the row does not say).
        Only what this reader may see, like any item."""
        store = C.store()
        room = store.rooms.get(uid) if store else None
        if not room:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        said, allowed = store.owners_map(), C.seen()
        if not dcim_owners.may_see(C.owner_of(store, said, 'room', uid), allowed):
            return jsonify({'error': wa._t('access_denied')}), 403
        reach = dcim_svc.reachable(store, said, allowed)
        estados = C.states()
        items = C.filtered(store.items_in_room(uid), store, said, allowed, 'item', reach)
        cajas = dcim_plankinds.device_defaults(wa)
        return jsonify({'items': [_out(store, i, estados, cajas) for i in items],
                        'roles': list(ITEM_ROLES), 'mounts': list(MOUNTS)})

    @app.route('/api/v1/dcim/rooms/<uid>/items', methods=['POST'])
    @C.edit_req
    def api_dcim_room_item_new(uid):
        """Put an item in a room: a PC on a desk, a printer, an access point on the ceiling, a wall
        outlet. ``role`` says what it is; where, like a piece of the plan."""
        store = C.store()
        room = _room_writable(store, uid)
        if room is None:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if room is False:
            return jsonify({'error': wa._t('access_denied')}), 403
        data = {k: v for k, v in _fresh(request.get_json(silent=True) or {}).items() if k in _EDITABLE}
        malo = _bad(store, data) or _bad_jack(store, data, None, uid)
        if malo:
            return jsonify({'error': wa._t(malo)}), 400
        data.update({'room_uid': uid, 'rack_uid': '', 'placement': 'room',
                     'u_start': 0, 'u_height': 0, 'face': 'full'})
        nuevo = store.items.create(data, actor=C.actor())
        wa._audit('dcim_placed', detail={'item': nuevo, 'room': uid})
        return jsonify({'uid': nuevo})

    @app.route('/api/v1/dcim/room-items/<uid>', methods=['PUT'])
    @C.edit_req
    def api_dcim_room_item_edit(uid):
        """Move, turn, rename a room item, or link its device. To another room of the same site
        too —a printer carried down the corridor—, never into a rack."""
        store = C.store()
        item = store.items.get(uid) if store else None
        if not item or str(item.get('placement') or '') != 'room':
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        if not C.may_write(store, store.owners_map(), C.seen(), 'item', uid):
            return jsonify({'error': wa._t('access_denied')}), 403
        data = {k: v for k, v in _without(request.get_json(silent=True) or {}, SERVER_COLS).items()
                if k in _EDITABLE}
        malo = _bad(store, data) or _bad_jack(store, data, item, data.get('room_uid') or item.get('room_uid'))
        if malo:
            return jsonify({'error': wa._t(malo)}), 400
        if 'room_uid' in data and str(data['room_uid']) != str(item.get('room_uid') or ''):
            destino = _room_writable(store, data['room_uid'])
            origen = store.rooms.get(str(item.get('room_uid') or '')) or {}
            if destino is None:
                return jsonify({'error': wa._t('dcim_not_found')}), 404
            if destino is False:
                return jsonify({'error': wa._t('access_denied')}), 403
            if str(destino.get('site_uid') or '') != str(origen.get('site_uid') or ''):
                return jsonify({'error': wa._t('dcim_room_other_site')}), 400
        store.items.update(uid, data, actor=C.actor())
        return jsonify({'ok': True})

    @app.route('/api/v1/dcim/items/<uid>/trace', methods=['GET'])
    @C.view_req
    def api_dcim_item_trace(uid):
        """Where each of an item's cables ends, following them through the passive items on the
        way — a patch panel, a wall outlet: what goes in at the front `N` comes out at the back
        `N-R`. A PC's port reads «PC → outlet A → (horizontal) → patch panel 7 → switch Gi1/0/7».
        ``?port=`` for one port. Only what this reader may see: a hop into somebody else's item
        is named as theirs and the walk stops there."""
        store = C.store()
        item = store.items.get(uid) if store else None
        if not item:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        said, allowed = store.owners_map(), C.seen()
        if not dcim_owners.may_see(C.owner_of(store, said, 'item', uid), allowed):
            return jsonify({'error': wa._t('access_denied')}), 403

        def visible(i_uid):
            return dcim_owners.may_see(C.owner_of(store, said, 'item', i_uid), allowed)

        return jsonify({'paths': dcim_svc.trace(store, uid, str(request.args.get('port') or ''),
                                                visible)})

    _ = (api_dcim_room_items, api_dcim_room_item_new, api_dcim_room_item_edit, api_dcim_item_trace)
