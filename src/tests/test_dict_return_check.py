#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para la clase ReturnModuleCheck."""

import pytest
from lib.modules.dict_return_check import ReturnModuleCheck


class TestReturnModuleCheck:

    def setup_method(self):
        self.r = ReturnModuleCheck()

    def test_initial_empty(self):
        assert self.r.count == 0
        assert self.r.list == {}

    def test_set_basic(self):
        assert self.r.set("key1", True, "OK") is True
        assert self.r.count == 1

    def test_set_and_get(self):
        self.r.set("k", True, "msg ok")
        data = self.r.get("k")
        assert data['status'] is True
        assert data['message'] == "msg ok"
        assert data['send'] is True

    def test_set_with_send_false(self):
        self.r.set("k", True, "msg", send_msg=False)
        assert self.r.get_send("k") is False

    def test_set_with_other_data(self):
        extra = {'temp': 50, 'alert': 80}
        self.r.set("k", True, "msg", other_data=extra)
        assert self.r.get_other_data("k") == extra

    def test_set_empty_key_returns_false(self):
        assert self.r.set("", True, "msg") is False
        assert self.r.set(None, True, "msg") is False

    def test_set_overwrites(self):
        self.r.set("k", True, "first")
        self.r.set("k", False, "second")
        assert self.r.get_status("k") is False
        assert self.r.get_message("k") == "second"
        assert self.r.count == 1

    def test_is_exist(self):
        self.r.set("k", True, "msg")
        assert self.r.is_exist("k") is True
        assert self.r.is_exist("nonexistent") is False

    def test_get_status(self):
        self.r.set("ok", True, "msg")
        self.r.set("fail", False, "msg")
        assert self.r.get_status("ok") is True
        assert self.r.get_status("fail") is False
        assert self.r.get_status("nonexistent") is False

    def test_get_message(self):
        self.r.set("k", True, "hello world")
        assert self.r.get_message("k") == "hello world"
        assert self.r.get_message("nonexistent") == ""

    def test_get_nonexistent(self):
        assert self.r.get("nonexistent") == {}

    def test_update_status(self):
        self.r.set("k", True, "msg")
        assert self.r.update("k", "status", False) is True
        assert self.r.get_status("k") is False

    def test_update_message(self):
        self.r.set("k", True, "old")
        assert self.r.update("k", "message", "new") is True
        assert self.r.get_message("k") == "new"

    def test_update_invalid_option(self):
        self.r.set("k", True, "msg")
        assert self.r.update("k", "invalid_option", "val") is False

    def test_update_nonexistent_key(self):
        assert self.r.update("nonexistent", "status", True) is False

    def test_update_empty_key(self):
        assert self.r.update("", "status", True) is False

    def test_remove(self):
        self.r.set("k", True, "msg")
        assert self.r.remove("k") is True
        assert self.r.is_exist("k") is False
        assert self.r.count == 0

    def test_remove_nonexistent(self):
        assert self.r.remove("nonexistent") is False

    def test_items(self):
        self.r.set("a", True, "msg_a")
        self.r.set("b", False, "msg_b")
        keys = [k for k, v in self.r.items()]
        assert "a" in keys
        assert "b" in keys

    def test_keys(self):
        self.r.set("a", True, "msg_a")
        self.r.set("b", False, "msg_b")
        assert set(self.r.keys()) == {"a", "b"}

    def test_multiple_entries(self):
        for i in range(10):
            self.r.set(f"key_{i}", i % 2 == 0, f"msg_{i}")
        assert self.r.count == 10
        assert self.r.get_status("key_0") is True
        assert self.r.get_status("key_1") is False

    def test_other_data_default_empty(self):
        self.r.set("k", True, "msg")
        assert self.r.get_other_data("k") == {}
        assert self.r.get_other_data("nonexistent") == {}
