#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security regression tests — one test per security fix, all of them in this file.

Each test documents a specific vulnerability that was fixed. If a future refactor breaks any
of them, the security property it names has been lost and must be restored before merging.

This was two files — ``test_security_regression.py`` and ``test_security_regressions.py``,
singular and plural, both meaning "one test per security fix". Nobody reading a failure in CI
could tell which was which, so they are one file with the origin of each half named instead:

  Fixes found one at a time
    #1  Path traversal in SNMP MIB file operations
    #2  Non-admin cannot delete an admin account
    #3  Role escalation via custom role creation/editing
    #4  Group admin-role protection
    #5  Config sensitive sections (ldap/oidc/email) require admin

  Bug audit of 2026-07 (``TestBugAudit202607``) — dated because that is what identifies it:
    A — GET /api/v1/overview/widget/<wid> must require a session (was anonymous-readable).
    B — a non-admin cannot grant the admin role to a group via the role UID (the guard
        compared the literal name 'admin', but the UI sends UIDs).
    D — a non-admin with users_add cannot create an admin account (create lacked the guard
        that update already had).
    L — parse_manual_ban rejects a negative duration (it became a silent permanent ban).


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_security_regressions.py`` lives in
``tests/integration/test_security_regressions.py``."""

import os



# ── Helpers ───────────────────────────────────────────────────────────────────

# ── Fix #1 · Path traversal in SNMP MIB file operations ──────────────────────

class TestPathTraversalSnmpMib:
    """Fix: the MIB file operations refuse to leave their directory.

    Attacked where an attacker actually arrives — the actions themselves — rather than at the
    helpers behind them. Those have their own unit tests next to the code
    (``watchfuls/snmp/tests/test_snmp.py``), and they prove the allowlist works; they cannot
    prove that every file operation USES it. A new action that forgot the guard would leave
    them all green, which is the failure this class exists to catch.

    The user needed only ``modules_view`` to reach these, so escaping the MIB directory would
    have turned a read-only role into an arbitrary file read and write.
    """

    _PAYLOADS = (
        '../../../etc/passwd',
        '..\..\..\windows\win.ini',
        '../config.json',
        'sub/dir.mib',
        '..',
        '.hidden',
    )

    @staticmethod
    def _mib_dirs(tmp_path):
        """A var_dir with the two MIB directories, and a secret one level above them."""
        var_dir = tmp_path / 'var'
        for kind in ('raw', 'compiled'):
            (var_dir / 'snmp_mibs' / kind).mkdir(parents=True)
        secret = var_dir / 'snmp_mibs' / 'secret.txt'
        secret.write_text('do not read me', encoding='utf-8')
        return str(var_dir), secret

    def test_upload_cannot_write_outside_the_mib_directory(self, tmp_path):
        """Containment, not rejection: ``upload_mib`` takes the basename BEFORE validating,
        so ``../../../etc/passwd`` is not refused — it is defused into ``passwd`` and lands
        inside raw/ like any other name. That is a fine defence and the property worth
        pinning is the one that matters: whatever the caller sends, nothing is created
        outside the MIB directory."""
        from watchfuls.snmp import Watchful
        var_dir, secret = self._mib_dirs(tmp_path)
        raw_dir = os.path.join(var_dir, 'snmp_mibs', 'raw')
        for payload in self._PAYLOADS:
            Watchful.upload_mib({'__var_dir__': var_dir, 'filename': payload,
                                 'content': 'pwned'})
        strays = [str(p) for p in (tmp_path / 'var').rglob('*')
                  if p.is_file() and p != secret and os.path.dirname(str(p)) != raw_dir]
        assert not strays, f'upload escaped the MIB directory: {strays}'
        assert secret.read_text(encoding='utf-8') == 'do not read me'

    def test_delete_refuses_a_path_outside_its_kind_directory(self, tmp_path):
        from watchfuls.snmp import Watchful
        var_dir, secret = self._mib_dirs(tmp_path)
        for kind in ('raw', 'compiled'):
            for payload in self._PAYLOADS + ('../secret.txt',):
                res = Watchful.delete_mib({'__var_dir__': var_dir, 'kind': kind,
                                           'name': payload})
                assert res.get('ok') is not True, f'delete accepted {payload!r} ({kind})'
        assert secret.is_file(), 'delete_mib removed a file outside the MIB directory'

    def test_reading_a_raw_mib_cannot_escape_its_directory(self, tmp_path):
        from watchfuls.snmp import Watchful
        var_dir, secret = self._mib_dirs(tmp_path)
        for payload in self._PAYLOADS + ('../secret.txt',):
            res = Watchful.get_raw_mib_details({'__var_dir__': var_dir, 'name': payload})
            assert res.get('ok') is not True, f'read accepted {payload!r}'
            assert 'do not read me' not in str(res)

    def test_a_legitimate_name_still_works(self):
        """A guard that refuses everything would pass the tests above and break the feature."""
        from watchfuls.snmp import Watchful
        res = Watchful.upload_mib({'__var_dir__': '', 'filename': 'AGENTX-MIB.mib',
                                   'content': 'x'})
        # Rejected for the missing var_dir, NOT for the name — the name got through.
        assert res.get('ok') is False and 'filename' not in res.get('message', '').lower()


# ── Fix #2 (complete) · Non-admin cannot delete an admin account ──────────────


# ── Fix #3 · Role escalation via custom role creation/editing ─────────────────


# ── Fix #4 · Group admin-role protection ──────────────────────────────────────


# ── Fix #5 · Config sensitive sections require admin ─────────────────────────


# ── Fix #6 · Security-relevant web_admin fields require admin ────────────────


# ── Fix #7 · LDAP empty-password unauthenticated bind ────────────────────────


