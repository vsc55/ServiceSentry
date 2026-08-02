#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config routes: /api/v1/config (GET, PUT) with per-field version tracking, plus the
read-only UI-metadata endpoints /api/v1/config/layout and /api/v1/config/schema.

All non-HTTP logic lives in the Flask-free :mod:`lib.core.config.service` — save planning
(format/versions/merge), locked-field enforcement, validation, and the frontend UI-schema
assembly.  This module owns only the HTTP surface: request parsing, the requester-context
guards (admin-only / ipban), persistence, the runtime side-effects (``setattr`` on ``wa``,
ProxyFix, service pokes) and audit.

Routes registered by this file:

    GET    /api/v1/config               effective config + per-field versions
    GET    /api/v1/config/versions      per-field version tokens only (poll)
    GET    /api/v1/config/layout        config UI layout (sub-tabs -> cards)
    GET    /api/v1/config/schema        field-level UI metadata (min/max/opts)
    PUT    /api/v1/config               partial versioned save of edited fields
    GET    /api/v1/config/db/targets/<op>  what a run will walk (tables, or nothing when
                                        the engine cannot split the operation)
    POST   /api/v1/config/db/<op>       database maintenance: optimize | compact
"""

import uuid

from flask import jsonify, request, session

from lib.debug import DebugLevel
from lib.config.spec import CFG_BY_PATH, admin_only_fields
from lib.config.layout import config_layout
from lib.core.config import service as config_svc
from lib.core.config.service import AdminOpError
from lib.security import secret_manager
from lib.util import fmt_bytes


def register(app, wa):
    # Per-field version tokens: {path_str: uuid} updated each time a field is saved.
    if not hasattr(wa, '_field_versions'):
        wa._field_versions = {}
    if not hasattr(wa, '_CONFIG_POLL_SECS'):
        wa._CONFIG_POLL_SECS = CFG_BY_PATH['web_admin|config_poll_secs'].default
    if not hasattr(wa, '_CONFIG_UPDATE_BANNER_SECS'):
        wa._CONFIG_UPDATE_BANNER_SECS = CFG_BY_PATH['web_admin|config_update_banner_secs'].default

    config_view_req = wa._perm_required('config_view', 'config_edit')
    config_edit_req = wa._perm_required('config_edit')

    # Sections that contain external-service credentials (LDAP bind password,
    # OIDC client secret, SMTP password, etc.).  Only admins may modify them.
    _ADMIN_ONLY_SECTIONS = frozenset({'ldap', 'oidc', 'saml2', 'email', 'telegram', 'msteams'})

    # Individual security-relevant web_admin fields that, like the sensitive
    # sections above, must be admin-only — they govern account lockout, cookie
    # security, password policy, trusted-proxy handling and public exposure.
    # A non-admin with config_edit must not be able to weaken these.
    # Derived from the central registry (fields flagged admin_only=True).
    _ADMIN_ONLY_FIELDS = frozenset(admin_only_fields())

    # --- API: config.json -----------------------------------------

    @app.route('/api/v1/config', methods=['GET'])
    @config_view_req
    def api_get_config():
        """Return the effective config and per-field version tokens."""
        raw = wa._read_config_file(wa._CONFIG_FILE) or {}
        # Overlay env var values so the UI always shows what is actually in effect.
        for path, value in wa._env_override_values.items():
            section, field = path.split('|')
            raw.setdefault(section, {})[field] = value
        # Webhooks live in their own store; bundle the list (read-only) so the
        # Notifications tab can render it.  Editing still goes through /api/v1/notify/webhooks.
        from lib.core.notify.webhook import channel as _wh_channel  # noqa: PLC0415
        from lib.core.notify.msteams import channel as _ms_channel  # noqa: PLC0415
        raw['webhooks'] = _wh_channel.load(wa._notify)
        # Teams channel destinations live in their own store too — bundle read-only.
        raw['msteams_channels'] = _ms_channel.load(wa._notify)
        resp = jsonify({
            'config': secret_manager.mask_sensitive(raw, wa._secret_keys),
            'versions': dict(wa._field_versions),
        })
        resp.headers['ETag'] = f'"{wa._config_version}"'
        return resp

    @app.route('/api/v1/config/versions', methods=['GET'])
    @config_view_req
    def api_get_config_versions():
        """Lightweight poll endpoint — returns only per-field version tokens."""
        return jsonify({'versions': dict(wa._field_versions)})

    # --- API: read-only UI metadata (layout + field schema) -------

    @app.route('/api/v1/config/layout', methods=['GET'])
    @config_view_req
    def api_get_config_layout():
        """The config UI layout (sub-tabs → cards) from the central registry
        (``lib.config.layout``) — so the web admin renders the config screen from
        this single source of truth instead of hardcoding the structure."""
        return jsonify(config_layout())

    @app.route('/api/v1/config/schema', methods=['GET'])
    @config_view_req
    def api_get_config_schema():
        """Field-level UI metadata (min, max, default, option lists, …) — assembled by
        the Flask-free :func:`config_svc.build_config_schema` from the central registry."""
        return jsonify(config_svc.build_config_schema())

    @app.route('/api/v1/config', methods=['PUT'])
    @config_edit_req
    def api_save_config():
        """Partial versioned save: only write fields that were actually edited.

        Request body: ``{"fields": {"section|field": {"value": ..., "version": "uuid"}}}``

        Each field is checked against its stored version token. If the token
        matches (or the field has no stored version yet), the field is saved.
        Mismatches are returned as conflicts with the server's current value.

        Also accepts the legacy flat format ``{"section": {"field": value}}``
        for backwards compatibility with older API clients.
        """
        data, err = wa._require_json()
        if err:
            return err

        # Sensitive-section / sensitive-field guard: only admins may modify
        # external-service credentials or security-relevant web_admin fields.
        _incoming_sections, _incoming_fields = config_svc.incoming_paths(data)
        _touches_admin_only = (
            bool(_incoming_sections & _ADMIN_ONLY_SECTIONS)
            or bool(_incoming_fields & _ADMIN_ONLY_FIELDS)
        )
        wa._dbg(f"> Config PUT >> received {len(_incoming_fields)} field(s) in "
                f"{sorted(_incoming_sections)}; admin_only={_touches_admin_only}", DebugLevel.debug)
        if _touches_admin_only and not wa._is_admin_requester():
            wa._dbg("> Config PUT >> rejected: non-admin touched admin-only field", DebugLevel.warning)
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        # fail2ban settings (web_admin|ipban_*) are security-sensitive: editing them
        # needs the dedicated ipban_config_edit permission on top of config access.
        if (any(f.startswith('web_admin|ipban_') for f in _incoming_fields)
                and not wa._is_admin_requester()
                and 'ipban_config_edit' not in wa._get_session_permissions()):
            wa._dbg("> Config PUT >> rejected: no ipban_config_edit for fail2ban settings",
                    DebugLevel.warning)
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        old_data = wa._read_config_file(wa._CONFIG_FILE) or {}

        # Flatten to {path: value}, resolving per-field version conflicts.
        to_apply, conflicts, legacy_mode = config_svc.plan_save(
            data, wa._field_versions, old_data)
        wa._dbg(f"> Config PUT >> mode={'legacy' if legacy_mode else 'versioned'}; "
                f"{len(to_apply)} to apply, {len(conflicts)} conflict(s)"
                + (f" {sorted(conflicts)}" if conflicts else ""), DebugLevel.debug)
        if not legacy_mode and not to_apply:
            # All fields conflicted — nothing to write.
            wa._dbg("> Config PUT >> all fields conflicted; nothing written", DebugLevel.warning)
            return jsonify({'ok': False, 'saved': [], 'conflicts': conflicts, 'versions': {}})

        # Build merged config: current saved + fields to apply.
        new_data = config_svc.merge_config(old_data, to_apply)
        wa._dbg(f"> Config PUT >> merged config: applying {sorted(to_apply.keys())}", DebugLevel.debug)

        # Locked fields must not be persisted — restore original effective values.
        # Env vars and ``config.json`` overrides are both read-only layers.
        _locked = set(wa._env_locked) | set(getattr(wa, '_file_locked', frozenset()))
        config_svc.enforce_locked(new_data, old_data, _locked)
        if _locked:
            wa._dbg(f"> Config PUT >> locked enforced (env+file): {sorted(_locked)}", DebugLevel.debug)

        wa._dbg("> Config PUT >> validating fields", DebugLevel.debug)
        try:
            config_svc.validate_config(new_data)
        except AdminOpError as e:
            wa._dbg(f"> Config PUT >> reject: {e.key} {e.args}", DebugLevel.warning)
            return jsonify({'error': wa._t(e.key, *e.args)}), 400

        wa._dbg("> Config PUT >> validation passed; restoring masked secrets, "
                "encrypting + writing editable layer to DB", DebugLevel.debug)
        secret_manager.restore_sensitive(new_data, old_data, keys=wa._secret_keys)

        if wa._write_config(new_data, actor=session.get('username', '')):
            wa._dbg(f"> Config >> saved {len(to_apply)} field(s): "
                    f"{sorted(to_apply.keys())}", DebugLevel.info)
            wa._dbg("> Config PUT >> file written; applying runtime values", DebugLevel.debug)
            # Apply the saved config to the running instance: runtime attributes (shared
            # with boot) + save-only side-effects (log level, cache, service pokes, restart
            # flags on port/proxy/syslog_db change, ProxyFix rebuild). Flask-/wa-coupled, so
            # it lives on WebAdmin, not in the Flask-free config service.
            wa._apply_config_on_save(old_data, new_data, to_apply)
            changes = wa._diff_dicts(old_data, new_data, sensitive=wa._sensitive_fields)
            # Only audit a save that actually changed something — a no-op save (e.g.
            # the SCIM wizard re-saving an unchanged token) would otherwise clutter the
            # log with blank-detail entries.
            if changes:
                wa._audit('config_saved', detail=changes)
            wa._config_version = str(uuid.uuid4())
            if wa._restart_pending:
                wa._dbg("> Config PUT >> restart_pending set (port/proxy changed)", DebugLevel.debug)

            # Update per-field version tokens for every saved field.
            new_token = str(uuid.uuid4())
            for path in to_apply:
                wa._field_versions[path] = new_token
            saved_versions = {p: new_token for p in to_apply}

            wa._dbg(f"> Config PUT >> done: {len(to_apply)} saved, {len(conflicts)} conflict(s), "
                    f"config_version={wa._config_version[:8]}", DebugLevel.debug)
            resp = jsonify({
                'ok': len(conflicts) == 0,
                'saved': list(to_apply.keys()),
                'conflicts': conflicts,
                'versions': saved_versions,
            })
            resp.headers['ETag'] = f'"{wa._config_version}"'
            return resp

        wa._dbg("> Config PUT >> save_file_error: write failed", DebugLevel.error)
        return jsonify({'error': wa._t('save_file_error')}), 500

    # --- API: database maintenance --------------------------------

    # The two halves of maintenance, kept apart because they cost wildly different things:
    # `optimize` refreshes the statistics the query planner reads and touches no storage;
    # `compact` rewrites it to hand free space back to the filesystem and can hold the
    # database for as long as that takes. Offering only the combined operation would mean the
    # cheap, safe one could never be run on its own — which is the one worth running often.
    _DB_OPS = {
        'optimize': ('optimize', 'db_optimized'),
        'compact':  ('compact',  'db_compacted'),
    }

    @app.route('/api/v1/config/db/targets/<op>', methods=['GET'])
    @wa._perm_required('db_maintenance')
    def api_db_targets(op):
        """What the run will walk, in the order it will walk it.

        The ENGINE decides the shape: a table per row where the statement works per table,
        and nothing at all where it does not — SQLite's VACUUM is one indivisible rewrite of
        the file, and reporting it as thirty-three tables would invent a granularity the
        engine does not have, making every tick a claim about work that had not finished.
        `divisible: false` is how the client knows to show a single row for the database
        itself instead of a list.

        Asked from the catalog rather than from the TableSpec declarations: what matters is
        what the database actually contains — a module table created at runtime is as real as
        a declared one, and a list that omitted it would tick to the end with work left.
        """
        if op not in _DB_OPS:
            return jsonify({'error': wa._t('db_maintenance_unknown_op')}), 400
        conn = getattr(wa, '_db_connector', None)
        if conn is None:
            return jsonify({'error': wa._t('db_not_available')}), 503
        targets = conn.maintenance_targets(op)
        return jsonify({'op': op, 'targets': targets, 'divisible': bool(targets)})

    @app.route('/api/v1/config/db/<op>', methods=['POST'])
    @wa._perm_required('db_maintenance')
    def api_db_maintenance(op):
        """Run one maintenance operation against the main database.

        The operation is looked up in a fixed table rather than called by name off the
        connector: `op` arrives from the URL, and `getattr(connector, op)` would turn this
        endpoint into a way to invoke any method the connector has.
        """
        entry = _DB_OPS.get(op)
        if not entry:
            return jsonify({'error': wa._t('db_maintenance_unknown_op')}), 400
        method, event = entry
        conn = getattr(wa, '_db_connector', None)
        if conn is None:
            return jsonify({'error': wa._t('db_not_available')}), 503

        # One table at a time, so the UI can show a tick that means THAT table finished
        # rather than a bar that means time passed. Only `optimize` takes it: analyzing one
        # table is cheap and independent, while a compaction is one rewrite of the whole
        # store on two of the three engines.
        body = request.get_json(silent=True) or {}
        table = str(body.get('table') or '').strip()
        if table:
            # Checked against what THIS operation can actually be split into, never trusted.
            # The name is interpolated into SQL (an identifier cannot be a bound parameter),
            # so accepting whatever arrived would be an injection point — quoting is not an
            # argument for skipping the check, it is the reason the check has to decide.
            # Asking `maintenance_targets` rather than `list_tables` also refuses a per-table
            # request for an operation the engine cannot divide: on SQLite a per-table
            # "compact" would silently rewrite the WHOLE database once per table.
            if table not in conn.maintenance_targets(op):
                return jsonify({'error': wa._t('db_table_unknown')}), 400

        size_before = None if table else config_svc.database_size(conn)
        try:
            getattr(conn, method)(table) if table else getattr(conn, method)()
        except Exception as exc:  # pylint: disable=broad-except
            wa._dbg(f'> DB >> {op} failed: {type(exc).__name__}: {exc}', DebugLevel.error)
            wa._audit(event, detail={'ok': False, 'table': table, 'error': str(exc)[:500]})
            return jsonify({'error': f'{wa._t("db_maintenance_failed")}: {exc}'}), 500
        # A per-table step reports no sizes and writes no audit entry of its own: the run is
        # ONE operator action, and one row per table would bury the record it belongs to.
        # The client closes the run with a final call carrying no table.
        if table:
            return jsonify({'ok': True, 'operation': op, 'table': table})
        size_after = config_svc.database_size(conn)

        # Audited like any other operator action, and with the numbers: "compacted" without
        # a before and after is a claim nobody can check, and the whole reason to run it is
        # to find out whether there was anything to reclaim.
        detail = {'ok': True, 'operation': op}
        freed = None
        if size_before is not None and size_after is not None:
            freed = max(0, size_before - size_after)
            detail.update({'bytes_before': size_before, 'bytes_after': size_after,
                           'bytes_freed': freed})
        # What each table reported. The per-table steps deliberately write no entry each, so
        # without this the record of a thirty-three table run is the word "ok" — true, and
        # useless to anyone asking WHICH table failed.
        #
        # It comes from the client because only the client watched the whole run; the server
        # answers one table per request and keeps nothing between them. So it is treated as a
        # claim and checked into shape: table names must be ones this operation could actually
        # have walked, and the errors are truncated. What it cannot be is a way to write
        # arbitrary text into the audit log.
        detail.update(config_svc.summarize_run(
            body.get('results'), conn.maintenance_targets(op),
            getattr(wa, '_AUDIT_DETAIL_MAX_ITEMS',
                    CFG_BY_PATH['web_admin|audit_detail_max_items'].default)))
        wa._audit(event, detail=detail)
        # Formatted HERE, by the formatter the rest of the panel already uses. The browser
        # would need its own to render this, and a second implementation of "bytes as a
        # human reads them" is a second answer to the same question: fmt_bytes scales in
        # 1024s, so a JS version counting in 1000s would print a different size for the same
        # number depending on which side of the wire formatted it.
        return jsonify({'ok': True, 'operation': op,
                        'bytes_before': size_before, 'bytes_after': size_after,
                        'bytes_freed': freed,
                        'freed_human': fmt_bytes(freed) if freed is not None else None})
