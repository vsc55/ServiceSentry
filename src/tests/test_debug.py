#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para la clase Debug."""

import io
import sys

from lib.debug.debug import Debug
from lib.debug.debug_level import DebugLevel


class _TtyIO(io.StringIO):
    """A StringIO that claims to be a TTY (to exercise the colour path)."""
    def isatty(self):
        return True


class TestDebug:

    def test_default_enabled(self):
        d = Debug()
        assert d.enabled is True

    def test_default_level(self):
        d = Debug()
        assert d.level == DebugLevel.info

    def test_set_enabled(self):
        d = Debug(enable=False)
        assert d.enabled is False

    def test_set_level(self):
        d = Debug(level=DebugLevel.debug)
        assert d.level == DebugLevel.debug

    def test_print_shows_message_when_enabled(self, capsys):
        d = Debug(True, DebugLevel.debug)
        d.print("test message", DebugLevel.debug)
        captured = capsys.readouterr()
        assert "test message" in captured.out

    def test_print_hides_message_when_disabled(self, capsys):
        d = Debug(False, DebugLevel.debug)
        d.print("test message", DebugLevel.debug)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_hides_message_below_level(self, capsys):
        d = Debug(True, DebugLevel.error)
        d.print("debug message", DebugLevel.debug)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_shows_message_at_level(self, capsys):
        d = Debug(True, DebugLevel.info)
        d.print("info message", DebugLevel.info)
        captured = capsys.readouterr()
        assert "info message" in captured.out

    def test_print_shows_message_above_level(self, capsys):
        d = Debug(True, DebugLevel.debug)
        d.print("error message", DebugLevel.error)
        captured = capsys.readouterr()
        assert "error message" in captured.out

    def test_print_force_bypasses_disabled(self, capsys):
        """force=True bypasses enabled=False and shows the message."""
        d = Debug(False, DebugLevel.error)
        d.print("forced message", DebugLevel.debug, force=True)
        captured = capsys.readouterr()
        assert "forced message" in captured.out

    def test_print_force_bypasses_level(self, capsys):
        """force=True bypasses level restriction when enabled=True."""
        d = Debug(True, DebugLevel.error)
        d.print("forced message", DebugLevel.debug, force=True)
        captured = capsys.readouterr()
        assert "forced message" in captured.out

    def test_print_non_string(self, capsys):
        d = Debug(True, DebugLevel.debug)
        d.print({"key": "value"}, DebugLevel.debug)
        captured = capsys.readouterr()
        assert "key" in captured.out

    def test_exception_prints_traceback(self, capsys):
        d = Debug()
        try:
            raise ValueError("test error")
        except ValueError as e:
            d.exception(e)
        captured = capsys.readouterr()
        assert "test error" in captured.out
        assert "Exception" in captured.out

    def test_exception_without_arg(self, capsys):
        d = Debug()
        try:
            raise ValueError("test")
        except ValueError:
            d.exception()
        captured = capsys.readouterr()
        assert "Exception in user code" in captured.out

    def test_debug_obj(self, capsys):
        d = Debug(True, DebugLevel.debug)
        d.debug_obj("test_module", {"a": 1}, "Test Data")
        captured = capsys.readouterr()
        assert "test_module" in captured.out
        assert "Test Data" in captured.out
        assert "'a': 1" in captured.out


class TestSetFromConfig:

    def test_off_disables(self):
        d = Debug(True, DebugLevel.info)
        d.set_from_config('off')
        assert d.enabled is False

    def test_empty_disables(self):
        d = Debug(True)
        d.set_from_config('')
        assert d.enabled is False

    def test_each_level(self):
        for name, lvl in [('debug', DebugLevel.debug), ('info', DebugLevel.info),
                          ('warning', DebugLevel.warning), ('error', DebugLevel.error)]:
            d = Debug(False, DebugLevel.info)
            d.set_from_config(name)
            assert d.enabled is True and d.level == lvl

    def test_unknown_enables_at_info(self):
        d = Debug(False)
        d.set_from_config('bogus')
        assert d.enabled is True and d.level == DebugLevel.info


class TestLevelPrefix:

    def test_prefix_present(self, capsys):
        Debug(True, DebugLevel.debug).print('hello', DebugLevel.warning)
        out = capsys.readouterr().out
        assert '[WARNING]' in out and 'hello' in out

    def test_no_ansi_when_not_tty(self, capsys):
        # capsys' stdout is not a TTY → output must be plain (safe for log files).
        Debug(True, DebugLevel.debug).print('hello', DebugLevel.error)
        assert '\033[' not in capsys.readouterr().out


class TestColour:

    def test_colour_on_tty(self, monkeypatch):
        buf = _TtyIO()
        monkeypatch.setattr(sys, 'stdout', buf)
        try:
            Debug.set_color(True)
            Debug(True, DebugLevel.error).print('x', DebugLevel.error)
        finally:
            Debug.set_color(True)
        assert '\033[' in buf.getvalue()

    def test_nocolor_disables_even_on_tty(self, monkeypatch):
        buf = _TtyIO()
        monkeypatch.setattr(sys, 'stdout', buf)
        try:
            Debug.set_color(False)
            Debug(True, DebugLevel.error).print('x', DebugLevel.error)
            out = buf.getvalue()
        finally:
            Debug.set_color(True)
        assert '\033[' not in out and '[ERROR' in out
