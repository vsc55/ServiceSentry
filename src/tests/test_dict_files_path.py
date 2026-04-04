#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para la clase DictFilesPath."""

import pytest
from lib.dict_files_path import DictFilesPath


class TestDictFilesPath:

    def setup_method(self):
        self.d = DictFilesPath()

    def test_initial_empty(self):
        assert self.d.files == {}

    def test_set_file(self):
        assert self.d.set("test", "/tmp/test") is True
        assert self.d.files == {"test": "/tmp/test"}

    def test_set_overwrite(self):
        self.d.set("test", "/tmp/test1")
        self.d.set("test", "/tmp/test2")
        assert self.d.files["test"] == "/tmp/test2"

    def test_set_empty_name_returns_false(self):
        assert self.d.set("", "/tmp/test") is False
        assert self.d.set(None, "/tmp/test") is False

    def test_set_multiple_files(self):
        self.d.set("a", "/path/a")
        self.d.set("b", "/path/b")
        assert len(self.d.files) == 2

    def test_is_exist_true(self):
        self.d.set("test", "/tmp/test")
        assert self.d.is_exist("test") is True

    def test_is_exist_false(self):
        assert self.d.is_exist("nonexistent") is False

    def test_is_exist_none(self):
        assert self.d.is_exist(None) is False

    def test_is_exist_empty(self):
        assert self.d.is_exist("") is False

    def test_find_existing(self):
        self.d.set("test", "/tmp/test")
        assert self.d.find("test") == "/tmp/test"

    def test_find_nonexistent_returns_default(self):
        assert self.d.find("nonexistent", "/dev/null") == "/dev/null"

    def test_find_nonexistent_returns_empty_string(self):
        assert self.d.find("nonexistent") == ""

    def test_remove_existing(self):
        self.d.set("test", "/tmp/test")
        assert self.d.remove("test") is True
        assert self.d.is_exist("test") is False

    def test_remove_nonexistent(self):
        assert self.d.remove("nonexistent") is False

    def test_clear(self):
        self.d.set("a", "/a")
        self.d.set("b", "/b")
        self.d.clear()
        assert self.d.files == {}
