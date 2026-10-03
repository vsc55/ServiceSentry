#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The scanner that notices somebody moved a patch cord — and says so.

:func:`lib.core.dcim.service.cable_check` already compares what is declared against what the
devices report over LLDP: a cable whose devices name ports other than the written ones comes
back ``other_port``, and an adjacency between two racked machines that nobody declared comes
back in ``undeclared``, already filled in and ready to accept. All of that only happened when a
person opened the cabling tab and pressed Check.

This is the half that was missing. Wake up, ask the same question, and tell somebody when the
answer changed — the same shape as the other three scanners next to it (service health,
certificate expiry, provider secrets) and for the same reason: nobody configured it, it has no
schedule of its own, and the panel is the only thing in a position to notice.

**Discovery proposes; it does not write.** Nothing here touches `dc_cable`. What is declared is
what a person declared, and the scanner's whole job is to stop them finding out six months later
by tracing a cable with a torch.

**Said once, not every half hour.** What has already been announced lives in `dc_drift`, a table
and not a dict, because in a container deployment the process that scans today is not the one
that scans tomorrow — see that module's docstring. A finding is announced when it appears and
when it *changes*; when it stops appearing the row goes, so the same cable moved again is news
again.
"""

from __future__ import annotations

import threading
import time

from lib.core.health import ScannerThread

#: Un cable cuyo puerto declarado no está entre los que los dispositivos nombran.
MOVED = 'cable_moved'
#: Dos equipos que se ven y que nadie ha declarado unidos.
UNDECLARED = 'cable_undeclared'

#: Cada cuánto se mira, por defecto. Media hora: esto cambia cuando alguien abre un armario, no
#: cuando pasa un minuto, y un explorador que corre sin encontrar nada cuesta una consulta.
DEFAULT_EVERY = 1800

#: Cuántos hallazgos se cuentan como mucho en una vuelta. Un armario recableado entero mandaría
#: cien mensajes seguidos, y cien mensajes son cero mensajes leídos. Lo que sobra se queda
#: apuntado y se dice en la siguiente vuelta.
MAX_PER_SCAN = 10


def findings(check: dict) -> dict:
    """``{clave: hallazgo}`` a partir de lo que devuelve ``cable_check``.

    Función pura, y por eso está aquí y no dentro del hilo: es la única parte que decide **qué
    es un hallazgo**, y lo demás es cuándo mirar y a quién decírselo.

    La huella es lo que distingue «esto sigue igual» de «esto ha vuelto a cambiar». Sin ella, un
    latiguillo movido a una tercera boca sería el mismo hallazgo de antes y se callaría.
    """
    fuera: dict = {}
    for c in (check.get('cables') or ()):
        if str(c.get('seen') or '') != 'other_port':
            continue
        uid = str(c.get('uid') or '')
        if not uid:
            continue
        declarados = [str(c.get('a_port') or ''), str(c.get('b_port') or '')]
        vistos = sorted(str(p) for p in (c.get('ports_seen') or ()))
        fuera[f'moved:{uid}'] = {
            'kind': MOVED,
            'fingerprint': '|'.join(declarados) + '>' + '|'.join(vistos),
            'a_label': str(c.get('a_label') or ''), 'b_label': str(c.get('b_label') or ''),
            'label': str(c.get('label') or ''), 'uid': uid,
            'declared': declarados, 'seen': vistos,
        }
    for u in (check.get('undeclared') or ()):
        # El par ordenado: estar enchufados es simétrico, y que el descubrimiento nombre primero
        # a uno o a otro según el orden de una consulta convertiría el mismo hallazgo en dos.
        par = tuple(sorted((str(u.get('from') or ''), str(u.get('to') or ''))))
        if not par[0] or not par[1]:
            continue
        puertos = u.get('ports') or {}
        huella = '|'.join(f'{h}={_boca(puertos.get(h))}' for h in par)
        fuera[f'undeclared:{par[0]}|{par[1]}'] = {
            'kind': UNDECLARED,
            'fingerprint': huella,
            'a_label': str(u.get('a_label') or par[0]), 'b_label': str(u.get('b_label') or par[1]),
            'a_port': str(u.get('a_port') or ''), 'b_port': str(u.get('b_port') or ''),
            'bundle': int(u.get('bundle') or 1),
        }
    return fuera


def _policy(cfg: dict) -> tuple:
    """``(cada_segundos, tope_de_veces)`` — cuánto insiste el aviso.

    Los dos números dicen las cinco cosas que se pueden querer, y por eso son dos y no un modo
    con nombre: un modo cerrado obliga a inventar un nombre para cada combinación y a tocar el
    código el día que alguien quiera una sexta.

        no avisar ...................... `notify_cabling` apagado
        decirlo una vez ................ cada = 0   (o tope = 1)
        repetir cada X para siempre .... cada = X,  tope = 0
        repetir cada X, N veces ........ cada = X,  tope = N
    """
    try:
        cada = max(0, int(cfg.get('cable_repeat_every_secs') or 0))
    except (TypeError, ValueError):
        cada = 0
    try:
        tope = max(0, int(cfg.get('cable_repeat_max', 1) or 0))
    except (TypeError, ValueError):
        tope = 1
    # `tope = 1` y `cada = X` dicen lo mismo que `cada = 0`: una vez. Se normaliza aquí para que
    # el bucle no tenga que saberlo dos veces.
    if tope == 1:
        cada = 0
    return cada, tope


def _boca(v) -> str:
    """El nombre de puerto de un lado, venga suelto o en lista."""
    if isinstance(v, (list, tuple)):
        return ','.join(sorted(str(x) for x in v))
    return str(v or '')


class CableDriftScanner(ScannerThread):
    """Mira el cableado cada tanto y avisa de lo que ha cambiado.

    *check_provider* devuelve lo mismo que la pantalla de contraste —``cable_check`` con las
    aristas puestas—; *state* es un :class:`~lib.core.dcim.drift.DriftStore`.
    """

    def __init__(self, *, check_provider, state, dispatch, config_getter, is_leader,
                 dbg=lambda *_a: None, text_fn=lambda k, *a: k) -> None:
        self._check = check_provider
        self._state = state
        self._dispatch = dispatch
        self._config = config_getter          # () -> dict (la sección 'dcim')
        self._is_leader = is_leader
        self._dbg = dbg
        self._text = text_fn
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── Una vuelta ───────────────────────────────────────────────────────────────

    def evaluate_once(self, *, now: float) -> dict:
        """Mirar una vez. Devuelve ``{clave: hallazgo}`` de lo que ha avisado."""
        cfg = self._config() or {}
        if not cfg.get('notify_cabling'):
            return {}
        if not self._is_leader():
            return {}
        try:
            check = self._check() or {}
        except Exception:  # pylint: disable=broad-except
            self._dbg('> Cabling >> the check could not be built')
            return {}
        # `checked` falso es **no se ha podido preguntar**, no «no hay nada». Sin esa diferencia,
        # una sonda que no contesta borraría el estado y al volver lo anunciaría todo otra vez
        # como si fuese nuevo — que es la misma forma de fallo que un 403 contado como «el
        # dispositivo no ha dicho nada».
        if not check.get('checked'):
            return {}
        ahora = findings(check)
        antes = self._state.known()

        # Lo que ya no se ve se olvida: es lo que vuelve a armar el aviso si pasa otra vez.
        idos = [k for k in antes if k not in ahora]
        if idos:
            self._state.forget(idos)

        cada, tope = _policy(cfg)
        decir = []
        for clave, hallazgo in sorted(ahora.items()):
            previo = antes.get(clave)
            if previo is None or previo.get('fingerprint') != hallazgo['fingerprint']:
                # Nuevo, o el MISMO latiguillo movido otra vez. Es otro hecho, no el mismo
                # insistiendo, así que se dice aunque el límite estuviera gastado y el contador
                # vuelve a empezar.
                decir.append((clave, hallazgo, previo, 1))
                continue
            if not cada:
                continue                     # «decirlo una vez»: no se repite nunca
            veces = int(previo.get('times') or 1)
            if tope and veces >= tope:
                continue                     # ya se ha insistido lo que se pidió
            if now - float(previo.get('notified_at') or 0) < cada:
                continue                     # todavía no toca
            decir.append((clave, hallazgo, previo, veces + 1))

        emitidos: dict = {}
        for clave, hallazgo, previo, veces in decir[:MAX_PER_SCAN]:
            try:
                self._emit(hallazgo)
            except Exception:  # pylint: disable=broad-except
                self._dbg(f'> Cabling >> dispatch failed for {clave!r}')
                continue
            self._state.remember(clave, hallazgo['kind'], hallazgo['fingerprint'], now,
                                 first_seen=(previo or {}).get('first_seen') or now,
                                 times=veces)
            emitidos[clave] = hallazgo
        if len(decir) > MAX_PER_SCAN:
            self._dbg(f'> Cabling >> {len(decir) - MAX_PER_SCAN} more findings next round')
        return emitidos

    def _emit(self, hallazgo: dict) -> None:
        a, b = hallazgo.get('a_label') or '?', hallazgo.get('b_label') or '?'
        if hallazgo['kind'] == MOVED:
            declarados = ', '.join(p for p in hallazgo.get('declared') or () if p) or '—'
            vistos = ', '.join(hallazgo.get('seen') or ()) or '—'
            msg = self._text('notif_msg_cable_moved', f'{a} ↔ {b}', declarados, vistos)
            item = hallazgo.get('label') or f'{a} ↔ {b}'
        else:
            puertos = ', '.join(p for p in (hallazgo.get('a_port'), hallazgo.get('b_port')) if p)
            msg = self._text('notif_msg_cable_undeclared', f'{a} ↔ {b}', puertos or '—')
            item = f'{a} ↔ {b}'
        self._dispatch(hallazgo['kind'], module='dcim', item=item,
                       status=self._text('notif_status_cabling'), message=msg)

    # ── El hilo ──────────────────────────────────────────────────────────────────

    def start(self, *, poll_getter=lambda: DEFAULT_EVERY) -> None:
        def _loop(stop_ev):
            # La primera vuelta no al arrancar: un pod que acaba de levantarse todavía no tiene
            # el mapa de la flota armado, y preguntar entonces devuelve «no se ve nada» sobre
            # todo — que con el estado vacío sería anunciarlo todo y luego desdecirse.
            cada = DEFAULT_EVERY
            if stop_ev.wait(120):
                return
            while True:
                try:
                    self.evaluate_once(now=time.time())
                except Exception:  # pylint: disable=broad-except
                    pass
                try:
                    cada = max(300, int(poll_getter() or DEFAULT_EVERY))
                except Exception:  # pylint: disable=broad-except
                    # A bad value or a failed config read (DB down) keeps the last
                    # interval; it must not end the thread.
                    pass
                if stop_ev.wait(cada):
                    return

        self._spawn('cable-scan', _loop)
