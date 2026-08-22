#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP surface for SNMP — the MIB library, the profile catalogue, and asking a device.

``/api/v1/snmp/<action>``. It used to be ``/api/v1/modules/watchfuls/snmp/<action>``, which
described where the code lived rather than what the endpoint is about: compiling a MIB or
writing a device profile is not something a *check* does, and it stayed reachable only
through a module long after the module stopped owning any of it.

The pipeline is deliberately the one a watchful action already went through, because the
actions are the same functions: the client never sends back a secret it was shown masked, a
bound host is resolved server-side, and a named credential wins over inline values.
Diverging here would mean an operation behaved differently depending on which URL reached it.

``discover`` is NOT here. It finds OIDs for the field of a check, so it is a check's action
and stays with the watchful — the split is by what the operation is about, not by where the
code ended up.
"""

from __future__ import annotations

from flask import jsonify, request, session

from lib.config.spec import CFG_BY_PATH
from lib.core.modules import actions as modules_actions
from lib.core.snmp.actions import SnmpActions
from lib.core.snmp.client import SnmpClient
from lib.core.snmp.manifest import ACTIONS, READ_ONLY
from lib.core.snmp.mibs.admin import MibAdmin


class _Ops(MibAdmin, SnmpActions, SnmpClient):
    """Every operation the panel may invoke, in one namespace.

    The three are combined for the reason ``Watchful`` combines them: a profile test reaches
    for ``cls._snmp_get``, and the MIB administration for its own helpers. None of them needs
    an instance — between the three there is not one instance method left — so this is a
    lookup table, not an object.
    """


def register(app, wa):

    @app.route('/api/v1/snmp/<action>', methods=['GET', 'POST'])
    @wa._login_required
    def api_snmp_action(action):
        """Run one SNMP operation.

        Reading the library or the catalogue needs ``snmp_view``; changing either — or the
        device — needs ``snmp_manage``. Nothing else grants them: SNMP owns its own flags now,
        so an admin can hand somebody the MIB library without handing them every module.
        """
        if action not in ACTIONS:
            return jsonify({'error': wa._t('action_not_supported')}), 404
        method = getattr(_Ops, action, None)
        if method is None:
            return jsonify({'error': wa._t('action_not_found')}), 404

        perms = wa._get_session_permissions()
        read_only = action in READ_ONLY
        if (('snmp_view' if read_only else 'snmp_manage')) not in perms:
            return jsonify({'error': wa._t('access_denied')}), 403

        if request.method != 'POST':
            return jsonify(method())

        config = request.get_json(silent=True) or {}
        # Internal control fields are never client-settable.
        for _k in [k for k in config if k.startswith('__') and k.endswith('__')]:
            del config[_k]
        modules_actions.fill_from_stored_item(wa, 'snmp', config)
        modules_actions.restore_action_secrets(wa, 'snmp', config)
        # The library's own settings, from the configuration and not from the client. They
        # used to arrive in the posted module config, which meant a browser could name the
        # directories to scan and hand over a token — and meant the token had to travel to
        # the browser at all, if only as a mask.
        # `_config_section` and not a bare read: it is the one place that knows which file
        # and how, and calling the reader by hand is how this arrived with the wrong argument
        # count — swallowed by the except below, so the settings silently never applied.
        _snmp_cfg = wa._config_section('snmp')
        for _k in ('mib_dirs', 'mib_repos', 'github_token'):
            config[_k] = _snmp_cfg.get(_k, '') or ''
        config['__var_dir__'] = wa._var_dir or ''
        config['__connector__'] = getattr(wa, '_db_connector', None)
        config['__user__'] = session.get('username', '')
        host_ctx = modules_actions.resolve_host_ctx(wa, config)
        if host_ctx is not None:
            config['__host__'] = host_ctx
            modules_actions.merge_host_conn(wa, 'snmp', config, host_ctx)
        modules_actions.apply_cred_to_config(wa, config)
        modules_actions.apply_item_identities(wa, 'snmp', config)

        try:
            result = method(config)
        except Exception as exc:  # pylint: disable=broad-except
            wa._audit('snmp_action', detail={'module': 'snmp', 'action': action,
                                             'ok': False, 'message': str(exc)})
            return jsonify({'ok': False, 'message': str(exc)}), 500

        if not read_only:
            _res = result if isinstance(result, dict) else {}
            _audit_fn = getattr(_Ops, 'audit_detail', None)
            _extra = (_audit_fn(action, _res) if callable(_audit_fn)
                      else {'ok': _res.get('ok', True), 'name': f'snmp / {action}'})
            if _extra is not None:
                # What is worth recording is the operation's call; how much of it one entry
                # may hold is not, or every surface invents its own ceiling.
                _extra = modules_actions.cap_audit_lists(
                    _extra, getattr(wa, '_AUDIT_DETAIL_MAX_ITEMS',
                                    CFG_BY_PATH['web_admin|audit_detail_max_items'].default))
                # `module` is not a claim that a module ran this: it names WHOSE
                # vocabulary the audit row should read the verb from, and these actions are
                # still worded in the SNMP module's own lang file. It moves when the words do.
                wa._audit('snmp_action',
                          detail={'module': 'snmp', 'action': action, **_extra})
        return jsonify(result)
