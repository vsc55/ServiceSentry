#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The web-admin partials follow a naming convention (see docs/explica-arquitectura.md).

The tree drifted before: three different names for "the section's list" (`_table`, `_list`,
`_render`), `_table` meaning two different things, a partial nobody included, and a 900-line
`_render.html` holding three sub-sections. These tests pin the convention so it stays put —
they check the FILE NAMES and the wiring, not the code inside.
"""

import io
import os
import re

import pytest

TPL = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                   'lib', 'web_admin', 'templates')
PARTIALS = os.path.join(TPL, 'partials')

# The vocabulary. A partial is named for its ROLE, not its size:
ROLES = {
    '_render',     # the section shell: its render<Section>() entry point + scaffolding
    '_list',       # the section's list (a createListTable spec, or a hand-written one)
    '_columns',    # column definitions + visibility/order/width state for a hand-built table
    '_modal',      # an add/edit modal
    '_index',      # a folder-level orchestrator that only includes its siblings
}
# Anything else must be a named CONCERN extracted as the file grew (_filters, _export, …).
# Those are free-form by design, so the rule is only that they are lowercase words.
NAME_RE = re.compile(r'^_[a-z0-9]+(_[a-z0-9]+)*$')


def _partials():
    for root, _dirs, files in os.walk(PARTIALS):
        for f in files:
            if f.endswith('.html'):
                yield os.path.relpath(os.path.join(root, f), TPL).replace(os.sep, '/')


def _all_template_text():
    out = {}
    for root, _dirs, files in os.walk(TPL):
        for f in files:
            if f.endswith('.html'):
                p = os.path.join(root, f)
                out[p] = io.open(p, encoding='utf-8', errors='replace').read()
    return out


def _python_text():
    src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
    out = []
    for root, dirs, files in os.walk(os.path.join(src, 'lib')):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        out += [io.open(os.path.join(root, f), encoding='utf-8', errors='replace').read()
                for f in files if f.endswith('.py')]
    return '\n'.join(out)


class TestNaming:

    def test_every_partial_is_underscore_prefixed(self):
        """The leading _ marks a fragment that is never routed to on its own."""
        for rel in _partials():
            name = os.path.basename(rel)
            assert name.startswith('_'), f'{rel}: partials are _-prefixed'

    def test_names_are_lowercase_words(self):
        for rel in _partials():
            stem = os.path.basename(rel)[:-len('.html')]
            assert NAME_RE.match(stem), f'{rel}: use lowercase_words, no camelCase or dashes'

    def test_no_ambiguous_table_partial(self):
        """`_table` used to mean both "the whole list" (clusters) and "column state"
        (events/syslog). It was retired: lists are `_list`, column state is `_columns`."""
        offenders = [r for r in _partials() if os.path.basename(r) == '_table.html']
        assert not offenders, f'rename to _list.html or _columns.html: {offenders}'

    def test_one_render_shell_per_section_folder(self):
        """A folder holds at most one `_render.html` — the section's single entry point."""
        seen = {}
        for rel in _partials():
            folder = os.path.dirname(rel)
            if os.path.basename(rel) == '_render.html':
                seen.setdefault(folder, 0)
                seen[folder] += 1
        assert all(n == 1 for n in seen.values()), seen


class TestWiring:

    def test_no_orphan_partials(self):
        """Every partial is included by some template or rendered from Python. An orphan is
        dead code that keeps showing up in greps (the old top navbar was one for a while)."""
        haystack = '\n'.join(_all_template_text().values()) + '\n' + _python_text()
        for rel in _partials():
            assert rel in haystack, f'{rel} is included by nobody — dead partial?'

    def test_script_partials_are_included_once(self):
        """The JS bundle is ONE <script>, so including a partial twice would redeclare its
        consts and throw at load. Only `{% include %}` emits content — a macro library pulled
        in with `{% from … import %}` is legitimately imported by several templates."""
        haystack = '\n'.join(_all_template_text().values())
        includes = re.findall(r'{%-?\s*include\s+[\'"]([^\'"]+)[\'"]', haystack)
        for rel in _partials():
            n = includes.count(rel)
            assert n <= 1, f'{rel} is included {n} times'


class TestSize:
    """A `_render.html` that keeps growing is a section hiding sub-sections inside it —
    which is exactly how ipban/_render.html reached 900 lines with three of them."""

    LIMIT = 450

    @pytest.mark.parametrize('rel', sorted(r for r in _partials()
                                           if os.path.basename(r) == '_render.html'))
    def test_render_shells_stay_thin(self, rel):
        """No exemptions. `cfg/_render.html` had one — "the config panel's registry-driven
        renderer, not a section shell with sub-sections to split out" — and it was wrong on
        both counts: it held the seeding pass, the search filter, the declared-action
        renderer and a localStorage inspector, which are four concepts and now four
        partials. An exemption written into a guard is a guard that has stopped guarding
        the one file it was pointed at."""
        n = len(io.open(os.path.join(TPL, rel), encoding='utf-8').read().splitlines())
        assert n <= self.LIMIT, (f'{rel} is {n} lines — split its sub-sections into '
                                 f'their own partials (see ipban/_bans|_history|_whitelist)')


class TestTheTwoShapesOfTheApiHelpersAreNotMixed:
    """`apiGet` answers the parsed BODY. `apiPost`, `apiPut` and `apiDelete` answer
    `{status, data}`. Two shapes in one module, and reading the wrong one does not fail
    loudly — it yields `undefined`, the caller falls to its default, and the screen shows a
    plausible wrong answer.

    Reported from the account page: an account WITH a second factor was drawn as "not set up",
    and the button then posted an enrolment the server correctly refused. One mistake, two
    symptoms, and neither of them said what was wrong.

    The guard is narrow on purpose. `r.data` after an `apiGet` is legitimate when the endpoint
    genuinely returns a body with a `data` key — `/api/v1/modules/page/<m>` does — so what is
    checked is the pattern that cannot be right: reading `.data` off the awaited call itself.
    """

    def _js_partials(self):
        for root, _dirs, files in os.walk(TPL):
            for name in files:
                if name.endswith('.html'):
                    yield os.path.join(root, name)

    def test_nothing_reads_data_straight_off_an_awaited_apiget(self):
        # `(await apiGet(…)).data` / `(await apiGet(…) || {}).data` — always wrong, because
        # the body IS the answer.
        bad_inline = re.compile(r'\(\s*await\s+apiGet(?:Silent)?\([^;]*?\)\s*(?:\|\|[^;]*?)?\)\s*\.data\b')
        offenders = []
        for path in self._js_partials():
            with io.open(path, encoding='utf-8') as fh:
                src = fh.read()
            if bad_inline.search(src):
                offenders.append(os.path.relpath(path, TPL))
        assert not offenders, (
            'these read `.data` off an apiGet, which answers the body itself: '
            + ', '.join(sorted(offenders)))

    def test_the_helpers_still_have_the_shapes_this_guard_assumes(self):
        """If `apiGet` ever starts returning a wrapper too, this guard becomes wrong rather
        than merely unnecessary — so it checks the premise instead of assuming it."""
        with io.open(os.path.join(TPL, 'partials', 'core', '_api.html'), encoding='utf-8') as fh:
            src = fh.read()
        get_body = src.split('async function apiGet(', 1)[1].split('async function', 1)[0]
        assert 'return await r.json();' in get_body, 'apiGet no longer answers the body'
        post_body = src.split('async function apiPost(', 1)[1].split('async function', 1)[0]
        assert 'status: r.status' in post_body, 'apiPost no longer answers {status, data}'


class TestAnEventHandlerIsEscapedOnce:
    """`jsStr` IS `escAttr(JSON.stringify(s))` — it says so where it is defined.

    Wrapping it again turns the `&quot;` it produced into `&amp;quot;`, the attribute decodes
    that back to a literal `&quot;`, and the browser hands the JS engine an ampersand where it
    expected a string. Reported from the console as::

        Uncaught SyntaxError: expected expression, got '&'

    which says nothing about escaping and points at a generated line nobody wrote. The value
    still LOOKS right in the markup, so it survives reading; it only fails when clicked.
    """

    def _templates(self):
        for root, dirs, files in os.walk(TPL):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if f.endswith('.html'):
                    yield os.path.join(root, f)

    def test_nothing_escapes_a_handler_argument_twice(self):
        bad = []
        for path in self._templates():
            src = io.open(path, encoding='utf-8-sig', errors='replace').read()
            if 'escAttr(jsStr(' in src:
                bad.append(os.path.relpath(path, TPL))
        assert not bad, (
            'escAttr(jsStr(…)) double-escapes — jsStr already calls escAttr: ' + ', '.join(bad))

    def test_the_helper_still_does_its_own_escaping(self):
        """If `jsStr` ever stops escaping, the rule above becomes wrong rather than merely
        redundant — and every handler in the panel becomes an attribute injection."""
        src = io.open(os.path.join(TPL, 'partials', 'core', '_utils.html'),
                      encoding='utf-8-sig', errors='replace').read()
        assert 'function jsStr(s) { return escAttr(JSON.stringify(s)); }' in src


class TestAPickerForwardsWhatItWasGiven:
    """A field picker is called with a different number of arguments by each pane.

    The Modules tab draws a check that HAS a path into `modulesData`, so three arguments say
    everything. The host modal is editing a draft that may never have been saved — the device
    the button would speak to lives in the form, not in the store — so it passes a fourth: a
    function that reads that draft.

    An arrow that names three parameters drops it without a word. Reported from the panel as
    "Test against the device → no host": the button was there, the request went out, and the
    address it was about had been discarded in a wrapper. Nothing logs that, and the same
    wrapper had been correct for as long as only one pane existed.
    """

    def _sources(self):
        """The templates AND the core packages' own screens — a picker registered from
        `lib/core/<domain>/web/` is the same registry entry."""
        roots = [TPL, os.path.join(os.path.dirname(TPL.split(os.sep + 'lib' + os.sep)[0]),
                                   'src', 'lib', 'core')]
        seen = set()
        for root in roots:
            for base, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for f in files:
                    if f.endswith('.html') and os.path.join(base, f) not in seen:
                        seen.add(os.path.join(base, f))
                        yield os.path.join(base, f)

    def test_every_registered_hook_is_variadic(self):
        bad = []
        hook = re.compile(r'[\s,{](open|run)\s*:\s*(\([^)]*\))\s*=>')
        for path in self._sources():
            src = io.open(path, encoding='utf-8-sig', errors='replace').read()
            if 'FIELD_PICKERS[' not in src:
                continue
            for m in hook.finditer(src):
                params = m.group(2)
                if '...' in params:
                    continue
                bad.append((os.path.basename(path), m.group(0)))
        assert not bad, (
            'a field-picker hook names its parameters instead of forwarding them — a pane that '
            'passes one more is silently ignored: ' + str(bad))

    def test_the_scan_finds_the_registry_at_all(self):
        """The rule above is vacuous if the walk misses the files that register pickers."""
        found = [p for p in self._sources()
                 if 'FIELD_PICKERS[' in io.open(p, encoding='utf-8-sig', errors='replace').read()]
        assert len(found) >= 2, f'the picker registrations are not being scanned: {found}'


class TestElModalDeConfirmacionRecibeUnaFuncion:
    """`showConfirmModal(mensaje, callback)` **no devuelve una promesa**.

    Escribirlo como `const ok = await showConfirmModal(msg, t('delete'))` compila, abre el modal
    y no falla nunca — pero `ok` es `undefined`, así que la comprobación siguiente sale por la
    puerta de «ha dicho que no» y **todo lo que venía después no ocurre**. Salió a la pantalla
    como «eliminar no funciona»: el modal preguntaba, el usuario confirmaba, y no pasaba nada.

    Un `await` sobre algo que no es una promesa es la equivocación que no falla: no rompe, no
    avisa, solo hace que el resto de la función no exista. Por eso se vigila desde fuera.
    """

    def _js(self):
        for path, texto in sorted(_all_template_text().items()):
            yield os.path.relpath(path, TPL), texto

    def test_nadie_espera_su_resultado(self):
        malos = [rel for rel, js in self._js()
                 if re.search(r'await\s+showConfirmModal', js)]
        assert not malos, f'`await showConfirmModal` no devuelve nada: {malos}'

    def test_ni_lo_guarda(self):
        malos = [rel for rel, js in self._js()
                 if re.search(r'=\s*showConfirmModal\s*\(', js)]
        assert not malos, f'`showConfirmModal` no devuelve nada que guardar: {malos}'

    def test_el_segundo_argumento_es_una_funcion(self):
        """Un texto donde va la función es un modal cuyo botón de aceptar no hace nada."""
        malos = []
        for rel, js in self._js():
            # La DECLARACIÓN también dice `showConfirmModal(msg, callback…` y no es una
            # llamada: se mira solo lo que no viene precedido de `function`.
            for llamada in re.findall(r'(?<!function )showConfirmModal\(([^;]{0,200})', js):
                resto = llamada.split(',', 1)[1] if ',' in llamada else ''
                if resto and not re.search(r'(\(\s*\)|function|=>|\w+\s*\))', resto[:60]):
                    malos.append((rel, llamada[:60]))
        assert not malos, malos
