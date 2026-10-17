#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the product ships says the same words in every language after its texts moved to i18n.

The SNMP profiles, the DCIM connectors and basics, and the demo's words used to carry their
translations inline (``{"es_ES": …, "en_EN": …}`` in each JSON, one word file per language for
the demo). They now live in the core lang files and the shipped data holds only the key. The
move must not change a single word anybody reads, so ``tests/fixtures/i18n_shipped_before.json``
was captured with :func:`capture` from the files AS THEY WERE, before the move, and this test
compares the same capture against the code as it is now.

The capture goes through the public readers — ``label_of``/``states_of``/``history_fields`` for
the profiles, ``connectors.all``/``signals``, ``basics.rows``/``platforms``, ``demo.texts`` —
because what has to stay the same is what comes OUT, not how it is stored.

When a shipped text is changed ON PURPOSE, regenerate the fixture and review its diff::

    .venv/Scripts/python.exe -m tests.unit.test_i18n_shipped_texts
"""

from __future__ import annotations

import io
import json
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
FIXTURE = os.path.join(SRC, 'tests', 'fixtures', 'i18n_shipped_before.json')

#: The languages read back, plus '' — "no language asked", which the DCIM readers resolve to
#: the default one and the demo to its base language.
LANGS = ('es_ES', 'en_EN', '')


def _snmp() -> dict:
    from lib.core.snmp import profiles as P                         # noqa: PLC0415
    out: dict = {}

    def put(key, lang, text):
        out.setdefault(key, {})[lang] = text

    for pid, prof in sorted(P.shipped().items()):
        for lang in LANGS[:2]:
            put(f'{pid}/label', lang, P.label_of(prof, lang))
            put(f'{pid}/short', lang, P.short_label_of(prof, lang))
            put(f'{pid}/desc', lang, P.label_of(
                {'label': prof.get('description') or {}, 'id': ''}, lang))
            fields = P.history_fields(prof, lang)
            for m in prof.get('metrics') or ():
                put(f'{pid}/{m["key"]}', lang, P.label_of(m, lang))
                chart = (fields.get(m['key']) or {}).get('chart_label')
                if chart:
                    put(f'{pid}/{m["key"]}/chart', lang, chart)
                for val, spec in P.states_of(m, lang).items():
                    put(f'{pid}/{m["key"]}/{val}', lang, spec['label'])
    return out


def _connectors() -> dict:
    from lib.core.dcim import connectors as C                       # noqa: PLC0415
    out: dict = {}
    for lang in LANGS:
        for c in C.all(lang):
            out.setdefault(f'{c["id"]}/name', {})[lang] = c['name']
            if 'note' in c:
                out.setdefault(f'{c["id"]}/note', {})[lang] = c['note']
            for g in c.get('gens') or ():
                out.setdefault(f'{c["id"]}/gen/{g["id"]}', {})[lang] = g['name']
        for s in C.signals(lang):
            out.setdefault(f'signal/{s["id"]}', {})[lang] = s['name']
    return out


def _basics() -> dict:
    from lib.core.dcim import basics as B                           # noqa: PLC0415
    out: dict = {}
    for lang in LANGS:
        rows = B.rows(lang)
        out.setdefault('__order__', {})[lang] = [r['slug'] for r in rows]
        for r in rows:
            for field in ('model', 'description'):
                if field in r:
                    out.setdefault(f'{r["slug"]}/{field}', {})[lang] = r[field]
            for k, v in (r.get('extra') or {}).items():
                out.setdefault(f'{r["slug"]}/extra/{k}', {})[lang] = v
        for p in B.platforms(lang):
            out.setdefault(f'platform/{p["name"]}/notes', {})[lang] = p.get('notes')
    return out


def _demo() -> dict:
    from lib.core.dcim import demo, demo_monitor                    # noqa: PLC0415
    return {
        'words': {lang: demo.texts(lang) for lang in LANGS},
        'monitor': {lang: demo_monitor.texts(lang) for lang in LANGS},
        # How the demo finds itself whatever language built it.
        'every': {k: sorted(demo._every(k))                         # noqa: SLF001
                  for k in demo.BRANCHES + ('org_operator',)},
    }


def capture() -> dict:
    """Every shipped text, resolved, per language."""
    return {'snmp_profiles': _snmp(), 'dcim_connectors': _connectors(),
            'dcim_basics': _basics(), 'dcim_demo': _demo()}


def _fixture() -> dict:
    with io.open(FIXTURE, encoding='utf-8') as fh:
        return json.load(fh)


class TestTheShippedTextsDidNotChange:

    def test_the_fixture_is_not_empty(self):
        """Guard the guard: a fixture that captured nothing would compare equal forever."""
        fx = _fixture()
        assert len(fx['snmp_profiles']) > 600
        assert len(fx['dcim_connectors']) > 150
        assert len(fx['dcim_basics']) > 100
        assert len(fx['dcim_demo']['words']['es_ES']) > 300

    def test_the_snmp_profiles_say_the_same(self):
        assert _snmp() == _fixture()['snmp_profiles']

    def test_the_connectors_say_the_same(self):
        assert _connectors() == _fixture()['dcim_connectors']

    def test_the_basics_say_the_same(self):
        assert _basics() == _fixture()['dcim_basics']

    def test_the_demo_says_the_same(self):
        assert _demo() == _fixture()['dcim_demo']


class TestWhoseWordsWin:
    """A text written in the object (the installation's) → the shipped key in the reader's
    language → the default language → the id."""

    def test_a_reference_becomes_a_text_per_language_and_a_text_stays(self):
        from lib.i18n import materialize                            # noqa: PLC0415
        doc = {'a': {'i18n': 'apc_ups/label'}, 'b': {'es_ES': 'Mío'}, 'c': ['x', 3]}
        got = materialize(doc, 'snmp_shipped_profiles')
        assert got['a'] == {'en_EN': 'APC UPS (PowerNet)', 'es_ES': 'SAI APC (PowerNet)'}
        assert got['b'] == {'es_ES': 'Mío'} and got['c'] == ['x', 3]
        assert doc['a'] == {'i18n': 'apc_ups/label'}                # a copy, never in place
        assert materialize({'i18n': 'no/such/key'}, 'snmp_shipped_profiles') == {}

    def test_a_raw_shipped_file_reads_its_words(self):
        """A probe builds its catalogue from raw files: `label_of` resolves the key itself."""
        from lib.core.snmp import profiles as P                     # noqa: PLC0415
        with io.open(os.path.join(os.path.dirname(P.__file__), 'sources', 'apc_ups.json'),
                     encoding='utf-8') as fh:
            raw = json.load(fh)
        assert raw['label'] == {'i18n': 'apc_ups/label'}
        assert P.label_of(raw, 'es_ES') == 'SAI APC (PowerNet)'
        assert P.label_of(raw['metrics'][0], 'en_EN') == 'Model'

    def test_an_override_with_its_own_words_keeps_them(self):
        from lib.core.snmp import profiles as P                     # noqa: PLC0415
        mine = {'id': 'apc_ups', 'label': 'Our UPS',
                'metrics': [{'key': 'apc_ups_model', 'oid': '1.3.6.1.4.1.318.1.1.1.1.1.1.0',
                             'kind': 'text', 'label': {'es_ES': 'El modelo'}}]}
        prof = P.catalog(custom=[mine])['apc_ups']
        assert prof['source'] == 'custom'
        assert P.label_of(prof, 'es_ES') == P.label_of(prof, 'en_EN') == 'Our UPS'
        assert P.label_of(prof['metrics'][0], 'es_ES') == 'El modelo'

    def test_a_copied_shipped_file_still_resolves_its_keys(self):
        from lib.core.snmp import profiles as P                     # noqa: PLC0415
        with io.open(os.path.join(os.path.dirname(P.__file__), 'sources', 'apc_ups.json'),
                     encoding='utf-8') as fh:
            raw = json.load(fh)
        raw['metrics'][0]['label'] = 'Modelo exacto'
        prof = P.catalog(custom=[raw])['apc_ups']
        assert P.label_of(prof, 'en_EN') == 'APC UPS (PowerNet)'
        assert P.label_of(prof['metrics'][0], 'en_EN') == 'Modelo exacto'

    def test_a_profile_written_in_the_panel_names_itself(self):
        from lib.core.snmp import profiles as P                     # noqa: PLC0415
        body = {'id': 'mi_sai', 'label': 'Mi SAI',
                'metrics': [{'key': 'v', 'oid': '1.3.6.1.2.1.1.1.0', 'kind': 'text'}]}
        prof = P.catalog(written=[body])['mi_sai']
        assert P.label_of(prof, 'en_EN') == 'Mi SAI'
        assert P.label_of(prof['metrics'][0], 'en_EN') == 'V'       # no word: from its key


class _Store:
    """The one call `connectors.effective` makes of the document store."""

    def __init__(self, body=None):
        self.body = body

    def get(self, name):
        return {'body': self.body} if self.body is not None else None


class TestTheConnectorsDocument:

    def test_the_editor_gets_the_words_and_a_save_keeps_them_literal(self):
        """The shipped document holds keys; the one handed to the editor holds the words, so
        what somebody saves is their text — and stays theirs when the lang file changes."""
        from lib.core.dcim import connectors as C                   # noqa: PLC0415
        with io.open(C.FILE, encoding='utf-8') as fh:
            raw = json.load(fh)
        c6 = next(c for c in raw['connectors'] if c['id'] == 'iec-60320-c6')
        assert c6['note'] == {'i18n': 'iec-60320-c6/note'}
        shown = C.effective(_Store())
        note = next(c for c in shown['connectors'] if c['id'] == 'iec-60320-c6')['note']
        assert set(note) == {'es_ES', 'en_EN'}
        saved = json.loads(json.dumps(shown))
        saved['version'] = C.next_version(_Store())
        for c in saved['connectors']:
            if c['id'] == 'iec-60320-c6':
                c['note'] = {'es_ES': 'El de mi portátil', 'en_EN': 'My laptop one'}
        store = _Store(saved)
        assert C.name('iec-60320-c6', 'es_ES', store) == 'IEC C6'
        mine = next(c for c in C.all('es_ES', store) if c['id'] == 'iec-60320-c6')
        assert mine['note'] == 'El de mi portátil'
        # «Restore default» deletes the saved one: the shipped words are back.
        back = next(c for c in C.all('es_ES', _Store()) if c['id'] == 'iec-60320-c6')
        assert back['note'] == 'El «trébol» de las fuentes de portátil.'

    def test_a_saved_document_that_kept_a_reference_reads_the_word(self):
        from lib.core.dcim import connectors as C                   # noqa: PLC0415
        doc = {'version': 10 ** 6, 'connectors': [
            {'id': 'iec-60320-c6', 'families': ['power-ports'],
             'note': {'i18n': 'iec-60320-c6/note'}}]}
        got = C.all('en_EN', _Store(doc))
        assert got[0]['note'] == 'The "cloverleaf" on laptop bricks.'


class TestTheDemoWords:

    def test_texts_is_a_copy(self):
        from lib.core.dcim import demo                              # noqa: PLC0415
        w = demo.texts('en_EN')
        w['spares'].append(['x'])
        w['site_dr'] = 'changed'
        again = demo.texts('en_EN')
        assert ['x'] not in again['spares'] and again['site_dr'] != 'changed'

    def test_an_unknown_language_gets_the_base_one(self):
        from lib.core.dcim import demo, demo_monitor                # noqa: PLC0415
        assert demo.texts('fr_FR') == demo.texts('es_ES')
        assert demo_monitor.texts('fr_FR') == demo_monitor.texts('es_ES')


if __name__ == '__main__':                                        # pragma: no cover
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with io.open(FIXTURE, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(capture(), fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write('\n')
    print('written', FIXTURE)
