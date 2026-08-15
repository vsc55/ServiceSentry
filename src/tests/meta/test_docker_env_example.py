#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``docker/env.example`` is the published list of what this app reads from the environment.

It is the file people copy to `docker/.env` and edit, and the only place a whole class of
settings is *discoverable*: an override that exists in the code and appears nowhere here is,
for anybody deploying, an override that does not exist. It rotted silently — sixteen supported
variables were missing when this was first counted, including every backup setting and the
fail2ban jail — because nothing connected `spec.py` to a text file in another directory.

Two directions, and both matter:

* **documented ⊇ supported** — a new ``Cfg(..., env='SS_X')`` is one line, and remembering to
  also write it here is exactly the kind of thing nobody remembers;
* **documented ⊆ real** — a name that no longer exists is worse than a missing one. It reads
  as supported, gets set, and does nothing at all, which is indistinguishable from the setting
  not working.

What counts as "supported" is taken from the three surfaces that actually read the
environment, never from a list kept here: the config registry, the container entrypoint, and
``os.environ`` in the source. A guard with its own copy of the answer is a second thing to
keep in sync.
"""

import io
import os
import re

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
ROOT = os.path.dirname(SRC)
DOCKER = os.path.join(ROOT, 'docker')
ENV_EXAMPLE = os.path.join(DOCKER, 'env.example')

# A trailing underscore is never a name: both this file and the entrypoint write families as
# `SS_DB_*` / `SS_SYSLOG_DB_*` in prose, and the same rule the i18n guard uses for keys built
# by concatenation applies here — there is nothing static behind a wildcard.
_NAME = re.compile(r'SS_[A-Z0-9_]*[A-Z0-9]')
# `os.environ['X']`, `os.environ.get('X')`, `os.getenv('X')` — the shapes that READ one.
_READ = re.compile(r"""(?:environ(?:\.get)?\(|environ\[|getenv\()\s*['"](SS_[A-Z0-9_]+)['"]""")

# Names `env.example` documents that no Python or entrypoint reads, because they are consumed
# BEFORE any container exists — by Compose itself, or by the database/proxy images. Each one
# is checked below to still be used somewhere, so this list cannot quietly go stale.
COMPOSE_ONLY = {
    'SS_IMAGE_TAG',                 # substituted into the compose file's image tag
    'SS_DB_ROOT_PASSWORD',          # provisions the MariaDB container
    'SS_SYSLOG_DB_ROOT_PASSWORD',   # same, for the syslog database
    'SS_DOMAIN',                    # Traefik router rule
    'SS_ACME_EMAIL',                # Let's Encrypt registration
    # Read through a module constant (`SECRET_KEY_ENV`) rather than a literal at the call
    # site, so the scan below cannot see it. It is the one that must never be missing.
    'SS_SECRET_KEY',
}


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8', errors='replace').read()


def _documented() -> set:
    """Every name the file NAMES, prose included.

    Deliberately generous, and only used for "is this documented at all": the per-topology
    variables (`SS_SERVICE_ROLE`, the `*_EMBEDDED` gates) are explained here in a paragraph
    that sends the reader to the compose file, which is documentation and is the shape this
    file wants for them. Demanding a line to assign would be demanding the opposite.
    """
    return set(_NAME.findall(_read(ENV_EXAMPLE)))


def _assigned() -> set:
    """Only the names written as a setting — `SS_X=…`, commented out or not.

    The strict half, for the other direction. Prose says `SS_DB_*` and `SS_SYSLOG_DB_*`,
    families rather than variables, and no regex tells a wildcard from a name once the star
    is gone. A line that assigns is unambiguous, and it is the thing somebody copies.
    """
    return set(re.findall(r'^\s*#?\s*(SS_[A-Z0-9_]+)\s*=', _read(ENV_EXAMPLE), re.M))


def _registry() -> set:
    """Every env-overridable config field — the machine-readable half of the answer."""
    from lib.config.spec import env_field_specs                    # noqa: PLC0415
    return set(env_field_specs())


def _entrypoint() -> set:
    """What the container entrypoint turns into command-line flags."""
    return set(_NAME.findall(_read(os.path.join(DOCKER, 'entrypoint.sh'))))


def _read_from_environ() -> set:
    """Every ``SS_*`` the source reads straight from the environment.

    The language files are skipped: they NAME variables inside help text meant for a human,
    and a sentence explaining a setting is not a place that reads one.
    """
    out = set()
    for root, dirs, files in os.walk(os.path.join(SRC, 'lib')):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        if os.path.join('i18n', 'lang') in root:
            continue
        for f in files:
            if f.endswith('.py'):
                out |= set(_READ.findall(_read(os.path.join(root, f))))
    out |= set(_READ.findall(_read(os.path.join(SRC, 'main.py'))))
    return out


def _supported() -> set:
    return _registry() | _entrypoint() | _read_from_environ()


class TestEverySupportedOverrideIsDocumented:
    """An override nobody can find is an override that does not exist."""

    @pytest.mark.parametrize('name', sorted(_registry()))
    def test_every_registry_override_is_in_env_example(self, name):
        """`spec.py` is where an override is BORN — one `env='SS_X'` on a field."""
        assert name in _documented(), (
            f'{name} is env-overridable in lib/config/spec.py and is not in '
            f'docker/env.example — document it beside the setting it belongs to')

    @pytest.mark.parametrize('name', sorted(_entrypoint()))
    def test_every_entrypoint_variable_is_in_env_example(self, name):
        """The entrypoint's variables never reach the config registry: they are turned into
        command-line flags before the app starts, so this file is their only documentation."""
        assert name in _documented(), (
            f'{name} is read by docker/entrypoint.sh and is not in docker/env.example')

    @pytest.mark.parametrize('name', sorted(_read_from_environ()))
    def test_every_variable_read_from_the_environment_is_in_env_example(self, name):
        assert name in _documented(), (
            f'{name} is read from os.environ and is not in docker/env.example')


class TestNothingIsDocumentedThatIsNotReal:
    """A name that no longer exists reads as supported, gets set, and does nothing."""

    def test_every_documented_name_is_read_by_something(self):
        unknown = sorted(_assigned() - _supported() - COMPOSE_ONLY)
        assert not unknown, (
            f'docker/env.example documents {unknown}, which nothing reads — remove them, or '
            f'add them to COMPOSE_ONLY with the reason if Compose consumes them')

    def test_the_compose_only_names_are_still_used(self):
        """The exception list is where this guard would die quietly: an entry kept after its
        variable is gone excuses a name that no longer means anything."""
        haystack = '\n'.join(
            _read(os.path.join(DOCKER, f)) for f in sorted(os.listdir(DOCKER))
            if f.endswith(('.yml', '.yaml', '.sh')))
        haystack += _read(os.path.join(SRC, 'lib', 'config', '__init__.py'))
        stale = [n for n in sorted(COMPOSE_ONLY) if n not in haystack]
        assert not stale, f'COMPOSE_ONLY still lists {stale}, used by nothing'


def test_the_scan_actually_finds_things():
    """Guard the guard: three empty sets would make every test above pass vacuously."""
    assert len(_registry()) > 30
    assert len(_entrypoint()) > 5
    assert len(_read_from_environ()) > 5
    assert len(_documented()) > 40
    assert len(_assigned()) > 40
