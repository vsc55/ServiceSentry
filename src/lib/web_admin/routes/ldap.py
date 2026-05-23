#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LDAP routes: /api/ldap/test."""

from flask import jsonify, request, session


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')

    @app.route('/api/ldap/test', methods=['POST'])
    @config_edit_req
    def api_test_ldap():
        """Test LDAP connection and, optionally, a user's credentials."""
        from lib.web_admin.auth import ldap_auth
        if not ldap_auth.is_available():
            return jsonify({'ok': False, 'message': wa._t('ldap_unavailable')}), 200

        data = wa._optional_json()
        stored_cfg = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('ldap') or {}

        server   = (data.get('server') or stored_cfg.get('server') or '').strip()
        port     = int(data.get('port') or stored_cfg.get('port') or 389)
        use_ssl  = bool(data.get('use_ssl', stored_cfg.get('use_ssl', False)))
        timeout  = int(data.get('timeout') or stored_cfg.get('timeout') or 5)
        bind_dn  = (data.get('bind_dn') or stored_cfg.get('bind_dn') or '').strip()

        raw_pw = data.get('bind_password')
        # stored_cfg comes from _read_config_file which already decrypts sensitive values
        bind_password = stored_cfg.get('bind_password') or '' if raw_pw is None else (raw_pw or '').strip()

        if not server:
            return jsonify({'ok': False, 'message': wa._t('ldap_test_missing')}), 200

        test_username = (data.get('test_username') or '').strip()
        test_password = (data.get('test_password') or '')

        try:
            from ldap3 import Server as _Srv, Connection as _Conn, ALL as _ALL, SUBTREE as _SUBTREE
            srv  = _Srv(server, port=port, use_ssl=use_ssl, get_info=_ALL, connect_timeout=timeout)
            conn = _Conn(srv, user=bind_dn or None, password=bind_password or None,
                         auto_bind=True, receive_timeout=timeout)
            conn.unbind()
        except Exception as exc:
            wa._audit('ldap_test', session.get('username', ''), request.remote_addr,
                      detail={'server': server, 'ok': False})
            return jsonify({'ok': False, 'message': f"{wa._t('ldap_test_error')}: {exc}"})

        if not test_username:
            wa._audit('ldap_test', session.get('username', ''), request.remote_addr,
                      detail={'server': server, 'ok': True})
            return jsonify({'ok': True, 'message': wa._t('ldap_test_ok')})

        # --- User authentication test ---
        # _Srv, _Conn, _ALL, _SUBTREE already in scope from the import above
        base_dn     = (data.get('base_dn') or stored_cfg.get('base_dn') or '').strip()
        user_filter = (data.get('user_filter') or stored_cfg.get('user_filter')
                       or '(sAMAccountName={username})')
        email_attr  = (data.get('email_attr') or stored_cfg.get('email_attr') or 'mail')
        name_attr   = (data.get('name_attr') or stored_cfg.get('name_attr') or 'displayName')
        group_attr  = (data.get('group_attr') or stored_cfg.get('group_attr') or 'memberOf')

        search_filter = user_filter.replace('{username}', ldap_auth._ldap_escape(test_username))

        try:
            srv  = _Srv(server, port=port, use_ssl=use_ssl, get_info=_ALL, connect_timeout=timeout)
            conn = _Conn(srv, user=bind_dn or None, password=bind_password or None,
                         auto_bind=True, receive_timeout=timeout)
            conn.search(base_dn, search_filter, search_scope=_SUBTREE,
                        attributes=[email_attr, name_attr, group_attr])
        except Exception as exc:
            wa._audit('ldap_test', session.get('username', ''), request.remote_addr,
                      detail={'server': server, 'ok': False, 'test_user': test_username})
            return jsonify({'ok': False, 'message': f"{wa._t('ldap_test_error')}: {exc}"})

        if not conn.entries:
            conn.unbind()
            wa._audit('ldap_test', session.get('username', ''), request.remote_addr,
                      detail={'server': server, 'ok': False, 'test_user': test_username,
                              'reason': 'user_not_found'})
            return jsonify({'ok': False, 'auth_tested': True,
                            'message': wa._t('ldap_user_not_found')})

        entry   = conn.entries[0]
        user_dn = str(entry.entry_dn)

        def _val(attr_name):
            try:
                v = getattr(entry, attr_name)
                if v and hasattr(v, 'values') and v.values:
                    return str(v.values[0])
            except Exception:
                pass
            return ''

        def _vals(attr_name):
            try:
                v = getattr(entry, attr_name)
                if v and hasattr(v, 'values'):
                    return [str(x) for x in v.values]
            except Exception:
                pass
            return []

        display_name = _val(name_attr)
        email        = _val(email_attr)
        groups       = _vals(group_attr)

        if test_password:
            try:
                uc = _Conn(srv, user=user_dn, password=test_password,
                           auto_bind=True, receive_timeout=timeout)
                uc.unbind()
            except Exception:
                conn.unbind()
                wa._audit('ldap_test', session.get('username', ''), request.remote_addr,
                          detail={'server': server, 'ok': False, 'test_user': test_username,
                                  'reason': 'invalid_credentials'})
                return jsonify({'ok': False, 'auth_tested': True,
                                'message': wa._t('ldap_invalid_credentials'),
                                'display_name': display_name, 'email': email,
                                'groups': groups, 'dn': user_dn})

        conn.unbind()
        wa._audit('ldap_test', session.get('username', ''), request.remote_addr,
                  detail={'server': server, 'ok': True, 'test_user': test_username})
        return jsonify({
            'ok': True, 'auth_tested': True,
            'message': wa._t('ldap_test_ok'),
            'display_name': display_name,
            'email':        email,
            'groups':       groups,
            'dn':           user_dn,
        })

    @app.route('/api/ldap/group_lookup', methods=['POST'])
    @config_edit_req
    def api_ldap_group_lookup():
        """Look up a single group by DN and return its display name."""
        from lib.web_admin.auth import ldap_auth
        if not ldap_auth.is_available():
            return jsonify({'ok': False, 'message': wa._t('ldap_unavailable')}), 200

        data = wa._optional_json()
        stored_cfg = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('ldap') or {}

        dn      = (data.get('dn') or '').strip()
        server  = stored_cfg.get('server', '').strip()
        port    = int(stored_cfg.get('port') or 389)
        use_ssl = bool(stored_cfg.get('use_ssl', False))
        timeout = int(stored_cfg.get('timeout') or 5)
        bind_dn = stored_cfg.get('bind_dn', '').strip()
        bind_password = stored_cfg.get('bind_password') or ''

        if not dn:
            return jsonify({'ok': False, 'message': 'dn required'}), 200
        if not server:
            return jsonify({'ok': False, 'message': wa._t('ldap_test_missing')}), 200

        import re
        try:
            from ldap3 import Server as _Srv, Connection as _Conn, NONE as _NONE, BASE as _BASE
            srv  = _Srv(server, port=port, use_ssl=use_ssl, get_info=_NONE, connect_timeout=timeout)
            conn = _Conn(srv, user=bind_dn or None, password=bind_password or None,
                         auto_bind=True, receive_timeout=timeout)
            conn.search(dn, '(objectClass=*)', search_scope=_BASE, attributes=['cn', 'displayName'])
            if not conn.entries:
                conn.unbind()
                return jsonify({'ok': True, 'found': False, 'name': None})
            entry = conn.entries[0]
            name = ''
            try:
                v = entry.displayName
                if v and hasattr(v, 'values') and v.values:
                    name = str(v.values[0])
            except Exception:
                pass
            if not name:
                try:
                    v = entry.cn
                    if v and hasattr(v, 'values') and v.values:
                        name = str(v.values[0])
                except Exception:
                    pass
            if not name:
                m = re.match(r'CN=([^,]+)', dn, re.IGNORECASE)
                name = m.group(1) if m else dn
            conn.unbind()
            return jsonify({'ok': True, 'found': True, 'name': name})
        except Exception as exc:
            return jsonify({'ok': False, 'message': f"{wa._t('ldap_test_error')}: {exc}"})

    @app.route('/api/ldap/groups', methods=['POST'])
    @config_edit_req
    def api_ldap_groups():
        """List groups from the LDAP directory."""
        from lib.web_admin.auth import ldap_auth
        if not ldap_auth.is_available():
            return jsonify({'ok': False, 'message': wa._t('ldap_unavailable')}), 200

        data = wa._optional_json()
        stored_cfg = (wa._read_config_file(wa._CONFIG_FILE) or {}).get('ldap') or {}

        server  = (data.get('server') or stored_cfg.get('server') or '').strip()
        port    = int(data.get('port') or stored_cfg.get('port') or 389)
        use_ssl = bool(data.get('use_ssl', stored_cfg.get('use_ssl', False)))
        timeout = int(data.get('timeout') or stored_cfg.get('timeout') or 5)
        bind_dn = (data.get('bind_dn') or stored_cfg.get('bind_dn') or '').strip()
        base_dn = (data.get('base_dn') or stored_cfg.get('base_dn') or '').strip()

        raw_pw = data.get('bind_password')
        # stored_cfg comes from _read_config_file which already decrypts sensitive values
        bind_password = stored_cfg.get('bind_password') or '' if raw_pw is None else (raw_pw or '').strip()

        if not server:
            return jsonify({'ok': False, 'message': wa._t('ldap_test_missing')}), 200

        import re
        try:
            from ldap3 import Server as _Srv, Connection as _Conn, NONE as _NONE, SUBTREE as _SUBTREE
            # get_info=NONE skips client-side schema validation so objectClass=group
            # is sent to the server as-is rather than being rejected before the query.
            srv  = _Srv(server, port=port, use_ssl=use_ssl, get_info=_NONE, connect_timeout=timeout)
            conn = _Conn(srv, user=bind_dn or None, password=bind_password or None,
                         auto_bind=True, receive_timeout=timeout)
            _gf = ('(|(objectClass=group)(objectClass=posixGroup)'
                   '(objectClass=groupOfNames)(objectClass=groupOfUniqueNames)'
                   '(objectClass=ipausergroup))')
            conn.search(base_dn, _gf, search_scope=_SUBTREE, attributes=['cn', 'displayName'])
            groups = []
            for entry in conn.entries:
                dn = str(entry.entry_dn)
                name = ''
                try:
                    v = entry.displayName
                    if v and hasattr(v, 'values') and v.values:
                        name = str(v.values[0])
                except Exception:
                    pass
                if not name:
                    try:
                        v = entry.cn
                        if v and hasattr(v, 'values') and v.values:
                            name = str(v.values[0])
                    except Exception:
                        pass
                if not name:
                    m = re.match(r'CN=([^,]+)', dn, re.IGNORECASE)
                    name = m.group(1) if m else dn
                groups.append({'dn': dn, 'name': name})
            conn.unbind()
            groups.sort(key=lambda g: g['name'].lower())
            wa._audit('ldap_groups', session.get('username', ''), request.remote_addr,
                      detail={'server': server, 'count': len(groups)})
            return jsonify({'ok': True, 'groups': groups})
        except Exception as exc:
            wa._audit('ldap_groups', session.get('username', ''), request.remote_addr,
                      detail={'server': server, 'ok': False})
            return jsonify({'ok': False, 'message': f"{wa._t('ldap_test_error')}: {exc}"})
