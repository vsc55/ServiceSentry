#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the audit log — recording, persistence and API access.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_audit.py`` lives in ``tests/integration/test_wa_audit.py``."""



# ──────────────────────────── Audit log ────────────────────────────


class TestEveryAuditedEventHasAName:
    """An event with no label renders in the audit screen as its raw identifier.

    Found while adding a prefix to the maintenance events: `ipban_history_cleared` had no
    label at all, and it was not alone — six events were shipping as bare snake_case. Nothing
    was checking, and they read fine in code; it is only on the screen an operator opens
    after an incident that they are unreadable.

    Scanned from the CALLS rather than from a list, because a list is the thing that goes
    stale: the events are written by ~30 modules and the next one added will not think to
    register itself anywhere.
    """

    @staticmethod
    def _events_used():
        import glob
        import io
        import os
        import re
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        used = set()
        for path in glob.glob(os.path.join(root, 'lib', '**', '*.py'), recursive=True):
            body = io.open(path, encoding='utf-8', errors='replace').read()
            used |= set(re.findall(r"_audit(?:_system|_auto)?\(\s*'([a-z0-9_]+)'", body))
        return used

    def test_the_scan_finds_the_events(self):
        """A guard over a parser that matches nothing passes for ever."""
        assert len(self._events_used()) >= 100

    def test_every_event_is_labelled_in_both_languages(self):
        from lib.i18n.lang import en_EN, es_ES
        for name, table in (('es_ES', es_ES.LANG), ('en_EN', en_EN.LANG)):
            catalog = table['audit_events']
            missing = sorted(e for e in self._events_used() if not catalog.get(e))
            assert not missing, f'{name} shows these as raw identifiers: {missing}'

    def test_the_labels_say_which_area_they_came_from(self):
        """Two hundred entries in one list: without a prefix naming the subsystem, filtering
        by eye is reading every row. One read simply "Estado borrado" — neither the area nor
        what it was the state OF."""
        from lib.i18n.lang import es_ES
        catalog = es_ES.LANG['audit_events']
        bare = sorted(k for k, v in catalog.items() if ':' not in v)
        assert not bare, f'audit labels with no area prefix: {bare}'


class TestEverySeverityIsDeclaredNotGuessed:
    """What an audit event MEANS is declared by the package that writes it.

    The badge — the only thing a glance down two hundred rows gives you — used to be worked
    out from the event NAME: a rule matching `deleted`/`revoked` plus a handful of names
    written out by hand. Two things were wrong with that, and only the first was visible:
    seven destructive events and fifteen failures rendered neutral grey (three of them
    security signals, plus `internal_error`, the entry written when the panel crashed); and
    even with the word lists widened, the colour still depended on the noun somebody chose.
    `purge_done` would have slipped through; `rule_failed` would have gone red for a rule
    that merely reported "no match".

    Same shape and same discovery as NOTIFY_EVENTS and MODULE_PERMISSIONS, so a package that
    adds an event declares it where the code that emits it lives.
    """

    @staticmethod
    def _emitted():
        import glob
        import io as _io
        import os as _os
        import re as _re
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        used = set()
        for path in glob.glob(_os.path.join(root, 'lib', '**', '*.py'), recursive=True):
            body = _io.open(path, encoding='utf-8', errors='replace').read()
            used |= set(_re.findall(r"_audit(?:_system|_auto)?\(\s*'([a-z0-9_]+)'", body))
        return used

    def test_every_emitted_event_declares_its_severity(self):
        """The check that makes the next event impossible to forget: emit one without
        declaring it and the build fails here, not in a grey badge nobody notices."""
        from lib.core.audit.events import audit_severity
        missing = sorted(self._emitted() - set(audit_severity()))
        assert not missing, f'emitted with no declared severity: {missing}'

    def test_every_LABELLED_event_declares_one_too(self):
        """The scan above reads literals, so it cannot see an event emitted through a
        variable — `wa._audit(event, …)` in the maintenance endpoint is exactly that, and
        `db_optimized`/`db_compacted` slipped past it.

        The i18n catalog is the second list, and a complete one: every event needs a label to
        render, and a guard already enforces that. Crossing the two closes the blind spot
        without asking anyone to remember it."""
        from lib.core.audit.events import audit_severity
        from lib.i18n.lang import es_ES
        declared = set(audit_severity())
        missing = sorted(e for e in es_ES.LANG['audit_events'] if e not in declared)
        assert not missing, f'labelled but no declared severity: {missing}'

    def test_nothing_is_declared_that_nobody_emits(self):
        """The rot that lasts longest: a declaration for an event that no longer exists,
        because nobody greps for a name that is gone.

        Checked against the literals AND the label catalog, since an event emitted through a
        variable is invisible to the scan but always has a label — without that union this
        would report the maintenance events as dead the moment they were declared."""
        from lib.core.audit.events import audit_severity
        from lib.i18n.lang import es_ES
        known = self._emitted() | set(es_ES.LANG['audit_events'])
        stale = sorted(set(audit_severity()) - known)
        assert not stale, f'declared but never emitted: {stale}'

    def test_each_event_is_declared_exactly_once(self):
        """Two packages declaring the same event is not harmless: the dict keeps whichever
        was scanned last, so the two can disagree and the winner is decided by import order —
        a difference nobody would think to look for.

        It happened while regrouping: `entra_oidc_secret_rotated` sat in both the audit domain
        and the Entra provider, `msteams_sso_*` in both notify and Entra. They agreed on the
        severity, which is exactly why it would have gone unnoticed until they did not.
        """
        import collections
        from lib.discovery import scan
        where = collections.defaultdict(list)
        for pkg, values in scan('AUDIT_EVENTS'):
            for value in values:
                where[value['key']].append(pkg)
        dupes = {k: v for k, v in where.items() if len(v) > 1}
        assert not dupes, f'declared in more than one package: {dupes}'

    def test_events_are_declared_by_the_package_that_writes_them(self):
        """The point of declaring them at all. They were first written into whichever
        manifest existed, which put SCIM, Teams, webhooks and the login events in the audit
        domain's file — a central list wearing a per-package shape, and the thing that goes
        stale the moment a module changes.

        The audit domain keeps only its own two plus the ones no package owns: the request
        lifecycle's (login, csrf, the crash handler), which `lib.web_admin` cannot declare
        because it is not a discovery root, and a couple raised from `lib/util`.
        """
        from lib.discovery import scan
        by_pkg = {pkg: {v['key'] for v in vals} for pkg, vals in scan('AUDIT_EVENTS')}
        for pkg, prefix in (('scim', 'scim_'), ('syslog', 'syslog_'),
                            ('entraid', 'entra_'), ('ipban', 'ip')):
            owned = {k for k in by_pkg.get(pkg, ()) if k.startswith(prefix)}
            assert owned, f'{pkg} declares none of its own {prefix}* events'
            elsewhere = {k for other, keys in by_pkg.items() if other != pkg
                         for k in keys if k.startswith(prefix)}
            assert not elsewhere, f'{prefix}* events declared outside {pkg}: {elsewhere}'
        assert len(by_pkg) >= 18, f'only {len(by_pkg)} packages declare events'

    def test_the_discovery_found_them(self):
        """A scan that silently matches nothing passes for ever."""
        from lib.core.audit.events import audit_severity
        assert len(audit_severity()) >= 100

    def test_only_known_severities_survive(self):
        """An unknown severity reaches the browser as a CSS class that does not exist, and the
        row renders with NO badge — worse than the wrong colour, because it reads as an event
        that carries no weight at all. Dropped at the door instead."""
        from lib.core.audit.events import VALID_SEVERITIES, _normalize, audit_severity
        assert set(audit_severity().values()) <= VALID_SEVERITIES
        assert _normalize({'key': 'x', 'severity': 'chartreuse'}) is None
        assert _normalize({'key': '', 'severity': 'danger'}) is None
        assert _normalize({'key': 'x', 'severity': 'danger'}) == {'key': 'x',
                                                                  'severity': 'danger'}

    def test_the_badge_reads_the_declaration_and_nothing_else(self):
        """No substring rules left in the renderer — that is the whole point."""
        import io as _io
        import os as _os
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        body = _io.open(_os.path.join(root, 'lib', 'web_admin', 'templates', 'partials',
                                      'audit', '_filters.html'), encoding='utf-8').read()
        fn = body[body.index('function _auditEventBadge'):]
        fn = fn[:fn.index('\n}')]
        assert 'AUDIT_SEVERITY[event]' in fn
        for guessy in ('includes(', "=== 'login", '_AUDIT_DESTRUCTIVE', '_AUDIT_FAILURE'):
            assert guessy not in fn, f'the badge is guessing again: {guessy}'

    def test_the_ones_that_started_this_are_right(self):
        """The reports, in order: "Estado De Checks Borrado" grey, then "Error Interno" grey."""
        from lib.core.audit.events import audit_severity
        sev = audit_severity()
        for event in ('status_cleared', 'internal_error', 'csrf_failed', 'scim_auth_failed',
                      'audit_cleared', 'syslog_cleared', 'ipban_history_cleared'):
            assert sev[event] == 'danger', f'{event} is {sev[event]}'
        # …and the two that must NOT be alarming: they reclaim space and change no row.
        for event in ('db_optimized', 'db_compacted'):
            assert sev[event] == 'muted', f'{event} is {sev[event]}'


class TestAnEntryAlwaysNamesWhoCausedIt:
    """Reported from the audit screen: a SCIM auth failure showed an empty USER column, with
    a suggestion that it should say `system`.

    It should not. `system` means the panel acted on its own — a service starting, a scheduled
    prune — and an intrusion attempt filed under it reads as the panel doing this to itself,
    in the one filter these entries are most often looked up by. Blank is no better: an empty
    cell reads as a missing value rather than as "there was no identity to record".
    """

    def test_the_scim_failure_names_an_anonymous_caller(self):
        from lib.core.constants import ANONYMOUS_USER, SYSTEM_USER
        import io as _io
        import os as _os
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        body = _io.open(_os.path.join(root, 'lib', 'providers', 'scim', 'routes.py'),
                        encoding='utf-8').read()
        assert "username=ANONYMOUS_USER" in body
        assert "username=''" not in body, 'an audit entry with no actor at all'
        assert ANONYMOUS_USER != SYSTEM_USER

    def test_no_audit_entry_is_written_with_a_blank_actor(self):
        """The one that existed was the only one; the guard is what keeps it that way."""
        import glob
        import io as _io
        import os as _os
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        offenders = []
        for path in glob.glob(_os.path.join(root, 'lib', '**', '*.py'), recursive=True):
            body = _io.open(path, encoding='utf-8', errors='replace').read()
            if "username=''" in body and '_audit' in body:
                offenders.append(_os.path.basename(path))
        assert not offenders, f'audit calls with an empty username: {offenders}'

    def test_both_audit_identities_are_reserved_usernames(self):
        """An account able to take either name would have its actions read as the panel's own
        or as an unauthenticated caller's, and "who did this" stops being answerable."""
        import pytest as _pytest
        from lib.core.constants import ANONYMOUS_USER, SYSTEM_USER
        from lib.core.users.service import AdminOpError, PasswordPolicy, create_user
        policy = PasswordPolicy()
        for reserved in (SYSTEM_USER, ANONYMOUS_USER, 'SYSTEM', 'Anonymous'):
            with _pytest.raises(AdminOpError) as exc:
                create_user({}, username=reserved, password='irrelevant-password',
                            policy=policy, custom_roles={}, groups={})
            assert exc.value.key == 'username_reserved', reserved
