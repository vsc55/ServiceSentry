#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A CBOR decoder written from the standard, checked against the standard's own table.

RFC 8949 Appendix A prints a list of encodings beside the values they mean, and that table is
the first class here — the same discipline the TOTP and QR code got, and for the same reason:
this parses a blob a security key sends to the login path, so an implementation that agrees
with itself is worth nothing.

The rest is what the table does not cover and what a parser on an authentication path lives or
dies on: it refuses the encodings WebAuthn's canonical form does not use (accepting two ways to
say one value is how a signature is computed over one and checked against the other), it says
how much it consumed (the credential key is CBOR followed by extensions, so "the rest of the
buffer" is not an answer), and every shape of malformed input is a `CborError` rather than an
exception nobody caught.

Flask-free, network-free, database-free.
"""

import pytest

from lib.core.mfa import cbor


class TestTheTableTheRfcPrints:
    """RFC 8949 Appendix A, the entries that matter for what an authenticator sends."""

    @pytest.mark.parametrize('encoded,value', [
        ('00', 0), ('01', 1), ('0a', 10), ('17', 23),
        ('1818', 24), ('1819', 25), ('1864', 100),
        ('1903e8', 1000), ('1a000f4240', 1000000),
        ('1b000000e8d4a51000', 1000000000000),
    ])
    def test_unsigned_integers_across_every_width(self, encoded, value):
        assert cbor.decode(bytes.fromhex(encoded)) == value

    @pytest.mark.parametrize('encoded,value', [
        ('20', -1), ('29', -10), ('3863', -100), ('3903e7', -1000),
    ])
    def test_negative_integers_are_minus_one_minus_n(self, encoded, value):
        assert cbor.decode(bytes.fromhex(encoded)) == value

    @pytest.mark.parametrize('encoded,value', [
        ('40', b''), ('4401020304', bytes([1, 2, 3, 4])),
    ])
    def test_byte_strings(self, encoded, value):
        assert cbor.decode(bytes.fromhex(encoded)) == value

    @pytest.mark.parametrize('encoded,value', [
        ('60', ''), ('6161', 'a'), ('6449455446', 'IETF'),
        ('62225c', chr(34) + chr(92)), ('62c3bc', 'ü'),
    ])
    def test_text_strings(self, encoded, value):
        assert cbor.decode(bytes.fromhex(encoded)) == value

    @pytest.mark.parametrize('encoded,value', [
        ('80', []), ('83010203', [1, 2, 3]), ('8301820203820405', [1, [2, 3], [4, 5]]),
    ])
    def test_arrays_including_nested_ones(self, encoded, value):
        assert cbor.decode(bytes.fromhex(encoded)) == value

    @pytest.mark.parametrize('encoded,value', [
        ('a0', {}), ('a201020304', {1: 2, 3: 4}),
        ('a26161016162820203', {'a': 1, 'b': [2, 3]}),
        ('826161a161626163', ['a', {'b': 'c'}]),
    ])
    def test_maps_which_is_what_everything_in_webauthn_is(self, encoded, value):
        assert cbor.decode(bytes.fromhex(encoded)) == value

    @pytest.mark.parametrize('encoded,value', [('f4', False), ('f5', True), ('f6', None)])
    def test_the_three_simple_values_that_appear(self, encoded, value):
        assert cbor.decode(bytes.fromhex(encoded)) == value

    def test_a_negative_integer_is_not_read_as_its_magnitude(self):
        """COSE keys use negative labels for the key material itself (-1, -2, -3), so getting
        the sign wrong here would look up the wrong field rather than fail."""
        assert cbor.decode(bytes.fromhex('20')) == -1
        assert cbor.decode(bytes.fromhex('22')) == -3


class TestItRefusesWhatTheCanonicalFormDoesNotUse:
    """WebAuthn requires the definite-length encoding (CTAP2 §6). Accepting the streaming form
    as well would mean accepting two encodings of one value — which is how a signature comes to
    be computed over one and checked against the other."""

    @pytest.mark.parametrize('encoded', [
        '5f42010243030405ff',    # indefinite-length byte string
        '7f6161616bff',          # indefinite-length text string
        '9f018202039f0405ffff',  # indefinite-length array
        'bf61610161629f0203ffff',  # indefinite-length map
    ])
    def test_the_streaming_form_is_refused(self, encoded):
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex(encoded))

    def test_a_repeated_key_is_refused_rather_than_resolved(self):
        """The two encodings disagree about what the map says, and picking one is picking for
        whoever sent it."""
        # map(2) { 1: 1, 1: 2 } — the same key twice.
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex('a201010102'))

    def test_trailing_data_is_an_error_for_a_whole_document(self):
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex('01') + b'\x02')


class TestItSaysHowMuchItConsumed:
    """Authenticator data carries the credential's public key as CBOR followed by whatever
    extensions were asked for, so where the key ENDS is a question with an answer — and a
    parser that ignores what follows cannot tell a key from a key with something appended."""

    def test_it_reports_the_length_of_the_item_it_read(self):
        value, consumed = cbor.decode_from(bytes.fromhex('a201020304') + b'\xde\xad\xbe\xef')
        assert value == {1: 2, 3: 4} and consumed == 5

    def test_it_can_start_part_way_through(self):
        blob = b'\xff\xff' + bytes.fromhex('6449455446')
        assert cbor.decode_from(blob, 2) == ('IETF', 5)

    def test_a_whole_document_call_still_refuses_the_leftovers(self):
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex('a201020304') + b'\x00')


class TestEveryMalformedInputIsARefusalAndNotACrash:
    """This runs on the login path against bytes somebody else composed."""

    @pytest.mark.parametrize('encoded', ['18', '19ff', '1b0000', '44010203', 'a201', '8302'])
    def test_a_header_promising_more_than_is_there(self, encoded):
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex(encoded))

    @pytest.mark.parametrize('encoded', ['ff', 'fc', 'f7', '1c', '1d', '1e'])
    def test_reserved_and_unassigned_encodings(self, encoded):
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex(encoded))

    def test_a_length_field_that_asks_for_a_gigabyte_is_refused_before_it_allocates(self):
        """A two-byte header must not be able to ask for the whole address space."""
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex('5bffffffffffffffff') + b'\x00')

    def test_deep_nesting_is_bounded(self):
        """A few bytes of nested arrays is otherwise a recursion limit away from being a
        denial of service on the one path that is reachable without a session."""
        with pytest.raises(cbor.CborError):
            cbor.decode(b'\x81' * 64 + b'\x00')

    def test_text_that_is_not_utf8_is_refused(self):
        with pytest.raises(cbor.CborError):
            cbor.decode(bytes.fromhex('62') + b'\xff\xfe')

    def test_nothing_at_all_is_an_error_and_not_none(self):
        with pytest.raises(cbor.CborError):
            cbor.decode(b'')
