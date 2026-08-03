#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the central config registry (lib.config.spec) and the small
schema-aware helpers added around it: cfg_default, cfg_get, cfg_validate,
normalize_url, frontend_schema, the derived rule dicts, coerce_lang and
track_change.

Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_config_spec.py`` lives in
``tests/unit/test_config_spec.py``."""


import pytest

from lib.config.spec import cfg_validate, normalize_url, frontend_schema, int_rules, json_dict_fields, env_field_specs
























class TestTheKeyFileHasOneName:
    """`.flask_secret` signs Flask's session cookies AND derives the Fernet key every stored
    secret is encrypted with — losing it is not "sign in again", it is every secret in the
    database becoming unreadable.

    Its name was spelled out in six places: the panel, the CLI and the four standalone
    services. One spelling away from a process that derives a different key, decrypts nothing,
    and reports the config as empty rather than as broken.
    """

    def test_only_the_registry_names_it(self):
        import io
        import os
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        spelled = []
        for base, dirs, files in os.walk(os.path.join(src, 'lib')):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for name in files:
                if not name.endswith('.py'):
                    continue
                path = os.path.join(base, name)
                if "'.flask_secret'" in io.open(path, encoding='utf-8').read():
                    spelled.append(os.path.relpath(path, src))
        assert spelled == [os.path.join('lib', 'config', '__init__.py')], spelled

    def test_the_helper_and_the_panel_agree(self):
        from lib.config import SECRET_KEY_FILENAME, secret_key_path
        # importorskip: el panel arrastra Flask, que puede no estar en una instalación slim.
        WebAdmin = pytest.importorskip('lib.web_admin.app').WebAdmin
        assert WebAdmin._SECRET_KEY_FILE == SECRET_KEY_FILENAME
        assert secret_key_path('/x').endswith(SECRET_KEY_FILENAME)


