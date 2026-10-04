#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""External syslog sources API: /api/v1/syslog/sources* — other programs' log databases.

Routes registered by this file:

    GET    /api/v1/syslog/sources              what the selector offers THIS user
    GET    /api/v1/syslog/sources/config       every source, password masked (Configuration)
    POST   /api/v1/syslog/sources              add one
    PUT    /api/v1/syslog/sources/<uid>        replace one (a null password keeps the stored one)
    DELETE /api/v1/syslog/sources/<uid>        remove one, and the per-source grants with it
    POST   /api/v1/syslog/sources/test         try a connection (saved or not) once

Reading a source's messages is the ordinary syslog API with ``?src=<uid>``
(:mod:`lib.services.syslog.routes`).
"""

from flask import jsonify, request, session

from lib.security import secret_manager
from lib.services.syslog import sources as _sources
from lib.services.syslog.store.sources import DRIVERS, clean_conn

_NETWORK = ('mysql', 'mariadb', 'postgresql')


def _payload(data: dict, stored: dict | None = None) -> dict:
    """A request body as the store's shape; a null/absent password keeps *stored*'s."""
    conn = clean_conn(data.get('data'))
    if conn.get('password') in (None, '') and stored:
        conn['password'] = (stored.get('data') or {}).get('password') or ''
    return {
        'name': str(data.get('name') or '').strip()[:80],
        'enabled': data.get('enabled') is not False,
        'watch': bool(data.get('watch')),
        'time_zone': str(data.get('time_zone') or 'UTC'),
        'data': conn,
    }


def _invalid(p: dict) -> str:
    """The i18n key of what is wrong with *p*, or ''."""
    if not p['name']:
        return 'syslog_source_need_name'
    conn = p['data']
    if conn['driver'] not in DRIVERS:
        return 'syslog_source_bad_driver'
    if conn['driver'] in _NETWORK and not (conn.get('host') and conn.get('name')):
        return 'syslog_source_need_host'
    if conn['driver'] == 'sqlite' and not conn.get('path'):
        return 'syslog_source_need_path'
    return ''


def _masked(row: dict, errors: dict) -> dict:
    out = dict(row)
    out['data'] = secret_manager.mask_sensitive(dict(row.get('data') or {}))
    out['error'] = errors.get(row['uid'], '')
    return out


def register(app, wa):
    syslog_view_req = wa._perm_required('syslog_view')
    config_view_req = wa._perm_required('config_view', 'config_edit')
    config_edit_req = wa._perm_required('config_edit')

    def _registry():
        return getattr(wa, '_syslog_sources', None)

    def _store():
        reg = _registry()
        return getattr(reg, '_store', None)

    @app.route('/api/v1/syslog/sources', methods=['GET'])
    @syslog_view_req
    def api_syslog_sources():
        """The internal source, then every enabled external one this user may read."""
        out = [{'uid': _sources.INTERNAL, 'name': '', 'internal': True}]
        reg = _registry()
        if reg is not None:
            perms = wa._get_session_permissions()
            for row in reg.list():
                if row['enabled'] and _sources.may_see(row['uid'], perms):
                    out.append({'uid': row['uid'], 'name': row['name'], 'internal': False,
                                'error': reg.errors.get(row['uid'], '')})
        return jsonify({'sources': out})

    @app.route('/api/v1/syslog/sources/config', methods=['GET'])
    @config_view_req
    def api_syslog_sources_config():
        reg = _registry()
        if reg is None:
            return jsonify({'sources': []})
        return jsonify({'sources': [_masked(r, reg.errors) for r in reg.list()]})

    @app.route('/api/v1/syslog/sources', methods=['POST'])
    @config_edit_req
    def api_syslog_source_create():
        data, err = wa._require_json()
        if err:
            return err
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('not_found')}), 404
        p = _payload(data)
        bad = _invalid(p)
        if bad:
            return jsonify({'error': wa._t(bad)}), 400
        uid = store.create(p, actor=session.get('username', ''))
        if not uid:
            return jsonify({'error': wa._t('syslog_source_name_taken')}), 409
        _registry().invalidate()
        wa._audit('syslog_source_created', detail={'uid': uid, 'name': p['name'],
                                                   'driver': p['data']['driver']})
        return jsonify({'ok': True, 'uid': uid}), 201

    @app.route('/api/v1/syslog/sources/<uid>', methods=['PUT'])
    @config_edit_req
    def api_syslog_source_update(uid):
        data, err = wa._require_json()
        if err:
            return err
        store = _store()
        stored = store.get(uid) if store is not None else None
        if stored is None:
            return jsonify({'error': wa._t('not_found')}), 404
        p = _payload(data, stored)
        bad = _invalid(p)
        if bad:
            return jsonify({'error': wa._t(bad)}), 400
        if not store.update(uid, p, actor=session.get('username', '')):
            return jsonify({'error': wa._t('syslog_source_name_taken')}), 409
        _registry().invalidate()
        changes = [k for k in ('name', 'enabled', 'watch', 'time_zone') if stored[k] != p[k]]
        if {k: v for k, v in stored['data'].items() if k != 'password'} != \
                {k: v for k, v in p['data'].items() if k != 'password'}:
            changes.append('connection')
        if (stored['data'].get('password') or '') != (p['data'].get('password') or ''):
            changes.append('password')
        wa._audit('syslog_source_updated', detail={'uid': uid, 'name': p['name'],
                                                   'changes': changes})
        return jsonify({'ok': True})

    @app.route('/api/v1/syslog/sources/<uid>', methods=['DELETE'])
    @config_edit_req
    def api_syslog_source_delete(uid):
        store = _store()
        stored = store.get(uid, decrypt=False) if store is not None else None
        if stored is None or not store.delete(uid):
            return jsonify({'error': wa._t('not_found')}), 404
        _registry().invalidate()
        # A grant to a source that no longer exists reads as one that might come back.
        wa._purge_scoped_permissions('syslogsrc', [uid])
        wa._audit('syslog_source_deleted', detail={'uid': uid, 'name': stored['name']})
        return jsonify({'ok': True})

    @app.route('/api/v1/syslog/sources/test', methods=['POST'])
    @config_edit_req
    def api_syslog_source_test():
        """Connect once with the form as it stands — saved or not. A blank password on a
        saved source means its stored one, as on save."""
        data, err = wa._require_json()
        if err:
            return err
        store = _store()
        stored = store.get(str(data.get('uid') or '')) if (store and data.get('uid')) else None
        p = _payload(data, stored)
        bad = _invalid({**p, 'name': p['name'] or '-'})
        if bad:
            return jsonify({'ok': False, 'error': wa._t(bad)}), 400
        return jsonify(_sources.probe(p, getattr(_registry(), 'credentials', None)))
