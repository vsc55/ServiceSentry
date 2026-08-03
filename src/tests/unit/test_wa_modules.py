#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for module routes: /api/modules, /api/status, /api/overview."""

import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.modules import ModuleBase
from watchfuls.web import Watchful as WebWatchful

from tests.conftest import _login, _SAMPLE_MODULES

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── API: modules ─────────────────────────



# ──────────────────────────── API: status ──────────────────────────



# ──────────────────────────── API: overview ────────────────────────



# ──────────────────────────── Module item schemas ──────────────────

class TestModuleItemSchemas:
    """ITEM_SCHEMA declared in each watchful and discovered dynamically."""

    @pytest.fixture(autouse=True)
    def _schemas(self):
        self.schemas = ModuleBase.discover_schemas()

    # ---- discovery returns data ----
    def test_discover_returns_non_empty(self):
        assert isinstance(self.schemas, dict)
        assert len(self.schemas) > 0

    # ---- per-module checks ----
    def test_web_list_schema_has_code(self):
        """web|list schema includes the 'code', 'server' and 'port' fields."""
        schema = self.schemas.get('web|list')
        assert schema is not None
        assert 'code' in schema
        assert schema['code']['default'] == 0
        assert schema['code']['type'] == 'int'
        assert 'enabled' in schema
        assert 'url' not in schema
        assert schema['server']['type'] == 'str'
        assert schema['port']['type'] == 'int'

    def test_ping_list_schema_fields(self):
        """ping|list schema has enabled, label, host, timeout, attempt, alert."""
        schema = self.schemas['ping|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'label', 'host', 'timeout', 'attempt', 'alert'}
        assert schema['port']['min'] == 1 if 'port' in schema else True
        # Verify rich format — 0 means "inherit from module-level setting"
        assert schema['timeout']['default'] == 0
        assert schema['timeout']['type'] == 'int'
        assert schema['timeout']['min'] == 0

    def test_datastore_list_schema_fields(self):
        """datastore|list schema has all connection fields across all engines."""
        schema = self.schemas['datastore|list']
        for field in ('enabled', 'db_type', 'conn_type', 'host', 'port',
                      'user', 'password', 'db', 'socket'):
            assert field in schema
        # db_type covers all supported engines (merged: mariadb→mysql, valkey→redis, opensearch→elasticsearch)
        engines = schema['db_type']['options']
        for eng in ('mysql', 'postgres', 'mssql', 'mongodb',
                    'redis', 'elasticsearch', 'influxdb', 'memcached'):
            assert eng in engines
        for removed in ('mariadb', 'valkey', 'opensearch'):
            assert removed not in engines
        # Password is marked sensitive
        assert schema['password'].get('sensitive') is True
        # SSH fields exist
        for f in ('ssh_host', 'ssh_port', 'ssh_user', 'ssh_password', 'ssh_key'):
            assert f in schema

    def test_service_status_schema_fields(self):
        """service_status|list: enabled, label, service, expected, remediation.

        The key is an opaque UID; 'label' carries the editable display name."""
        schema = self.schemas['service_status|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'label', 'service', 'expected', 'remediation'}
        assert schema['enabled']['type'] == 'bool'
        assert schema['service']['type'] == 'str'
        assert schema['label']['type'] == 'str'
        assert schema['__check_title_field__'] == 'label'
        assert schema['__discovery_uid_key__'] is True

    def test_temperature_list_schema_fields(self):
        """temperature is host-centric: a sensor + alert per check, bound to a host."""
        schema = self.schemas['temperature|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'sensor', 'label', 'alert'}
        assert schema['alert']['type'] == 'float'
        import watchfuls.temperature as _t
        assert _t.Watchful.ITEM_SCHEMA['__host_profile__']['key'] == 'ssh'

    def test_hddtemp_list_schema_fields(self):
        """hddtemp is host-centric: the daemon address comes from the bound host."""
        schema = self.schemas['hddtemp|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'label', 'port', 'exclude', 'alert'}
        assert schema['exclude']['type'] == 'list'
        # Per-item threshold inherits the module-level default (50) when blank/0.
        assert schema['alert']['default'] == 0
        assert schema['alert']['placeholder_module'] == 'alert'
        import watchfuls.hddtemp as _h
        assert _h.Watchful.ITEM_SCHEMA['__host_profile__']['address_field'] == 'host'

    def test_raid_list_schema_fields(self):
        """raid is host-centric: the check holds only enabled/label; the SSH
        connection now comes from the bound host (__host_profile__)."""
        schema = self.schemas['raid|list']
        assert 'enabled' in schema and 'label' in schema
        for gone in ('host', 'port', 'user', 'password', 'key_file'):
            assert gone not in schema
        import watchfuls.raid as _raid
        assert _raid.Watchful.ITEM_SCHEMA['__host_profile__']['key'] == 'ssh'

    # ---- modules with __module__-level scalar fields ----
    def test_ram_swap_module_schema(self):
        """ram_swap is host-centric: thresholds live per-check in |list, and the
        check binds to a host (__host_profile__ ssh)."""
        schema = self.schemas.get('ram_swap|list')
        assert schema is not None
        assert 'alert_ram' in schema and 'alert_swap' in schema
        # Per-item default is 0 → inherits the module-level threshold (60).
        assert schema['alert_ram']['default'] == 0
        assert schema['alert_ram']['placeholder_module'] == 'alert_ram'
        assert schema['alert_ram']['min'] == 0 and schema['alert_ram']['max'] == 100
        mod_schema = self.schemas.get('ram_swap|__module__')
        assert mod_schema['alert_ram']['default'] == 60
        assert mod_schema['alert_swap']['default'] == 60
        import watchfuls.ram_swap as _rs
        assert _rs.Watchful.ITEM_SCHEMA['__host_profile__']['key'] == 'ssh'

    def test_filesystemusage_list_schema_fields(self):
        """filesystemusage|list: key is an opaque UID; 'label' is the editable
        display name (host - partition)."""
        schema = self.schemas['filesystemusage|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'alert', 'partition', 'label'}
        assert schema['__check_title_field__'] == 'label'
        assert schema['__discovery_uid_key__'] is True

    # ---- ITEM_SCHEMA on the Watchful class directly ----
    def test_watchful_class_declares_schema(self):
        """Each watchful with an ITEM_SCHEMA has a dict-of-dicts."""
        assert isinstance(WebWatchful.ITEM_SCHEMA, dict)
        assert 'list' in WebWatchful.ITEM_SCHEMA
        assert 'code' in WebWatchful.ITEM_SCHEMA['list']
        assert WebWatchful.ITEM_SCHEMA['list']['code']['default'] == 0

    # ---- discover_schemas with invalid dir ----
    def test_discover_with_bad_dir_returns_empty(self):
        assert ModuleBase.discover_schemas('/nonexistent/path') == {}

    # ---- frontend integration ----
    def test_dashboard_contains_item_schemas_json(self, client):
        """Dashboard HTML includes ITEM_SCHEMAS as a JS constant."""
        _login(client)
        html = client.get("/admin").data.decode()
        assert 'ITEM_SCHEMAS' in html
        assert 'web|list' in html

    def test_schemas_passed_to_template(self, admin, client):  # noqa: ARG002
        """item_schemas variable is present in the rendered dashboard."""
        _login(client)
        html = client.get("/admin").data.decode()
        # Rich schema: code has a 'default' key
        assert '"default": 200' in html or '"default":200' in html


# ──────────────────────────── Config-file edge cases ───────────────





class TestRekeyItemsByUid:
    """_rekey_items_by_uid makes every item's dict key equal its uid, across
    flat ``list`` collections and snmp's nested ``servers``/``checks``."""

    def test_a_duplicate_uid_is_visible_before_it_is_resolved(self):
        """Re-keying now repairs a collision, which also means it erases the evidence. The
        duplicate is read BEFORE that and recorded in the same audit entry as the save that
        carried it — the record somebody will be reading when they ask where an item went."""
        from lib.core.modules.service import duplicate_item_uids
        data = {"ping": {"list": {"a": {"uid": "SAME"}, "b": {"uid": "SAME"},
                                  "c": {"uid": "OTHER"}}}}
        assert duplicate_item_uids(data) == ["ping/SAME"]
        assert duplicate_item_uids({"ping": {"list": {"a": {"uid": "U1"}}}}) == []

    def test_two_items_sharing_a_uid_both_survive(self):
        """Reported after a save: two items in a module, one disabled, and on reload there
        was one. Re-keying builds a dict keyed by uid, so a repeated uid meant the second
        write silently replaced the first — no error, nothing in the audit, a check that
        stopped existing.

        Whatever put the duplicate there (an imported config, a hand-edited file), saving
        does not get to resolve it by dropping a check."""
        from lib.core.modules.service import rekey_items_by_uid as _rekey
        data = {"ping": {"list": {
            "a": {"uid": "SAME", "label": "keep me", "enabled": False},
            "b": {"uid": "SAME", "label": "and me"},
        }}}
        _rekey(data)
        lst = data["ping"]["list"]
        assert len(lst) == 2, f'a check was lost: {lst}'
        assert {v["label"] for v in lst.values()} == {"keep me", "and me"}
        assert all(k == v["uid"] for k, v in lst.items()), 'the invariant broke instead'

    def test_an_item_keyed_as_another_items_uid_survives_too(self):
        """The same collision from the other direction: one item's KEY is another's uid."""
        from lib.core.modules.service import rekey_items_by_uid as _rekey
        data = {"ping": {"list": {
            "U2": {"uid": "U1", "label": "first"},
            "other": {"uid": "U2", "label": "second"},
        }}}
        _rekey(data)
        assert len(data["ping"]["list"]) == 2
        assert {v["label"] for v in data["ping"]["list"].values()} == {"first", "second"}

    def test_rekey_flat_and_nested(self):
        from lib.core.modules.service import rekey_items_by_uid as _rekey_items_by_uid
        data = {
            "ping": {"list": {
                "host1": {"uid": "U1", "label": "A"},
                "host2": {"label": "B"},            # missing uid → generated
            }},
            "snmp": {"enabled": True, "threads": 5, "servers": {
                "srvA": {"uid": "SV", "checks": {
                    "chk1": {"uid": "C1"},
                    "chk2": {},                      # missing uid → generated
                }},
            }},
        }
        _rekey_items_by_uid(data)

        # Flat: existing uid kept as key; generated uid used as key for host2.
        lst = data["ping"]["list"]
        assert "U1" in lst and lst["U1"]["label"] == "A"
        assert all(k == v["uid"] for k, v in lst.items())

        # Nested: server keyed by uid; checks keyed by uid; scalars untouched.
        assert data["snmp"]["enabled"] is True and data["snmp"]["threads"] == 5
        assert "SV" in data["snmp"]["servers"]
        checks = data["snmp"]["servers"]["SV"]["checks"]
        assert "C1" in checks
        assert all(k == v["uid"] for k, v in checks.items())
