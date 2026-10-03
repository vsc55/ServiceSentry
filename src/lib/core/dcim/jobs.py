#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Importing the catalogue, which takes long enough that somebody has to be able to watch it.

Several thousand small YAML files is a minute or two of work: too long to hold a request open —
a browser or a reverse proxy gives up first and the operator is left not knowing whether it
worked — and short enough that nobody wants a whole scheduling system for it. Same shape as the
collection, the backup and the MIB compile: the work goes on a thread, the answer is a job id
the browser polls, and the jobs screen picks it up because this package declares it.

**One at a time.** A second import while the first is running would have two writers replacing
the same source's rows, and the loser's work is silently lost. There is no queue: the second
caller is told there is one running, which is the truth and is what they would want to know.

**In memory on purpose.** A job is about THIS process; it dies with it, and a browser polling a
job whose process is gone gets a 404, which is also the truth. What the import *produces* is in
the database, which is where it belongs and where it survives.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

from . import catalog

#: Runs in flight and recently finished, by job id.
_JOBS: dict = {}
_LOCK = threading.Lock()

#: How long a finished job stays around to be asked about — long enough that somebody who
#: walked away still gets an answer rather than a 404 that reads like a failure.
_KEEP_FINISHED = 30 * 60


def _prune(now: float) -> None:
    for jid, job in list(_JOBS.items()):
        if job.get('done') and (now - float(job.get('_ended') or now)) > _KEEP_FINISHED:
            _JOBS.pop(jid, None)


def job_status(job_id: str) -> dict | None:
    """The job, or ``None``. Private keys (leading ``_``) never leave."""
    job = _JOBS.get(str(job_id or ''))
    if job is None:
        return None
    return {k: v for k, v in job.items() if not k.startswith('_')}


def running_job() -> dict | None:
    """The import in flight, if there is one — the server's answer, not a browser's memory.

    F5 loses the job id and nothing else: the work is a thread here and does not depend on
    anybody watching. Asking the server is also the right answer for a second tab, a
    colleague's laptop, and the person who closed the browser and came back.
    """
    for job in _JOBS.values():
        if not job.get('done'):
            return {k: v for k, v in job.items() if not k.startswith('_')}
    return None


def start_import(store, source: str, kind: str, path: str, *, actor: str = '',
                 var_dir: str = '', media_dir: str = '', vendors=None, paths=None,
                 cleanup: str = '') -> tuple:
    """Import a catalogue in the background. Returns ``(job_id, error)``.

    *kind* is ``'dir'``, ``'zip'``, ``'github'`` (the ticked manufacturers, file by file) or
    ``'github_all'`` (the whole repository as one archive — cheaper only when the answer really
    is «all of it»); *path* is a directory, an archive or a
    repository URL that the CALLER has already decided is legitimate. Nothing here validates it:
    this module is about running work on a thread, and a path check written here as well as at
    the route is the second copy that disagrees with the first.

    *vendors* solo pinta con ``'github'``: qué fabricantes traer de la biblioteca. Vacío son
    todos, y todos son seis mil ficheros — el catálogo tiene su propio tope para eso. *paths* es
    el índice que la pantalla ya pidió al enseñar la lista, para no volver a pedirlo.

    *cleanup* es un fichero que se borra al terminar, salga bien o mal: el zip que alguien subió
    por el navegador y que se dejó en un temporal para poder abrirlo. Lo borra QUIEN LO LEE y no
    quien lo escribió, porque la lectura pasa en otro hilo y termina más tarde — borrarlo al
    devolver el identificador del trabajo sería borrarlo antes de abrirlo.

    *var_dir* y *media_dir* son dónde guardar las imágenes de elevación que la biblioteca trae
    al lado de cada modelo. Sin ellos la importación funciona igual y los modelos entran sin
    imagen — que es como estaban antes.
    """
    if catalog._yaml is None:                   # noqa: SLF001  (the one honest peek)
        return '', catalog.NO_PARSER
    with _LOCK:
        if running_job():
            return '', 'dcim_catalog_busy'
        now = time.time()
        _prune(now)
        job_id = uuid.uuid4().hex[:12]
        _JOBS[job_id] = {'id': job_id, 'source': str(source or 'library'), 'kind': str(kind),
                         'count': 0, 'done': False, 'error': '', 'started': now,
                         # Lo que hay que enseñar mientras dura. `total` en cero significa «no
                         # se sabe», que es la verdad para un zip y deja de serlo para GitHub.
                         'total': 0, 'phase': '', 'fetched': 0,
                         '_started': now, '_actor': str(actor or '')}

    def _run() -> None:
        job = _JOBS[job_id]
        def _voy(hechos, total, fase):
            """Lo que va haciendo la descarga, mientras la hace.

            No es lo mismo que `count`: aquello son modelos ya leídos y esto son ficheros ya
            pedidos. Confundirlos es lo que dejaba la pantalla en «0 modelos leídos» durante
            todo el trabajo — porque leídos, hasta el final, no había ninguno.
            """
            job['fetched'] = int(hechos)
            job['total'] = int(total)
            job['phase'] = str(fase)

        try:
            rows = (catalog.read_whole(path, var_dir, _voy) if kind == 'github_all'
                    else catalog.read_remote(path, vendors, paths, _voy) if kind == 'github'
                    else catalog.read_zip(path) if kind == 'zip'
                    else catalog.read_dir(path))
            # Counted as they are read, so the screen moves instead of sitting at zero for a
            # minute and then finishing. There is no total to divide by — nobody knows how many
            # device types an archive holds until it has been read — so this is a tally and not
            # a bar, and a tally is what is drawn.
            kept = []
            for row in rows:
                kept.append(row)
                job['count'] = len(kept)
            job['phase'] = 'saving'
            # Y reemplazando SOLO lo que este trabajo cubría. Elegir fabricantes en la
            # pantalla es traerse esos; la fuente entera únicamente cuando la importación
            # afirma serlo —un zip, una carpeta, la biblioteca completa—, que es cuando «lo
            # que ya no está arriba» significa algo.
            job['count'] = store.replace(job['source'], kept, var_dir, media_dir,
                                         partial=(kind == 'github' and bool(vendors)))
        except Exception as exc:                # pylint: disable=broad-except
            job['error'] = str(exc) or exc.__class__.__name__
        finally:
            job['done'] = True
            job['_ended'] = time.time()
            if cleanup:
                try:
                    os.remove(cleanup)
                except OSError:
                    # Que no se pueda borrar un temporal no invalida una importación que ya
                    # está en la base de datos. El sistema los limpia solo antes o después.
                    pass

    threading.Thread(target=_run, name=f'dcim-catalog-{job_id}', daemon=True).start()
    return job_id, ''


def live(_wa) -> list:
    """What this package is running now, for the background-jobs screen.

    Declared in the manifest (``BACKGROUND_JOBS``) rather than the screen reaching in here: a
    core that imported four job registries by name is a core that has to be edited to learn
    about a fifth.
    """
    now = time.time()
    out = []
    for jid, job in list(_JOBS.items()):
        out.append({
            'id': jid,
            'kind': 'dcim_catalog',
            'label': str(job.get('source') or ''),
            'detail': str(job.get('count') or 0),
            'state': ('failed' if job.get('error') else 'done') if job.get('done')
                     else 'running',
            'started': float(job.get('_started') or now),
            # A denominator only where there IS one. A zip's size in models is not known
            # until it has been read, and a bar that invents one lies about how far along it
            # is; a GitHub import counted its files before it started, so it gets a real bar.
            'done': int(job.get('fetched') or job.get('count') or 0),
            'total': int(job.get('total') or 0),
            'error': str(job.get('error') or ''),
            'steps': [],
        })
    return out
