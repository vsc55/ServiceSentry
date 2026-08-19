#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The WebAuthn ceremonies, built here and then taken apart one check at a time.

There is no published vector for a whole ceremony the way RFC 6238 prints codes, so these are
BUILT: a real P-256 key, a real authenticator-data blob assembled byte by byte to the layout
the specification fixes, a real signature. What that proves on its own is only that the happy
path agrees with itself — so the shape of this file is the opposite of the happy path. Every
class below takes a ceremony that WOULD verify and breaks exactly one thing, because each of
those single things is the whole feature when it is missing:

* a challenge from a different sign-in → replay,
* an origin that merely *looks* like ours → a phishing site's assertion accepted,
* an RP ID hash from another site → a credential borrowed across domains,
* no user-presence flag → a credential that is a file rather than a factor,
* a signature over anything but `authData || SHA-256(clientDataJSON)` → a signature over a
  ceremony somebody else chose,
* a counter that stopped moving → a cloned authenticator.

Flask-free, network-free, database-free.
"""

import hashlib
import json
import struct

import pytest

from lib.core.mfa import cbor, cose, webauthn as wa

pytest.importorskip('cryptography')

from cryptography.hazmat.primitives import hashes                    # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec             # noqa: E402

from tests.webauthn_fabric import (                                  # noqa: E402
    ORIGIN, RP_ID, _assertion, _auth_data, _cbor_map, _client_data, _key, _registration)


class TestTheHappyPathAgreesWithItself:
    """Only that — which is why it is one class and the rest of the file is the other five."""

    def test_a_registration_yields_the_credential_to_store(self):
        ch = wa.new_challenge()
        _priv, key, att, cdj = _registration(ch)
        out = wa.verify_registration(attestation_object=att, client_data_json=cdj,
                                     challenge=ch, rp_id=RP_ID, origin=ORIGIN)
        assert out['credential_id'] == b'cred-0001'
        assert out['alg'] == cose.ES256 and out['public_key'] == key
        assert out['sign_count'] == 1

    def test_the_key_bytes_it_hands_back_are_the_key(self):
        """The credential is STORED as the bytes it arrived in and re-parsed by this same
        decoder when an assertion turns up — one representation, so there is no second place
        that can disagree about what the key is.

        Which makes this slice the whole of that promise. `decode_from` answers how far it read
        FROM WHERE IT STARTED, and reading that number as an absolute offset produced a
        truncated key: it stored without complaint, and failed on the first sign-in — the shape
        of bug that only surfaces on the second half of the feature.
        """
        ch = wa.new_challenge()
        _priv, key, att, cdj = _registration(ch)
        out = wa.verify_registration(attestation_object=att, client_data_json=cdj,
                                     challenge=ch, rp_id=RP_ID, origin=ORIGIN)
        assert cbor.decode(out['public_key_raw']) == key

    def test_it_stops_at_the_key_and_not_at_whatever_follows(self):
        """Extensions come after the key in the same blob, so "the rest of the buffer" is not
        an answer either."""
        ch = wa.new_challenge()
        priv, key = _key()
        auth = _auth_data(cose_key=key, extra=b'\xa0' * 8)
        att = (b'\xa3' + b'\x63fmt' + b'\x64none' + b'\x67attStmt' + b'\xa0'
               + b'\x68authData' + b'\x59' + struct.pack('>H', len(auth)) + auth)
        out = wa.verify_registration(attestation_object=att,
                                     client_data_json=_client_data('webauthn.create', ch),
                                     challenge=ch, rp_id=RP_ID, origin=ORIGIN)
        assert cbor.decode(out['public_key_raw']) == key
        assert priv is not None

    def test_an_assertion_from_that_credential_verifies(self):
        ch = wa.new_challenge()
        priv, key, att, cdj = _registration(ch)
        reg = wa.verify_registration(attestation_object=att, client_data_json=cdj,
                                     challenge=ch, rp_id=RP_ID, origin=ORIGIN)
        ch2 = wa.new_challenge()
        auth, cdj2, sig = _assertion(priv, ch2)
        out = wa.verify_assertion(auth_data=auth, client_data_json=cdj2, signature=sig,
                                  challenge=ch2, rp_id=RP_ID, origin=ORIGIN,
                                  public_key=reg['public_key'], alg=reg['alg'],
                                  last_sign_count=reg['sign_count'])
        assert out['sign_count'] == 2

    def test_a_challenge_is_fresh_and_long_enough_to_be_one(self):
        a, b = wa.new_challenge(), wa.new_challenge()
        assert a != b and len(wa.b64u_decode(a)) == wa.CHALLENGE_BYTES


class TestTheChallengeIsTheOneThisServerIssued:
    """Without it, an assertion captured once is an assertion replayable forever — which is
    the whole of what a second factor is supposed to prevent."""

    def test_a_challenge_from_another_sign_in_is_refused(self):
        priv, key, att, cdj = _registration(wa.new_challenge())
        with pytest.raises(wa.CeremonyError):
            wa.verify_registration(attestation_object=att, client_data_json=cdj,
                                   challenge=wa.new_challenge(), rp_id=RP_ID, origin=ORIGIN)

    def test_replaying_an_assertion_against_a_new_challenge_is_refused(self):
        priv, key = _key()[0], None
        ch = wa.new_challenge()
        auth, cdj, sig = _assertion(priv, ch)
        _p, k = _key()
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=wa.new_challenge(), rp_id=RP_ID, origin=ORIGIN,
                                public_key=k, alg=cose.ES256)

    def test_no_challenge_at_all_never_passes(self):
        _priv, _key_, att, cdj = _registration('')
        with pytest.raises(wa.CeremonyError):
            wa.verify_registration(attestation_object=att, client_data_json=cdj,
                                   challenge='', rp_id=RP_ID, origin=ORIGIN)


class TestTheOriginIsCompareExactly:
    """`https://panel.example.com.attacker.net` passes any test that is not equality."""

    @pytest.mark.parametrize('origin', [
        'https://panel.example.com.attacker.net',
        'https://evil.com',
        'http://panel.example.com',          # the scheme is part of it
        'https://panel.example.com:8443',    # so is the port
        'https://PANEL.example.com',
        '',
    ])
    def test_anything_but_the_exact_origin_is_refused(self, origin):
        ch = wa.new_challenge()
        priv, _k = _key()
        auth, cdj, sig = _assertion(priv, ch, origin=origin)
        _p, k = _key()
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                public_key=k, alg=cose.ES256)


class TestTheCredentialIsScopedToThisSite:

    def test_an_rp_id_hash_from_another_site_is_refused(self):
        ch = wa.new_challenge()
        _priv, _k, att, cdj = _registration(ch, rp_id='someone-else.example')
        with pytest.raises(wa.CeremonyError):
            wa.verify_registration(attestation_object=att, client_data_json=cdj,
                                   challenge=ch, rp_id=RP_ID, origin=ORIGIN)

    def test_and_on_an_assertion_too(self):
        ch = wa.new_challenge()
        priv, k = _key()
        auth, cdj, sig = _assertion(priv, ch, rp_id='someone-else.example')
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                public_key=k, alg=cose.ES256)


class TestSomebodyHasToHaveBeenThere:
    """A credential that can be exercised without anybody touching anything is a file."""

    def test_a_registration_with_no_user_presence_is_refused(self):
        ch = wa.new_challenge()
        _priv, _k, att, cdj = _registration(ch, flags=wa.FLAG_AT)
        with pytest.raises(wa.CeremonyError):
            wa.verify_registration(attestation_object=att, client_data_json=cdj,
                                   challenge=ch, rp_id=RP_ID, origin=ORIGIN)

    def test_an_assertion_with_no_user_presence_is_refused(self):
        ch = wa.new_challenge()
        priv, k = _key()
        auth, cdj, sig = _assertion(priv, ch, flags=0)
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                public_key=k, alg=cose.ES256)

    def test_user_verification_is_asked_for_only_when_it_is_required(self):
        ch = wa.new_challenge()
        priv, k = _key()
        auth, cdj, sig = _assertion(priv, ch)                       # UP only, no UV
        kw = dict(auth_data=auth, client_data_json=cdj, signature=sig, challenge=ch,
                  rp_id=RP_ID, origin=ORIGIN, public_key=k, alg=cose.ES256)
        assert wa.verify_assertion(**kw)['uv'] is False
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(**kw, require_uv=True)


class TestTheSignatureCoversTheCeremonyAndNotSomethingElse:

    def test_a_signature_over_the_authenticator_data_alone_is_refused(self):
        """The client data is where the challenge and the origin live: a signature that does
        not cover its hash is a signature over a ceremony somebody else chose."""
        ch = wa.new_challenge()
        priv, k = _key()
        auth = _auth_data(flags=wa.FLAG_UP, count=2)
        cdj = _client_data('webauthn.get', ch)
        sig = priv.sign(auth, ec.ECDSA(hashes.SHA256()))        # no client-data hash
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                public_key=k, alg=cose.ES256)

    def test_another_keys_signature_is_refused(self):
        ch = wa.new_challenge()
        priv, _k = _key()
        auth, cdj, sig = _assertion(priv, ch)
        _other, other_key = _key()
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                public_key=other_key, alg=cose.ES256)

    def test_a_registration_response_is_not_an_assertion(self):
        """Replayed at login, a `webauthn.create` response would otherwise be a login."""
        ch = wa.new_challenge()
        priv, k = _key()
        auth = _auth_data(flags=wa.FLAG_UP, count=2)
        cdj = _client_data('webauthn.create', ch)               # the wrong ceremony type
        sig = priv.sign(auth + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                public_key=k, alg=cose.ES256)


class TestACounterThatStopsMoving:
    """The one signal in this protocol that says two devices are answering for one
    credential."""

    @pytest.mark.parametrize('count,last', [(5, 5), (4, 9)])
    def test_a_counter_that_did_not_move_forward_is_refused(self, count, last):
        ch = wa.new_challenge()
        priv, k = _key()
        auth, cdj, sig = _assertion(priv, ch, count=count)
        with pytest.raises(wa.CeremonyError):
            wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                public_key=k, alg=cose.ES256, last_sign_count=last)

    @pytest.mark.parametrize('count,last', [(0, 0), (0, 7), (7, 0)])
    def test_an_authenticator_that_keeps_no_counter_is_not_accused(self, count, last):
        """Zero on either side means it does not keep one — allowed, and common on platform
        authenticators. Only a counter that EXISTS and went backwards is evidence."""
        ch = wa.new_challenge()
        priv, k = _key()
        auth, cdj, sig = _assertion(priv, ch, count=count)
        assert wa.verify_assertion(auth_data=auth, client_data_json=cdj, signature=sig,
                                   challenge=ch, rp_id=RP_ID, origin=ORIGIN,
                                   public_key=k, alg=cose.ES256,
                                   last_sign_count=last)['sign_count'] == count


class TestWhereTheRpIdComesFrom:
    """From `public_url` and never from the request: behind a reverse proxy the request says
    whatever the proxy last said, and a credential registered against the wrong name is one
    that silently never works again."""

    @pytest.mark.parametrize('url,rp_id', [
        ('https://panel.example.com', 'panel.example.com'),
        ('https://panel.example.com/', 'panel.example.com'),
        ('https://panel.example.com:8443/admin', 'panel.example.com'),
        ('panel.example.com', 'panel.example.com'),
        ('HTTPS://Panel.Example.COM', 'panel.example.com'),
        ('https://panel.example.com.', 'panel.example.com'),
    ])
    def test_the_registrable_domain_and_nothing_else(self, url, rp_id):
        assert wa.rp_id_from(url) == rp_id

    @pytest.mark.parametrize('url', ['', '   ', 'https://10.0.0.5', 'http://192.168.1.1:8080',
                                     'https://[2001:db8::1]', '10.0.0.5'])
    def test_nothing_usable_is_empty_rather_than_a_guess(self, url):
        """The caller does not offer WebAuthn instead — a guess here produces a credential
        that never works and nothing that says why."""
        assert wa.rp_id_from(url) == ''

    @pytest.mark.parametrize('url,origin', [
        ('https://panel.example.com', 'https://panel.example.com'),
        ('https://panel.example.com/', 'https://panel.example.com'),
        ('https://panel.example.com:8443/x', 'https://panel.example.com:8443'),
        ('panel.example.com', 'https://panel.example.com'),
    ])
    def test_the_origin_keeps_the_port_because_the_browser_sends_it(self, url, origin):
        assert wa.origin_from(url) == origin


class TestMalformedInputIsARefusalAndNotACrash:
    """All of it arrives from the browser, on a path reachable without a session."""

    @pytest.mark.parametrize('blob', [b'', b'\x00' * 36, None])
    def test_authenticator_data_shorter_than_its_fixed_head(self, blob):
        with pytest.raises(wa.CeremonyError):
            wa.parse_auth_data(blob)

    def test_a_blob_claiming_a_credential_and_carrying_none(self):
        """The AT flag says attested credential data follows; nothing does."""
        blob = hashlib.sha256(RP_ID.encode()).digest() + bytes([wa.FLAG_UP | wa.FLAG_AT]) \
            + struct.pack('>I', 1)
        with pytest.raises(wa.CeremonyError):
            wa.parse_auth_data(blob)

    def test_the_head_alone_is_a_valid_assertion_blob(self):
        """An assertion carries no credential — only registration does, so 37 bytes is
        complete rather than truncated."""
        blob = hashlib.sha256(RP_ID.encode()).digest() + bytes([wa.FLAG_UP]) \
            + struct.pack('>I', 9)
        assert wa.parse_auth_data(blob)['sign_count'] == 9

    def test_a_credential_id_length_that_overruns_the_buffer(self):
        blob = hashlib.sha256(RP_ID.encode()).digest() + bytes([wa.FLAG_UP | wa.FLAG_AT]) \
            + struct.pack('>I', 1) + b'\x00' * 16 + struct.pack('>H', 5000)
        with pytest.raises(wa.CeremonyError):
            wa.parse_auth_data(blob)

    @pytest.mark.parametrize('raw', [b'', b'not json', b'[]', b'{}'])
    def test_client_data_that_is_not_an_object_with_the_fields(self, raw):
        with pytest.raises(wa.CeremonyError):
            wa.verify_registration(attestation_object=b'\xa0', client_data_json=raw,
                                   challenge='x', rp_id=RP_ID, origin=ORIGIN)

    def test_an_attestation_object_without_authenticator_data(self):
        ch = wa.new_challenge()
        with pytest.raises(wa.CeremonyError):
            wa.verify_registration(attestation_object=b'\xa0',
                                   client_data_json=_client_data('webauthn.create', ch),
                                   challenge=ch, rp_id=RP_ID, origin=ORIGIN)

    def test_base64url_that_is_not_is_empty_rather_than_an_exception(self):
        assert wa.b64u_decode('!!!!') == b'' and wa.b64u_decode(None) == b''
        assert wa.b64u_decode(wa.b64u_encode(b'\x00\xff')) == b'\x00\xff'
