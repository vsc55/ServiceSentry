#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The tick that takes the scheduled copies, for the background-timers list.

One timer, and the most consequential one on the list: an installation whose web role is
stopped takes no copies at all, and nothing about that is visible anywhere until somebody needs
a restore. Which replica is holding the lease is exactly the question this list exists to
answer.

The tick is ten minutes and not a minute on purpose — the interval rule stays true until a copy
is taken, so a coarse tick costs a few minutes of drift and saves 1430 wakeups a day. That is
why ``every`` here is the tick and not the schedule: the schedule says *when a copy is due*,
which is a different question with its own screen.

Which is exactly why this timer declares its own ``next_run``. The list works the next round out
as «last round + every», and for almost every timer that is right — they wake, they do their
round, they renew the lease. This one does not: it takes the lease **only when there is work**,
so the lease says *when a copy last happened*, not *when the thread last woke*. Adding ten
minutes to that gives an instant that means nothing, and the moment the schedule is sparser than
the tick — hourly, daily — it is always in the past. The screen said «overdue by 41 min» about a
job that had copied on time, which was reported from it with the copies right there on the next
screen.

So the number this row carries is the one somebody actually wants: **when the next copy is due**,
which the schedule knows and the tick does not.

And ``every`` goes with it, for the same reason, once the second half of the same report came
back: «cada 10 min» beside «siguiente: ahora» is two clocks in one row, and nobody reading it can
tell what is going to happen. Worse, the progress bar is drawn on ``every`` — ten minutes against
a countdown of an hour — so it filled up and stayed full. Both numbers now come from the
schedule: the row is about the copies, and the ten-minute tick is the granularity with which they
are checked, which is what the line under the name says.
"""

from __future__ import annotations


def live(wa) -> list:
    """The scheduled-copy tick, and whether the schedule it serves is on at all."""
    from lib.core.backup.runner import (LEASE_KEY, TICK_SECONDS,             # noqa: PLC0415
                                        BackupRunner)
    # Cuántas tareas hay ENCENDIDAS, preguntado igual que lo pregunta el propio hilo. El hilo
    # arranca siempre —si no hay ninguna, cada vuelta es una comparación— pero la lista tiene
    # que decir la verdad de lo que va a pasar, y sin tareas encendidas lo que va a pasar es
    # nada.
    try:
        tareas = BackupRunner(wa)._tasks() or []
    except Exception:  # pylint: disable=broad-except
        tareas = []
    proxima, cada = _siguiente(wa, tareas)
    return [{
        'id': 'backup_tick', 'kind': 'backup',
        'label': wa._t('timer_backup'),
        # Y el tic, dicho donde no se confunde con el periodo de las copias: explica por qué
        # una copia que tocaba a y cuarto se hace a y veinte, que es la pregunta siguiente.
        'detail': (wa._t('timer_backup_tasks_tick', _tareas(wa, len(tareas)),
                         int(TICK_SECONDS // 60)) if tareas
                   else wa._t('timer_detail_backup_none')),
        'setting': 'backup|schedule',
        # Éste no se enciende en Configuración: una copia programada es una **tarea** de la
        # pantalla de Copias, no una casilla de la configuración. La pista la pone el paquete
        # porque es el único que lo sabe; los demás dejan que se resuelva contra el registro.
        'setting_label': wa._t('timer_backup_where'),
        'enabled': bool(tareas),
        # Las dos del mismo reloj: el de la programación, no el del hilo. Ver la cabecera.
        'every': int(cada or TICK_SECONDS),
        'next_run': proxima,
        # Y con qué precisión se puede cumplir: una vuelta del hilo. Medio periodo —la regla
        # por defecto— serían treinta minutos de silencio sobre una copia horaria que no se
        # está tomando, y el silencio es de lo que se quejó quien la miraba.
        'slack': int(TICK_SECONDS),
        'lease': LEASE_KEY,
    }]


def _siguiente(wa, tareas: list) -> tuple:
    """``(cuándo le toca a la primera, cada cuánto le toca a ésa)``.

    La más cercana y no una fila por tarea: la lista tiene un temporizador, que es el hilo, y lo
    que hace falta saber de él es cuándo volverá a hacer algo. Cuál de las tres tareas sea es la
    pregunta de la pantalla de Copias, que las enseña una por una.

    Y el periodo es el **de esa misma tarea**, no el del hilo ni un promedio de las tres: es lo
    que hace que la barra de avance signifique algo — lo que queda, sobre lo que dura el hueco
    que se está recorriendo.

    Que se caiga no puede costar la fila entera: sin números se enseña el estado y ya está, que
    es lo que hacía esta lista antes de saber contestar esto.
    """
    if not tareas:
        return 0.0, 0.0
    try:
        import time                                              # noqa: PLC0415
        from lib.core.backup import schedule as _sched           # noqa: PLC0415
        from lib.core.backup import service as _svc              # noqa: PLC0415
        ahora = time.time()
        hay = _svc.list_backups(wa._var_dir or '',
                                str(getattr(wa, '_BACKUP_DIR', '') or ''))
        cola = []
        for t in tareas:
            cuando = _sched.next_due_at(t, ahora, _sched.last_auto_ts(hay, t.get('name')))
            if cuando:
                cola.append((cuando, _sched.due_span(t, ahora)))
        return min(cola) if cola else (0.0, 0.0)
    except Exception:  # pylint: disable=broad-except
        return 0.0, 0.0


def _tareas(wa, cuantas: int) -> str:
    """«1 tarea encendida» o «3 tareas encendidas», no «1 tarea(s) encendida(s)».

    Un plural entre paréntesis es lo que escribe un programa que no quiso elegir, y esta línea
    va debajo del nombre en una tabla que se lee de un vistazo.
    """
    return (wa._t('timer_backup_task_one') if cuantas == 1
            else wa._t('timer_backup_tasks', cuantas))
