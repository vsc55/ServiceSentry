#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para la clase Debug."""

import pytest

from lib.debug.debug import Debug
from lib.debug.debug_level import DebugLevel


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
