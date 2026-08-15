#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comparing one process's packages against another's.

Split into containers — web, worker, syslog receiver, event processor — the diagnostics page
describes the process that served the request and nothing else. Each service publishes what it
runs on into the heartbeat registry, and the panel reads it from there: the standalone services
answer no HTTP unless `SS_CONTROL_TOKEN` is set, which is not the default, and a diagnostics
screen that only works on the installs that opted into a token is a screen for somebody else.

What is tested here is the comparison itself, which is the part that can quietly lie. Two
properties matter:

* **the answer is the DIFFERENCE.** Four containers built from one image carry four identical
  lists, and "same as this process" is the whole answer when it is true. Printing the list four
  times is a screen nobody reads to find the one row that matters.
* **a package is a name AND a version.** The web at 3.4.9 and a worker at 3.5.0 are two
  questions for the advisory service, and answering one of them for both is how a container
  gets reported clean because a different one is.

Flask-free and database-free: the functions take dicts.
"""

import pytest

from lib.core.diagnostics import service as diag


def _env(lock=None, extra=None, **kw):
    """One process's published fingerprint, as the heartbeat row carries it."""
    return {'python': '3.14.0', 'os': 'Debian GNU/Linux 12',
            'lock': [{'name': n, 'required': v, 'installed': v}
                     for n, v in (lock or {}).items()],
            'extra': [{'name': n, 'installed': v} for n, v in (extra or {}).items()],
            'features': [], **kw}


class TestTellingTwoProcessesApart:

    def test_the_same_image_reports_no_difference(self, ):
        """The common case, and the one that must cost nothing to confirm: the containers are
        meant to be one image, and saying so in a word is the useful answer."""
        env = _env({'flask': '3.1.0'}, {'pip': '26.1.1'})
        out = diag.compare_environments(env, env)
        assert out['same'] is True and out['rows'] == [] and out['count'] == 0

    def test_a_different_version_is_named_with_both_sides(self, ):
        """"They differ" is not actionable. Which package, and from what to what, is."""
        out = diag.compare_environments(_env({'flask': '3.1.0'}), _env({'flask': '3.0.0'}))
        assert out['same'] is False
        assert out['rows'] == [{'name': 'flask', 'here': '3.1.0', 'there': '3.0.0',
                                'kind': 'version'}]

    def test_a_package_only_one_side_has_says_which_side(self, ):
        """The two directions are different findings. A worker missing `paramiko` runs every
        SSH check as skipped; the web having a package the worker lacks is not that."""
        out = diag.compare_environments(_env({'a': '1.0'}), _env({'b': '2.0'}))
        kinds = {r['name']: r['kind'] for r in out['rows']}
        assert kinds == {'a': 'missing_there', 'b': 'missing_here'}

    def test_the_lock_and_the_rest_are_one_list_here(self, ):
        """The question is "does that process run the same code", and `pip` runs there too."""
        out = diag.compare_environments(_env({'a': '1.0'}, {'pip': '26.1'}),
                                        _env({'a': '1.0'}, {'pip': '26.2'}))
        assert [r['name'] for r in out['rows']] == ['pip']

    def test_the_same_package_spelled_two_ways_is_not_a_difference(self, ):
        """`charset-normalizer` in one process's lock and `charset_normalizer` from another's
        installed set. Compared literally, every container would look like it drifted."""
        out = diag.compare_environments(_env({'charset-normalizer': '3.5.0'}),
                                        _env({'charset_normalizer': '3.5.0'}))
        assert out['same'] is True, out['rows']

    def test_it_is_sorted_so_the_list_does_not_reshuffle(self, ):
        out = diag.compare_environments(_env({'z': '1', 'a': '1'}), _env({'z': '2', 'a': '2'}))
        assert [r['name'] for r in out['rows']] == ['a', 'z']

    def test_an_instance_that_published_nothing_is_not_a_difference(self, ):
        """An older build, or one that has not beaten since it started. "Unknown" and "differs"
        are different words on the screen, and only one of them means somebody has work."""
        out = diag.compare_environments(_env({'a': '1.0'}), {})
        assert out['count'] == 1 and out['rows'][0]['kind'] == 'missing_there'


class TestWhatOnlyTheOtherProcessesRun:
    """The extra names the remote check must cover, and no more.

    One round of requests for the whole installation. Each container asking PyPI and OSV about
    its own list would put four processes on the internet for nearly the same question, in
    exactly the deployment where that is least welcome.
    """

    class _WA:
        def __init__(self, instances):
            self._service_instances_store = object()
            self._rows = instances

        def _service_instances_list(self, _key=None):
            return self._rows

    def _wa(self, monkeypatch, instances, here):
        monkeypatch.setattr(diag, 'dependency_rows', lambda _wa: [
            {'name': n, 'required': v, 'installed': v, 'status': 'ok'}
            for n, v in here.items()])
        monkeypatch.setattr(diag, 'unpinned_rows', lambda _wa: [])
        monkeypatch.setattr(diag.collect, 'environment', lambda _p: _env(here))
        return self._WA(instances)

    def test_one_image_everywhere_adds_nothing(self, monkeypatch):
        wa = self._wa(monkeypatch,
                      [{'service_key': 'monitoring', 'env': _env({'flask': '3.1.0'})}],
                      {'flask': '3.1.0'})
        assert diag.elsewhere_rows(wa) == []

    def test_a_version_only_another_process_runs_is_added(self, monkeypatch):
        wa = self._wa(monkeypatch,
                      [{'service_key': 'monitoring', 'env': _env({'flask': '3.0.0'})}],
                      {'flask': '3.1.0'})
        assert diag.elsewhere_rows(wa) == [
            {'name': 'flask', 'required': '', 'installed': '3.0.0', 'status': 'elsewhere'}]

    def test_this_process_is_not_asked_about_twice(self, monkeypatch):
        wa = self._wa(monkeypatch,
                      [{'service_key': 'monitoring', 'is_self': True,
                        'env': _env({'flask': '9.9.9'})}],
                      {'flask': '3.1.0'})
        assert diag.elsewhere_rows(wa) == [], 'the local row is already in the first list'

    def test_two_containers_at_two_versions_are_two_questions(self, monkeypatch):
        """Keyed by name AND version. Asking once and reusing the answer is how a container
        gets told it is clean because a different one is."""
        wa = self._wa(monkeypatch,
                      [{'service_key': 'monitoring', 'env': _env({'flask': '3.0.0'})},
                       {'service_key': 'syslog', 'env': _env({'flask': '2.0.0'})}],
                      {'flask': '3.1.0'})
        assert [r['installed'] for r in diag.elsewhere_rows(wa)] == ['2.0.0', '3.0.0']

    def test_the_same_version_twice_is_one_question(self, monkeypatch):
        wa = self._wa(monkeypatch,
                      [{'service_key': 'monitoring', 'env': _env({'flask': '3.0.0'})},
                       {'service_key': 'syslog', 'env': _env({'flask': '3.0.0'})}],
                      {'flask': '3.1.0'})
        assert len(diag.elsewhere_rows(wa)) == 1

    def test_a_package_with_no_version_is_not_asked_about(self, monkeypatch):
        """The question is about what is RUNNING, and a name with no version is not that."""
        wa = self._wa(monkeypatch,
                      [{'service_key': 'monitoring', 'env': _env({'ghost': ''})}],
                      {'flask': '3.1.0'})
        assert diag.elsewhere_rows(wa) == []


class TestTheListDegradesInsteadOfFailing:
    """It is reached from the page somebody opened because something is already wrong."""

    def test_no_registry_is_an_empty_list(self):
        assert diag.instances(object()) == []

    def test_a_store_that_raises_costs_the_card_and_nothing_else(self, monkeypatch):
        class _Boom:
            _service_instances_store = object()

            def _service_instances_list(self, _key=None):
                raise RuntimeError('database is gone')

        assert diag.instances(_Boom()) == []

    def test_an_instance_without_an_environment_is_marked_unknown(self, monkeypatch):
        """Said, never guessed at: an older build, or one whose first beat has not landed."""
        monkeypatch.setattr(diag.collect, 'environment', lambda _p: _env({'a': '1.0'}))

        class _WA:
            _service_instances_store = object()

            def _service_instances_list(self, _key=None):
                return [{'service_key': 'syslog', 'mode': 'standalone', 'host': 'box',
                         'running': True, 'env': {}}]

        row = diag.instances(_WA())[0]
        assert row['known'] is False and row['diff'] is None and row['packages'] == []


@pytest.mark.parametrize('env,expected', [
    ({'lock': [{'name': 'A_b', 'installed': '1'}]}, {'a-b': '1'}),
    ({'extra': [{'name': 'pip', 'installed': '26'}]}, {'pip': '26'}),
    ({}, {}),
])
def test_the_versions_of_one_process_are_read_from_both_halves(env, expected):
    assert diag._versions(env) == expected


class TestListingWhatOneProcessRuns:
    """"Same as here (42)" does not say WHICH 42, so the cell opens the list.

    One shape for the screen and for the remote check: a second, flatter copy of the same
    versions beside it is how the two come to disagree about what is installed over there.
    """

    def test_both_halves_are_in_it_and_say_which_is_which(self):
        rows = diag.packages_of({'lock': [{'name': 'flask', 'installed': '3.1.0'}],
                                 'extra': [{'name': 'pip', 'installed': '26.1'}]})
        assert rows == [{'name': 'flask', 'version': '3.1.0', 'pinned': True},
                        {'name': 'pip', 'version': '26.1', 'pinned': False}]

    def test_it_is_sorted_by_name_across_both(self):
        """Read as a list, so the order is the reader's and not the lock's."""
        rows = diag.packages_of({'lock': [{'name': 'zope', 'installed': '1'}],
                                 'extra': [{'name': 'anyio', 'installed': '2'}]})
        assert [r['name'] for r in rows] == ['anyio', 'zope']

    def test_nothing_published_is_an_empty_list(self):
        assert diag.packages_of({}) == [] and diag.packages_of(None) == []
