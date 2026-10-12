#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/dns found by the 2026-10-12 audit (Windows `nslookup`)."""

from watchfuls.dns.client import _parse_nslookup


_ES_A = """Servidor:  dns.example.test
Address:  192.0.2.53

Respuesta no autoritativa:
Nombre:  www.example.test
Addresses:  2001:db8::10
          192.0.2.10
          192.0.2.11

"""

_EN_AUTHORITATIVE_A = """Server:  ns1.example.test
Address:  192.0.2.53

Name:    host.example.test
Address:  192.0.2.20

"""

_ES_MX = """Servidor:  dns.example.test
Address:  192.0.2.53

Respuesta no autoritativa:
example.test    MX preference = 10, mail exchanger = mail.example.test

"""

_TXT = """Server:  dns.example.test
Address:  192.0.2.53

Non-authoritative answer:
example.test    text =

        "v=spf1 -all"
example.test    text =

        "first-half-"
        "second-half"

"""


class TestLocalisedNslookup:
    """The answer was only read after an English "Name:" or "Non-authoritative answer:"
    header; on a Spanish Windows those read "Nombre:" / "Respuesta no autoritativa:" and
    nothing was ever parsed."""

    def test_spanish_a_with_continuation_lines(self):
        assert _parse_nslookup('A', _ES_A) == ['2001:db8::10', '192.0.2.10', '192.0.2.11']

    def test_the_server_address_is_not_an_answer(self):
        assert _parse_nslookup('A', _EN_AUTHORITATIVE_A) == ['192.0.2.20']

    def test_spanish_mx(self):
        # the same "10 host" form dig and dnspython give
        assert _parse_nslookup('MX', _ES_MX) == ['10 mail.example.test']

    def test_error_output_resolves_nothing(self):
        out = ("Servidor:  dns.example.test\nAddress:  192.0.2.53\n\n"
               "*** dns.example.test no encuentra nope.example.test: Non-existent domain\n")
        assert _parse_nslookup('A', out) == []


class TestTxtValues:
    """nslookup prints `text =` and the quoted strings on the FOLLOWING lines, so every TXT
    record came back empty. A record split into several strings is joined, like dnspython."""

    def test_txt_values_are_read_from_the_following_lines(self):
        assert _parse_nslookup('TXT', _TXT) == ['v=spf1 -all', 'first-half-second-half']

    def test_crlf_output(self):
        assert _parse_nslookup('TXT', _TXT.replace('\n', '\r\n')) == [
            'v=spf1 -all', 'first-half-second-half']
