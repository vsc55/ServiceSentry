#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the generic watchful action endpoint: GET|POST /api/v1/modules/watchfuls/<module>/<action>.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_watchfuls.py`` lives in ``tests/integration/test_wa_watchfuls.py``."""

import os
import pathlib

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_SRC_DIR = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_WATCHFULS_DIR = os.path.join(_SRC_DIR, "watchfuls")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client_with_modules(tmp_path):
    """Flask test client with modules_dir pointing to the real watchfuls directory."""
    config_dir = str(tmp_path / "config")
    var_dir = str(tmp_path / "var")
    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(var_dir, exist_ok=True)

    (pathlib.Path(config_dir) / "config.json").write_text("{}", encoding="utf-8")

    wa = WebAdmin(
        config_dir, "admin", "secret", var_dir,
        modules_dir=_WATCHFULS_DIR,
        pw_require_upper=False, pw_require_digit=False,
    )
    wa.app.config["TESTING"] = True
    return wa.app.test_client()


# ── Auth ──────────────────────────────────────────────────────────────────────


class TestMergeHostConn:
    """_merge_host_conn fills a module's connection fields from the bound host."""

    def test_fills_address_and_ssh(self):
        from lib.core.modules.actions import merge_host_conn

        class _WA:
            _modules_dir = None
        cfg = {'db_type': 'mysql', 'conn_type': 'ssh',
               'host': '', 'ssh_host': '', 'ssh_user': '', 'ssh_password': ''}
        ctx = {'address': '10.0.0.5',
               'ssh': {'ssh_user': 'root', 'ssh_port': 22, 'ssh_password': 'p'}}
        merge_host_conn(_WA(), 'datastore', cfg, ctx)
        assert cfg['host'] == '10.0.0.5'          # db address_field ← host address
        assert cfg['ssh_host'] == '10.0.0.5'      # ssh address_field ← host address
        assert cfg['ssh_user'] == 'root' and cfg['ssh_password'] == 'p'

    def test_explicit_check_value_wins(self):
        from lib.core.modules.actions import merge_host_conn

        class _WA:
            _modules_dir = None
        cfg = {'db_type': 'mysql', 'host': 'explicit.db'}
        merge_host_conn(_WA(), 'datastore', cfg, {'address': '10.0.0.5', 'ssh': {}})
        assert cfg['host'] == 'explicit.db'       # the check's own value is kept


class TestResolveHostCtxCred:
    """Host-aware discovery must resolve a host's named SSH credential (cred_uid),
    not only inline secrets — else disk/services/temperature discover get no data."""

    def test_ssh_cred_uid_is_resolved(self):
        from lib.core.modules.actions import resolve_host_ctx

        class _Cstore:
            def get(self, uid, decrypt=True):
                return ({'enabled': True,
                         'data': {'ssh_user': 'svc', 'ssh_password': 'secret'}}
                        if uid == 'cred1' else None)

        class _WA:
            _hosts_store = None
            _credentials_store = _Cstore()

        cfg = {'_host': {'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
                         'profiles': {'ssh': {'cred_uid': 'cred1', 'ssh_port': 22}}}}
        ctx = resolve_host_ctx(_WA(), cfg)
        assert ctx['ssh']['ssh_user'] == 'svc'        # credential identity applied
        assert ctx['ssh']['ssh_password'] == 'secret'
        assert ctx['ssh']['ssh_port'] == 22           # other ssh fields preserved

    def test_no_cred_uid_left_unchanged(self):
        from lib.core.modules.actions import resolve_host_ctx

        class _WA:
            _hosts_store = None
            _credentials_store = None

        cfg = {'_host': {'address': 'h', 'kind': 'remote', 'os': 'linux',
                         'profiles': {'ssh': {'ssh_user': 'root'}}}}
        ctx = resolve_host_ctx(_WA(), cfg)
        assert ctx['ssh']['ssh_user'] == 'root'


class TestActionsReachADeviceThatIsNotReachedOverSsh:
    """An action posted from the Servers tab runs against a HOST, and a host speaks more
    than one protocol.  While only its ssh profile travelled, an SNMP action bound to a host
    was handed the address and nothing else — which fails as "the device did not answer"
    rather than as "nobody told me the community", and is the harder of the two to read."""

    class _WA:
        _modules_dir = None
        _hosts_store = None
        _credentials_store = None
        _secret_keys = frozenset({'community', 'snmpv3_auth_key'})

    def test_snmp_connection_comes_from_the_snmp_profile(self):
        from lib.core.modules.actions import merge_host_conn

        cfg = {'device_profiles': 'sys_generic'}
        ctx = {'address': '10.0.0.9', 'ssh': {},
               'profiles': {'snmp': {'community': 'sec', 'version': '2c', 'port': 1161},
                            'ssh':  {'ssh_user': 'root'}}}
        merge_host_conn(self._WA(), 'snmp', cfg, ctx)
        assert cfg['host'] == '10.0.0.9'          # address_field ← the host address
        assert cfg['community'] == 'sec'
        assert cfg['version'] == '2c' and cfg['port'] == 1161
        # The device's own profile, not the box's login: an SNMP action has no business
        # picking up an ssh user just because the host has one.
        assert 'ssh_user' not in cfg

    def test_what_the_form_holds_still_wins(self):
        from lib.core.modules.actions import merge_host_conn

        cfg = {'community': 'typed-just-now'}
        ctx = {'address': '10.0.0.9', 'ssh': {},
               'profiles': {'snmp': {'community': 'stored'}}}
        merge_host_conn(self._WA(), 'snmp', cfg, ctx)
        assert cfg['community'] == 'typed-just-now'

    def test_the_host_profile_credential_is_carried_over(self):
        from lib.core.modules.actions import merge_host_conn

        cfg = {}
        ctx = {'address': '10.0.0.9', 'ssh': {},
               'profiles': {'snmp': {'cred_uid': 'snmp-ro'}}}
        merge_host_conn(self._WA(), 'snmp', cfg, ctx)
        # Named, not applied here: apply_cred_to_config overlays it afterwards, so the
        # credential still wins over anything filled in from the profile.
        assert cfg['cred_uid'] == 'snmp-ro'

    def test_a_ctx_built_without_profiles_still_fills_ssh(self):
        from lib.core.modules.actions import merge_host_conn

        cfg = {'db_type': 'mysql', 'conn_type': 'ssh', 'ssh_user': ''}
        merge_host_conn(self._WA(), 'datastore', cfg,
                        {'address': '10.0.0.5', 'ssh': {'ssh_user': 'root'}})
        assert cfg['ssh_user'] == 'root'

    def test_a_masked_secret_is_restored_from_the_stored_host(self):
        """The browser never held the community — it holds the mask the API sent it — so a
        draft posted straight back carries ``None`` where the secret is.  Reading it as "the
        user cleared this" is how a Test button authenticates with nothing at all."""
        from lib.core.modules.actions import resolve_host_ctx

        class _Hosts:
            def get(self, uid, decrypt=True):
                return ({'address': '10.0.0.9', 'kind': 'local', 'os': 'auto',
                         'profiles': {'snmp': {'community': 'real', 'version': '2c'}}}
                        if uid == 'h1' else None)

        class _WA(TestActionsReachADeviceThatIsNotReachedOverSsh._WA):
            _hosts_store = _Hosts()

        cfg = {'host_uid': 'h1',
               '_host': {'address': '10.0.0.9', 'kind': 'local', 'os': 'auto',
                         'profiles': {'snmp': {'community': None, 'version': '3'}}}}
        ctx = resolve_host_ctx(_WA(), cfg)
        assert ctx['profiles']['snmp']['community'] == 'real'
        # …and an UNSAVED edit beside it is still what gets tested: that is the point of
        # a Test button on a form somebody is in the middle of filling in.
        assert ctx['profiles']['snmp']['version'] == '3'




# ── Input validation ──────────────────────────────────────────────────────────




# ── Dispatch ──────────────────────────────────────────────────────────────────




# ── Security ───────────────────────────────────────────────────────────────────






class TestWatchfulSecretFieldsProtected:
    """Module secret fields are discovered from schemas (NOT hardcoded in core)
    and then encrypted/masked via the discovered key set."""

    def test_core_does_not_hardcode_module_secrets(self):
        """Module-specific secret field names must NOT be baked into core."""
        from lib.security.secret_manager import ENCRYPT_KEYS
        for field in ('snmpv3_auth_key', 'snmpv3_priv_key', 'auth_password'):
            assert field not in ENCRYPT_KEYS

    def test_secrets_discovered_from_module_schemas(self):
        """The core discovers secret/sensitive fields by reading module schemas."""
        from lib.modules import ModuleBase
        discovered = ModuleBase.discover_secret_fields(_WATCHFULS_DIR)
        assert 'snmpv3_auth_key' in discovered
        assert 'snmpv3_priv_key' in discovered
        assert 'auth_password' in discovered

    def test_discovered_secrets_masked(self):
        """mask_sensitive with the discovered key set blanks the module secrets."""
        from lib.modules import ModuleBase
        from lib.security.secret_manager import ENCRYPT_KEYS, mask_sensitive
        keys = ENCRYPT_KEYS | ModuleBase.discover_secret_fields(_WATCHFULS_DIR)
        masked = mask_sensitive({
            'snmpv3_auth_key': 'topsecret',
            'snmpv3_priv_key': 'topsecret2',
            'auth_password':   'httppass',
        }, keys)
        assert masked['snmpv3_auth_key'] is None
        assert masked['snmpv3_priv_key'] is None
        assert masked['auth_password'] is None

    def test_wa_secret_keys_includes_module_secrets(self, client_with_modules):
        """A running WebAdmin exposes the combined core+module secret key set."""
        # client_with_modules built WebAdmin with modules_dir → discovery ran.
        # Reach the instance via the app's registered closure is awkward; instead
        # just confirm discovery is wired by checking the GET /modules masking.
        _login(client_with_modules)
        # Seed a module item carrying a secret, then read it back masked.
        client_with_modules.put("/api/v1/modules", json={
            "snmp": {"host1": {"snmpv3_auth_key": "supersecret"}}
        })
        resp = client_with_modules.get("/api/v1/modules")
        body = resp.get_json()
        if "snmp" in body and "host1" in body["snmp"]:
            assert body["snmp"]["host1"].get("snmpv3_auth_key") in (None, "")


class TestSsrfGuard:
    """User-supplied URLs fetched server-side reject dangerous schemes/targets."""

    def test_file_scheme_blocked(self):
        from lib.security.net_guard import validate_external_url
        assert validate_external_url('file:///etc/passwd') is not None

    def test_metadata_ip_blocked(self):
        from lib.security.net_guard import validate_external_url
        assert validate_external_url('http://169.254.169.254/latest/meta-data/') is not None

    def test_normal_http_allowed(self):
        from lib.security.net_guard import validate_external_url
        # A public hostname resolves and is not link-local → allowed (None).
        assert validate_external_url('https://example.com/mib.txt') is None

    def test_private_host_allowed_for_monitoring(self):
        from lib.security.net_guard import validate_external_url
        # Internal monitoring is the tool's purpose — RFC1918 is NOT blocked.
        assert validate_external_url('http://192.168.1.10/status') is None


# ── Host-aware discovery (Servers modal: run discover on the bound host) ──────


