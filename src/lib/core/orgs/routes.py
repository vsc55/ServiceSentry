#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The company registry over HTTP — all under ``/api/v1/orgs``:

    GET     /api/v1/orgs              the companies, with what each has on its name
    POST    /api/v1/orgs              create one
    PUT     /api/v1/orgs/<uid>        rename one, or correct its short form
    DELETE  /api/v1/orgs/<uid>        remove one, un-filing what was hers
    POST    /api/v1/orgs/owner        say whose something is (any declared scope)

The last one is the reason this is not four CRUD handlers. Ownership crosses packages: the scope
comes from whoever declared it (:mod:`lib.core.orgs.scopes`), so the same endpoint files a rack,
a host, and whatever the next package learns to own — without this file naming any of them.
"""

from __future__ import annotations

from flask import jsonify, request, session

from lib.core.orgs import owners as org_owners
from lib.core.orgs import scopes as org_scopes


def register(app, wa):
    view_req = wa._perm_required('orgs_view')
    # Its own flag, and no role carries it: in a group this decides what is billed to which
    # company and who may see it, which is not the same authority as tidying a rack.
    edit_req = wa._perm_required('orgs_edit')

    def _store():
        return getattr(wa, '_orgs_store', None)

    def _actor():
        return session.get('username', '')

    def _seen():
        return org_owners.visible_orgs(set(wa._get_session_permissions() or []))

    @app.route('/api/v1/orgs', methods=['GET'])
    @view_req
    def api_orgs():
        """The companies, with **what each has on its name**.

        The count is not decoration: it is the other half of the question this screen answers.
        From a rack you ask "whose is this?"; from here, "what belongs to this company?" — and
        without it, deleting one is pressing blind, because what was hers stops being on
        anybody's name and nobody knew how much that was.

        Narrowed to what the caller may see: somebody holding one company's scope and not the
        fleet gets that company. Listing them all would be an enumeration of the group's
        subsidiaries to somebody granted exactly one of them.
        """
        store = _store()
        if store is None:
            return jsonify({'orgs': [], 'scopes': []})
        allowed = _seen()
        rows = store.orgs.list()
        if allowed is not None:
            rows = [r for r in rows if r['uid'] in allowed]
        said = store.counts()
        # The scopes go with the list rather than being written into the screen: what CAN belong
        # to a company is whatever the installed packages declare, so a screen with the four
        # inventory ones written in would stop telling the truth the day a module declares a
        # fifth — and would say nothing about it.
        conocidos = [{'scope': s, 'label_key': str(d.get('label_key') or '')}
                     for s, d in sorted(org_scopes.registry().items())]
        return jsonify({'orgs': [dict(r, said=said.get(str(r.get('uid') or ''), {}))
                                 for r in rows],
                        'scopes': conocidos})

    def _free(store, data, skip=''):
        """Neither the name nor the short form belongs to another company. ``None`` if writable.

        Here and not in the database: `org.name` carries a unique index — the backstop — and an
        index does not answer in words. What it produces is an `IntegrityError`, which reaches a
        person as an HTTP 500 with a Werkzeug traceback across the screen. That is exactly how it
        came out; reported from the screen.

        The two separately, because they are two things: two companies with the same name are one
        company typed twice, and two with the same short form put a badge on an elevation that
        does not say whose the cabinet is — which is the only thing a short form is for.
        """
        for col, key in (('name', 'orgs_name_taken'), ('short', 'orgs_short_taken')):
            if col not in data:
                continue
            value = str(data.get(col) or '').strip()
            if store.taken(col, value, skip=skip):
                return jsonify({'error': wa._t(key, value)}), 409
        return None

    @app.route('/api/v1/orgs', methods=['POST'])
    @edit_req
    def api_org_create():
        store = _store()
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': wa._t('orgs_name_required')}), 400
        # La abreviatura también: es lo que se pinta en una chapa y en un alzado, donde el nombre
        # legal no entra. Sin ella, esos sitios enseñan un hueco — y un hueco en un alzado
        # compartido entre sociedades es exactamente la pregunta que el alzado venía a contestar.
        short = str(data.get('short') or '').strip()
        if not short:
            return jsonify({'error': wa._t('orgs_short_required')}), 400
        campos = {'name': name, 'short': short,
                  'description': str(data.get('description') or '')}
        taken = _free(store, campos)
        if taken is not None:
            return taken
        try:
            uid = store.orgs.create(campos, actor=_actor())
        except Exception:                       # pylint: disable=broad-except
            # The backstop: another request fits between the check and the INSERT, and what the
            # index answers then is not something a person can be shown.
            return jsonify({'error': wa._t('orgs_name_taken', name)}), 409
        return jsonify({'uid': uid})

    @app.route('/api/v1/orgs/<uid>', methods=['PUT'])
    @edit_req
    def api_org_update(uid):
        store = _store()
        if not store.orgs.get(uid):
            return jsonify({'error': wa._t('orgs_not_found')}), 404
        data = request.get_json(silent=True) or {}
        if 'name' in data and not str(data.get('name') or '').strip():
            return jsonify({'error': wa._t('orgs_name_required')}), 400
        # Sólo si viene: un PUT que corrige la descripción no manda la abreviatura, y exigirla
        # ahí sería pedir que se confirme un dato que quien escribe no está mirando.
        if 'short' in data and not str(data.get('short') or '').strip():
            return jsonify({'error': wa._t('orgs_short_required')}), 400
        taken = _free(store, data, skip=uid)
        if taken is not None:
            return taken
        try:
            store.orgs.update(uid, data, actor=_actor())
        except Exception:                       # pylint: disable=broad-except
            return jsonify({'error': wa._t('orgs_name_taken',
                                            str(data.get('name') or ''))}), 409
        return jsonify({'ok': True})

    @app.route('/api/v1/orgs/<uid>', methods=['DELETE'])
    @edit_req
    def api_org_delete(uid):
        """Remove a company, and every ownership that named it.

        Both, or the rows outlive the company and the resolver returns a uid nothing can be
        looked up by — a thing that belongs to a name nobody can read. What was hers is not
        deleted: it goes back to unclaimed, which is where an installation starts.
        """
        store = _store()
        row = store.orgs.get(uid) or {}
        if not row:
            return jsonify({'error': wa._t('orgs_not_found')}), 404
        store.forget_org(uid)
        store.orgs.delete(uid)
        wa._audit('org_deleted', detail={'uid': uid, 'name': str(row.get('name') or '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/orgs/owner', methods=['POST'])
    @edit_req
    def api_org_set_owner():
        """Say whose something is. An empty ``org_uid`` stops saying, which is back to
        inheriting — a different state from "owned by nobody"."""
        store = _store()
        data = request.get_json(silent=True) or {}
        scope = str(data.get('scope') or '')
        uid = str(data.get('uid') or '')
        if not uid or not org_scopes.known(scope):
            return jsonify({'error': wa._t('orgs_bad_scope')}), 400
        org = str(data.get('org_uid') or '')
        if org and not store.orgs.get(org):
            return jsonify({'error': wa._t('orgs_not_found')}), 404
        store.set_owner(scope, uid, org, actor=_actor())
        wa._audit('org_owner_set', detail={'scope': scope, 'uid': uid,
                                           'org': org, 'cleared': not org})
        return jsonify({'ok': True})

    _ = (api_orgs, api_org_create, api_org_update, api_org_delete, api_org_set_owner)
