#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Infrastructure: the three grouping views.
#
"""Tres formas más de leer la misma flota, y lo que las mantiene honestas.

La lista contesta «qué máquina está en problemas» y las tarjetas la contestan desde el otro
lado de la habitación. Lo que ninguna contestaba es la pregunta que aparece cuando la flota
deja de caber en la cabeza: **qué TIPO de cosa está en problemas** — los switches, los NAS,
los hipervisores — y, sabiendo eso, cuál de ellos.

Son tres porque son tres lecturas y no tres pieles: la **agrupada** enseña todo y te pide que
bajes; el **rail** enseña una cosa y te pide que elijas (con cuatro tipos gana la primera, con
veinte gana el segundo, así que decide la flota); y el **tablero** no agrupa por tipo en
absoluto — es la lectura de triaje, una columna por estado.

Lo que se fija aquí no es cómo se ven, que ningún test puede juzgar, sino las cuatro cosas que
las romperían en silencio:

* **una vista nueva no puede quedarse fuera del bundle.** Su función no existiría y el
  conmutador ofrecería una vista que deja la sección en blanco;
* **las columnas son las que el usuario eligió.** Tres vistas dibujan las mismas filas ahora, y
  una segunda copia de «cómo se pinta una celda de tipo» es cómo una de ellas acaba imprimiendo
  un token crudo bajo una cabecera traducida;
* **por qué se agrupa es un dato**, no algo escrito dentro del render;
* y **`''` no es lo mismo que «sin elegir»** — la trampa que cazó el arnés de node.

Sin Flask: esto lee ficheros y comprueba lo que dicen.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
INFRA = os.path.join(TPL, 'partials', 'infra')
BUNDLE = os.path.join(TPL, 'partials', '_js_sections.html')
CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')
LANGS = os.path.join(SRC, 'lib', 'i18n', 'lang')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _views() -> str:
    return _read(os.path.join(INFRA, '_views.html'))


def _group() -> str:
    return _read(os.path.join(INFRA, '_group_views.html'))


class TestTheViewsAreWiredUp:

    def test_the_registry_declares_all_three(self):
        src = _views()
        for vid, fn in (('grouped', '_infraGroupedBody'),
                        ('rail', '_infraRailBody'),
                        ('board', '_infraBoardBody')):
            assert f"id: '{vid}'" in src, vid
            assert fn in src, fn

    def test_the_partial_is_in_the_bundle(self):
        """A view whose render function is not loaded is a switcher entry that blanks the
        section — and nothing raises, because the dispatch is by name."""
        assert 'partials/infra/_group_views.html' in _read(BUNDLE)

    def test_it_loads_after_the_list(self):
        """It reads the list's cell renderer and its column state. Both are `function` and
        `let` declarations in a concatenated bundle, so the ORDER is the dependency."""
        src = _read(BUNDLE)
        assert src.index('partials/infra/_list.html') < src.index('partials/infra/_group_views.html')

    def test_every_render_function_exists(self):
        """The registry names them as STRINGS — a typo is a blank section at runtime and
        nothing at all at review time.

        Searched across the whole section rather than against a list of which file holds
        which: a skip list is a second place to update every time a view moves, and the one
        that gets forgotten is the guard."""
        section = ''.join(_read(os.path.join(INFRA, f))
                          for f in sorted(os.listdir(INFRA)) if f.endswith('.html'))
        for fn in re.findall(r"render: '([^']+)'", _views()):
            assert f'function {fn}(' in section, fn

    def test_each_view_is_named_in_both_languages(self):
        keys = re.findall(r"label_key: '([^']+)'", _views())
        for lang in ('es_ES', 'en_EN'):
            words = _read(os.path.join(LANGS, f'{lang}.py'))
            for k in keys:
                assert f"'{k}'" in words, f'{k} unworded in {lang}'


class TestTheyShowWhatTheTableShows:
    """Switching how you look at the fleet must not silently change WHAT you are looking at."""

    def test_the_columns_come_from_the_chooser(self):
        src = _group()
        assert '_infraOrderedCols()' in src
        assert '_INFRA_COLS' not in src, 'it built its own column list'

    def test_the_cells_come_from_one_renderer(self):
        """Three views draw the same rows now. A second copy of "what a device_type cell looks
        like" is how one of them ends up printing a raw token under a translated heading —
        which is the bug the `kind` column already had once."""
        src = _group()
        assert '_infraCell(' in src
        assert 'hostTypeLabel' in _read(os.path.join(INFRA, '_list.html'))
        # …and the list's own table delegates to the same one rather than keeping a copy.
        assert '_infraCell(uid, colId)' in _read(os.path.join(INFRA, '_list.html'))

    def test_the_chooser_stays_on_screen_for_them(self):
        """They draw their own tables out of the chosen columns, so hiding the column chooser
        would be taking the control away from the thing it controls."""
        src = _read(os.path.join(INFRA, '_list.html'))
        line = next(ln for ln in src.splitlines() if 'showChooser' in ln)
        assert '_infraView.view().columns' in line, line
        assert "columns: true" in _views()

    def test_they_get_the_whole_fleet_and_not_one_page(self):
        """A group split across a page boundary is a group whose count is a lie, and a rail
        that loses half its machines to pagination is worse."""
        src = _views()
        for vid in ('grouped', 'rail', 'board'):
            entry = next(ln for ln in src.splitlines() if f"id: '{vid}'" in ln)
            assert "mode: 'summary'" in entry, entry


class TestWhatItGroupsByIsData:

    def test_the_groupers_are_a_declared_list(self):
        """One entry, one reading. A fleet tagged by rack is grouped by tag and one being
        migrated by operating system, and none of that is written into the render."""
        src = _group()
        keys = re.findall(r"\{ key: '([^']+)', label_key:", src)
        assert set(keys) >= {'device_type', 'tags', 'os', 'kind', 'status'}, keys

    def test_the_default_is_the_kind_of_device(self):
        assert re.search(r"_INFRA_GROUPERS = \[\s*\{ key: 'device_type'", _group())

    def test_a_machine_can_be_in_several_groups(self):
        """`of()` returns a LIST because a machine has one device type and any number of tags,
        and a box that appears under both `prod` and `nas` is the point."""
        line = next(ln for ln in _group().splitlines() if "key: 'tags'" in ln)
        body = _group().split("key: 'tags'")[1].split('},')[0]
        assert 'h.tags' in body and '.slice()' in body, line

    def test_the_groups_read_worst_first(self):
        """The whole reason this section sorts by state is that it is opened when something is
        wrong. A grouping that then put the switches first because "s" comes early would be
        answering a question nobody asked."""
        body = _group().split('function _infraGroups(')[1].split('\n}')[0]
        assert 'counts.error' in body and 'sort(' in body

    def test_maintenance_is_not_counted_as_trouble(self):
        """Somebody chose that state. Counting it as an error would put a group at the top of
        the screen for a decision its owner made."""
        body = _group().split('function _infraGroups(')[1].split('\n}')[0]
        assert 'h.maintenance' in body


class TestTheTrapsThatWereActuallyHit:

    def test_an_unset_rail_is_not_the_untyped_group(self):
        """`null` is "nothing picked yet" and `''` is "the machines with no device type" — two
        different things that collapse the moment either is written as a falsy string. They
        did: an unset rail opened on the untyped group, because a fleet HAS one. Caught by
        running the real code, not by reading it.
        """
        src = _group()
        assert "|| ''; } catch (_) { return ''; }" not in src
        assert '_infraRailPick !== null' in src, 'the two emptinesses are one again'

    def test_a_pick_that_no_longer_exists_falls_back(self):
        """A fleet loses a device type the day its last switch is deleted, and a rail pinned to
        it would open on an empty screen and look broken."""
        body = _group().split('function _infraRailBody(')[1].split('\n}')[0]
        assert 'groups[0].value' in body

    def test_the_board_keeps_an_empty_lane(self):
        """"No machine is down" is the answer somebody came for, and an empty column says it
        where a missing column says nothing at all."""
        body = _group().split('function _infraBoardBody(')[1].split('\n}')[0]
        assert 'infra_board_empty' in body

    def test_the_group_heading_does_not_read_as_a_row(self):
        """It is furniture inside a table of data, and the class that says so is shared with
        the routing matrix — which is also why these tables pair it with the accent hover
        rather than the grey one, or the row under the cursor looks like another heading."""
        assert 'ss-group-row' in _group()
        css = _read(CSS)
        assert '.ss-group-row' in css
        assert 'ss-hover-accent' in _group(), 'the grey hover would match the heading fill'

    def test_every_class_it_uses_is_defined(self):
        """A layout class that only exists in the markup is a view that lays itself out by
        accident — the rail has a fixed width and its own scroll for a reason."""
        css = _read(CSS)
        for cls in ('ss-infra-rail', 'ss-infra-board'):
            assert cls in _group(), cls
            assert f'.{cls}' in css, f'{cls} is used and not defined'


class TestTheLinkMap:
    """El otro mapa: no direcciones, **cables**.

    El mapa de red contesta «quién alcanza a quién» — direcciones, las redes en las que están y
    la salida de cada una — porque esa es la capa que el panel siempre puede ver: toda máquina
    conoce su propia dirección. Lo que ese mapa no puede contestar es **qué está enchufado a
    qué**, y eso sí lo sabe el equipo: la tabla de vecinos de un switch nombra la caja del otro
    extremo y el puerto por el que contestó, y su tabla de reenvío coloca una máquina en un
    puerto por la MAC que aprendió ahí.

    **El servidor ya lo construye.** `infra/topology.py` emite esa adyacencia al lado de las
    redes, con el puerto de cada extremo y quién lo dijo. Esto es una segunda LECTURA de un
    único payload, no un segundo endpoint: dos joins sobre la misma evidencia serían dos
    respuestas a «¿está ese cable ahí?».

    Y lo que no puede dejar de decir es **cómo lo sabe**. Un vecino que los dos extremos
    confirman es un hecho; uno que dice un solo extremo casi lo es; una máquina colocada por
    una tabla de reenvío es una deducción — dice que es *alcanzable* por ese puerto. Tres
    afirmaciones, tres trazos, y la leyenda las nombra las tres.
    """

    def _links(self):
        return _read(os.path.join(INFRA, '_links.html'))

    def test_the_view_is_registered_and_bundled(self):
        assert "id: 'links'" in _views() and '_infraLinksBody' in _views()
        assert 'partials/infra/_links.html' in _read(BUNDLE)

    def test_it_loads_after_the_map_it_shares_data_with(self):
        """It reads the map's loader, its cache and its clipping helper — all `function` and
        `let` in a concatenated bundle, so the order IS the dependency."""
        src = _read(BUNDLE)
        assert src.index('partials/infra/_map.html') < src.index('partials/infra/_links.html')

    def test_it_asks_for_no_JOIN_of_its_own(self):
        """One join, two readings. A second fleet-wide join over the same evidence would be a
        second answer to whether a cable is there — and twice the work on every open.

        It may ask for the CALLER's own things, which is a different kind of request: the
        arrangement somebody saved is about this screen and about nobody else's fleet.
        """
        src = self._links()
        urls = set(re.findall(r"api(?:Get|Put|Post|Delete)\w*\('([^']+)'", src))
        assert '/api/v1/infra/map' not in urls, 'the map payload is fetched once, elsewhere'
        assert urls <= {'/api/v1/infra/link-layout'}, urls
        assert '_infraMap' in src and '_infraMapLoad(' in src

    def test_a_gateway_is_not_a_cable(self):
        """A default route is a statement about traffic, not about a wire: drawing it here
        would put a line between two machines that may be four hops apart."""
        body = self._links().split('function _infraLinkEdges(')[1].split('\n}')[0]
        assert "'lldp'" in body and "'port'" in body
        assert "'gateway'" not in body

    def test_the_three_claims_are_drawn_differently(self):
        """The difference between a cable two devices agree on and a MAC a switch happened to
        learn is the difference between a fact and a good guess. A picture that draws them
        alike is lying about which of the two it has."""
        src = self._links()
        strokes = src.split('_LNK_STROKE = {')[1].split('};')[0]
        for claim in ('both', 'one', 'learned'):
            assert claim in strokes, claim
        # The table is DATA now — the same three answers are drawn as the cable, as the sample
        # beside the panel heading, and twice as a legend — so what is checked is the dash on
        # the one that is an inference, not the word in an attribute string.
        learned = strokes.split('learned:')[1].split('}')[0]
        assert re.search(r"dash: '\d", learned), 'the inference is drawn like a fact'
        # …and every one of them is named on screen.
        for claim in ('both', 'one', 'learned'):
            assert f'infra_link_claim_{claim}' in src

    def test_an_empty_map_says_where_the_lines_would_come_from(self):
        """"No cables found" and "nothing here serves neighbour discovery" are the same screen
        and very different problems, and only one is something to go and fix."""
        assert 'infra_link_none' in self._links()
        for lang in ('es_ES', 'en_EN'):
            words = _read(os.path.join(LANGS, f'{lang}.py'))
            assert "'infra_link_none'" in words, lang
        note = _read(os.path.join(LANGS, 'es_ES.py'))
        line = next(ln for ln in note.splitlines() if "'infra_link_none'" in ln)
        assert 'LLDP' in line, 'it shrugs instead of saying where they come from'

    def test_a_machine_with_no_cable_is_named_and_not_floated(self):
        """A box with nothing attached, inside a diagram OF attachments, reads as a link that
        failed to draw — which is exactly what somebody would report."""
        src = self._links()
        assert 'infra_link_loose' in src
        body = src.split('function _infraLinkLayout(')[1].split('\n}')[0]
        assert 'loose' in body

    def test_the_layout_is_stable_between_redraws(self):
        """A map that reorders itself on every refresh reads as movement nobody caused. Both
        the root and the order inside a tier are sorted, not taken as they arrive."""
        body = self._links().split('function _infraLinkLayout(')[1].split('\n}')[0]
        assert body.count('sort(') >= 2, body.count('sort(')

    def test_it_carries_no_layout_library(self):
        """The page is self-contained — no CDN — and a spring simulation on a flat rack
        produces the hairball the other map was rewritten to stop producing."""
        src = self._links()
        for word in ('d3', 'cytoscape', 'vis.js', 'import '):
            assert word not in src, word


class TestTheCachedMapReachesWhoeverIsWaitingForIt:
    """The fleet-wide join is fetched once and cached. Whoever is on screen when it lands has
    to be redrawn — and the redraw named ONE view.

    Reported from the screen: open Links, and it says "loading…" for ever. The request had
    landed, the cache was full, and the answer was in memory the whole time; the only thing
    that never happened was the redraw, because the condition was written when `map` was the
    only view that read the payload.

    So the fact moved into the registry, where the view declares that it reads it. A third
    reader needs no edit here — which is the actual fix, because the bug was not the condition
    being wrong, it was being somewhere a second reader had no reason to look.
    """

    def _map(self):
        return _read(os.path.join(INFRA, '_map.html'))

    def test_the_loader_redraws_by_what_the_view_declares(self):
        body = self._map().split('async function _infraMapLoad(')[1].split(chr(10) + '}')[0]
        assert '_infraView.view().map' in body, body
        assert "_infraView.is('map')" not in body, 'it names one view again'

    def test_both_map_readers_declare_it(self):
        src = _views()
        for vid in ('map', 'links'):
            entry = next(ln for ln in src.splitlines() if f"id: '{vid}'" in ln)
            assert 'map: true' in entry, entry

    def test_and_nothing_else_does(self):
        """The flag means "this view reads the fleet-wide join". A list view carrying it would
        be redrawn under the user by a fetch it never asked for."""
        src = _views()
        for vid in ('card', 'table', 'grouped', 'rail', 'board'):
            entry = next(ln for ln in src.splitlines() if f"id: '{vid}'" in ln)
            assert 'map: true' not in entry, entry

    def test_one_fetch_serves_both(self):
        """Two views over one payload — the cache is what makes that true, and a second view
        that refetched on every switch would make the section slower the more it is used."""
        body = self._map().split('async function _infraMapLoad(')[1].split(chr(10) + '}')[0]
        assert '_infraMapBusy' in body and '_infraMap && !force' in body


class TestTheLinkMapCanBeMovedAround:
    """A diagram that only fits is a diagram you cannot read.

    Reported from the screen with a picture attached: eight devices, the boxes squeezed to the
    pane's width, port names on top of each other. Two separate problems in one image — the
    picture had no zoom, and every cable between the same two tiers crossed the same centre, so
    every label was written into the same ten-pixel channel.

    The window is a **viewBox** and not a transform on a group: with a viewBox the strokes and
    the text scale WITH the picture, so zooming in to read a port name actually makes it
    bigger. A scaled group does the same to the geometry and then every `stroke-width` has to
    be divided back out by hand, or the lines fatten into slabs.

    It lives in `_canvas.html` now, because the address map needed the same thing and a second
    copy of "where am I looking" would agree with this one until the day it did not.
    """

    def _links(self):
        return _read(os.path.join(INFRA, '_links.html'))

    def _canvas(self):
        return _read(os.path.join(INFRA, '_canvas.html'))

    def test_the_canvas_is_a_window_and_not_a_stretched_picture(self):
        src = self._links()
        assert 'ss-infra-canvas' in src
        css = _read(CSS)
        assert '.ss-infra-canvas' in css
        block = css.split('.ss-infra-canvas {')[1].split('}')[0]
        assert 'height' in block, 'a window with no height is the picture again'

    def test_it_zooms_by_the_viewbox(self):
        """Not by scaling a group: the strokes and the labels have to grow with it, or zooming
        in to read a port name gives you a bigger blur."""
        src = self._canvas()
        assert "setAttribute('viewBox'" in src
        assert 'transform="scale' not in src and 'transform="scale' not in self._links()

    def test_the_wheel_does_not_scroll_the_page(self):
        """A wheel meant for the map that also moves the page underneath is a map you cannot
        zoom without losing it. Inline handlers are not passive, which is why it is one."""
        assert 'onwheel="ssCanvasWheel(' in self._links()
        body = self._canvas().split('function ssCanvasWheel(')[1].split(chr(10) + '}')[0]
        assert 'preventDefault()' in body

    def test_the_zoom_is_bounded_both_ways(self):
        """Past a few times in it is one box on screen and past a few times out the devices are
        specks. Both are one wheel flick away and neither is a view of anything."""
        body = self._canvas().split('function ssCanvasZoomAt(')[1].split(chr(10) + '}')[0]
        assert 'Math.min(' in body and 'Math.max(' in body

    def test_and_there_is_one_window_and_not_one_per_map(self):
        """Two copies of pan, zoom and fit would agree until the day they did not — and the day
        they did not, one map would zoom about the cursor and the other about the centre for
        reasons nobody could find. Keyed by the id of the `<svg>`, so two drawings can be in
        two places at once without being two implementations."""
        canvas = self._canvas()
        assert 'const _ssVB = {}' in canvas, 'the window is a single value again'
        for name in ('ssCanvasWindow', 'ssCanvasFit', 'ssCanvasZoomAt', 'ssCanvasPoint',
                     'ssCanvasPanStart', 'ssCanvasTools'):
            assert f'function {name}(id' in canvas, name
        # …and neither map keeps one of its own.
        for f in ('_links.html', '_map.html'):
            src = _read(os.path.join(INFRA, f))
            assert 'getBoundingClientRect()' not in src, f'{f} works out its own coordinates'

    def test_a_drag_on_a_device_does_not_move_the_map(self):
        """A click that opens a device and a drag that pans would share a gesture, and the map
        would jump every time somebody missed by two pixels."""
        src = self._links()
        assert 'data-node' in src
        body = src.split('function _infraLinkDown(')[1].split(chr(10) + '}')[0]
        # The selector is a LIST now — a port chip must not start a pan either — so what is
        # pinned is that a device is in it, not the exact string.
        assert 'data-node' in body and 'closest(' in body

    def test_there_is_a_way_back_to_the_whole_thing(self):
        """"Show me all of it" has no gesture, and a trackpad pinch is not something every
        pointer can do."""
        assert "function ssCanvasFit(" in self._canvas()
        assert 'ssCanvasTools(' in self._links(), 'the map lost its zoom buttons'
        for key in ('infra_link_zoom_in', 'infra_link_zoom_out', 'infra_link_fit'):
            assert key in self._canvas()
            for lang in ('es_ES', 'en_EN'):
                assert f"'{key}'" in _read(os.path.join(LANGS, f'{lang}.py')), (key, lang)

    def test_no_text_is_drawn_over_the_cables_at_all(self):
        """Where the port names used to be. Three attempts — midpoint captions, end captions,
        chips — and every one collided, because every cable out of a box starts at the same
        point. They live in the hover panel now, which has room for them."""
        body = self._links().split('function _infraLinkWires(')[1].split(chr(10) + '}')[0]
        assert '<text' not in body and 'text-anchor' not in body

    def test_the_window_is_not_remembered_across_reloads(self):
        """It is where you are looking right now. A remembered zoom over a map whose boxes have
        since moved is a window onto empty space, and the fleet moves.

        The ARRANGEMENT is remembered, and the two are not the same thing: where somebody put
        a box is a decision, and where they happened to be zoomed is a moment. So the guard is
        no longer "this file does not persist" — it is that the only thing it persists is the
        arrangement, under its own key.
        """
        src = self._canvas()
        # The CALLS, not the word: this file's own prose says what it does and does not keep,
        # which is exactly the sentence a guard on the word would trip over.
        calls = re.findall(r'localStorage\.\w+\(([^,)]*)', src)
        assert calls, 'the arrangement is not being kept at all'
        # `was` is the one key it reads and never writes: the arrangement somebody saved
        # before this moved, carried forward under the key above. And `ss_infra_panel` is
        # whether the reading panel is shown at all — a preference about LOOKING, which is the
        # same kind of thing as the arrangement and not the same kind as the window: somebody
        # turned it off on purpose and it has to still be off tomorrow.
        assert set(x.strip() for x in calls) == {
            '_SS_POS_KEY', 'was', "'ss_infra_panel'"}, calls
        assert (re.findall(r'localStorage\.setItem\(([^,)]*)', src)
                == ['_SS_POS_KEY', "'ss_infra_panel'"])
        # …and the window itself is never in it: `_ssVB` is written by nothing that persists.
        assert '_ssVB' not in re.sub(r'^(?!.*localStorage).*$', '', src, flags=re.M)
        # Neither map keeps one of its own either.
        for f in ('_links.html', '_map.html'):
            assert 'localStorage' not in _read(os.path.join(INFRA, f)), f


class TestTheMapTakesTheWorkArea:
    """A fixed height is a band of empty page on a tall screen and a cut-off map on a short one.

    Reported with the wasted band circled in red: the canvas was `62vh`, which is a guess about
    somebody else's window. It takes what is left after the note above it and the legend below
    instead — the same chain the rail boxes already use, where the scroll container becomes a
    flex column that does not scroll and the fill inside it takes the rest.
    """

    def test_the_canvas_fills_instead_of_measuring_the_viewport(self):
        css = _read(CSS)
        block = css.split('.ss-infra-canvas {')[1].split('}')[0]
        assert 'flex: 1 1 auto' in block, block
        assert 'vh' not in block, 'a slice of the viewport is not the work area'

    def test_the_chain_that_lets_it(self):
        """Three rules and all three are needed: the scroll container stops scrolling and
        becomes a column, the body fills it, and the canvas takes what is left. Miss one and
        the map is back to its own content height with the page scrolling around it."""
        css = _read(CSS)
        assert '.ss-vscroll:has(.ss-mapfill)' in css
        assert '.ss-mapfill {' in css
        assert 'ss-mapfill' in _read(os.path.join(INFRA, '_links.html'))


class TestAPortOnTheMapGoesToThePort:
    """"Which port of which device" is the question somebody opened that map to answer.

    Having answered it, the screen should be able to take you there — rather than leave you to
    find the same port again in a list of forty-eight.

    The names are NOT on the canvas. They were captions, then end captions, then chips, and
    every one collided for the same reason: every cable out of a box leaves from the SAME
    point, so four labels land in one place beside the switch, and staggering them along their
    curves only spreads them as far as the curves have diverged — which near the box is not
    far. Reported twice, with a picture each time. The detail moved into a panel instead, where
    it has room to be the whole reading: both machines, both ports, how it is known, and a way
    into each of the four.

    The match is a ladder and not an equality, because the two ends do not have to agree on the
    spelling: a neighbour reports `bridge1/sfp-sfpplus1` for what the device itself calls
    `sfp-sfpplus1` — the bridge in front is the far end saying where the port sits, not part of
    its name.
    """

    def _det(self):
        return _read(os.path.join(INFRA, '_details.html'))

    def _links(self):
        return _read(os.path.join(INFRA, '_links.html'))

    def test_a_cable_is_hoverable_on_purpose(self):
        """A 1.4-pixel dashed line is not something anybody can hover deliberately, so there is
        a transparent fat stroke under the visible one."""
        wires = self._links().split('function _infraLinkWires(')[1].split(chr(10) + '}')[0]
        assert 'stroke="transparent"' in wires and 'stroke-width="14"' in wires
        assert 'onpointerenter="_infraLinkHover(' in wires

    def test_a_hover_is_a_question_and_a_click_is_a_decision(self):
        """Two states, because they answer to two gestures.

        A hover ends when the pointer leaves. A click has to survive it: the panel carries four
        links — two machines, two ports — and one that vanished on the way to being clicked
        would be one nobody could use. Reported from the screen with the panel circled: every
        hover pinned itself, so the map ended up permanently wearing a reading of a cable
        nobody had asked about.
        """
        src = self._links()
        assert 'let _lnkHover' in src and 'let _lnkPick' in src
        wires = src.split('function _infraLinkWires(')[1].split(chr(10) + '}')[0]
        assert 'onpointerleave="_infraLinkHover(null)"' in wires, 'a hover has to end'
        assert '_infraLinkPin(' in wires, 'and a click has to keep it'

    def test_hovering_reads_the_cable_under_the_pointer_and_then_gives_it_back(self):
        """With one kept, hovering another still reads it — otherwise the pin would make the
        rest of the map unreadable — and letting go returns to the one being worked on."""
        body = self._links().split('function _lnkOn(')[1].split(chr(10) + '}')[0]
        assert '_lnkHover !== null ? _lnkHover : _lnkPick' in body

    def test_an_unkept_panel_offers_the_gesture_instead_of_a_close_button(self):
        """An × on a panel that disappears when the pointer leaves the cable is a button that
        cannot be reached to be pressed. What goes there is what would make it stay."""
        body = self._links().split('function _infraLinkPanelHtml(')[1].split(chr(10) + '}')[0]
        assert 'kept ?' in body and "infra_link_pin'" in body
        for lang in ('en_EN', 'es_ES'):
            assert "'infra_link_pin'" in _read(os.path.join(LANGS, lang + '.py')), lang

    def test_and_there_are_two_ways_to_put_a_kept_one_away(self):
        src = self._links()
        assert 'function _infraLinkHide(' in src
        down = src.split('function _infraLinkDown(')[1].split(chr(10) + '}')[0]
        assert '_infraLinkHide()' in down
        # …clicking the kept cable again included, which is the gesture that kept it.
        pin = src.split('function _infraLinkPin(')[1].split(chr(10) + '}')[0]
        assert '_lnkPick === i ? null : i' in pin

    def test_the_panel_offers_all_four_ends(self):
        """Two machines and two ports: the map answered which port of which device, so it can
        take you to either side of either."""
        body = self._links().split('function _infraLinkPanelHtml(')[1].split(chr(10) + '}')[0]
        assert 'infraOpen(' in body and 'e.from' in body and 'e.to' in body
        # The port half is one helper away — the panel says WHICH port, that says how to draw
        # one, and a port is a path that can be several things (see below).
        assert '_infraLinkPortHtml(' in body

    def test_a_cable_with_one_port_named_says_so(self):
        """A forwarding-table link knows the switch's port and nothing about the far end.
        Leaving that side blank reads as a panel that failed to fill in."""
        body = self._links().split('function _infraLinkPortHtml(')[1].split(chr(10) + '}')[0]
        assert 'infra_link_no_port' in body
        for lang in ('es_ES', 'en_EN'):
            assert "'infra_link_no_port'" in _read(os.path.join(LANGS, lang + '.py')), lang

    def test_a_port_path_is_drawn_as_the_things_it_names(self):
        """A MikroTik answers `bridge1/bond1/ether11`: the physical port that
        carried the frame, and above it the bond it belongs to and the bridge that bond is in.
        As one string it reads as a port with a long name, and the fact that matters — this is
        ONE MEMBER of a four-port LAG — is buried in the middle. Reported in those words: "it
        says ether11, but it is not just ether11".

        Not an inference: the DEVICE wrote the path, and each segment is something it named.
        Each is its own way in, because each may be a row on its page — a bond has counters of
        its own and so does a member."""
        # In the one-port helper: a side is a LIST now (a trunk puts several of a machine's
        # ports on the same pair of boxes), and each of those is a path of its own.
        body = self._links().split('function _infraLinkOnePort(')[1].split(chr(10) + '}')[0]
        assert "split('/')" in body
        assert body.count('infraOpenPort(') == 1, 'one jump per segment, from one place'

    def test_a_port_mac_is_not_offered_as_a_port(self):
        """A device with no port description reports its portId instead, and on a good many
        switches that is the port's hardware address. True, and not a port name: there is no
        interface called `00:00:5E:00:53:01` to open, and a button that landed on the device's
        summary would be one that looks like it failed."""
        src = self._links()
        assert '_LNK_MAC' in src
        body = src.split('function _infraLinkOnePort(')[1].split(chr(10) + '}')[0]
        mac_branch = body.split('_LNK_MAC.test(raw)')[1].split('    const parts')[0]
        assert 'infraOpenPort(' not in mac_branch, 'it offers a jump to a name nothing has'
        assert 'infra_link_port_mac' in mac_branch
        for lang in ('es_ES', 'en_EN'):
            assert "'infra_link_port_mac'" in _read(os.path.join(LANGS, lang + '.py')), lang

    def test_a_box_says_what_kind_of_thing_it_is(self):
        """A rack drawn as eight identical boxes makes you read every name to find the switch.
        Through `hostTypeIcon`, so it is the same icon as the list, the cards and the device
        page — a second table of "what a NAS looks like" is how one screen ends up disagreeing
        with the others about a device somebody just retyped."""
        box = self._links().split('function _infraLinkBox(')[1].split(chr(10) + '}')[0]
        assert 'hostTypeIcon(' in box
        assert 'foreignObject' in box, 'SVG has no <i>, and these are font glyphs'

    def test_the_port_waits_for_the_payload(self):
        """The machine may not be loaded. Waiting inside the click handler would mean two code
        paths for opening a device, and the one used less is the one that rots."""
        src = self._det()
        assert '_infraPortWanted' in src
        body = src.split('function infraOpenPort(')[1].split(chr(10) + '}')[0]
        assert 'infraOpen(' in body
        assert '_infraFocusPort()' in _read(os.path.join(INFRA, '_render.html'))

    def test_it_finds_the_row_through_the_tallies(self):
        """A count knows which rows it is about, so the port's row is looked up in those rather
        than re-derived — the same reason the rows pane does not re-derive them either."""
        body = self._det().split('function _infraFocusPort(')[1].split(chr(10) + '}')[0]
        assert "headline !== 'tally'" in body and 'row_key' in body

    def test_a_name_qualified_by_its_bridge_still_matches(self):
        body = self._det().split('function _infraFocusPort(')[1].split(chr(10) + '}')[0]
        assert 'lastIndexOf' in body, 'only an exact match is tried'

    def test_a_port_that_matches_nothing_just_opens_the_device(self):
        """A mixed rack where the two ends spell a port differently is normal, and an error
        message for a click that did what it looked like it would is not."""
        body = self._det().split('function _infraFocusPort(')[1].split(chr(10) + '}')[0]
        assert 'if (!hit) return;' in body
        assert 'showToast' not in body


class TestWhichEndIsTheOneSayingIt:
    """"One end says so" is a claim about the EVIDENCE, and the first thing anybody asks of it
    is which one.

    Reported from the screen with the banner open: the cable read "Lo dice un extremo" and
    nothing on it said whether that was the router or the server. The answer is what decides
    where you go looking — a machine that reports no neighbours is a machine with no LLDP
    agent, or with one that is not publishing LLDP-MIB over SNMP — so leaving the reader to
    infer it from which side happens to have a port name is leaving out the point.

    `by` has been in the payload since the map was built; it simply never reached the screen.
    """

    def _panel(self):
        src = _read(os.path.join(INFRA, '_links.html'))
        return src.split('function _infraLinkPanelHtml(')[1].split(chr(10) + '}')[0]

    def test_the_end_that_reported_it_is_marked_on_that_end(self):
        body = self._panel()
        assert '(e.by || []).includes(uid)' in body, 'the payload already says who'
        assert 'infra_link_said' in body and 'infra_link_silent' in body

    def test_and_only_where_the_claim_is_about_one_end(self):
        """Two reporters need no badge — both did — and a cable read off a forwarding table
        was reported by neither, so a badge there would be answering a question nobody asked
        of it."""
        body = self._panel()
        assert "claim === 'one' ?" in body

    def test_the_silent_end_says_what_silence_means(self):
        """A badge that only says "no" sends somebody to look for a fault. The two reasons an
        end reports nothing are both configuration, and one of them is the whole of it on
        Debian: lldpd runs, and without its AgentX subagent nothing is served over SNMP."""
        for lang in ('en_EN', 'es_ES'):
            text = _read(os.path.join(LANGS, lang + '.py'))
            line = [x for x in text.splitlines() if "'infra_link_silent_tt'" in x]
            assert line, lang
            assert 'agentx' in line[0].lower() and 'lldpd' in line[0].lower(), lang


class TestABoxIsAlsoSomethingToREAD:
    """"Which machine is that box" is the other question this map gets asked.

    The cables already answer theirs in a panel; a box answered with a name and a link count.
    So it uses the same panel — and a box under the pointer wins over any cable, because it is
    what is being pointed AT, with the kept cable coming back the moment the box is left.

    Built from what is ALREADY loaded and never from a fetch: this runs on every pointer that
    crosses a box, and a request per hover is a request per pixel of travel across a rack.
    """

    def _src(self):
        return _read(os.path.join(INFRA, '_links.html'))

    def _fn(self, name):
        return self._src().split('function ' + name + '(')[1].split(chr(10) + '}')[0]

    def _card(self):
        return _read(os.path.join(INFRA, '_canvas.html')).split(
            'function ssHostCard(')[1].split(chr(10) + '}')[0]

    def test_a_box_reads_from_what_is_already_in_hand(self):
        body = self._card()
        assert 'apiGet' not in body and 'fetch(' not in body, 'a request per hover'
        assert '_infraHosts' in body, 'the list screen already holds the rest of the row'

    def test_and_says_the_things_somebody_hovers_a_box_to_learn(self):
        body = self._card()
        for key in ('infra_link_addresses', 'infra_link_networks', 'infra_link_gateway',
                    'infra_link_cables', 'col_host_os', 'host_type'):
            assert key in body, key
        for lang in ('en_EN', 'es_ES'):
            text = _read(os.path.join(LANGS, lang + '.py'))
            for key in ('infra_link_addresses', 'infra_link_networks', 'infra_link_gateway',
                        'infra_link_cables', 'infra_link_node_hint'):
                assert f"'{key}'" in text, (key, lang)

    def test_what_the_pointer_is_on_is_what_the_panel_shows(self):
        body = self._fn('_infraLinkPanelHtml')
        assert 'if (auto && _lnkNode && L.pos[_lnkNode]) return _infraLinkNodeHtml(' in body
        # …and it is only ever a hover, so leaving gives back whatever was kept.
        assert "_lnkNode = ''" in self._src()

    def test_and_switched_off_it_still_answers_a_question_that_was_ASKED(self):
        """The switch is about the panel turning up on its own. Pressing a cable is somebody
        asking, and refusing that would leave no way at all to find out what a cable is —
        uncluttered by being unreadable."""
        body = self._fn('_infraLinkPanelHtml')
        assert 'if (!auto && _lnkPick === null) return' in body, \
            'switching it off takes the answer away from the question too'
        assert 'const on = auto ? _lnkOn() : _lnkPick;' in body, \
            'with it off, the pointer passing over a cable still opens it'

    def test_a_field_the_device_did_not_answer_is_not_a_blank_row(self):
        """A card of empty labels reads as a machine that answered nothing, which is a
        different thing from a machine with no tags."""
        assert 'const row = (icon, label, value) => (value' in self._card()

    def test_and_BOTH_maps_show_the_same_machine_the_same_way(self):
        """"Which machine is that box" is asked of either picture, and two answers to it are
        two things to keep in agreement."""
        for f in ('_links.html', '_map.html'):
            assert 'ssHostCard(' in _read(os.path.join(INFRA, f)), f


class TestTheBoxesCanBePutWhereTheyBelong:
    """A generated layout is a good first answer and is nobody's rack.

    The person reading either map knows which switch is in which cupboard, and a picture they
    can arrange the way the room is arranged is a different picture from one they can only look
    at. Both maps take one, so it lives in `_canvas.html` with the window: a second copy of
    "where did somebody put this" would agree with the first until the day it did not.

    The whole difficulty is that a box already HAS a gesture — clicking it opens the device —
    so "move this" and "open this" have to come apart without a modifier key nobody discovers.
    """

    def _canvas(self):
        return _read(os.path.join(INFRA, '_canvas.html'))

    def _fn(self, name, where='_canvas.html'):
        return _read(os.path.join(INFRA, where)).split(
            'function ' + name + '(')[1].split(chr(10) + '}')[0]

    def test_a_press_becomes_a_drag_only_after_it_travels(self):
        """In SCREEN pixels, so the threshold means the same at every zoom: three units of a
        picture scaled to a quarter is a third of a millimetre, and every click on a box would
        move it."""
        assert '_SS_GRIP' in self._canvas()
        body = self._fn('ssCanvasDragMove')
        assert '_SS_GRIP' in body and 'ev.clientX' in body

    def test_a_press_that_did_not_travel_still_opens_the_device(self):
        """Fired from the pointerup and not from an `onclick` on the box, and either half of
        the reason is enough on its own: the pointer capture the drag runs on retargets the
        click to the `<svg>`, so a handler on the `<g>` never sees it — and a drag redraws the
        picture, so the element that was pressed is gone before the click can land on it.

        Reported from the screen as "clicking a device only moves it now": the guard that
        replaced it was checking the handler existed, which it did.
        """
        end = self._fn('ssCanvasDragEnd')
        assert 'return drag.uid' in end, 'nothing tells the caller it was a click'
        for f, up in (('_links.html', '_infraLinkUp'), ('_map.html', '_infraMapUp')):
            src = _read(os.path.join(INFRA, f))
            assert 'onclick' not in src.split('function ' + (
                '_infraLinkBox(' if 'links' in f else '_infraMapBox('))[1].split(
                    chr(10) + '}')[0], f
            body = src.split('function ' + up + '(')[1].split(chr(10) + '}')[0]
            assert 'ssCanvasDragEnd(' in body and 'infraOpen(' in body, f

    def test_where_a_box_was_put_is_applied_in_the_LAYOUT(self):
        """Not at draw time. Everything downstream reads one set of positions — the wires, the
        extent, the panel — and a line computed from the generated layout while the box is
        drawn somewhere else is a line that ends in the air."""
        for f, fn in (('_links.html', '_infraLinkLayout'), ('_map.html', '_infraMapLayout')):
            body = _read(os.path.join(INFRA, f)).split(
                'function ' + fn + '(')[1].split(chr(10) + '}')[0]
            assert 'ssCanvasPlace(' in body, f

    def test_and_the_drawing_grows_to_hold_it(self):
        """A box dragged past the old extent would sit outside the viewBox: a device you moved
        and then could not find."""
        body = self._fn('ssCanvasPlace')
        assert 'farX' in body and 'farY' in body and 'nearX' in body

    def test_a_box_can_be_put_anywhere_at_all(self):
        """It was clamped at the origin, which was reported from the screen: the pane is
        letterboxed around a fitted drawing, so there is visibly empty room to the left of the
        picture and a box would not go into it.

        The fix is not a bigger clamp. The drawing's own ORIGIN moves to wherever its leftmost
        and topmost box is, so nothing is out of bounds — the picture is simply bigger — and
        "fit" starts there rather than at zero, or half of it would be off screen.
        """
        assert 'Math.max(' not in self._fn('ssCanvasDragMove'), 'a clamp is back'
        place = self._fn('ssCanvasPlace')
        assert 'Math.min(0, nearX' in place and 'Math.min(0, nearY' in place
        for name in ('ssCanvasFit', 'ssCanvasWindow'):
            assert 'svg.dataset.x' in self._fn(name), name

    def test_the_arrangement_survives_leaving_the_screen(self):
        """A layout that resets on every navigation is one nobody bothers to make. Per browser,
        because it is a preference about a picture and not a fact about the fleet — and two
        admins are entitled to two arrangements of one rack."""
        canvas = self._canvas()
        assert "_SS_POS_KEY = 'ss_infra_pos'" in canvas
        read = self._fn('_ssMovedAll')
        assert 'Number.isFinite' in read, 'one bad number puts a box at NaN, which draws nothing'
        assert 'catch' in read, 'a private window has no store and this must still draw'
        assert 'catch' in self._fn('ssCanvasMovedSave')

    def test_and_one_drawing_is_not_the_other(self):
        """Where a machine sits on the map of cables says nothing about where it belongs on the
        map of addresses. Keyed by the canvas, in the browser and on the account alike."""
        assert 'function ssCanvasMoved(id)' in self._canvas()
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        assert 'def normalise_map_layouts(' in svc

    def test_it_is_written_on_release_and_not_on_every_move(self):
        """A drag is a stream of events; sixty writes for one box that ends in one place."""
        assert 'ssCanvasMovedSave()' in self._fn('ssCanvasDragEnd')
        assert 'ssCanvasMovedSave' not in self._fn('ssCanvasDragMove')

    def test_the_toolbar_is_repainted_where_the_drawing_is_not(self):
        """Reported from the screen: the save button only turned up after leaving the section
        and coming back. A drag redraws the PICTURE — that is what keeps it smooth — and the
        toolbar is not in it, while whether there is anything to save is a fact about the
        arrangement rather than about the drawing."""
        for f, up, box in (('_links.html', '_infraLinkUp', 'infraLinkTools'),
                           ('_map.html', '_infraMapUp', 'infraNetTools')):
            src = _read(os.path.join(INFRA, f))
            body = src.split('function ' + up + '(')[1].split(chr(10) + '}')[0]
            assert 'ToolsPaint' in body, f
            assert f'id="{box}"' in src, f

    def test_the_redraw_keeps_the_element_the_gesture_is_running_on(self):
        """The pointer capture lives on the `<svg>`. Replacing it mid-drag drops the hand off
        the box being moved."""
        for f, fn in (('_links.html', '_infraLinkRedraw'), ('_map.html', '_infraMapRedraw')):
            body = _read(os.path.join(INFRA, f)).split(
                'function ' + fn + '(')[1].split(chr(10) + '}')[0]
            assert 'svg.innerHTML =' in body, f

    def test_there_is_a_way_back_to_the_layout_the_panel_chose(self):
        for f, fn in (('_links.html', 'infraLinkArrange'), ('_map.html', 'infraMapArrange')):
            assert 'ssCanvasArrange(' in _read(os.path.join(INFRA, f)).split(
                'function ' + fn + '(')[1].split(chr(10) + '}')[0], f
        assert 'removeItem' not in self._fn('ssCanvasArrange'), (
            'resetting one drawing now forgets the other')

    def test_there_is_a_way_back_to_what_the_account_holds(self):
        """The other half of the reset. One says "forget where I put them", the other "give me
        back the ones I saved" — and a screen with only the first makes resetting unrecoverable
        while the answer sits on the account."""
        body = self._fn('ssCanvasRestore')
        assert '_ssKeptParsed()' in body and 'ssCanvasMovedSave' in body
        for f in ('_links.html', '_map.html'):
            tools = _read(os.path.join(INFRA, f))
            assert 'Restore()' in tools and 'ssCanvasHasKept(' in tools, f

    def test_and_an_arrangement_saved_before_this_moved_still_comes_back(self):
        """A rename that loses somebody's arrangement is a rename that broke something.
        Reported the moment this moved: the boxes back at their generated places, with nothing
        on screen to press to get them back — because the browser key and the account field
        had both changed name under it.

        Read once and written forward, on both sides. The entry names one drawing because that
        drawing is where the data physically is, and it can go when nobody could still hold it.
        """
        canvas = self._canvas()
        assert "_SS_POS_WAS = {infraLinkSvg: 'ss_infra_linkpos'}" in canvas
        assert '_SS_POS_WAS' in self._fn('_ssMovedAll'), 'declared and read by nobody'
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        assert "LINK_LAYOUT_WAS = {'infraLinkSvg': 'infra_link_layout'}" in svc
        assert 'def map_layouts_of(' in svc
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        assert 'infra_svc.map_layouts_of(user)' in routes, 'the GET reads the record raw'
        assert 'LINK_LAYOUT_WAS.values()' in routes, 'the old field is never cleared'
