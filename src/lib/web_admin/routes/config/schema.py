#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config schema route: /api/v1/config/schema (field-level UI metadata)."""

from flask import jsonify

from ...constants import SUPPORTED_LANGS
from lib.config.spec import cfg_default, cfg_meta, frontend_schema
from lib.config.layout import config_layout


def register(app, wa):
    config_view_req = wa._perm_required('config_view', 'config_edit')

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
        """Return field-level metadata (min, max, default) for config fields.

        The per-field type/range/default come from the central registry
        (``frontend_schema()``); only UI-specific extras — option lists, the
        numeric-string flag and pure frontend prefs — are added here.
        """
        schema = frontend_schema()
        schema['web_admin|default_page_size'] = {
            'options_int': [25, 50, 100, 200, 0],
            'default': cfg_default('web_admin|default_page_size'),
        }
        schema['web_admin|audit_sort'] = {
            'options': ['time', 'event', 'user', 'ip'],
            'default': 'time',
        }
        schema['web_admin|audit_sort_dir'] = {
            'options': ['desc', 'asc'],
            'default': 'desc',
        }
        schema['web_admin|status_lang'] = {
            'options': [''] + list(SUPPORTED_LANGS),
            'default': '',
        }
        schema['email|lang'] = {
            'options': [''] + list(SUPPORTED_LANGS),
            'default': '',
        }
        schema['global|log_level'] = {
            'options': ['off', 'debug', 'info', 'warning', 'error'],
            'default': cfg_default('global|log_level'),
        }
        # modules section: not web_admin-instance-backed, so expose its registry
        # metadata (type/default/min/max) here so the UI knows the source-of-truth
        # defaults and ranges (no hardcoded values in the frontend).
        schema['modules|threads'] = cfg_meta('modules|threads')
        schema['modules|timeout'] = cfg_meta('modules|timeout')
        # Both live in one "Default roles" card; each renders with a path-specific
        # label (labels['users|default_role'] / labels['groups|default_role'] in the
        # lang files) so they don't both show the bare 'default_role' label.
        schema['users|default_role'] = cfg_meta('users|default_role')
        schema['groups|default_role'] = cfg_meta('groups|default_role')
        # database / syslog_db: the engine renders as a select of the supported
        # drivers; the port is driver-specific (blank ⇒ the connector's
        # 5432/3306 default) so it carries a hint + range.
        _DB_DRIVERS = ['sqlite', 'postgresql', 'mysql', 'mariadb']
        # The port placeholder shows the engine's default (live-keyed by driver);
        # blank stores null so the connector uses that default.
        _DB_PORT_DEFAULTS = {'postgresql': 5432, 'mysql': 3306, 'mariadb': 3306}
        schema['database|driver'] = {**cfg_meta('database|driver'), 'options': _DB_DRIVERS}
        schema['database|port'] = {
            **cfg_meta('database|port'), 'min': 1, 'max': 65535, 'nullable': True,
            'placeholder_map_field': 'driver', 'placeholder_map': _DB_PORT_DEFAULTS,
        }
        schema['syslog_db|driver'] = {**cfg_meta('syslog_db|driver'), 'options': _DB_DRIVERS}
        schema['syslog_db|port'] = {
            **cfg_meta('syslog_db|port'), 'min': 1, 'max': 65535, 'nullable': True,
            'placeholder_map_field': 'driver', 'placeholder_map': _DB_PORT_DEFAULTS,
        }
        # Syslog listener numeric fields: blank = use the registry default (shown as
        # the placeholder), so clearing one never auto-fills the previous value.
        for _p in ('syslog|udp_port', 'syslog|tcp_port', 'syslog|tls_port',
                   'syslog|retention_days', 'syslog|max_rows'):
            schema[_p] = {**cfg_meta(_p), 'nullable': True}
        # Sender allowlist renders as a removable-chips list; each entry must be a
        # valid IPv4/IPv6 address OR a CIDR network (192.168.0.0/24, 2001:db8::/32).
        schema['syslog|allowed_sources'] = {
            **cfg_meta('syslog|allowed_sources'), 'multi': True, 'ipkind': 'cidr'}
        # Bind addresses: a chips list so the receiver can listen on several
        # interfaces (IPv4 and/or IPv6); blank = all IPv4 (0.0.0.0). Each entry is a
        # plain bind address (no CIDR mask).
        schema['syslog|bind_host'] = {
            **cfg_meta('syslog|bind_host'), 'multi': True, 'ipkind': 'ip'}
        # Web panel bind address: a single IPv4/IPv6 the HTTP server listens on
        # (0.0.0.0 = all IPv4); validated as an IP, no CIDR.
        schema['web_admin|host'] = {**cfg_meta('web_admin|host'), 'ipkind': 'ip'}
        schema['telegram|chat_id'] = {'numericString': True}
        schema['web_admin|role_modal_scrollable'] = {'type': 'bool', 'default': True}
        # SAML2 certificate / private-key fields render as multiline textareas so a
        # PEM block pastes with its line breaks intact (a single-line input would
        # mangle it).
        for _pem, _ph in (('saml2|sp_cert',  '-----BEGIN CERTIFICATE-----'),
                          ('saml2|sp_key',   '-----BEGIN PRIVATE KEY-----'),
                          ('saml2|idp_cert', '-----BEGIN CERTIFICATE-----')):
            schema[_pem] = {**schema.get(_pem, {}),
                            'textarea': True, 'rows': 6, 'placeholder': _ph}
        return jsonify(schema)
