#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the SS_* environment-variable fallbacks of the CLI arguments
(used for Docker) and the NO_COLOR standard."""

import main

_SS_VARS = ['SS_WEB', 'SS_WEB_PORT', 'SS_WEB_HOST', 'SS_VERBOSE', 'SS_NOCOLOR',
            'SS_MONITOR', 'SS_TIMER', 'SS_CONFIG_DIR', 'SS_LANG', 'SS_LOG_LEVEL',
            'SS_SYSLOG_HOST', 'SS_SYSLOG_PORT', 'NO_COLOR']


def _clear_env(monkeypatch):
    for k in _SS_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr('sys.argv', ['main.py'])


def test_defaults_without_env(monkeypatch):
    _clear_env(monkeypatch)
    a = main.args_init()
    assert a.web_mode is False
    assert a.web_port is None
    assert a.web_host is None
    assert a.verbose is False
    assert a.nocolor is False
    assert a.monitor_mode is False
    assert a.timer_check is None
    assert a.path is None


def test_env_maps_to_args(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv('SS_WEB', 'true')
    monkeypatch.setenv('SS_WEB_PORT', '9090')
    monkeypatch.setenv('SS_WEB_HOST', '127.0.0.1')
    monkeypatch.setenv('SS_VERBOSE', '1')
    monkeypatch.setenv('SS_MONITOR', 'yes')
    monkeypatch.setenv('SS_TIMER', '120')
    a = main.args_init()
    assert a.web_mode is True
    assert a.web_port == 9090 and isinstance(a.web_port, int)
    assert a.web_host == '127.0.0.1'
    assert a.verbose is True
    assert a.monitor_mode is True
    assert a.timer_check == 120


def test_nocolor_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv('SS_NOCOLOR', '1')
    assert main.args_init().nocolor is True


def test_no_color_standard_env(monkeypatch):
    """The de-facto NO_COLOR standard: present (non-empty) disables colour."""
    _clear_env(monkeypatch)
    monkeypatch.setenv('NO_COLOR', '1')
    assert main.args_init().nocolor is True


def test_bool_falsey_values(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv('SS_WEB', 'false')
    monkeypatch.setenv('SS_VERBOSE', '0')
    a = main.args_init()
    assert a.web_mode is False and a.verbose is False


def test_cli_flag_overrides_absent_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr('sys.argv', ['main.py', '--web', '--web-port', '7000'])
    a = main.args_init()
    assert a.web_mode is True and a.web_port == 7000
