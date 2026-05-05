#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the configurable password policy (_validate_password + API enforcement)."""

import json
import pathlib

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_ADMIN_HASH = generate_password_hash("Admin123!", method="pbkdf2:sha256")


def _make_wa(config_dir, var_dir, **policy):
    """Create a WebAdmin instance with admin user pre-seeded and given policy."""
    users = {
        "admin": {
            "password_hash": _ADMIN_HASH,
            "role": "admin",
            "display_name": "Administrator",
        }
    }
    (pathlib.Path(config_dir) / "users.json").write_text(
        json.dumps(users), encoding="utf-8"
    )
    wa = WebAdmin(config_dir, "admin", "Admin123!", var_dir, **policy)
    wa.app.config["TESTING"] = True
    return wa


# ──────────────────────────── _validate_password unit tests ────────


class TestValidatePasswordUnit:
    """Direct calls to _validate_password — no HTTP stack needed."""

    def test_accepts_valid_password_no_policy(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir)
        assert wa._validate_password("Admin123!") is None  # meets all defaults

    def test_too_short(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_min_len=10)
        result = wa._validate_password("Short1!")
        assert result is not None
        assert result[0] == "password_too_short"
        assert result[1] == "10"

    def test_too_long(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_max_len=10)
        result = wa._validate_password("A" * 11)
        assert result is not None
        assert result[0] == "password_too_long"
        assert result[1] == "10"

    def test_exactly_min_len_accepted(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_min_len=6,
                      pw_require_upper=False, pw_require_digit=False)
        assert wa._validate_password("abcdef") is None

    def test_exactly_max_len_accepted(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_max_len=8,
                      pw_require_upper=False, pw_require_digit=False)
        assert wa._validate_password("abcdefgh") is None

    # ── require_upper ───────────────────────────────────────────────

    def test_require_upper_rejects_all_lower(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_upper=True)
        result = wa._validate_password("alllower1!")
        assert result is not None
        assert result[0] == "password_need_upper"

    def test_require_upper_rejects_all_upper(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_upper=True)
        result = wa._validate_password("ALLUPPER1!")
        assert result is not None
        assert result[0] == "password_need_upper"

    def test_require_upper_accepts_mixed_case(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_upper=True)
        assert wa._validate_password("MixedCase1") is None

    def test_no_require_upper_accepts_all_lower(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_upper=False)
        assert wa._validate_password("alllower1") is None

    # ── require_digit ───────────────────────────────────────────────

    def test_require_digit_rejects_no_digit(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_digit=True)
        result = wa._validate_password("NoDigitsHere!")
        assert result is not None
        assert result[0] == "password_need_digit"

    def test_require_digit_accepts_with_digit(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_digit=True)
        assert wa._validate_password("HasADigit1") is None

    def test_no_require_digit_accepts_no_digit(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_digit=False)
        assert wa._validate_password("NoDigitsHere") is None

    # ── require_symbol ──────────────────────────────────────────────

    def test_require_symbol_rejects_no_symbol(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_symbol=True)
        result = wa._validate_password("NoSymbols1A")
        assert result is not None
        assert result[0] == "password_need_symbol"

    def test_require_symbol_accepts_with_symbol(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_symbol=True)
        assert wa._validate_password("HasSymbol1!") is None

    def test_no_require_symbol_accepts_no_symbol(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_symbol=False)
        assert wa._validate_password("NoSymbols1A") is None

    # ── combined rules ──────────────────────────────────────────────

    def test_all_rules_enabled_accepts_strong_password(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir,
                      pw_min_len=8, pw_require_upper=True,
                      pw_require_digit=True, pw_require_symbol=True)
        assert wa._validate_password("Strong1!") is None

    def test_all_rules_enabled_rejects_missing_digit(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir,
                      pw_require_upper=True, pw_require_digit=True,
                      pw_require_symbol=True)
        result = wa._validate_password("NoDigitHere!")
        assert result is not None
        assert result[0] == "password_need_digit"

    def test_all_rules_enabled_rejects_missing_symbol(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir,
                      pw_require_upper=True, pw_require_digit=True,
                      pw_require_symbol=True)
        result = wa._validate_password("NoSymbol1Ab")
        assert result is not None
        assert result[0] == "password_need_symbol"

    def test_priority_length_before_complexity(self, config_dir, var_dir):
        """Length check must fire before complexity checks."""
        wa = _make_wa(config_dir, var_dir,
                      pw_min_len=12, pw_require_upper=True,
                      pw_require_digit=True, pw_require_symbol=True)
        result = wa._validate_password("Short1!")
        assert result is not None
        assert result[0] == "password_too_short"

    def test_returns_none_means_no_error(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir,
                      pw_min_len=4, pw_max_len=256,
                      pw_require_upper=False, pw_require_digit=False,
                      pw_require_symbol=False)
        assert wa._validate_password("anyp") is None


# ──────────────────────────── API enforcement tests ────────────────


class TestPasswordPolicyApi:
    """Policy enforcement via the HTTP API (create user, update user, change password)."""

    # ── POST /api/users ─────────────────────────────────────────────

    def test_create_user_rejects_short_password(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_min_len=12)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            resp = c.post("/api/users", json={
                "username": "u1", "password": "Short123!", "role": "viewer",
            })
        assert resp.status_code == 400
        assert "password" in resp.get_json().get("error", "").lower()

    def test_create_user_rejects_no_digit(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_digit=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            resp = c.post("/api/users", json={
                "username": "u2", "password": "NoDigitsHere!", "role": "viewer",
            })
        assert resp.status_code == 400
        assert "password" in resp.get_json().get("error", "").lower()

    def test_create_user_rejects_no_upper(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_upper=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            resp = c.post("/api/users", json={
                "username": "u3", "password": "alllower123!", "role": "viewer",
            })
        assert resp.status_code == 400

    def test_create_user_rejects_no_symbol(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_symbol=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            resp = c.post("/api/users", json={
                "username": "u4", "password": "NoSymbol1Abcd", "role": "viewer",
            })
        assert resp.status_code == 400

    def test_create_user_accepts_compliant_password(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir,
                      pw_require_upper=True, pw_require_digit=True,
                      pw_require_symbol=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            resp = c.post("/api/users", json={
                "username": "u5", "password": "Strong1!Aa", "role": "viewer",
            })
        assert resp.status_code == 201

    # ── PUT /api/users/<username> (password reset by admin) ─────────

    def test_update_password_rejects_policy_violation(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_digit=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            # first create the user with a valid password
            c.post("/api/users", json={
                "username": "victim", "password": "Admin123!", "role": "viewer",
            })
            resp = c.put("/api/users/victim", json={"password": "NoDigitHere!"})
        assert resp.status_code == 400

    def test_update_password_accepts_compliant_password(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_digit=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            c.post("/api/users", json={
                "username": "victim2", "password": "Admin123!", "role": "viewer",
            })
            resp = c.put("/api/users/victim2", json={"password": "HasDigit1A"})
        assert resp.status_code == 200

    # ── POST /api/users/me/password (change own password) ───────────

    def test_change_own_password_rejects_policy_violation(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_symbol=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            resp = c.put("/api/users/me/password", json={
                "current_password": "Admin123!",
                "new_password": "NoSymbol1Ab",
            })
        assert resp.status_code == 400

    def test_change_own_password_accepts_compliant_password(self, config_dir, var_dir):
        wa = _make_wa(config_dir, var_dir, pw_require_symbol=True)
        with wa.app.test_client() as c:
            _login(c, password="Admin123!")
            resp = c.put("/api/users/me/password", json={
                "current_password": "Admin123!",
                "new_password": "NewPass123!",
            })
        assert resp.status_code == 200
