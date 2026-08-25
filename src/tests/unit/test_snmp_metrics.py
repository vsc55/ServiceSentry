#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Counters, and the two ways they lie.

A byte counter is cumulative: charted raw it is a line that only ever goes up, on which an
outage is a flat spot nobody notices. What a chart of a link wants is the RATE between samples,
and computing it has exactly one hard case — the new value is smaller than the old one.

That happens for two opposite reasons and looks identical from here:

* the counter **wrapped** (a 32-bit octet counter fills in ~34 seconds on a gigabit link), and
  the answer is to add the range back;
* the device **rebooted**, and the answer is that this sample means nothing.

Guessing wrong is not a rounding error. Treat a reboot as a wrap and the chart gets a spike of
four billion bytes in one interval, which is not merely wrong — it rescales the axis and hides
every real value on the screen behind it.

The rule is the WIDTH, and this file is mostly about it: 32-bit counters wrap constantly, so a
backwards step is assumed to be one; 64-bit counters do not wrap in any practical sense (~4.6
years at a terabit), so a backwards step is a reboot and the sample is dropped.
"""

import pytest

from lib.core.snmp import metrics


class TestScaling:

    def test_a_raw_reading_becomes_its_unit(self):
        """Centiseconds to seconds, KB to bytes, tenths of a degree to degrees: the one
        transformation devices actually need."""
        assert metrics.scale_value(12345, 0.01) == 123.45
        assert metrics.scale_value(2048, 1024) == 2097152

    def test_an_integer_stays_an_integer(self):
        """"41" reads as a reading; "41.0" reads as the result of a computation."""
        assert metrics.scale_value(41, None) == 41
        assert isinstance(metrics.scale_value(41, 1), int)

    def test_garbage_is_not_a_number(self):
        assert metrics.scale_value('n/a', 1) is None
        assert metrics.scale_value(None, 1) is None

    def test_a_broken_scale_does_not_lose_the_reading(self):
        """The factor comes from a profile somebody edited; the reading came from the device.
        Dropping the second because of the first would be losing data over a typo."""
        assert metrics.scale_value(41, 'x') == 41


class TestTheRate:

    def test_it_is_the_difference_over_the_time(self):
        assert metrics.counter_rate(2000, 1000, 10) == 100.0

    def test_two_samples_with_no_time_between_them_are_not_a_rate(self):
        assert metrics.counter_rate(2000, 1000, 0) is None
        assert metrics.counter_rate(2000, 1000, -5) is None

    def test_a_32_bit_counter_that_went_backwards_wrapped(self):
        """It fills in about 34 seconds on a gigabit link, so a backwards step is the normal
        case and dropping it would mean losing a sample every few minutes on a busy port."""
        rate = metrics.counter_rate(100, 2 ** 32 - 100, 10, width=32)
        assert rate == 20.0            # (100 + 2**32 - (2**32 - 100)) / 10

    def test_a_64_bit_counter_that_went_backwards_rebooted(self):
        """It does not wrap in any practical sense, so this is a device that restarted — and
        the wrapped reading would be a spike of four billion in one interval."""
        assert metrics.counter_rate(100, 2 ** 40, 10, width=64) is None

    def test_an_impossible_rate_is_refused_when_the_link_says_so(self):
        """The one case the width cannot settle: a 32-bit counter after a reboot. A ceiling is
        the only thing that can tell "wrapped" from "restarted" there, and it is knowledge
        about the link, so it lives in the profile."""
        assert metrics.counter_rate(100, 2 ** 32 - 100, 10, width=32, max_rate=5) is None
        assert metrics.counter_rate(100, 2 ** 32 - 100, 10, width=32, max_rate=1000) == 20.0

    def test_a_nonsense_ceiling_does_not_drop_the_sample(self):
        assert metrics.counter_rate(2000, 1000, 10, max_rate='fast') == 100.0

    def test_garbage_in_is_no_rate_out(self):
        assert metrics.counter_rate('x', 1000, 10) is None
        assert metrics.counter_rate(2000, None, 10) is None


class TestOneSample:

    def test_a_gauge_is_the_value_it_returned(self):
        value, state = metrics.sample({'key': 'cpu', 'kind': 'gauge'}, 41, None, 100.0)
        assert value == 41 and state is None

    def test_a_gauge_keeps_no_state(self):
        """Only counters need yesterday to mean anything today, and state that nothing reads
        is state that will be wrong one day without anybody noticing."""
        _v, state = metrics.sample({'kind': 'gauge', 'scale': 0.01}, 5000, {'v': 1, 't': 1}, 2.0)
        assert state is None

    def test_the_first_sample_of_a_counter_is_only_a_baseline(self):
        """There is nothing to subtract from. Recording a value here would put the machine's
        entire uptime on the chart as one second's traffic."""
        value, state = metrics.sample({'kind': 'counter'}, 1000, None, 100.0)
        assert value is None
        assert state == {'v': 1000.0, 't': 100.0}

    def test_the_second_one_is_a_rate(self):
        value, state = metrics.sample({'kind': 'counter'}, 2000, {'v': 1000, 't': 90.0}, 100.0)
        assert value == 100
        assert state == {'v': 2000.0, 't': 100.0}

    def test_a_dropped_counter_sample_still_moves_the_baseline(self):
        """Otherwise the NEXT sample is computed against a value from before the reboot, and
        one bad reading becomes two."""
        value, state = metrics.sample({'kind': 'counter', 'width': 64},
                                      5, {'v': 2 ** 40, 't': 90.0}, 100.0)
        assert value is None
        assert state == {'v': 5.0, 't': 100.0}

    def test_a_counter_that_answers_garbage_records_nothing(self):
        value, state = metrics.sample({'kind': 'counter'}, 'n/a', {'v': 1, 't': 1}, 2.0)
        assert value is None and state is None

    def test_text_is_never_a_number(self):
        """A name, a model, a serial: what the machine IS. It travels as an attribute, and a
        chart of it would be a chart of nothing."""
        value, state = metrics.sample({'kind': 'text'}, 'nas-01', None, 100.0)
        assert value is None and state is None

    def test_the_rate_is_scaled_like_any_other_value(self):
        """A profile may serve a counter in KB and want B/s, which is a scale on the rate and
        not on the raw reading — scaling the counter first would multiply the wrap point."""
        value, _s = metrics.sample({'kind': 'counter', 'scale': 1024},
                                   {}.get('x', 2000), {'v': 1000, 't': 90.0}, 100.0)
        assert value == 102400


class TestAttributes:

    def test_bytes_become_a_name(self):
        assert metrics.attribute({}, b'nas-01') == 'nas-01'

    def test_padding_is_not_part_of_a_name(self):
        """A device that answers with trailing whitespace must not get a different name from
        one that does not — the name is what the screen groups by."""
        assert metrics.attribute({}, '  switch-3 \n') == 'switch-3'

    def test_nothing_is_an_empty_name_and_not_the_word_none(self):
        assert metrics.attribute({}, None) == ''

    def test_an_address_is_recorded_the_way_people_write_it(self):
        """`0x94103e692443` is what an OctetString with nothing printable in it prints as, and
        it is the same six bytes that are on the sticker, in the switch's own CLI and in every
        other tool — written the way nobody writes them. On the ROLE the profile declared, so
        a serial that happens to look like twelve hex digits is left exactly as it came."""
        assert metrics.attribute({'role': 'mac'}, '0x94103E692443') == '94:10:3e:69:24:43'
        assert metrics.attribute({'role': 'serial'}, '0x94103E692443') == '0x94103E692443'

    def test_an_address_that_already_reads_as_one_is_left_alone(self):
        for text in ('94:10:3e:69:24:43', '94-10-3e-69-24-43', '9410.3e69.2443'):
            assert metrics.attribute({'role': 'mac'}, text) == text, (
                'a second spelling of the same address, invented by the panel')

    def test_only_six_bytes_are_an_address(self):
        """An OID or a hex serial of another length is not a MAC with something missing."""
        for text in ('0xdeadbeef', '0x94103e69244312', '0xzzzzzzzzzzzz'):
            assert metrics.attribute({'role': 'mac'}, text) == text
