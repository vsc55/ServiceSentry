#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para la clase Switch."""

import pytest
from lib.switch import Switch


class TestSwitchBasic:
    """Tests de comparación básica de valores."""

    def test_match_integer(self):
        with Switch(5) as case:
            if case(5):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"

    def test_no_match_integer(self):
        with Switch(5) as case:
            if case(3):
                result = "matched"
            else:
                result = "not matched"
        assert result == "not matched"

    def test_match_multiple_values(self):
        with Switch(2) as case:
            if case(1, 2, 3):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"

    def test_match_string(self):
        with Switch("hello") as case:
            if case("hello"):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"

    def test_no_match_string(self):
        with Switch("hello") as case:
            if case("world"):
                result = "matched"
            else:
                result = "not matched"
        assert result == "not matched"

    def test_elif_chain(self):
        with Switch(3) as case:
            if case(1):
                result = "one"
            elif case(2):
                result = "two"
            elif case(3):
                result = "three"
            else:
                result = "other"
        assert result == "three"

    def test_else_branch(self):
        with Switch(99) as case:
            if case(1):
                result = "one"
            elif case(2):
                result = "two"
            else:
                result = "other"
        assert result == "other"

    def test_none_value(self):
        with Switch(None) as case:
            if case(None):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"

    def test_bool_value(self):
        with Switch(True) as case:
            if case(True):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"


class TestSwitchIgnoreCase:
    """Tests con invariant_culture_ignore_case."""

    def test_case_insensitive_match(self):
        with Switch("Hello", invariant_culture_ignore_case=True) as case:
            if case("hello"):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"

    def test_case_insensitive_upper(self):
        with Switch("HELLO", invariant_culture_ignore_case=True) as case:
            if case("hello"):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"

    def test_case_sensitive_no_match(self):
        with Switch("Hello", invariant_culture_ignore_case=False) as case:
            if case("hello"):
                result = "matched"
            else:
                result = "not matched"
        assert result == "not matched"


class TestSwitchIsInstance:
    """Tests con check_isinstance."""

    def test_isinstance_string(self):
        with Switch("hello", check_isinstance=True) as case:
            if case(str):
                result = "string"
            elif case(int):
                result = "int"
            else:
                result = "other"
        assert result == "string"

    def test_isinstance_int(self):
        with Switch(42, check_isinstance=True) as case:
            if case(str):
                result = "string"
            elif case(int):
                result = "int"
            else:
                result = "other"
        assert result == "int"

    def test_isinstance_list(self):
        with Switch([1, 2], check_isinstance=True) as case:
            if case(str):
                result = "string"
            elif case(int, float):
                result = "number"
            elif case(list):
                result = "list"
            else:
                result = "other"
        assert result == "list"

    def test_isinstance_dict(self):
        with Switch({}, check_isinstance=True) as case:
            if case(list):
                result = "list"
            elif case(dict):
                result = "dict"
            else:
                result = "other"
        assert result == "dict"

    def test_isinstance_multiple_types(self):
        with Switch(3.14, check_isinstance=True) as case:
            if case(int, float):
                result = "number"
            else:
                result = "other"
        assert result == "number"


class TestSwitchContain:
    """Tests con check_contain."""

    def test_contain_match(self):
        with Switch("hello world", check_contain=True) as case:
            if case("world"):
                result = "matched"
            else:
                result = "not matched"
        assert result == "matched"

    def test_contain_no_match(self):
        with Switch("hello world", check_contain=True) as case:
            if case("foo"):
                result = "matched"
            else:
                result = "not matched"
        assert result == "not matched"

    def test_contain_multiple(self):
        with Switch("error 2003 connection", check_contain=True) as case:
            if case("timed out"):
                result = "timeout"
            elif case("2003"):
                result = "conn_error"
            else:
                result = "other"
        assert result == "conn_error"


class TestSwitchContextManager:
    """Tests del context manager."""

    def test_exit_returns_false(self):
        """__exit__ debe retornar False para permitir propagación de excepciones."""
        s = Switch(1)
        assert s.__exit__(None, None, None) is False
