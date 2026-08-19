#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A COSE key turned into something that can check a signature — and refusing the rest.

There is no published table to check this against the way RFC 6238 and RFC 8949 provide one,
so the vectors here are MADE: a real key pair is generated with `cryptography`, exported into
the COSE map an authenticator would send, and the signature it produces is checked through
this module. That is a round trip rather than an oracle, and it is honest about being one —
what it proves is that the labels are read as the standard numbers them, which is the half
that silently produces "signature invalid" for every user when it is wrong.

What is NOT a round trip, and matters more, is the second class: the algorithm is the one
recorded at REGISTRATION, never the one the key claims when the assertion arrives. A key that
picks its own algorithm at verification time is the JWT `alg` flaw wearing different words.

Flask-free, network-free, database-free.
"""

import pytest

from lib.core.mfa import cose

cryptography = pytest.importorskip('cryptography')

from cryptography.hazmat.primitives import hashes                       # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa  # noqa: E402


def _es256_key():
    priv = ec.generate_private_key(ec.SECP256R1())
    nums = priv.public_key().public_numbers()
    return priv, {1: cose.KTY_EC2, 3: cose.ES256, -1: cose.CRV_P256,
                  -2: nums.x.to_bytes(32, 'big'), -3: nums.y.to_bytes(32, 'big')}


def _ed25519_key():
    priv = ed25519.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)
    return priv, {1: cose.KTY_OKP, 3: cose.EdDSA, -1: cose.CRV_ED25519, -2: raw}


def _rs256_key(bits=2048):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    nums = priv.public_key().public_numbers()
    return priv, {1: cose.KTY_RSA, 3: cose.RS256,
                  -1: nums.n.to_bytes((nums.n.bit_length() + 7) // 8, 'big'),
                  -2: nums.e.to_bytes((nums.e.bit_length() + 7) // 8, 'big')}


DATA = b'authenticator data || client data hash'


class TestTheThreeAlgorithmsAuthenticatorsActuallySend:
    """ES256 is every security key; RS256 is what Windows Hello produced for years and what a
    lot of installed hardware still sends; EdDSA is the newer ones."""

    def test_es256_round_trips(self):
        priv, key = _es256_key()
        sig = priv.sign(DATA, ec.ECDSA(hashes.SHA256()))
        assert cose.verify(key, cose.ES256, sig, DATA) is True

    def test_ed25519_round_trips(self):
        priv, key = _ed25519_key()
        assert cose.verify(key, cose.EdDSA, priv.sign(DATA), DATA) is True

    def test_rs256_round_trips(self):
        priv, key = _rs256_key()
        sig = priv.sign(DATA, padding.PKCS1v15(), hashes.SHA256())
        assert cose.verify(key, cose.RS256, sig, DATA) is True

    @pytest.mark.parametrize('maker,alg', [(_es256_key, cose.ES256),
                                           (_ed25519_key, cose.EdDSA)])
    def test_a_signature_over_something_else_does_not_verify(self, maker, alg):
        priv, key = maker()
        sig = priv.sign(b'other data', ec.ECDSA(hashes.SHA256())) if alg == cose.ES256 \
            else priv.sign(b'other data')
        assert cose.verify(key, alg, sig, DATA) is False

    def test_another_keys_signature_does_not_verify(self):
        priv, _key = _es256_key()
        _other_priv, other_key = _es256_key()
        sig = priv.sign(DATA, ec.ECDSA(hashes.SHA256()))
        assert cose.verify(other_key, cose.ES256, sig, DATA) is False


class TestTheAlgorithmIsTheOneRegistered:
    """A key that chooses its own algorithm when the assertion arrives is the JWT `alg` flaw
    with different words: whoever presents the assertion picks how it is checked."""

    def test_a_key_that_disagrees_with_what_was_registered_is_refused(self):
        _priv, key = _es256_key()
        key[3] = cose.RS256                      # the key now claims something else
        with pytest.raises(cose.CoseError):
            cose.public_key(key, cose.ES256)

    def test_an_algorithm_that_is_not_supported_is_refused_rather_than_guessed(self):
        """One this cannot check is one whose signature it would have to take on trust."""
        _priv, key = _es256_key()
        for alg in (0, -35, -36, -257 + 1, 999, None):
            with pytest.raises(cose.CoseError):
                cose.public_key(key, alg)

    def test_a_key_with_no_alg_label_is_accepted_under_the_registered_one(self):
        """Not every authenticator fills it in, and the stored value is the authority."""
        priv, key = _es256_key()
        del key[3]
        sig = priv.sign(DATA, ec.ECDSA(hashes.SHA256()))
        assert cose.verify(key, cose.ES256, sig, DATA) is True


class TestAKeyThatIsNotOneIsRefused:

    @pytest.mark.parametrize('key', [None, [], b'', 'x', {}, {1: 2}])
    def test_shapes_that_are_not_a_cose_key(self, key):
        with pytest.raises(cose.CoseError):
            cose.public_key(key, cose.ES256)

    def test_the_wrong_curve_for_the_algorithm(self):
        _priv, key = _es256_key()
        key[-1] = cose.CRV_ED25519
        with pytest.raises(cose.CoseError):
            cose.public_key(key, cose.ES256)

    def test_the_wrong_key_type_for_the_algorithm(self):
        _priv, key = _ed25519_key()
        with pytest.raises(cose.CoseError):
            cose.public_key(key, cose.ES256)

    @pytest.mark.parametrize('label,value', [(-2, b'\x00' * 31), (-3, b'\x00' * 33),
                                             (-2, 'not bytes'), (-3, None)])
    def test_coordinates_of_the_wrong_size_or_type(self, label, value):
        _priv, key = _es256_key()
        key[label] = value
        with pytest.raises(cose.CoseError):
            cose.public_key(key, cose.ES256)

    def test_an_rsa_modulus_small_enough_to_factor_is_refused(self):
        """The authenticator chose the size, so the floor is checked rather than assumed."""
        _priv, key = _rs256_key(1024)
        with pytest.raises(cose.CoseError):
            cose.public_key(key, cose.RS256)

    def test_verify_never_raises_whatever_it_is_handed(self):
        """Every way this fails must look the same to whoever sent the assertion."""
        for key in (None, {}, {1: 99}, {1: cose.KTY_EC2, -2: b'short'}):
            assert cose.verify(key, cose.ES256, b'', b'') is False
        assert cose.verify(None, 12345, b'', b'') is False
