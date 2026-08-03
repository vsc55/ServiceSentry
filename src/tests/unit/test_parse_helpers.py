#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para los helpers estáticos _parse_conf_* de ModuleBase."""

import pytest
from lib.modules.module_base import ModuleBase


class TestParseConfInt:

    def test_valid_integer_string(self):
        assert ModuleBase._parse_conf_int("5", 10) == 5

    def test_valid_integer(self):
        assert ModuleBase._parse_conf_int(5, 10) == 5

    def test_zero_returns_default(self):
        assert ModuleBase._parse_conf_int("0", 10) == 10

    def test_negative_returns_default(self):
        assert ModuleBase._parse_conf_int("-1", 10) == 10

    def test_empty_string_returns_default(self):
        assert ModuleBase._parse_conf_int("", 10) == 10

    def test_whitespace_string_returns_default(self):
        assert ModuleBase._parse_conf_int("  ", 10) == 10

    def test_non_numeric_returns_default(self):
        assert ModuleBase._parse_conf_int("abc", 10) == 10

    def test_float_string_returns_default(self):
        assert ModuleBase._parse_conf_int("3.14", 10) == 10

    def test_large_number(self):
        assert ModuleBase._parse_conf_int("99999", 10) == 99999

    def test_one_is_valid(self):
        assert ModuleBase._parse_conf_int("1", 10) == 1

    def test_custom_min_val_above(self):
        assert ModuleBase._parse_conf_int("5", 10, min_val=5) == 5

    def test_custom_min_val_below(self):
        assert ModuleBase._parse_conf_int("4", 10, min_val=5) == 10

    def test_min_val_zero_allows_zero(self):
        assert ModuleBase._parse_conf_int("0", 10, min_val=0) == 0

    def test_with_whitespace(self):
        assert ModuleBase._parse_conf_int(" 7 ", 10) == 7

    def test_none_returns_default(self):
        assert ModuleBase._parse_conf_int(None, 10) == 10

    def test_bool_true_returns_default(self):
        # str(True) = "True", which is not numeric
        assert ModuleBase._parse_conf_int(True, 10) == 10


class TestParseConfFloat:

    def test_valid_float_string(self):
        assert ModuleBase._parse_conf_float("3.14", 10.0) == 3.14

    def test_valid_integer_string(self):
        assert ModuleBase._parse_conf_float("5", 10.0) == 5.0

    def test_zero_returns_default(self):
        assert ModuleBase._parse_conf_float("0", 10.0) == 10.0

    def test_negative_returns_default(self):
        assert ModuleBase._parse_conf_float("-1", 10.0) == 10.0

    def test_empty_string_returns_default(self):
        assert ModuleBase._parse_conf_float("", 10.0) == 10.0

    def test_non_numeric_returns_default(self):
        assert ModuleBase._parse_conf_float("abc", 10.0) == 10.0

    def test_positive_float(self):
        assert ModuleBase._parse_conf_float("80.5", 50.0) == 80.5

    def test_small_positive(self):
        assert ModuleBase._parse_conf_float("0.1", 50.0) == 0.1

    def test_with_whitespace(self):
        assert ModuleBase._parse_conf_float(" 42.5 ", 10.0) == 42.5

    def test_none_returns_default(self):
        assert ModuleBase._parse_conf_float(None, 10.0) == 10.0


class TestParseConfStr:

    def test_valid_string(self):
        assert ModuleBase._parse_conf_str("hello", "default") == "hello"

    def test_empty_string_returns_default(self):
        assert ModuleBase._parse_conf_str("", "default") == "default"

    def test_whitespace_returns_default(self):
        assert ModuleBase._parse_conf_str("  ", "default") == "default"

    def test_strips_whitespace(self):
        assert ModuleBase._parse_conf_str("  hello  ", "default") == "hello"

    def test_no_default(self):
        assert ModuleBase._parse_conf_str("hello") == "hello"

    def test_empty_no_default(self):
        assert ModuleBase._parse_conf_str("") == ""

    def test_none_converted_to_string(self):
        # str(None) = "None" which is non-empty, so it returns "None"
        assert ModuleBase._parse_conf_str(None, "default") == "None"

    def test_number_converted_to_string(self):
        assert ModuleBase._parse_conf_str(42, "default") == "42"

    def test_bool_converted_to_string(self):
        assert ModuleBase._parse_conf_str(True, "default") == "True"
