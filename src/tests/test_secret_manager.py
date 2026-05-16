#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for lib/secret_manager.py.

Covers: fernet_from_secret_file, decrypt_all, encrypt_sensitive, and
enc:-prefix injection attack scenarios.
"""

import secrets

import pytest

from lib.secret_manager import (
    ENCRYPT_KEYS,
    ENC_PREFIX,
    decrypt_all,
    encrypt_sensitive,
    fernet_from_secret_file,
)

cryptography = pytest.importorskip("cryptography", reason="cryptography not installed")


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_secret_file(tmp_path):
    """Write a valid 64-hex-char secret file and return its path."""
    path = tmp_path / ".flask_secret"
    path.write_text(secrets.token_hex(32), encoding="utf-8")
    return str(path)


def _make_fernet(tmp_path):
    path = _make_secret_file(tmp_path)
    return fernet_from_secret_file(path), path


# ── fernet_from_secret_file ───────────────────────────────────────────────────


class TestFernetFromSecretFile:

    def test_returns_fernet_for_valid_file(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        assert fernet is not None

    def test_can_encrypt_and_decrypt_with_returned_fernet(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        token = fernet.encrypt(b"hello")
        assert fernet.decrypt(token) == b"hello"

    def test_returns_none_for_missing_file(self, tmp_path):
        result = fernet_from_secret_file(str(tmp_path / "does_not_exist"))
        assert result is None

    def test_returns_none_for_invalid_hex(self, tmp_path):
        path = tmp_path / ".flask_secret"
        path.write_text("not-valid-hex!!", encoding="utf-8")
        assert fernet_from_secret_file(str(path)) is None

    def test_returns_none_for_empty_file(self, tmp_path):
        path = tmp_path / ".flask_secret"
        path.write_text("", encoding="utf-8")
        assert fernet_from_secret_file(str(path)) is None

    def test_two_instances_from_same_file_are_compatible(self, tmp_path):
        path = _make_secret_file(tmp_path)
        f1 = fernet_from_secret_file(path)
        f2 = fernet_from_secret_file(path)
        token = f1.encrypt(b"data")
        assert f2.decrypt(token) == b"data"


# ── decrypt_all ───────────────────────────────────────────────────────────────


class TestDecryptAll:

    def test_decrypts_valid_token(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        token = ENC_PREFIX + fernet.encrypt(b"secret123").decode()
        result = decrypt_all({"password": token}, fernet)
        assert result["password"] == "secret123"

    def test_plain_string_unchanged(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        result = decrypt_all({"host": "192.168.1.1"}, fernet)
        assert result["host"] == "192.168.1.1"

    def test_malformed_enc_token_kept_as_is(self, tmp_path):
        """A bad enc: value must NOT crash — original string must be preserved."""
        fernet, _ = _make_fernet(tmp_path)
        bad = {"password": "enc:this-is-not-a-valid-fernet-token"}
        result = decrypt_all(bad, fernet)
        assert result["password"] == "enc:this-is-not-a-valid-fernet-token"

    def test_nested_dict_decrypted(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        token = ENC_PREFIX + fernet.encrypt(b"pass").decode()
        data = {"db": {"list": {"db1": {"password": token}}}}
        decrypt_all(data, fernet)
        assert data["db"]["list"]["db1"]["password"] == "pass"

    def test_nested_list_decrypted(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        token = ENC_PREFIX + fernet.encrypt(b"val").decode()
        data = [{"password": token}, {"host": "localhost"}]
        decrypt_all(data, fernet)
        assert data[0]["password"] == "val"
        assert data[1]["host"] == "localhost"

    def test_none_fernet_does_not_crash(self):
        """When fernet is None, decrypt_all must not raise."""
        data = {"password": "enc:something", "host": "x"}
        result = decrypt_all(data, None)
        assert result["password"] == "enc:something"

    def test_non_string_values_unchanged(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        data = {"enabled": True, "port": 3306, "ratio": 0.5, "tags": None}
        result = decrypt_all(data, fernet)
        assert result == {"enabled": True, "port": 3306, "ratio": 0.5, "tags": None}

    def test_modifies_dict_in_place_and_returns_it(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        token = ENC_PREFIX + fernet.encrypt(b"x").decode()
        data = {"password": token}
        returned = decrypt_all(data, fernet)
        assert returned is data
        assert data["password"] == "x"


# ── encrypt_sensitive ─────────────────────────────────────────────────────────


class TestEncryptSensitive:

    def test_sensitive_key_encrypted(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        result = encrypt_sensitive({"password": "plain"}, fernet)
        assert result["password"].startswith(ENC_PREFIX)

    def test_non_sensitive_key_unchanged(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        result = encrypt_sensitive({"host": "192.168.1.1"}, fernet)
        assert result["host"] == "192.168.1.1"

    def test_all_encrypt_keys_are_encrypted(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        data = {k: "value" for k in ENCRYPT_KEYS}
        result = encrypt_sensitive(data, fernet)
        for k in ENCRYPT_KEYS:
            assert result[k].startswith(ENC_PREFIX), f"key '{k}' was not encrypted"

    def test_already_encrypted_value_not_re_encrypted(self, tmp_path):
        """Values already starting with enc: must pass through unchanged."""
        fernet, _ = _make_fernet(tmp_path)
        already = ENC_PREFIX + fernet.encrypt(b"original").decode()
        result = encrypt_sensitive({"password": already}, fernet)
        assert result["password"] == already

    def test_empty_string_not_encrypted(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        result = encrypt_sensitive({"password": ""}, fernet)
        assert result["password"] == ""

    def test_nested_dict_sensitive_fields_encrypted(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        data = {"db": {"list": {"db1": {"password": "s3cr3t", "host": "localhost"}}}}
        result = encrypt_sensitive(data, fernet)
        assert result["db"]["list"]["db1"]["password"].startswith(ENC_PREFIX)
        assert result["db"]["list"]["db1"]["host"] == "localhost"

    def test_returns_new_dict_does_not_mutate_input(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        original = {"password": "plain"}
        result = encrypt_sensitive(original, fernet)
        assert original["password"] == "plain"
        assert result["password"].startswith(ENC_PREFIX)

    def test_none_fernet_returns_data_unchanged(self):
        """When fernet is None, encryption must silently skip."""
        result = encrypt_sensitive({"password": "plain"}, None)
        assert result["password"] == "plain"

    def test_roundtrip_encrypt_then_decrypt(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        original = "my-super-secret-password"
        encrypted = encrypt_sensitive({"password": original}, fernet)
        decrypted = decrypt_all(encrypted, fernet)
        assert decrypted["password"] == original

    def test_roundtrip_all_encrypt_keys(self, tmp_path):
        fernet, _ = _make_fernet(tmp_path)
        data = {k: f"value-for-{k}" for k in ENCRYPT_KEYS}
        decrypted = decrypt_all(encrypt_sensitive(data, fernet), fernet)
        for k in ENCRYPT_KEYS:
            assert decrypted[k] == f"value-for-{k}"


# ── enc: injection attack scenarios ──────────────────────────────────────────


class TestEncPrefixInjection:
    """Verify the enc: prefix cannot be abused to bypass or corrupt encryption."""

    def test_injected_bad_enc_token_not_decrypted_to_garbage(self, tmp_path):
        """
        Attacker sends 'enc:invalid' in a config field.
        decrypt_all must preserve the raw string on failure — not crash or
        return an empty / wrong value.
        """
        fernet, _ = _make_fernet(tmp_path)
        payload = {"password": "enc:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}
        result = decrypt_all(payload, fernet)
        assert result["password"].startswith("enc:")

    def test_injected_enc_value_not_re_encrypted(self, tmp_path):
        """
        An enc:-prefixed value (even attacker-crafted) must pass through
        encrypt_sensitive unchanged — no double-encoding.
        """
        fernet, _ = _make_fernet(tmp_path)
        fake = "enc:attacker-controlled-garbage"
        result = encrypt_sensitive({"password": fake}, fernet)
        assert result["password"] == fake

    def test_fake_enc_sibling_does_not_affect_legitimate_encryption(self, tmp_path):
        """A fake enc: value in one field must not corrupt a real value in another."""
        fernet, _ = _make_fernet(tmp_path)
        data = {
            "password": "real-password",
            "ssh_password": "enc:fake-injected-value",
        }
        result = encrypt_sensitive(data, fernet)
        assert result["password"].startswith("enc:")
        assert result["ssh_password"] == "enc:fake-injected-value"
        # Real password decrypts correctly
        assert decrypt_all({"password": result["password"]}, fernet)["password"] == "real-password"

    def test_enc_prefix_in_non_sensitive_key_never_decrypted(self, tmp_path):
        """enc: in a non-sensitive key (e.g. 'host') is left completely untouched."""
        fernet, _ = _make_fernet(tmp_path)
        data = {"host": "enc:looks-like-encrypted-but-not-a-sensitive-key"}
        encrypted = encrypt_sensitive(data, fernet)
        assert encrypted["host"] == "enc:looks-like-encrypted-but-not-a-sensitive-key"
        decrypted = decrypt_all(encrypted, fernet)
        assert decrypted["host"].startswith("enc:")
