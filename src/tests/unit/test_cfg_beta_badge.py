#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A channel still in beta says so on its own card.

Webhooks and Microsoft Teams deliver, and both are short of validations the older channels
have. The badge is declared ONCE — `beta: True` on the card in `lib/config/layout.py` — and
drawn by `cfgCardOpen`, the single function every card opens with, so a bespoke renderer gets
it without being told and leaving beta is one line in one file.

These are the two halves that can rot apart: the declaration, and the template actually
reading it.
"""

import io
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'cfg', '_card.html')

BETA_CARDS = {'webhook', 'msteams'}


def _layout():
    from lib.config.layout import CARDS
    return {c['id']: c for c in CARDS}


class TestTheDeclaration:

    def test_the_beta_channels_are_flagged(self):
        cards = _layout()
        for cid in BETA_CARDS:
            assert cards[cid].get('beta') is True, f'{cid} should carry beta: True'

    def test_nothing_else_is(self):
        """A flag that spreads by copy-paste stops meaning anything."""
        flagged = {cid for cid, c in _layout().items() if c.get('beta')}
        assert flagged == BETA_CARDS, flagged

    def test_the_flag_travels_to_the_browser(self):
        """The card metadata is served as-is, so the badge needs no second endpoint."""
        from lib.config.layout import config_layout
        cards = {c['id']: c for c in config_layout()['cards']}
        assert all(cards[cid].get('beta') for cid in BETA_CARDS)


class TestTheTemplateReadsIt:

    def test_the_badge_is_drawn_from_the_registry(self):
        html = io.open(TPL, encoding='utf-8').read()
        assert '_cfgBetaBadge' in html
        # Resolved inside the shared opener, not at each call site: that is what makes a
        # bespoke renderer (webhook and msteams are both bespoke) inherit it.
        assert '${_cfgBetaBadge(id)}' in html
        assert 'card.beta' in html

    def test_it_says_beta_in_both_languages(self):
        from lib.i18n.lang import en_EN, es_ES
        for mod in (en_EN, es_ES):
            assert mod.LANG['cfg_beta'] == 'BETA'
            assert mod.LANG['cfg_beta_tt']
