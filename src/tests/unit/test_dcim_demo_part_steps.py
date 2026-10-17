#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Every step of every part registered with the demo has its words in every language.

The demo's progress dialog names a step by ``step_<key>`` in the demo's words (``dcim_demo_words`` in each lang file) and
falls back to the bare key: a part whose steps had no words showed «monitor_devices
(350/356)» to the person installing it. Reported from the dialog.
"""

import pytest

import lib.core.dcim                                   # noqa: F401  (registers the parts)
from lib.core.dcim import demo
from lib.i18n import TRANSLATIONS

_LANGS = sorted(TRANSLATIONS)


def _words(lang):
    return (TRANSLATIONS[lang].get(demo.WORDS) or {})


def test_the_monitoring_part_is_registered_with_steps():
    parts = {p.name: p for p in demo.DEMO_PARTS}
    assert 'monitor' in parts and parts['monitor'].steps


@pytest.mark.parametrize('lang', _LANGS)
def test_every_part_step_has_a_label(lang):
    assert {'es_ES', 'en_EN'} <= set(_LANGS)
    words = _words(lang)
    missing = [k for p in demo.DEMO_PARTS for k in p.steps
               if not str(words.get(f'step_{k}') or '').strip()
               or str(words.get(f'step_{k}')).strip() == k]
    assert not missing, f'{lang}: no words for {missing}'


def test_the_label_is_what_the_progress_shows():
    seen = []
    prog = demo.Progress(seen.append, demo.texts('en_EN'), ['monitor_devices'])
    prog('monitor_devices', 1, 2)
    assert seen[-1]['step'] != 'monitor_devices' and seen[-1]['step'].strip()
