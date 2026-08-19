#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A COSE key (RFC 8152) as something `cryptography` can verify a signature with.

The authenticator hands back its public key as a CBOR map of integer labels. This turns that
map into a key object and nothing else: it does not verify, it does not decide what is
acceptable, it does not touch the network. Verification lives with the ceremony that has the
signature and the data it was made over.

**The algorithm comes from the key, and the key comes from what was registered.** A COSE key
carries its own `alg`, and trusting that field at *authentication* time would let whoever
presents the assertion choose the algorithm it is checked with — which is the flaw that
emptied a generation of JWT libraries. The caller stores the algorithm at registration and
passes it back in; this module refuses a key whose own label disagrees with it.

Three algorithms, and the reasons are the same each time — these are what authenticators
actually ship:

* **ES256** (`-7`), ECDSA over P-256 with SHA-256: every security key and platform
  authenticator in existence.
* **RS256** (`-257`), RSASSA-PKCS1-v1_5 with SHA-256: what Windows Hello produced for years
  and what a lot of installed hardware still sends.
* **EdDSA** (`-8`) over Ed25519: newer keys, and the one with nothing to configure.

Anything else is refused rather than guessed at. An algorithm this cannot check is one whose
signature it would have to take on trust, and a second factor taken on trust is not one.
"""

from __future__ import annotations

# COSE key common labels (RFC 8152 §7.1) and the per-family ones (§13).
_KTY, _ALG = 1, 3
_CRV, _X, _Y = -1, -2, -3            # OKP / EC2 key material
_N, _E = -1, -2                      # RSA key material (same labels, different family)

KTY_OKP, KTY_EC2, KTY_RSA = 1, 2, 3
CRV_P256, CRV_ED25519 = 1, 6

ES256, EdDSA, RS256 = -7, -8, -257

# What this is willing to verify with, and the digest each one is defined over. Declared as
# data so adding one is a row, and so the list of what is NOT here is readable.
SUPPORTED = (ES256, RS256, EdDSA)


class CoseError(ValueError):
    """Not a key this can verify with — malformed, or an algorithm it will not guess at."""


def algorithm_of(key: dict) -> int:
    """The `alg` label a COSE key declares, or 0.

    Read at REGISTRATION and stored. Never used to decide how to check an assertion later:
    that is the caller's stored value, because a key that chooses its own algorithm at
    verification time is the JWT `alg: none` shape with different words.
    """
    try:
        return int((key or {}).get(_ALG) or 0)
    except (TypeError, ValueError):
        return 0


def public_key(key: dict, expect_alg: int):
    """A `cryptography` public key object for *key*, or raise.

    *expect_alg* is what was recorded when this credential was registered. A key whose own
    label disagrees is refused: the two coming apart means either the wrong credential was
    looked up or somebody is choosing the algorithm, and neither is something to resolve
    quietly in favour of one of them.
    """
    if not isinstance(key, dict):
        raise CoseError('not a COSE key')
    alg = int(expect_alg or 0)
    if alg not in SUPPORTED:
        raise CoseError('unsupported algorithm')
    declared = algorithm_of(key)
    if declared and declared != alg:
        raise CoseError('key algorithm does not match the one registered')
    kty = key.get(_KTY)

    if alg == ES256:
        if kty != KTY_EC2 or key.get(_CRV) != CRV_P256:
            raise CoseError('ES256 needs an EC2 key on P-256')
        x, y = key.get(_X), key.get(_Y)
        if not isinstance(x, bytes) or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
            raise CoseError('malformed P-256 coordinates')
        from cryptography.hazmat.primitives.asymmetric import ec   # noqa: PLC0415
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, 'big'), int.from_bytes(y, 'big'), ec.SECP256R1()).public_key()

    if alg == EdDSA:
        if kty != KTY_OKP or key.get(_CRV) != CRV_ED25519:
            raise CoseError('EdDSA needs an OKP key on Ed25519')
        x = key.get(_X)
        if not isinstance(x, bytes) or len(x) != 32:
            raise CoseError('malformed Ed25519 point')
        from cryptography.hazmat.primitives.asymmetric import ed25519   # noqa: PLC0415
        return ed25519.Ed25519PublicKey.from_public_bytes(x)

    # RS256
    if kty != KTY_RSA:
        raise CoseError('RS256 needs an RSA key')
    n, e = key.get(_N), key.get(_E)
    if not isinstance(n, bytes) or not isinstance(e, bytes) or not n or not e:
        raise CoseError('malformed RSA key')
    # A modulus small enough to factor is a signature anybody can forge, and the authenticator
    # chose it — so the floor is checked here rather than assumed.
    modulus = int.from_bytes(n, 'big')
    if modulus.bit_length() < 2048:
        raise CoseError('RSA modulus is too small')
    from cryptography.hazmat.primitives.asymmetric import rsa   # noqa: PLC0415
    return rsa.RSAPublicNumbers(int.from_bytes(e, 'big'), modulus).public_key()


def verify(key: dict, alg: int, signature: bytes, data: bytes) -> bool:
    """Does *signature* cover *data* under this key? True or False — never an exception.

    A boolean because every caller does the same thing with a failure, and because the ways
    this can fail (a malformed key, a bad signature, an algorithm mismatch) must not be
    distinguishable to whoever sent the assertion.
    """
    try:
        pub = public_key(key, alg)
        from cryptography.hazmat.primitives import hashes            # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec, padding   # noqa: PLC0415
        if alg == ES256:
            pub.verify(bytes(signature), bytes(data), ec.ECDSA(hashes.SHA256()))
        elif alg == RS256:
            pub.verify(bytes(signature), bytes(data), padding.PKCS1v15(), hashes.SHA256())
        else:
            pub.verify(bytes(signature), bytes(data))                # Ed25519 takes no hash
        return True
    except Exception:      # pylint: disable=broad-except
        return False
