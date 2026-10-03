#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The recurring work: what wakes up on its own, how often, and — in a cluster — WHERE.

The list next door (:mod:`lib.core.jobs.service`) answers *what is happening*: a job with a
start, a progress and an end. A timer is not that. It sleeps ninety-nine per cent of the time
and has no total to be a fraction of, and putting one in that list would show five permanent
rows in ``running`` that never advance — ruining the screen that exists to tell you what is
being done right now.

So it is a second question with a second descriptor, collected the same way: each package
declares ``BACKGROUND_TIMERS`` and this gathers them. A core that imported five schedulers by
name would be a core that has to be edited to learn about a sixth.

Why this screen is worth having
-------------------------------
Eleven threads run behind this panel and until now **not one of them appeared anywhere**. On a
single machine that is merely opaque. In containers it is a real question with no way to ask it:
with three web replicas, which pod is taking the backups? Which one is scanning the cabling? The
answer is written in `service_leader` — holder, device, and when the lease expires — and nothing
ever showed it.

That is also why a timer declares its ``lease`` key rather than a boolean: a timer with no lease
runs **in every replica**, and whether that is right (a config watcher is local to its process)
or wrong (anything that writes or notifies) is a judgement somebody can only make if they can
see it.
"""

from __future__ import annotations

import time

from lib.discovery import scan
from lib.i18n import DEFAULT_LANG, TRANSLATIONS, translate

#: The manifest key a package declares. The value is a callable taking the web admin and
#: returning ``[{...}]`` in the shape :func:`live` documents.
DESCRIPTOR = 'BACKGROUND_TIMERS'


#: Los tres estados de un temporizador, y son tres porque dos mienten.
#:
#: `running`   el cron está programado y cada vuelta hace algo
#: `idle`      el cron **está programado y corre igual**, pero su trabajo está desactivado en
#:             Configuración, así que cada vuelta es una comparación y nada más
#: `stopped`   el cron no está montado en este proceso
#:
#: La primera versión de esta pantalla ponía «Apagado» al segundo caso, y era falso: el hilo
#: despierta cada treinta segundos, está vivo, y lo único apagado es lo que hace al despertar.
#: «Detenido» tiene que significar que el cron no corre — cualquier otra cosa manda a alguien a
#: buscar un proceso muerto que está perfectamente vivo.
RUNNING, IDLE, STOPPED = 'running', 'idle', 'stopped'


def normalise(package: str, raw: dict, leases: dict, now: float) -> dict:
    """One timer, with the lease resolved and the next run worked out.

    ``next_run`` is computed here and not by the screen: the browser's clock and the server's
    are two clocks, and «in 4 minutes» computed on the wrong one shows a scan that already ran
    as still pending. Everything that is arithmetic on time goes out already done, with ``now``
    beside it — the same rule the jobs list follows.
    """
    llave = str(raw.get('lease') or '')
    arriendo = leases.get(llave) if llave else None
    cada = _int(raw.get('every'))
    # Cuándo corrió por última vez. El arriendo manda sobre lo que diga el paquete: se renueva
    # en cada vuelta del que lo sostiene, así que es el único «cuándo corrió» que se ve desde
    # **otro contenedor**. Lo que el hilo recuerda vive en su proceso, y en una réplica que no
    # es la líder valdría cero — que se leería como «no ha corrido nunca» en vez de como «no lo
    # corro yo».
    #
    # Y se lee **también de un arriendo caducado**, que es el caso normal y no la excepción: un
    # escaneo diario con un arriendo de una hora lo tiene expirado el 96 % del tiempo. Filtrarlo
    # dejaba la pantalla diciendo «todavía no» sobre algo que corrió esta mañana.
    ultimo = _float((arriendo or {}).get('renewed_at')) or _float(raw.get('last_run'))
    corre = bool(raw.get('scheduled', True))
    activo = bool(raw.get('enabled', True))
    fila = {
        'id':       f'{package}:{raw.get("id") or raw.get("kind") or "timer"}',
        'package':  package,
        'kind':     str(raw.get('kind') or ''),
        'label':    str(raw.get('label') or ''),
        'detail':   str(raw.get('detail') or ''),
        # Qué ajuste lo enciende. Va aparte del detalle para que la pantalla pueda enseñarlo
        # como una pista y no como la descripción — un `certs|scan_every_secs` a palo seco
        # debajo del nombre no le dice nada a quien no ha escrito este código.
        'setting':  str(raw.get('setting') or ''),
        # Y cómo se dice eso en voz alta. Lo pone el paquete cuando el ajuste **no** vive en
        # Configuración —una copia programada es una tarea de la pantalla de Copias— y lo
        # rellena `live()` contra el registro de configuración cuando sí.
        'setting_label': str(raw.get('setting_label') or ''),
        'enabled':  activo,
        'scheduled': corre,
        'state':    STOPPED if not corre else (RUNNING if activo else IDLE),
        'every':    cada,
        'last_run': ultimo or 0.0,
        'lease':    llave,
        # `None` es «no usa arriendo», que es distinto de «lo usa y ahora mismo no lo tiene
        # nadie» — uno corre en todas las réplicas y el otro no corre en ninguna.
        'holder':   None if not llave else (arriendo or {}).get('instance_id') or '',
        'host':     None if not llave else (arriendo or {}).get('host') or '',
        'expires':  None if not llave else (arriendo or {}).get('expires_at') or 0.0,
        # Si lo sostiene AHORA o sólo lo sostuvo. Para un trabajo lento, lo segundo es lo
        # normal, y pintar «sin dueño» en ámbar por eso es una alarma que no significa nada.
        'holding':  None if not llave else bool((arriendo or {}).get('live')),
    }
    # «Última vuelta + cada cuánto», salvo que el paquete lo sepa mejor y lo diga.
    #
    # Casi todos despiertan, hacen su vuelta y renuevan el arriendo: para ésos la suma es la
    # verdad. El de las copias no — toma el arriendo **sólo cuando hay trabajo**, así que su
    # marca es «cuándo se copió por última vez» y no «cuándo despertó el hilo». Sumarle diez
    # minutos daba un instante sin significado, y en cuanto la programación es más espaciada
    # que el tic queda siempre en el pasado: la pantalla decía «atrasado 41 min» de un trabajo
    # que había copiado a su hora, con las copias visibles en la pantalla de al lado.
    #
    # Reportado desde ahí. Quien conoce su calendario es el paquete, así que puede declararlo.
    declarado = _float(raw.get('next_run'))
    fila['next_run'] = (declarado if declarado
                        else (ultimo + cada) if (ultimo and cada and corre and activo)
                        else 0.0)
    # Atrasado sólo tiene sentido si de verdad tenía que haber corrido. Uno cuyo trabajo está
    # desactivado no llega a tomar el arriendo, así que su «última vuelta» se queda quieta para
    # siempre y saldría atrasado el resto de la vida del panel.
    # Cuánto retraso es NORMAL antes de que sea noticia.
    #
    # Medio periodo es una buena regla para un temporizador que se despierta y hace su vuelta:
    # media hora de margen sobre una hora. Deja de serlo cuando la vuelta la decide otro reloj:
    # el de las copias comprueba cada diez minutos, así que a los once ya se sabe que no se ha
    # tomado — y con el margen de media hora la pantalla se quedaba callada veinte minutos
    # mientras la copia que tocaba a la 01:13 seguía sin hacerse a la 01:33. Reportado así, con
    # la carpeta de copias delante.
    #
    # Así que el paquete puede decir con qué precisión puede cumplir. Quien no lo diga sigue con
    # la regla de siempre.
    margen = _float(raw.get('slack')) or max(60, cada * 0.5)
    fila['overdue'] = bool(corre and activo and fila['next_run']
                           and fila['next_run'] < now - margen)
    return fila


def setting_label(lang: str, setting: str) -> str:
    """«certs|notify_expiry» → «Avisar por caducidad de certificados».

    Un temporizador declara **la clave** del ajuste que lo enciende, que es lo correcto: es lo
    que se lee de la configuración y lo único estable entre idiomas. Pero enseñar la clave en la
    pantalla es enseñar la tubería — `certs|notify_expiry` bajo un nombre no le dice nada a quien
    no ha escrito este código, y lo peor es que tampoco le dice **dónde** ir a encenderlo: en
    Configuración ese campo se llama por su etiqueta, no por su clave.

    Las palabras son las mismas que usa la pantalla de Configuración, del bloque `labels` de los
    ficheros de idioma: primero `sección|campo` —por si dos secciones comparten el nombre de un
    campo con sentidos distintos— y luego el campo a secas, que es como están escritas casi
    todas. Si no hay etiqueta se devuelve cadena vacía y la pantalla enseña la clave: una pista
    fea es mejor que ninguna.
    """
    if not setting:
        return ''
    for idioma in (lang, DEFAULT_LANG):
        etiquetas = (TRANSLATIONS.get(idioma) or {}).get('labels') or {}
        texto = etiquetas.get(setting) or etiquetas.get(setting.split('|')[-1])
        if isinstance(texto, str) and texto:
            return texto
    return ''


def _int(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def _float(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def live(wa, *, now: float | None = None) -> list:
    """Every recurring timer declared in this installation, grouped work first.

    Each package declaring :data:`DESCRIPTOR` hands back its own, answering:

    ``id``        what it is called inside its package
    ``kind``      what sort of recurring work it is
    ``label``     what a person calls it
    ``detail``    anything worth saying about this round
    ``enabled``   whether the setting that governs it is on
    ``every``     seconds between runs, read LIVE from the config
    ``last_run``  epoch seconds, or 0 when it has not run in this process
    ``lease``     the `service_leader` key it coordinates on, or '' when it has none

    A package that raises is skipped rather than taking the list down — the same rule the jobs
    list follows, and for the same reason: three of four is worth more than none of four.
    """
    ahora = time.time() if now is None else float(now)
    leases = _leases(wa)
    fuera: list = []
    for nombre, descriptor in scan(DESCRIPTOR):
        if not callable(descriptor):
            continue
        try:
            got = descriptor(wa) or []
        except Exception:  # pylint: disable=broad-except
            continue
        for raw in got:
            if isinstance(raw, dict):
                fuera.append(normalise(nombre, raw, leases, ahora))
    # La etiqueta del ajuste se resuelve aquí y no en `normalise`, que es una función pura y no
    # sabe de idiomas ni de sesión. Y se resuelve en el servidor y no en el navegador porque el
    # bloque `labels` es de la pantalla de Configuración: mandarlo entero para traducir cinco
    # cadenas sería copiar un diccionario de doscientas para usar cinco.
    lang = wa._lang() if hasattr(wa, '_lang') else DEFAULT_LANG  # noqa: SLF001
    for fila in fuera:
        if fila.get('setting_label'):
            continue
        etiqueta = setting_label(lang, fila.get('setting') or '')
        fila['setting_label'] = (translate(lang, 'jobs_timers_in_config', etiqueta)
                                 if etiqueta else '')
    return ordered(fuera)


def _leases(wa) -> dict:
    """``{service_key: fila}`` de **todos** los arriendos, caducados incluidos.

    Caducado no es «no ha corrido»: es «corrió y todavía no le toca». Ver
    :meth:`~lib.services.manager.leader.ServiceLeaderStore.leases`.
    """
    store = getattr(wa, '_service_leader_store', None)
    if store is None:
        return {}
    try:
        return {str(r.get('service_key') or ''): r for r in (store.leases() or ())}
    except Exception:  # pylint: disable=broad-except
        return {}


def ordered(rows: list) -> list:
    """Lo que necesita mirarse primero: lo atrasado, luego lo encendido, luego lo apagado.

    Y dentro de cada grupo por nombre, no por cuándo corrió: esta lista se lee buscando algo
    concreto, y un orden que cambia cada vez que alguien refresca obliga a releerla entera.
    """
    orden = {RUNNING: 1, IDLE: 2, STOPPED: 3}
    return sorted(rows or (),
                  key=lambda r: (0 if r.get('overdue') else orden.get(r.get('state'), 9),
                                 str(r.get('label') or ''), str(r.get('id') or '')))


def summary(rows: list) -> dict:
    """Los números del distintivo: cuántos hay, cuántos encendidos, cuántos atrasados y
    cuántos corren en todas las réplicas por no tener arriendo."""
    filas = list(rows or ())
    return {
        'total':     len(filas),
        'enabled':   len([r for r in filas if r.get('state') == RUNNING]),
        'idle':      len([r for r in filas if r.get('state') == IDLE]),
        'overdue':   len([r for r in filas if r.get('overdue')]),
        'unleased':  len([r for r in filas if r.get('state') == RUNNING and not r.get('lease')]),
    }
