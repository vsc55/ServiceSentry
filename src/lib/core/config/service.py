#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free config-save operations — the planning, merging, locked-field enforcement and
validation extracted from :mod:`lib.core.config.routes`.

Everything here is a pure function over plain dicts and leans on the central registry
(:mod:`lib.config.spec`) for the per-field rules — it does not duplicate them.  The route
owns request parsing, the requester-context guards (admin-only / ipban permissions),
persistence, the runtime side-effects (setattr on ``wa``, ProxyFix, service pokes) and
audit.  Validation failures raise :class:`~lib.core.users.service.AdminOpError`.
"""

from __future__ import annotations

import copy
import ipaddress
import re

from lib.config.spec import (
    CFG_BY_PATH, int_rules, bool_rules, json_dict_fields, normalize_url, cfg_validate,
    cfg_default, cfg_meta, frontend_schema,
)
from lib.i18n import SUPPORTED_LANGS
from lib.core.users.service import AdminOpError

# Materialized rule dicts derived from the central registry (edit spec.CONFIG_FIELDS, not
# this file).  This is config *data*, not route logic — it lives here so the route (runtime
# apply), the validator below and app.py (bootstrap coercion) share one source.
#   INT_RULES  {path: {min, max, attr[, flask_cfg]}}
#   BOOL_RULES {path: attr}  (attr may be None when not mirrored on wa)
INT_RULES = int_rules()
BOOL_RULES = bool_rules()
JSON_DICT_FIELDS = json_dict_fields()

# IP-address config fields (authoritative server-side check, mirrors the frontend
# ``meta.ipkind``).  ``'ip'`` = a bind address, IPv4/IPv6 only (no mask); ``'cidr'``
# = an IPv4/IPv6 address OR a CIDR network (192.168.0.0/24, 2001:db8::/32).  The
# list-valued fields are comma/space/newline separated; ``web_admin|host`` is a
# single value.
IP_FIELDS = {
    'web_admin|host': 'ip',
    'syslog|bind_host': 'ip',
    'syslog|allowed_sources': 'cidr',
}


def _ip_token_ok(token, kind) -> bool:
    """True if ``token`` is a valid IP (kind 'ip') or IP/CIDR (kind 'cidr')."""
    token = token.strip().strip('[]')          # tolerate bracketed IPv6
    if not token:
        return False
    try:
        if kind == 'cidr' and '/' in token:
            ipaddress.ip_network(token, strict=False)
        else:
            ipaddress.ip_address(token)
        return True
    except ValueError:
        return False


# ── planning ─────────────────────────────────────────────────────────────────────
def incoming_paths(data: dict) -> tuple[set, set]:
    """Return ``(sections, field_paths)`` present in a save body — handling both the
    legacy nested format and the versioned ``{"fields": {...}}`` format.  Used by the
    route to apply the admin-only / ipban requester guards."""
    sections: set[str] = set()
    fields: set[str] = set()
    raw_fields = data.get('fields')
    if isinstance(raw_fields, dict):
        for path in raw_fields:
            sections.add(path.split('|')[0])
            fields.add(path)
    else:
        for key, val in data.items():
            sections.add(key.split('|')[0])
            if isinstance(val, dict):
                for fname in val:
                    fields.add(f'{key}|{fname}')
            else:
                fields.add(key)
    return sections, fields


def plan_save(data: dict, field_versions: dict, old_data: dict) -> tuple[dict, dict, bool]:
    """Flatten a save body to ``(to_apply, conflicts, legacy_mode)``.

    ``to_apply`` maps ``"section|field"`` → value for every field that should be written;
    ``conflicts`` maps a path → ``{server_value, server_version}`` for a field whose
    submitted version token no longer matches the stored one (versioned mode only)."""
    fields = data.get('fields')
    legacy_mode = not (isinstance(fields, dict) and fields)
    to_apply: dict = {}
    conflicts: dict = {}
    if legacy_mode:
        for key, value in data.items():
            if isinstance(value, dict):
                for field_name, fval in value.items():
                    to_apply[f"{key}|{field_name}"] = fval
            elif value is not None:
                to_apply[key] = value
        return to_apply, conflicts, True

    for path, info in fields.items():
        if not isinstance(info, dict) or 'value' not in info:
            continue
        submitted_version = info.get('version')
        current_version = field_versions.get(path)
        # No stored version yet means this field was never written by the new system —
        # always allow (first save after upgrade).
        if current_version is None or submitted_version == current_version:
            to_apply[path] = info['value']
        else:
            parts = path.split('|', 1)
            section, field = parts[0], parts[1] if len(parts) > 1 else None
            server_val = (old_data.get(section) or {}).get(field) if field else None
            conflicts[path] = {
                'server_value': server_val,
                'server_version': current_version,
            }
    return to_apply, conflicts, False


def merge_config(old_data: dict, to_apply: dict) -> dict:
    """Deep-copy *old_data* and overlay *to_apply* (``"section|field"`` → value),
    returning the merged config."""
    new_data = copy.deepcopy(old_data)
    for path, value in to_apply.items():
        parts = path.split('|', 1)
        section, field = parts[0], parts[1] if len(parts) > 1 else None
        if field:
            new_data.setdefault(section, {})[field] = value
        else:
            new_data[section] = value
    return new_data


def enforce_locked(new_data: dict, old_data: dict, locked) -> None:
    """Restore locked fields (env-var / config.json read-only layers) to their original
    effective values so an edit to them is never persisted.  Mutates *new_data* in place."""
    for path in locked:
        section, field = path.split('|')
        sec_new = new_data.get(section)
        if not isinstance(sec_new, dict):
            continue
        sec_old = old_data.get(section)
        if isinstance(sec_old, dict) and field in sec_old:
            sec_new[field] = sec_old[field]
        elif field in sec_new:
            del sec_new[field]


# ── validation ───────────────────────────────────────────────────────────────────
def validate_config(new_data: dict) -> None:
    """Validate the merged config and normalise ``public_url`` in place.  Raises
    :class:`AdminOpError` (i18n key + args) on the first violation.  Per-field type/range
    and JSON-dict checks defer to :func:`lib.config.spec.cfg_validate`; the cross-field and
    IP/CIDR rules that the registry doesn't cover live here."""
    # Integer fields (type + [min, max] range) via the registry.
    for path, rule in INT_RULES.items():
        section, field = path.split('|')
        sec_data = new_data.get(section)
        if not isinstance(sec_data, dict) or field not in sec_data:
            continue
        _f = CFG_BY_PATH.get(path)
        if sec_data[field] is None and _f is not None and _f.nullable:
            continue                     # blank = "use the registry default" (valid)
        ok, _err = cfg_validate(path, sec_data[field])
        if not ok:
            raise AdminOpError('invalid_config_int', field, rule['min'], rule['max'])

    # JSON-dict fields (ldap|group_role_map, oidc|group_role_map).
    for path in JSON_DICT_FIELDS:
        section, field = path.split('|')
        sec_data = new_data.get(section)
        if not isinstance(sec_data, dict) or field not in sec_data:
            continue
        ok, _err = cfg_validate(path, sec_data[field])
        if not ok:
            raise AdminOpError('invalid_json_field', field)

    # table_rows_options: non-empty list of non-negative ints.
    web_data = new_data.get('web_admin')
    if isinstance(web_data, dict) and 'table_rows_options' in web_data:
        raw_ps = web_data['table_rows_options']
        if not isinstance(raw_ps, list) or len(raw_ps) == 0:
            raise AdminOpError('invalid_table_rows_options')
        for v in raw_ps:
            if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
                raise AdminOpError('invalid_table_rows_options')

    # pw_max_len must not be below pw_min_len.
    if isinstance(web_data, dict):
        pm = web_data.get('pw_min_len')
        px = web_data.get('pw_max_len')
        if (isinstance(pm, int) and not isinstance(pm, bool) and
                isinstance(px, int) and not isinstance(px, bool) and px < pm):
            raise AdminOpError('pw_max_less_than_min')

    # public_url: string, normalised, no embedded whitespace.
    if isinstance(web_data, dict) and 'public_url' in web_data:
        v = web_data.get('public_url', '')
        if not isinstance(v, str):
            raise AdminOpError('invalid_public_url')
        v = normalize_url(v)
        if v and (' ' in v or '\n' in v or '\t' in v):
            raise AdminOpError('invalid_public_url')
        web_data['public_url'] = v

    # IP / bind-address fields (single value or comma/space/newline list). Blank is
    # allowed (falls back to the registry default); any entry must be a real IP/CIDR.
    for path, kind in IP_FIELDS.items():
        section, field = path.split('|')
        sec_data = new_data.get(section)
        if not isinstance(sec_data, dict) or field not in sec_data:
            continue
        raw = sec_data[field]
        if not isinstance(raw, str):
            raise AdminOpError('invalid_ip_field', field, raw)
        tokens = [t for t in re.split(r'[,\s]+', raw) if t]
        bad = [t for t in tokens if not _ip_token_ok(t, kind)]
        if bad:
            raise AdminOpError('invalid_ip_field', field, ', '.join(bad))


def syslog_db_changed(old_data: dict, new_data: dict) -> bool:
    """True if the ``syslog_db`` section changed — the syslog DB connector is built at
    startup, so a change needs a process restart (like the system database section)."""
    return (old_data.get('syslog_db') or {}) != (new_data.get('syslog_db') or {})


# ── frontend UI metadata ─────────────────────────────────────────────────────────
def _opt_labels(keys: dict) -> dict:
    """``{option: {lang: label}}`` from ``{option: i18n key}``.

    The shape ``renderField`` already reads for a select's per-option labels. Built here so a
    select can be DECLARED rather than hand-written: the labels used to live inside the JS that
    drew each of these controls, which is what made writing them by hand look necessary.
    """
    from lib.i18n import SUPPORTED_LANGS, TRANSLATIONS  # noqa: PLC0415
    return {
        opt: {lang: TRANSLATIONS.get(lang, {}).get(key, opt) for lang in SUPPORTED_LANGS}
        for opt, key in keys.items()
    }


def build_config_schema() -> dict:
    """Assemble the field-level UI metadata for the config screen.

    Per-field type/range/default come from the central registry (``frontend_schema()``);
    this only layers the UI-specific extras — option lists, placeholder maps, ``ipkind``
    flags, PEM textareas and i18n option labels.  Pure data composition (no Flask), so the
    ``/api/v1/config/schema`` route is a one-line ``jsonify`` over it."""
    from lib.web_admin.constants import landing_pages, page_label  # noqa: PLC0415
    schema = frontend_schema()
    # Rows per table: the sizes the chooser offers, and which of them a table opens on. The
    # first is the reference for the second — `_updateConfigPageSizes` re-reads it after every
    # save, so editing the list changes what the other option can be set to.
    schema['web_admin|table_rows_options'] = {
        'int_list': True,
        'default': cfg_default('web_admin|table_rows_options'),
    }
    schema['web_admin|table_rows_default'] = {
        'options_int': list(cfg_default('web_admin|table_rows_options')),
        'default': cfg_default('web_admin|table_rows_default'),
    }
    # Four selects the panel used to draw by hand, each with its option labels written into
    # the JS. Declared here instead, so `renderField` draws them like every other option and
    # they inherit what a hand-written control kept missing — chiefly the env/file lock, whose
    # absence let an admin edit a pinned option and watch the save be discarded in silence.
    #
    # `on_change` is the one thing a select could need that the registry could not say: a
    # sibling to refresh when the value changes. The name of the function belongs to whoever
    # needs it, not to the core — same rule as a module naming its own action.
    schema['web_admin|audit_sort'] = {
        'options': ['time', 'event', 'user', 'ip'],
        'options_i18n': _opt_labels({'time': 'col_time', 'event': 'col_event',
                                     'user': 'col_user', 'ip': 'col_ip'}),
        'default': 'time',
    }
    schema['web_admin|audit_sort_dir'] = {
        'options': ['desc', 'asc'],
        'options_i18n': _opt_labels({'desc': 'sort_desc', 'asc': 'sort_asc'}),
        'default': 'desc',
        'on_change': '_applyAuditSortDir',
    }
    schema['email|provider'] = {
        **cfg_meta('email|provider'),
        'options': ['smtp', 'microsoft365', 'gmail'],
        'options_i18n': _opt_labels({'smtp': 'email_provider_smtp',
                                     'microsoft365': 'email_provider_ms365',
                                     'gmail': 'email_provider_gmail'}),
        'default': cfg_default('email|provider'),
        'on_change': '_emailProviderChanged',
    }
    schema['msteams|delivery'] = {
        **cfg_meta('msteams|delivery'),
        'options': ['activity_feed', 'bot'],
        'options_i18n': _opt_labels({'activity_feed': 'msteams_delivery_activity',
                                     'bot': 'msteams_delivery_bot'}),
        'default': cfg_default('msteams|delivery'),
        'on_change': '_msteamsDeliveryChanged',
    }
    schema['web_admin|status_lang'] = {
        'options': [''] + list(SUPPORTED_LANGS),
        'default': '',
    }
    # Default landing page: a select of every destination a user can be sent to, labelled per
    # supported language. Built from `landing_pages()`, which is the whole list — core pages
    # AND module sections, one entry per view where a section has several. It used to read the
    # core tuple only, so a module section was offered with its raw id for a name ("m365") and
    # a section with two views hid one of them behind the other.
    schema['web_admin|landing_page'] = {
        **cfg_meta('web_admin|landing_page'),
        'options': [p['id'] for p in landing_pages()],
        'options_i18n': {
            p['id']: {lang: page_label(p, lang) for lang in SUPPORTED_LANGS}
            for p in landing_pages()
        },
        'default': cfg_default('web_admin|landing_page'),
    }
    # Global notification language ('' = system default). Rendered by the unified language
    # selector in _field_render.html (key 'notif_lang') — native names + a translated Default
    # option — so `options` here is only for validation.
    schema['notifications|lang'] = {
        'options': [''] + list(SUPPORTED_LANGS),
        'default': '',
    }
    # Allowed iframe origins (CSP frame-ancestors): a removable-chips input — each origin
    # is added on Enter — rather than one free-text string. Stored space-separated (the
    # backend splits on comma/whitespace), same as syslog|allowed_sources.
    schema['web_admin|frame_ancestors'] = {**cfg_meta('web_admin|frame_ancestors'),
                                           'multi': True}
    schema['global|log_level'] = {
        'options': ['off', 'debug', 'info', 'warning', 'error'],
        'default': cfg_default('global|log_level'),
    }
    # modules section: not web_admin-instance-backed, so expose its registry metadata
    # (type/default/min/max) here so the UI knows the source-of-truth defaults and ranges.
    schema['modules|threads'] = cfg_meta('modules|threads')
    schema['modules|timeout'] = cfg_meta('modules|timeout')
    # Both live in one "Default roles" card; each renders with a path-specific label
    # (labels['users|default_role'] / labels['groups|default_role'] in the lang files).
    schema['users|default_role'] = cfg_meta('users|default_role')
    schema['groups|default_role'] = cfg_meta('groups|default_role')
    # database / syslog_db: the engine renders as a select of the supported drivers; the
    # port is driver-specific (blank ⇒ the connector's 5432/3306 default) so it carries a
    # hint + range.
    _DB_DRIVERS = ['sqlite', 'postgresql', 'mysql', 'mariadb']
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
    # Syslog listener numeric fields: blank = use the registry default (shown as the
    # placeholder), so clearing one never auto-fills the previous value.
    for _p in ('syslog|udp_port', 'syslog|tcp_port', 'syslog|tls_port',
               'syslog|retention_days', 'syslog|max_messages'):
        schema[_p] = {**cfg_meta(_p), 'nullable': True}
    # Sender allowlist renders as a removable-chips list; each entry must be a valid
    # IPv4/IPv6 address OR a CIDR network (192.168.0.0/24, 2001:db8::/32).
    schema['syslog|allowed_sources'] = {
        **cfg_meta('syslog|allowed_sources'), 'multi': True, 'ipkind': 'cidr'}
    # Bind addresses: a chips list so the receiver can listen on several interfaces (IPv4
    # and/or IPv6); blank = all IPv4 (0.0.0.0). Each entry is a plain bind address (no CIDR).
    schema['syslog|bind_host'] = {
        **cfg_meta('syslog|bind_host'), 'multi': True, 'ipkind': 'ip'}
    # Web panel bind address: a single IPv4/IPv6 the HTTP server listens on (0.0.0.0 = all
    # IPv4); validated as an IP, no CIDR.
    schema['web_admin|host'] = {**cfg_meta('web_admin|host'), 'ipkind': 'ip'}
    # Recipient lists render as removable chips (type an address, Enter adds it; paste a
    # comma list to add several) with a typeahead (`suggest: 'recipients'`) over panel
    # users' emails and groups. A group is stored as the token `group:<uid>` and expanded
    # to its members' emails on send (RecipientResolver). Stored as a comma-joined string —
    # the channels split it on comma/semicolon (email _parse_recipients, msteams).
    schema['email|recipients'] = {
        **cfg_meta('email|recipients'), 'multi': True, 'suggest': 'recipients'}
    schema['msteams|recipients'] = {
        **cfg_meta('msteams|recipients'), 'multi': True, 'suggest': 'recipients'}
    schema['telegram|chat_id'] = {'numericString': True}
    schema['web_admin|role_modal_scrollable'] = {'type': 'bool', 'default': True}
    # SAML2 certificate / private-key fields render as multiline textareas so a PEM block
    # pastes with its line breaks intact (a single-line input would mangle it).
    for _pem, _ph in (('saml2|sp_cert',  '-----BEGIN CERTIFICATE-----'),
                      ('saml2|sp_key',   '-----BEGIN PRIVATE KEY-----'),
                      ('saml2|idp_cert', '-----BEGIN CERTIFICATE-----')):
        schema[_pem] = {**schema.get(_pem, {}),
                        'textarea': True, 'rows': 6, 'placeholder': _ph}
    return schema


def database_size(conn) -> int | None:
    """Bytes the database currently occupies, or ``None`` when the engine will not say.

    Asked before and after a maintenance run so the result can state what it reclaimed.
    "Compacted" on its own is a claim nobody can check, and finding out whether there WAS
    anything to reclaim is most of the reason to run it.

    Each engine is asked its own way, and ``None`` is a real answer rather than a failure:
    a managed PostgreSQL can refuse ``pg_database_size`` to a non-superuser, and the action
    still succeeded — it just cannot report a number. Callers must treat it as unknown, never
    as zero, which would read as "freed nothing".
    """
    kind = getattr(conn, 'KIND', '')
    try:
        if kind == 'sqlite':
            path = getattr(conn, '_path', '')
            if not path or path == ':memory:':
                return None
            import os  # noqa: PLC0415
            # The WAL and shared-memory files are part of what the database occupies on disk;
            # counting only the main file would report a drop that merely moved into the WAL.
            total = 0
            for suffix in ('', '-wal', '-shm'):
                try:
                    total += os.path.getsize(path + suffix)
                except OSError:
                    pass
            return total or None
        if kind == 'mysql':
            row = conn.fetchone(
                'SELECT COALESCE(SUM(data_length + index_length), 0) '
                'FROM information_schema.tables WHERE table_schema = DATABASE()')
            return int(row[0]) if row and row[0] is not None else None
        if kind == 'postgresql':
            row = conn.fetchone('SELECT pg_database_size(current_database())')
            return int(row[0]) if row and row[0] is not None else None
    except Exception:  # pylint: disable=broad-except
        return None
    return None


def summarize_run(results, known_tables, max_listed: int = 100) -> dict:
    """Fold a per-table run into what is worth keeping: the counts, and the names on each side.

    *results* is what the browser watched — ``[{table, ok, error}]``. The server answers one
    table per request and keeps nothing between them, so the client is the only witness to
    the run as a whole. That makes this a CLAIM, not a measurement, and it is checked into
    shape rather than stored as it arrived:

    * a table name that this operation could not have walked is dropped — the audit log is
      not a place anyone gets to write arbitrary strings into;
    * errors are truncated, and each list stops at *max_listed*.

    Both sides are named, not just the failures: "33 of 33" answers a question nobody asked,
    and on a clean run the counts alone left the entry with nothing in it to read. What the
    reader wants is WHICH tables the run covered.

    ``max_listed=0`` turns the NAMES off and keeps the counts — for an operator who wants the
    entry to stay small. The counts are never dropped: they are the part that says the run
    happened and how it went, and an entry without them would record nothing at all.

    *max_listed* is a PARAMETER rather than a constant so the caller can hand it the
    configured value (``web_admin|audit_detail_max_items``) — this module is Flask-free and
    reads no config of its own. The default only matters to a caller that passes nothing.

    Returns ``{}`` for a run that reported nothing, so the entry keeps the shape it had
    before per-table progress existed.
    """
    try:
        cap = max(0, int(max_listed))
    except (TypeError, ValueError):
        cap = 100
    if not isinstance(results, list) or not results:
        return {}
    allowed = set(known_tables or ())
    ok_tables, failed = [], []
    for item in results:
        if not isinstance(item, dict):
            continue
        table = str(item.get('table') or '').strip()
        if table not in allowed:
            continue
        if item.get('ok'):
            ok_tables.append(table)
        else:
            failed.append({'table': table, 'error': str(item.get('error') or '')[:200]})
    if not ok_tables and not failed:
        return {}
    out = {'tables_total': len(ok_tables) + len(failed),
           'tables_ok': len(ok_tables), 'tables_failed': len(failed)}
    # The names, not only the counts. "33 of 33" answers a question nobody asked; the entry
    # exists so that somebody can see WHICH tables the run covered and which it did not —
    # and with zero failures the counts alone left the detail showing nothing at all.
    # cap == 0 → the names are off; the counts above stay, because they are what says the run
    # happened and how it went.
    if ok_tables and cap:
        out['ok_tables'] = ok_tables[:cap]
        if len(ok_tables) > cap:
            out['ok_truncated'] = len(ok_tables) - cap
    if failed and cap:
        out['failed'] = failed[:cap]
        if len(failed) > cap:
            out['failed_truncated'] = len(failed) - cap
    return out
