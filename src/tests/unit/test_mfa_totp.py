#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Time-based one-time passwords, against the numbers the RFC itself publishes.

:mod:`lib.core.mfa.totp` is thirty lines of arithmetic that decides whether somebody gets in,
so it is not tested by agreeing with itself. RFC 6238 Appendix B prints a table of expected
codes for a known secret at known instants, and that table is the first class here — an
implementation that passes it is the one the phone in somebody's pocket implements.

The rest is the part the RFC does not cover and that a login flow lives or dies on: a code is
good exactly ONCE (thirty seconds is a long time to hold somebody else's), the clock tolerance
is one step in each direction and not two, and everything that is not a code — empty, letters,
the wrong length, a secret that is not base32 — answers "no" instead of raising.

Flask-free, database-free, network-free: every function under test is a function of its
arguments, which is what makes the published vectors usable as a test at all.
"""

import base64

import pytest

from lib.core.mfa import totp


# RFC 6238 Appendix B: the shared secret is the ASCII string '12345678901234567890'.
_RFC_SECRET = base64.b32encode(b'12345678901234567890').decode('ascii').rstrip('=')


class TestTheNumbersTheRfcPublishes:
    """Appendix B, SHA-1. The table prints eight digits; a six-digit code is its last six —
    the truncation is the same, the modulus is not."""

    @pytest.mark.parametrize('when,expected8', [
        (59,          '94287082'),
        (1111111109,  '07081804'),
        (1111111111,  '14050471'),
        (1234567890,  '89005924'),
        (2000000000,  '69279037'),
        (20000000000, '65353130'),
    ])
    def test_the_code_at_each_published_instant(self, when, expected8):
        step = totp.current_step(when)
        assert totp.code_at(_RFC_SECRET, step, digits=8) == expected8
        assert totp.code_at(_RFC_SECRET, step, digits=6) == expected8[-6:]

    def test_the_step_is_the_counter_the_rfc_names(self):
        """T = floor(unix / 30). The vectors are only reproducible if the counter is."""
        assert totp.current_step(59) == 1
        assert totp.current_step(1111111109) == 0x023523EC
        assert totp.current_step(20000000000) == 0x27BC86AA


class TestACodeIsGoodExactlyOnce:
    """A code lives thirty seconds, so one read over a shoulder — or off a phishing page —
    works until it expires. The verifier answers with the STEP so the caller can refuse it."""

    def test_it_answers_the_step_and_not_a_boolean(self):
        at = 1111111109
        step = totp.current_step(at)
        assert totp.verify(_RFC_SECRET, totp.code_at(_RFC_SECRET, step), now=at) == step

    def test_the_same_code_does_not_work_twice(self):
        at = 1111111109
        step = totp.current_step(at)
        code = totp.code_at(_RFC_SECRET, step)
        assert totp.verify(_RFC_SECRET, code, now=at) == step
        assert totp.verify(_RFC_SECRET, code, now=at, after_step=step) is None

    def test_nor_does_an_older_one_that_is_still_inside_the_window(self):
        """The previous step is accepted for clock skew, which is also where a replay of the
        code from thirty seconds ago would land."""
        at = 1111111109
        step = totp.current_step(at)
        old = totp.code_at(_RFC_SECRET, step - 1)
        assert totp.verify(_RFC_SECRET, old, now=at) == step - 1
        assert totp.verify(_RFC_SECRET, old, now=at, after_step=step) is None


class TestTheClockToleranceIsOneStep:
    """Zero reads as "the feature is broken" on any machine half a minute out. Two is a code
    that stays good for a minute and a half."""

    @pytest.mark.parametrize('offset,ok', [(-1, True), (0, True), (1, True),
                                           (-2, False), (2, False)])
    def test_one_step_either_side_and_no_more(self, offset, ok):
        at = 1234567890
        code = totp.code_at(_RFC_SECRET, totp.current_step(at) + offset)
        assert (totp.verify(_RFC_SECRET, code, now=at) is not None) is ok


class TestEverythingThatIsNotACodeSaysNo:
    """This is reached from a login form, so every shape of nonsense arrives eventually and
    none of them may raise: an exception here is a 500 on the page that guards the panel."""

    @pytest.mark.parametrize('code', ['', '   ', 'abcdef', '12345', '1234567', None,
                                      '12 34 56', '000000'])
    def test_a_wrong_shape_is_refused_and_never_raises(self, code):
        assert totp.verify(_RFC_SECRET, code, now=1234567890) is None

    @pytest.mark.parametrize('secret', ['', None, 'not base32!', '1'])
    def test_a_secret_that_is_not_one_verifies_nothing(self, secret):
        """Fails closed: an unreadable secret must never be the reason somebody gets in."""
        assert totp.code_at(secret, 1) == ''
        assert totp.verify(secret, '123456', now=1234567890) is None

    def test_the_right_code_for_the_wrong_secret_is_still_wrong(self):
        other = totp.secret_new()
        code = totp.code_at(_RFC_SECRET, totp.current_step(1234567890))
        assert totp.verify(other, code, now=1234567890) is None


class TestReadingASecretTheWayAPersonTypesIt:

    def test_lowercase_spaces_and_padding_are_all_the_same_secret(self):
        """The enrolment screen prints it in groups of four, and somebody types that in."""
        want = totp.secret_bytes(_RFC_SECRET)
        for variant in (_RFC_SECRET.lower(), totp.secret_groups(_RFC_SECRET),
                        _RFC_SECRET + '=' * (-len(_RFC_SECRET) % 8)):
            assert totp.secret_bytes(variant) == want

    def test_a_fresh_secret_is_160_bits_and_never_the_same_twice(self):
        first, second = totp.secret_new(), totp.secret_new()
        assert first != second
        assert len(totp.secret_bytes(first)) == totp.SECRET_BYTES

    def test_it_is_printed_in_groups_of_four(self):
        assert totp.secret_groups('ABCDEFGHIJ') == 'ABCD EFGH IJ'


class TestTheLinkTheAppReads:

    def test_it_carries_the_issuer_twice_on_purpose(self):
        """Once in the label prefix (what the older apps read) and once as the parameter the
        specification defines — otherwise the entry shows up as a bare username."""
        uri = totp.provisioning_uri('ABCD', 'ana', 'ServiceSentry')
        assert uri.startswith('otpauth://totp/ServiceSentry%3Aana?')
        assert 'issuer=ServiceSentry' in uri and 'secret=ABCD' in uri

    def test_an_account_that_is_an_email_survives_the_trip(self):
        """`@` and `:` in a path segment are how the link arrives at the phone truncated."""
        uri = totp.provisioning_uri('ABCD', 'ana@example.com', 'ServiceSentry')
        assert 'ana%40example.com' in uri and '@' not in uri

    def test_the_parameters_are_the_ones_every_app_assumes(self):
        uri = totp.provisioning_uri('ABCD', 'ana', 'SS')
        for part in ('algorithm=SHA1', 'digits=6', 'period=30'):
            assert part in uri

    def test_nothing_to_enrol_is_no_link(self):
        assert totp.provisioning_uri('', 'ana', 'SS') == ''
        assert totp.provisioning_uri('ABCD', '', 'SS') == ''
