#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One dialog, four openers, and the two things a dialog with a field in it owes the keyboard.

``#infoModal`` is a single element that four helpers drive: a key/value dump, a list of links,
a table, and ``showHtmlModal`` — the one whose body the CALLER composes, and the only one that
can hold a control. That sharing is what makes it worth guarding: whatever one opener leaves
behind is what the next one opens with.

**The footer slot.** A caller's action button used to be written into the BODY, which put
"Verify" floating over the footer as if it belonged to the field above it while the actual
footer held only Close. It moved next to Close, where every other dialog in the panel keeps its
confirm — and because the slot is a shared element, it is emptied on every open by the one
function all four end in. Skip that and a table of NUT variables arrives with a Verify button
on it.

**Enter.** The second-factor dialogs exist to receive a code. There is no ``<form>`` in them —
a modal built from a string is not one — so Enter in a lone input does nothing at all, which
reads as the key being ignored rather than unsupported. It is bound explicitly, and the field
takes the cursor when the dialog opens: same observation, twice.

Both were reported from the screen, which is where a keypress that does nothing is found.
"""

import os
import re
from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
TOAST = os.path.join(TPL, 'partials', 'core', '_toast.html')
DIALOGS = os.path.join(TPL, 'partials', 'modals', '_dialogs.html')
MFA = os.path.join(TPL, 'partials', 'account', '_mfa.html')
BEHAVIORS = os.path.join(TPL, 'partials', 'init', '_behaviors.html')

# The four helpers that drive `#infoModal`.
_OPENERS = ('showInfoModal', 'showLinksModal', 'showTableModal', 'showHtmlModal')


class TestTheScanItself:

    def test_the_four_openers_are_found(self):
        src = _read(TOAST)
        for name in _OPENERS:
            assert _fn(src, name), name


class TestEveryOpenerGoesThroughOneDoor:

    def test_none_of_them_shows_the_modal_by_itself(self):
        """A helper that calls `bootstrap.Modal(...).show()` directly has skipped the place
        where the shared footer is emptied — and inherits the previous dialog's buttons."""
        src = _strip_comments(_read(TOAST))
        for name in _OPENERS:
            body = _fn(src, name)
            assert 'Modal.getOrCreateInstance' not in body, (
                f'{name} opens the dialog on its own again — it has to go through '
                '_infoModalOpen, which is what clears the footer slot')
            assert '_infoModalOpen(' in body, name

    def test_the_shared_door_always_clears_the_slot(self):
        body = _fn(_strip_comments(_read(TOAST)), '_infoModalOpen')
        assert 'infoModalActions' in body
        # Unconditional: `actions || ''` writes an empty slot when there are none, which is
        # the whole point. An `if (actions)` here is the bug this test exists for.
        assert re.search(r"innerHTML\s*=\s*actions\s*\|\|", body), \
            'the footer slot is only written when there ARE buttons — the previous dialog’s survive'

    def test_only_the_caller_composed_dialog_can_fill_it(self):
        """The three escaping helpers take data, not markup; giving them a raw-HTML footer
        would hand them the one property `showHtmlModal` is named for."""
        src = _strip_comments(_read(TOAST))
        for name in ('showInfoModal', 'showLinksModal', 'showTableModal'):
            assert '_infoModalOpen()' in _fn(src, name), f'{name} passes footer markup'

    def test_the_slot_exists_in_the_markup(self):
        assert 'id="infoModalActions"' in _read(DIALOGS)

    def test_it_sits_in_the_footer_beside_close(self):
        src = _read(DIALOGS)
        footer = src[src.index('id="infoModalBody"'):]
        footer = footer[:footer.index('</div>\n        </div>')]
        assert 'modal-footer' in footer
        i_close, i_slot = footer.index('data-bs-dismiss="modal"'), footer.index('infoModalActions')
        assert i_close < i_slot, 'the action lands left of Close — the confirm goes last'


class TestTheCodeFieldAnswersTheKeyboard:

    def _mfa(self) -> str:
        return _strip_comments(_read(MFA))

    def test_enter_runs_the_same_thing_the_button_does(self):
        body = _fn(self._mfa(), '_accMfaWireCode')
        assert "e.key !== 'Enter'" in body or "e.key === 'Enter'" in body
        assert 'run()' in body

    def test_it_stops_the_key_from_doing_anything_else(self):
        """Without `preventDefault` the same Enter can also submit whatever form the dialog
        happens to sit inside, which is a second action nobody asked for."""
        assert 'preventDefault' in _fn(self._mfa(), '_accMfaWireCode')

    def test_the_field_takes_the_cursor_when_the_dialog_opens(self):
        """Through `shown.bs.modal` while it is opening — focus set before Bootstrap has
        finished showing the dialog is focus Bootstrap takes straight back — and directly when
        the box is already up, which is the regenerate path replacing a dialog that never
        closed."""
        body = _fn(self._mfa(), '_accMfaWireCode')
        assert 'shown.bs.modal' in body and 'focus()' in body
        assert "classList.contains('show')" in body

    def test_both_dialogs_that_ask_for_a_code_are_wired(self):
        src = self._mfa()
        for name in ('_accMfaBegin', '_accMfaAskCode'):
            assert '_accMfaWireCode(' in _fn(src, name), name

    def test_neither_of_them_leaves_its_button_in_the_body(self):
        """The regression: a confirm written into the body renders above the footer and reads
        as belonging to the field, with Close sitting alone underneath."""
        src = self._mfa()
        for name in ('_accMfaBegin', '_accMfaAskCode'):
            body = _fn(src, name)
            i_open = body.index('showHtmlModal(')
            # Everything between the opening call and its closing `);` is the body string plus
            # the variant plus the footer markup — the button must be in the LAST argument.
            call = body[i_open:body.index(');', i_open)]
            assert call.index('mfa_step_verify') > call.index('form-control'), \
                f'{name} still writes its confirm into the dialog body'


class TestNothingWaitsInSilence:
    """Every action in the second-factor card talks to the server, and each was doing it with
    nothing on screen to say so: press Verify and the dialog sat exactly as it was until the
    answer arrived. Reported as "you cannot tell whether it is doing anything" — which is also
    the state in which somebody presses the button again, and a code is spent once.

    `ssBtnBusy` is the one mechanism: it disables the control, prepends a spinner and hands back
    the restore. The guards pin that each waiting path uses it and that the helper still does
    both halves, because a spinner that does not also disable is decoration in front of a
    double submit.
    """

    def test_the_helper_disables_as_well_as_spins(self):
        body = _fn(_strip_comments(_read(os.path.join(TPL, 'partials', 'core', '_utils.html'))),
                   'ssBtnBusy')
        assert 'spinner-border' in body
        assert 'disabled = true' in body, \
            'the busy state is a spinner and nothing else — the button is still pressable'

    def test_it_restores_a_button_that_was_already_disabled(self):
        """`disabled = false` on the way out enables a control that was off before the call —
        quietly, and only in the state where something else had turned it off."""
        body = _fn(_strip_comments(_read(os.path.join(TPL, 'partials', 'core', '_utils.html'))),
                   'ssBtnBusy')
        assert re.search(r'const was = \w*\.?\s*btn\.disabled|was = btn\.disabled', body)
        assert 'disabled = was' in body

    def test_it_keeps_a_label_and_replaces_a_lone_icon(self):
        """A labelled button replaced by a spinner shrinks to the width of one, so the bar
        jumps at the moment somebody is watching it — and the label is the only thing saying
        WHAT is taking a moment. An icon-only button has neither problem, and there the spinner
        takes the icon's place, which is how the copies this replaced behaved."""
        body = _fn(_strip_comments(_read(os.path.join(TPL, 'partials', 'core', '_utils.html'))),
                   'ssBtnBusy')
        assert 'textContent' in body, 'the two cases are no longer told apart'
        assert re.search(r"innerHTML\s*=\s*\w+\s*\?\s*\w+\s*\+\s*html\s*:", body), \
            'a labelled button no longer keeps its label beside the spinner'

    def test_every_request_in_the_card_shows_it(self):
        """Named one by one: minting a secret (nothing on screen yet, so the card's own button
        carries it), confirming an enrolment, and the two that ask for a code before spending
        it."""
        src = _strip_comments(_read(MFA))
        for name in ('_accMfaBegin', '_accMfaConfirm', '_accMfaAskCode'):
            assert 'ssBtnBusy(' in _fn(src, name), f'{name} waits with nothing on screen'

    def test_the_two_code_spenders_share_one_busy_state(self):
        """Regenerate and disable both go through `_accMfaAskCode`, so the rule lives there
        once. A copy in each callback is two rules that can drift."""
        src = _strip_comments(_read(MFA))
        for name in ('_accMfaRegen', '_accMfaDisable'):
            assert 'ssBtnBusy(' not in _fn(src, name), \
                f'{name} manages the busy state itself instead of leaving it to _accMfaAskCode'

    def test_the_shared_one_always_gives_the_button_back(self):
        """Without `finally`, a callback that throws leaves a spinner that never stops on a
        button that never comes back."""
        assert 'finally' in _fn(_strip_comments(_read(MFA)), '_accMfaAskCode')

    def test_the_card_says_it_is_asking(self):
        """The GET behind the card had the same problem with no button to hang it on: the
        section sat on its static description through the round trip."""
        body = _fn(_strip_comments(_read(MFA)), '_accMfaLoad')
        assert 'spinner-border' in body


class TestARefusalIsShownWhereItHappened:
    """A refused code used to raise a toast: away from the field it is about, gone a few
    seconds later while the dialog it referred to is still open, and saying "that code is not
    valid" whatever actually went wrong — which is a lie when the code was RIGHT and the write
    failed, or when the factor was removed from another session in between.

    Now the field is marked and the reason is written next to it, taken from the server's own
    error rather than assumed. The dialog stays open on what was typed, and the text is
    selected: a retyped code is usually one character different from the refused one.
    """

    def _mfa(self) -> str:
        return _strip_comments(_read(MFA))

    def test_the_reason_comes_from_the_server(self):
        body = _fn(self._mfa(), '_accMfaErrText')
        for err in ('bad_code', 'not_enrolled', 'write_failed', 'no_key'):
            assert f"'{err}'" in body, f'{err} falls through to the generic message'
        assert 'default' in body, 'an error this does not know becomes nothing at all'

    def test_the_field_is_marked_and_the_message_placed_next_to_it(self):
        body = _fn(self._mfa(), '_accMfaFieldError')
        assert "classList.add('is-invalid')" in body
        # Bootstrap only draws `.invalid-feedback` beside an `.is-invalid` control, so the two
        # go together or neither shows.
        assert "'Err'" in body or '"Err"' in body, 'the message element is no longer looked up'
        assert 'select()' in body, 'the refused code is cleared instead of offered for editing'

    def test_both_dialogs_have_somewhere_to_put_it(self):
        src = self._mfa()
        for field in ('accMfaCode', 'accMfaAsk'):
            assert f'id="{field}Err"' in src, f'{field} has no message element'
            assert 'invalid-feedback' in src

    def test_typing_clears_the_last_refusal(self):
        """A field that stays red while it is being corrected is arguing with what is
        currently in it."""
        body = _fn(self._mfa(), '_accMfaWireCode')
        assert "removeatit" not in body
        assert "classList.remove('is-invalid')" in body

    def test_no_path_falls_back_to_a_toast_for_a_refused_code(self):
        """The regression: `showToast(t('mfa_bad_code'))` is the shape this replaced, and it is
        also the shape somebody adds back when writing the next dialog."""
        src = self._mfa()
        for name in ('_accMfaConfirm', '_accMfaRegen', '_accMfaDisable'):
            body = _fn(src, name)
            assert "showToast(t('mfa_bad_code')" not in body, \
                f'{name} reports a refusal away from the field again'
            assert '_accMfaFieldError(' in body, name


class TestElPieDecideLaTallaDeSusBotones:
    """«Cerrar» está en el marcado y es `btn-sm`. La acción la manda quien abre el diálogo, y de
    los seis sitios que mandan una, cuatro la mandaban sin talla y dos con ella — así que el par
    salía descuadrado, uno más alto que el otro, según de dónde viniera.

    Se normaliza en la puerta común y no pidiéndoselo a los seis: una convención que hay que
    recordar en cada sitio es una convención que se rompe en el séptimo.
    """

    def test_la_accion_se_iguala_a_cerrar(self):
        body = _fn(_strip_comments(_read(TOAST)), '_infoModalOpen')
        assert 'btn-sm' in body, \
            'el pie ya no iguala la talla: el par vuelve a salir descuadrado'

    def test_y_cerrar_sigue_siendo_esa_talla(self):
        """La otra mitad del par. Si el marcado cambia de talla, igualar contra `btn-sm` deja de
        igualar nada y el descuadre vuelve por el otro lado."""
        src = _read(DIALOGS)
        pie = src[src.index('modal-footer'):]
        pie = pie[:pie.index('infoModalActions')]
        assert 'btn-sm' in pie, 'Cerrar cambió de talla y la acción se iguala contra la vieja'


class TestUnaFichaQueNoCreceNoOfreceCrecer:
    """`showHtmlModal` se estira y se maximiza porque casi siempre trae un formulario o una
    tabla. Una ficha de SOLO LECTURA no: no tiene nada que enseñar de más, y maximizarla estira
    el mismo contenido dentro de más hueco vacío.

    Lo que lo decide es `ss-modal-fit`, y el botón de maximizar lo inyecta el comportamiento
    compartido **una vez por modal**. Un mismo modal que se abre estirable y luego no —
    `#infoModal` es literalmente eso— se quedaba con el botón puesto: un botón de maximizar en
    un diálogo que no se puede maximizar no hace nada al pulsarlo, que es la peor clase de botón.
    """

    def test_quien_compone_el_cuerpo_dice_de_que_tamano_es(self):
        """UNA pregunta con tres respuestas y no dos interruptores que se pueden contradecir:
        «encogido» y «ancho» no pueden ser ciertos a la vez, y con dos booleanos sí."""
        src = _strip_comments(_read(TOAST))
        assert 'function showHtmlModal(title, html, variant, actions, size)' in src, \
            'ya no se puede pedir un tamaño de diálogo'
        assert '_infoModalSize(size)' in _fn(src, 'showHtmlModal'), \
            'el tamaño que se pide no llega a ninguna parte'

    def test_las_tres_respuestas_estan(self):
        cuerpo = _fn(_strip_comments(_read(TOAST)), '_infoModalSize')
        assert "size === 'fit'" in cuerpo, 'una ficha vuelve a ofrecer maximizarse'
        assert "size === 'wide'" in cuerpo, 'una tabla ancha vuelve a mirarse por una ranura'

    def test_y_sin_decir_nada_es_el_de_siempre(self):
        """Los que ya lo usaban traen formularios: la tercera respuesta —no decir nada— tiene que
        seguir significando lo de antes, o esto arregla dos pantallas y cambia cinco."""
        cuerpo = _fn(_strip_comments(_read(TOAST)), '_infoModalSize')
        # `undefined` no es ninguna de las dos comparaciones, así que no se pone ninguna clase.
        assert '_infoModalFit(' not in _read(TOAST), 'quedan dos funciones decidiendo lo mismo'

    def test_el_tamano_del_anterior_no_se_queda_puesto(self):
        """Un modal compartido que hereda el tamaño del que se cerró es la misma clase de fallo
        que el hueco del pie heredando sus botones: por eso las dos clases se ponen y se quitan
        siempre, no solo se ponen."""
        cuerpo = _fn(_strip_comments(_read(TOAST)), '_infoModalSize')
        assert cuerpo.count('classList.toggle(') == 2, \
            'alguna de las dos clases se pone sin quitarse'

    def test_el_boton_de_maximizar_se_va_cuando_el_dialogo_deja_de_poder(self):
        cuerpo = _fn(_strip_comments(_read(BEHAVIORS)), '_modalMaxSync')
        assert '_modalResizable(' in cuerpo, 'ya no mira si el diálogo puede estirarse'
        assert 'modal-max-btn' in cuerpo and 'remove()' in cuerpo, \
            'un modal que no puede estirarse conserva el botón de maximizar'

    def test_y_una_talla_declarada_no_se_ofrece_deshacer(self):
        """Ni `fit` ni `wide`. Una talla que el que abre ha declarado es una decisión, y un botón
        para maximizar es ofrecer que no valga: `ss-modal-wide` ya mide 96vw como mucho, así que
        lo único que añade es alto vacío debajo de lo que se ha venido a leer."""
        cuerpo = _strip_comments(_fn(_read(BEHAVIORS), '_modalResizable'))
        for clase in ('ss-modal-fit', 'ss-modal-wide'):
            assert f"contains('{clase}')" in cuerpo, clase

    def test_y_se_vuelve_a_mirar_en_CADA_apertura(self):
        """`show.bs.modal` no basta: Bootstrap no lo emite sobre un modal que YA está abierto, y
        `#infoModal` es justo el que pasa de una ficha a un formulario sin cerrarse en medio.

        Mirándolo sólo ahí salían las dos mitades del mismo despiste — la ficha con el botón que
        no le toca, y el formulario de encima sin el que sí. Arreglada una, la otra apareció el
        mismo día."""
        assert '_modalMaxSync(' in _fn(_strip_comments(_read(TOAST)), '_infoModalOpen'), \
            'un formulario abierto sobre una ficha se queda sin el botón de maximizar'
