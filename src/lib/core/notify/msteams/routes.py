#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Teams notification routes: /api/v1/notify/msteams*.

Channels (Incoming Webhooks) are records in their own store (CRUD below); user
delivery is configured in the ``msteams`` config section and exercised by the
user-test route.  The bot messaging endpoint (``/auth/msteams/messages``) is public
(Bot Framework-authenticated) and registered separately in ``app.py``'s route setup.

Routes registered by this file:

    GET    /api/v1/notify/msteams/channels             list channels (URL masked)
    POST   /api/v1/notify/msteams/channels             create a channel
    PUT    /api/v1/notify/msteams/channels/<cid>       update a channel
    DELETE /api/v1/notify/msteams/channels/<cid>       delete a channel
    POST   /api/v1/notify/msteams/channels/<cid>/test  send a test card to a channel
    POST   /api/v1/notify/msteams/test                 test the configured user delivery
    POST   /auth/msteams/messages                         Bot Framework inbound (external; CSRF-exempt)
"""

import uuid

from flask import Response, jsonify, request, session
from lib.config.spec import cfg_get
from lib.security import secret_manager


def _validate_channel(data: dict, *, require_url: bool = True) -> str | None:
    raw = data.get('webhook_url')
    if raw is None and not require_url:
        return None                      # keep-stored sentinel on update
    url = (raw or '').strip()
    if not url:
        return 'webhook_url is required'
    if not (url.startswith('https://') or url.startswith('http://')):
        return 'webhook_url must be an http(s) URL'
    return None


def register(app, wa):
    config_view_req = wa._perm_required('config_view', 'config_edit')
    config_edit_req = wa._perm_required('config_edit')
    from lib.core.notify.msteams import channel as _channel
    store = _channel.get_store(wa._notify)
    # The bot messaging endpoint is a Bot Framework webhook (JWT-authenticated) — CSRF-exempt.
    wa._register_csrf_exempt('/auth/msteams/messages')

    @app.route('/api/v1/notify/msteams/channels', methods=['GET'])
    @config_view_req
    def api_list_msteams():
        return jsonify({'channels': secret_manager.mask_sensitive(_channel.load(wa._notify))})

    @app.route('/api/v1/notify/msteams/channels', methods=['POST'])
    @config_edit_req
    def api_create_msteams():
        data, err = wa._require_json()
        if err:
            return err
        err_msg = _validate_channel(data)
        if err_msg:
            return jsonify({'error': err_msg}), 400
        channel = {
            'id': str(uuid.uuid4()),
            'name': (data.get('name') or '').strip() or 'Teams channel',
            'enabled': bool(data.get('enabled', True)),
            'webhook_url': (data.get('webhook_url') or '').strip(),
        }
        if store.upsert(channel, actor=session.get('username', '')):
            wa._field_versions['msteams_channels|_version'] = str(uuid.uuid4())
            wa._audit('msteams_channel_created', detail={
                'name': channel['name'], 'id': channel['id']})
            return jsonify({'ok': True, 'channel': secret_manager.mask_sensitive(channel)})
        return jsonify({'error': wa._t('save_file_error')}), 500

    @app.route('/api/v1/notify/msteams/channels/<cid>', methods=['PUT'])
    @config_edit_req
    def api_update_msteams(cid):
        data, err = wa._require_json()
        if err:
            return err
        # webhook_url == None → keep the stored URL (it's a masked secret), so don't require it.
        err_msg = _validate_channel(data, require_url=data.get('webhook_url') is not None)
        if err_msg:
            return jsonify({'error': err_msg}), 400
        stored = store.get(cid)
        if stored is None:
            return jsonify({'error': 'Not found'}), 404
        # null webhook_url = masked field, keep stored value
        url = data.get('webhook_url')
        if url is None:
            url = stored.get('webhook_url') or ''
        updated = {
            'id': cid,
            'name': (data.get('name') or stored.get('name') or 'Teams channel').strip(),
            'enabled': bool(data.get('enabled', stored.get('enabled', True))),
            'webhook_url': (url or '').strip(),
        }
        if store.upsert(updated, actor=session.get('username', '')):
            wa._field_versions['msteams_channels|_version'] = str(uuid.uuid4())
            changed = []
            for _k in ('name', 'enabled', 'webhook_url'):
                _new, _old = updated[_k], stored.get(_k)
                _same = (_new or '') == (_old or '') if isinstance(_new, str) else _new == _old
                if not _same:
                    changed.append(_k)
            if changed == ['enabled']:
                ev = 'msteams_channel_enabled' if updated['enabled'] else 'msteams_channel_disabled'
            else:
                ev = 'msteams_channel_updated'
            wa._audit(ev, detail={'name': updated['name'], 'id': cid})
            return jsonify({'ok': True, 'channel': secret_manager.mask_sensitive(updated)})
        return jsonify({'error': wa._t('save_file_error')}), 500

    @app.route('/api/v1/notify/msteams/channels/<cid>', methods=['DELETE'])
    @config_edit_req
    def api_delete_msteams(cid):
        deleted = store.get(cid)
        if deleted is None or not store.delete(cid):
            return jsonify({'error': 'Not found'}), 404
        wa._field_versions['msteams_channels|_version'] = str(uuid.uuid4())
        wa._audit('msteams_channel_deleted', detail={'id': cid, 'name': (deleted or {}).get('name', '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/notify/msteams/channels/<cid>/test', methods=['POST'])
    @config_edit_req
    def api_test_msteams_channel(cid):
        from lib.core.notify.msteams import notify as ms_notify
        stored = store.get(cid)
        if stored is None:
            return jsonify({'error': 'Not found'}), 404
        ok, msg = ms_notify.send_channel_test(stored)
        wa._audit('msteams_test_ok' if ok else 'msteams_test_fail',
                  detail={'id': cid, **({} if ok else {'error': msg})})
        return jsonify({'ok': ok, 'message': msg})

    @app.route('/api/v1/notify/msteams/test', methods=['POST'])
    @config_edit_req
    def api_test_msteams_users():
        from lib.core.notify.msteams import notify as ms_notify
        # Test the CURRENT (possibly unsaved) user-mode settings from the request body,
        # falling back to the stored section — mirrors the email/telegram test flow.
        body = wa._optional_json() or {}
        cfg = dict(wa._config_section('msteams'))
        cfg.update({k: v for k, v in body.items() if v is not None})
        # Route through the notification router (owns the Teams stores / channel access).
        ok, msg = ms_notify.send_user_test(wa._notify, cfg)
        wa._audit('msteams_test_ok' if ok else 'msteams_test_fail',
                  detail={'mode': 'users', **({} if ok else {'error': msg})})
        return jsonify({'ok': ok, 'message': msg})

    @app.route('/api/v1/notify/msteams/app-package', methods=['GET'])
    @config_view_req
    def api_msteams_app_package():
        """Download the Teams app package (manifest + icons) wired to the Graph app,
        so the admin can upload/sideload it and install it for the recipients — the
        prerequisite for activity-feed notifications."""
        from lib.core.notify.msteams import app_package
        cfg = wa._config_section('msteams')
        # client_id from the query (current, possibly unsaved) or the stored config.
        client_id = (request.args.get('client_id') or cfg.get('client_id') or '').strip()
        if not client_id:
            return jsonify({'error': wa._t('msteams_pkg_no_client')}), 400
        public_url = wa.public_base_url() if hasattr(wa, 'public_base_url') else ''
        data = app_package.build_package(client_id, public_url=public_url)
        return Response(data, mimetype='application/zip', headers={
            'Content-Disposition': 'attachment; filename="servicesentry-teams-app.zip"'})

    # ── Bot Framework inbound (public; Bot Framework-authenticated) ──────────
    # Teams POSTs an Activity here when a user interacts with the bot; we capture
    # the conversation reference so alerts can be pushed 1:1 later. NOT login-gated
    # (the path is CSRF-exempt in app.py) — every request must carry a valid Bot
    # Framework JWT (audience == the bot's app id). If PyJWT is unavailable we refuse
    # (HTTP 501) rather than trust it. Returns 404 unless bot delivery is enabled, so
    # the endpoint isn't advertised when unused.
    @app.route('/auth/msteams/messages', methods=['POST'])
    def api_msteams_bot_inbound():
        from lib.core.notify.msteams import bot_inbound
        cfg = wa._config_section('msteams')
        app_id = (cfg.get('bot_app_id') or '').strip()
        delivery = cfg_get(cfg, 'msteams|delivery', falsy=True)
        if not (cfg.get('user_enabled') and delivery == 'bot' and app_id):
            return jsonify({'error': 'Teams bot delivery is not enabled'}), 404
        store_ = _channel.get_bot_store(wa._notify)
        if store_ is None:
            return jsonify({'error': 'Teams bot store unavailable'}), 503
        try:
            bot_inbound.validate_bearer(request.headers.get('Authorization', ''), app_id)
        except bot_inbound.BotValidationUnavailable:
            return jsonify({'error': 'Teams bot endpoint requires the PyJWT package'}), 501
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({'error': f'unauthorized: {exc}'}), 401
        activity = request.get_json(silent=True) or {}
        ref = bot_inbound.reference_from_activity(activity)
        if ref.get('service_url') and ref.get('conversation_id'):
            store_.save_reference(ref)
        return jsonify({'type': 'message',
                        'text': 'ServiceSentry: you will now receive alerts here.'})
