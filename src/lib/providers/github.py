#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub: traerse un repositorio como un zip, una vez y para quien lo necesite.

Un proveedor externo como los demás de esta carpeta —habla con una API ajena y depende solo
de la biblioteca estándar— y por eso vive aquí y no entre las utilidades: lo que hace no es
una cuenta ni una conversión, es una conversación con una máquina de otro.

Lo usaban las MIB y lo necesita el catálogo de modelos del inventario físico. Copiarlo habría
sido copiar la parte difícil —la caché con revalidación, el progreso, el tope de tamaño, no
extraer nunca nada— y el día que una copia aprendiera algo, la otra seguiría sin saberlo.

**`codeload` y no la API, para recorrer.** La API de GitHub da sesenta peticiones por hora sin
credencial, y recorrer las carpetas de un repositorio con cuatrocientas cuesta cuatrocientas.
`codeload` sirve el repositorio entero como **un** fichero y no cuenta contra ese límite.

**Salvo cuando el repositorio no cabe.** Eso vale mientras «entero» sean treinta megas. Hay
repositorios de ochocientos cincuenta —una imagen por dispositivo— donde bajarlo todo para leer un
índice no es una optimización sino lo contrario. Para esos hay dos caminos más: `list_tree`, que
trae el índice completo en **una** petición de la API, y `fetch_file`, que trae un fichero suelto
por `raw.githubusercontent.com`, que tampoco es la API ni gasta de ese límite.

Cuál usar no lo decide esto: lo decide quien sabe cómo de grande es lo que va a pedir.

**A fichero y no a memoria.** Lo que esto existe para traer son decenas de megabytes, y
`zipfile.ZipFile` quiere poder saltar por el archivo — que es justo lo que un fichero le da
gratis.

**Nada se extrae nunca.** Las entradas se leen por nombre desde el índice del zip. Un archivo que
nombra `../../etc/algo` es un archivo que escribe donde no debe, y la única defensa que aguanta es
no poner su contenido en un disco.

Este módulo no sabe de MIB ni de modelos de dispositivos: analiza una URL, descarga, y devuelve un
fichero y los nombres que hay dentro. Lo que se haga con ellos es de quien llama.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import time
import zipfile

# El nombre con el que este panel se presenta ante un servidor ajeno. De su única casa:
# un `User-Agent` inventado aquí sería un segundo sitio donde el producto se llama de otra
# forma el día que alguien lo renombre.
from lib import APP_NAME

_GH_TREE_RE = re.compile(r'^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.+?))?/?$')
_GH_ROOT_RE = re.compile(r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$')

#: La subcarpeta donde se deja el archivo descargado con su ETag al lado.
_ARCHIVE_CACHE = '.archive-cache'



def parse_folder(url: str):
    """Parse a GitHub folder URL → (owner, repo, branch, path) or None.

    Accepts ``.../tree/<branch>/<path>``, ``.../tree/<branch>`` and bare
    ``github.com/<owner>/<repo>`` (root of the default branch).
    """
    m = _GH_TREE_RE.match(url.strip())
    if m:
        return m.group(1), m.group(2), m.group(3), (m.group(4) or '')
    m = _GH_ROOT_RE.match(url.strip())
    if m:
        return m.group(1), m.group(2), '', ''
    return None


# What a MIB says about itself. Every other rule here is a guess about a NAME; this one
# reads the file — and a name is exactly what the offenders are good at: net-snmp's `mibs/`
# folder ships `nodemap`, `rfclist`, `ianalist`, `mibfetch` and `smistrip`, none of which is a
# MIB and all of which look like one from outside.
#
# Asked of the parser that already answers it, rather than with a second regex of its own.
# The second regex was wrong in a way only real files show: it read the RAW text, so
# `NAME`, a comment, and then `DEFINITIONS ::= BEGIN` on the next line did not match — and
# ASN.1 does not care where a comment falls between two tokens. LibreNMS ships several
# written that way (FROGFOOT-RESOURCES-MIB, ADIC-INTELLIGENT-STORAGE-MIB), and every import
# quietly refused them as "not a MIB" while the panel's own module-name reader, which blanks
# comments first, read their names perfectly well.


def zip_url(url: str) -> tuple:
    """A GitHub folder URL as ``(zip url, path inside the repo)``, or ``(None, '')``.

    ``codeload`` serves the repository as one file and is not the API: it costs no request
    against the sixty an hour, which is the whole reason to prefer it for a repository whose
    folders would cost four hundred.
    """
    parsed = parse_folder(url)
    if not parsed:
        return None, ''
    owner, repo, branch, path = parsed
    branch = branch or 'master'
    return (f'https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}',
            str(path or '').strip('/'))


def _rm_quiet(path: str) -> None:
    """Borrar sin quejarse. Un fichero temporal que ya no está es el estado que se buscaba."""
    try:
        os.remove(path)
    except OSError:
        pass


def cache_dir_for(var_dir: str, owner: str) -> str:
    """Dónde se guarda un archivo descargado entre usos: al lado de lo que lo usa, no dentro.

    *owner* es la carpeta de quien lo pide —`snmp_mibs`, `dcim_media`— y va como argumento
    porque este módulo no sabe quién lo llama ni tiene por qué: dos que se traen repositorios
    distintos no quieren pisarse la caché.
    """
    return os.path.join(var_dir, str(owner or ''), _ARCHIVE_CACHE) if var_dir else ''


def _cache_slot(cache_dir: str, url: str):
    """``(zip_path, etag_path)`` for *url*, or ``('', '')`` with no cache."""
    if not cache_dir:
        return '', ''
    key = hashlib.sha1(url.encode('utf-8', 'replace')).hexdigest()[:16]
    return os.path.join(cache_dir, key + '.zip'), os.path.join(cache_dir, key + '.etag')


def prune_cache(cache_dir: str, keep: int = 2, max_age_days: int = 7) -> None:
    """Keep the last few archives and nothing old.

    A cached archive is 86 MB of somebody's disk; keeping every one ever downloaded is a
    cache that only grows. Two is the flow this exists for — compare, then import — with room
    for a second source in between.
    """
    if not cache_dir or not os.path.isdir(cache_dir):
        return
    try:
        names = os.listdir(cache_dir)
        # A download that died half way leaves its `.part`. Anything older than an hour is
        # not somebody's download in flight, it is somebody's crash.
        stale = time.time() - 3600
        for f in names:
            p = os.path.join(cache_dir, f)
            if f.endswith('.part') and os.path.getmtime(p) < stale:
                _rm_quiet(p)
        zips = [os.path.join(cache_dir, f) for f in names if f.endswith('.zip')]
        zips.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        cutoff = time.time() - max_age_days * 86400
        for i, p in enumerate(zips):
            if i < keep and os.path.getmtime(p) >= cutoff:
                continue
            _rm_quiet(p)
            _rm_quiet(p[:-4] + '.etag')
    except OSError:
        pass


def download(url: str, max_bytes: int, on_progress=None, cache_dir: str = '',
                      fresh: bool = False):
    """Stream *url* to a file. Returns ``(path, '')`` or ``(None, message)``.

    **Kept and revalidated.** Comparing an archive and then importing it is the same 86 MB
    twice, and pressing Compare first is exactly what the panel asks you to do — the second
    download answers a question the first one already answered. So the file is kept beside the
    library with the ETag the server gave it, and every use asks the server whether that copy
    is still current: a 304 costs one request and no megabytes, and a server that does not do
    conditional requests simply sends the file again, which is what happened before.

    *fresh* asks for the file itself and not for an opinion about it: no conditional
    request, and whatever comes back replaces what was there. Reusing is the right default —
    the server is asked every time and a changed archive downloads by itself — but "ask
    again" and "fetch it again" are different requests, and only one of them can be made by
    pressing the same button twice.

    Returns ``(path, message, from_cache)``. The path may be the cached copy — the caller
    prunes the cache, it does not delete what it was handed — and *from_cache* is what lets
    the report say why it was instant.

    To a file and not to memory, because the thing this exists for is a whole-repository zip
    of tens of megabytes — and because :class:`zipfile.ZipFile` wants to seek, which is what a
    file gives it for free.

    *on_progress* is called with ``(bytes_so_far, bytes_total)`` once per chunk. It is the
    only thing that can be said honestly while this runs: 86 MB over somebody's line is a
    minute of a button that otherwise looks stuck. ``bytes_total`` is 0 when the server sends
    no ``Content-Length`` — a bar with no end is still a bar that is moving.
    """
    import tempfile           # noqa: PLC0415
    import urllib.error       # noqa: PLC0415
    import urllib.request     # noqa: PLC0415

    cached, etag_path = _cache_slot(cache_dir, url)
    etag = ''
    if fresh:
        _rm_quiet(cached)
        _rm_quiet(etag_path)
    elif cached and os.path.isfile(cached) and os.path.isfile(etag_path):
        try:
            with io.open(etag_path, encoding='utf-8') as fh:
                etag = fh.read().strip()
        except OSError:
            etag = ''

    # IN the cache directory, and this is not a detail: `os.replace` cannot move a file
    # across volumes on Windows, and the system temp is on C: while somebody's data directory
    # is on D:. Every download went to C:, every rename failed, the failure was swallowed as
    # "then keep the temp file" — so nothing was ever cached, every use downloaded again, and
    # each one left 86 MB behind. Born on the destination volume, the rename is a rename.
    if cache_dir:
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            cache_dir, cached, etag_path = '', '', ''
    fd, path = tempfile.mkstemp(prefix='ss-mib-archive-', suffix='.part',
                                dir=cache_dir or None)
    total = 0
    _last_etag = ''
    try:
        headers = {'User-Agent': APP_NAME}
        if etag:
            headers['If-None-Match'] = etag
        req = urllib.request.Request(url, headers=headers)
        # The file object FIRST, so the descriptor is adopted before anything can raise.
        # Opened inside the same `with` as the request, it is never adopted at all when the
        # request throws — and an unclosed handle on Windows is a file that cannot be
        # deleted, which is how a 304 (an exception, in urllib) left its empty `.part`.
        with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(req, timeout=180) as r:
            # Defensively: a response without headers is not a reason to lose the
            # download, it is a reason to have no total.
            try:
                _h = getattr(r, 'headers', None) or {}
                expected = int(_h.get('Content-Length') or 0)
                _last_etag = _h.get('ETag') or ''
            except (AttributeError, TypeError, ValueError):
                expected = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    # Out of the loop rather than out of the function: the temp file is still
                    # open here, and on Windows a delete under an open handle fails — which
                    # is how a refused download used to leave its half behind.
                    break
                out.write(chunk)
                if on_progress is not None:
                    on_progress(total, expected)
    except urllib.error.HTTPError as exc:
        _rm_quiet(path)
        # 304: the copy on disk IS the answer. Anything else is a failure like any other.
        if exc.code == 304 and cached and os.path.isfile(cached):
            return cached, '', True
        return None, str(exc), False
    except Exception as exc:   # pylint: disable=broad-except
        _rm_quiet(path)
        return None, str(exc), False
    if total > max_bytes:
        _rm_quiet(path)
        return None, 'Archive too large', False
    if not cached:
        return path, '', False
    # Into the cache with the tag that identifies it, so the next use can ask instead of
    # downloading. A cache that cannot be revalidated is a guess with a disk cost.
    try:
        os.replace(path, cached)
        new_etag = str(_last_etag or '').strip()
        if new_etag:
            with io.open(etag_path, 'w', encoding='utf-8') as fh:
                fh.write(new_etag)
        else:
            _rm_quiet(etag_path)
        return cached, '', False
    except OSError:
        # Could not be filed. The file is still the answer to THIS call — the caller deletes
        # it, having been handed something that is not in the cache.
        return path, '', False


# How much of a file is enough to see what it is. A licence banner is fifty lines; a
# readme says what it is in the first three.


def member_inner(member, strip: str = '') -> str:
    """A zip member's path with the wrapper folder removed, using forward slashes."""
    inner = str(getattr(member, 'filename', '')).replace('\\', '/').strip('/')
    if strip and (inner == strip or inner.startswith(strip + '/')):
        inner = inner[len(strip):].strip('/')
    return inner


def wrapper_of(members) -> str:
    """The single top-level directory every member sits under, or ``''``.

    Archives are usually packed with one wrapper folder — Synology's is called "MIB files" —
    and it belongs to the packaging, not to the layout. Keeping it buries every MIB one level
    deeper for no reason, and the day the vendor renames it, the next import lands beside the
    old one instead of updating it.

    Only when ALL of them share it: a mixed archive has real structure and it is kept whole.

    **Directory entries do not count.** A zip from GitHub carries the wrapper's own directory
    entry — `devicetype-library-master/` — and read as if it were a file, that is a name with one
    part: "something at the root", so there is no wrapper. The wrapper prevented itself from
    being detected, every name kept it, and no elevation image was ever found — with nothing
    failing, because thousands of real models have no picture and eight thousand without one is a
    believable answer.

    A folder is not something AT the root: it is the root. What decides whether there is a
    wrapper are the FILES.
    """
    tops = set()
    for m in members:
        crudo = str(getattr(m, 'filename', '')).replace('\\', '/')
        if crudo.endswith('/') or getattr(m, 'is_dir', lambda: False)():
            continue
        head = crudo.strip('/').split('/')
        if len(head) < 2:
            return ''            # a FILE sits at the root: there is no wrapper
        tops.add(head[0])
    return tops.pop() if len(tops) == 1 else ''


# ── Mirar sin traer ─────────────────────────────────────────────────────────────────────
#
# El índice de un repositorio en una petición, y un fichero suelto en otra. Es lo que hace falta
# cuando el repositorio pesa demasiado para bajarlo entero — y también cuando solo se quiere una
# décima parte de él, que es el caso normal de un catálogo de doscientos fabricantes.

#: La API, para el índice. Cuesta una petición de las sesenta por hora que hay sin credencial,
#: lo que la hace cara de repetir y barata de usar una vez.
_API = 'https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1'

#: Los ficheros, por la puerta que no es la API. `raw.githubusercontent.com` sirve contenido y no
#: gasta de ese límite, que es lo que permite traerse doscientos YAML seguidos.
_RAW = 'https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}'

#: Tope del índice. Tres megas es lo que ocupa el de un repositorio de once mil ficheros; treinta
#: deja sitio a uno diez veces mayor sin dejar sitio a que una respuesta rara llene la memoria.
_MAX_TREE = 30 * 1024 * 1024


def _ref_of(url: str):
    """La URL de un repositorio como ``(owner, repo, rama, subcarpeta)``, o ``None``."""
    parsed = parse_folder(url)
    if not parsed:
        return None
    owner, repo, branch, path = parsed
    return owner, repo, branch or 'master', str(path or '').strip('/')


def list_tree(url: str, token: str = '', timeout: int = 60):
    """Los ficheros que hay en el repositorio, sin bajar ninguno.

    Devuelve ``(rutas, '')`` o ``([], mensaje)``. Las rutas son relativas a la raíz del
    repositorio, tal como GitHub las nombra.

    Una sola petición para todo el árbol, y no una por carpeta: la diferencia entre eso y
    recorrer es la diferencia entre gastar una de las sesenta que hay por hora y gastarlas
    todas antes de llegar a la mitad.

    Lo que no devuelve es el tamaño ni el contenido. Para saber qué hay dentro de un fichero
    hay que pedirlo, y esta función existe precisamente para no pedir los que no interesan.
    """
    ref = _ref_of(url)
    if not ref:
        return [], 'bad_url'
    owner, repo, branch, _sub = ref
    cab = {'Accept': 'application/vnd.github+json',
           'User-Agent': '%s catalogue' % APP_NAME}
    if token:
        cab['Authorization'] = 'Bearer %s' % token
    pedir = _API.format(owner=owner, repo=repo, ref=branch)
    try:
        req = _urlreq().Request(pedir, headers=cab)
        with _urlreq().urlopen(req, timeout=timeout) as resp:
            crudo = resp.read(_MAX_TREE + 1)
    except Exception as exc:                        # pylint: disable=broad-except
        # Una rama que no existe da 404, y es el error que más se da: quien escribe la URL de
        # un fork suyo escribe `main` donde el original tiene `master`. Se dice tal cual —
        # traducir el número a «no se pudo» borraría justo el dato que lo arregla.
        return [], _http_reason(exc)
    if len(crudo) > _MAX_TREE:
        return [], 'too_large'
    try:
        d = _json().loads(crudo.decode('utf-8', 'replace'))
    except Exception:                               # pylint: disable=broad-except
        return [], 'bad_json'
    if d.get('truncated'):
        # GitHub corta por encima de cien mil entradas. Devolver la mitad sin decirlo haría que
        # el listado enseñara la mitad de los fabricantes como si fueran todos.
        return [], 'truncated'
    return [str(e.get('path') or '') for e in (d.get('tree') or [])
            if e.get('type') == 'blob'], ''


def fetch_file(url: str, path: str, max_bytes: int = 2 * 1024 * 1024, timeout: int = 30):
    """Un fichero del repositorio, en memoria. ``(bytes, '')`` o ``(None, mensaje)``.

    En memoria y no a disco, al revés que :func:`download`, porque lo que se pide por aquí son
    kilobytes: un YAML, una imagen de alzado. *max_bytes* es el corte, y corta de verdad — se
    lee uno de más para saber si sobraba.
    """
    ref = _ref_of(url)
    if not ref:
        return None, 'bad_url'
    owner, repo, branch, _sub = ref
    pedir = _RAW.format(owner=owner, repo=repo, ref=branch,
                        path=_quote(str(path or '').lstrip('/')))
    try:
        req = _urlreq().Request(pedir, headers={'User-Agent': '%s catalogue' % APP_NAME})
        with _urlreq().urlopen(req, timeout=timeout) as resp:
            datos = resp.read(max_bytes + 1)
    except Exception as exc:                        # pylint: disable=broad-except
        return None, _http_reason(exc)
    if len(datos) > max_bytes:
        return None, 'too_large'
    return datos, ''


def _urlreq():
    """`urllib.request`, importado al usarlo.

    Tarde y no arriba porque este módulo lo importa quien solo quiere analizar una URL, y
    `urllib.request` arrastra `ssl` y `http.client` detrás.
    """
    import urllib.request                           # noqa: PLC0415
    return urllib.request


def _json():
    import json                                     # noqa: PLC0415
    return json


def _quote(path: str) -> str:
    """La ruta, escapada para una URL — sin tocar las barras, que son estructura y no texto."""
    from urllib.parse import quote                  # noqa: PLC0415
    return quote(path, safe='/')


def _http_reason(exc) -> str:
    """Por qué falló, en una línea que sirva para arreglarlo.

    El código HTTP entero y no «no se pudo»: 404 dice que la rama no se llama así, 403 que se
    acabaron las sesenta peticiones de la hora, y son dos problemas con dos soluciones
    distintas. Un mensaje que los junta obliga a adivinar cuál de los dos fue.
    """
    codigo = getattr(exc, 'code', None)
    if codigo == 403:
        return 'rate_limited'
    if codigo == 404:
        return 'not_found'
    if codigo:
        return 'http_%s' % codigo
    return str(getattr(exc, 'reason', '') or exc) or 'failed'


def fetch_many(url: str, paths, max_bytes: int = 2 * 1024 * 1024, timeout: int = 30):
    """Varios ficheros por una sola conexión. Va soltando ``(ruta, bytes, mensaje)``.

    Uno a uno con :func:`fetch_file` son tantos saludos TLS como ficheros, y el saludo cuesta
    más que el fichero: un YAML de dos kilobytes tarda un segundo del que el contenido es la
    milésima parte. Con la conexión abierta tarda lo que ocupa.

    Si la conexión se cae a mitad se abre otra y se sigue por donde iba — un servidor puede
    cerrar cuando quiera, y perder los ochenta ficheros que quedaban por eso sería perderlos por
    algo que no es un error.

    En el orden en que se piden, y de uno en uno: quien llama va enseñando por dónde va.
    """
    ref = _ref_of(url)
    if not ref:
        for path in paths:
            yield str(path), None, 'bad_url'
        return
    owner, repo, branch, _sub = ref
    http = _httplib()
    conn = None
    try:
        for path in paths:
            rel = str(path or '').lstrip('/')
            destino = '/%s/%s/%s/%s' % (owner, repo, branch, _quote(rel))
            datos, err = None, ''
            for intento in (1, 2):
                try:
                    if conn is None:
                        conn = http.HTTPSConnection('raw.githubusercontent.com',
                                                    timeout=timeout)
                    conn.request('GET', destino,
                                 headers={'User-Agent': '%s catalogue' % APP_NAME,
                                          'Accept': '*/*'})
                    resp = conn.getresponse()
                    cuerpo = resp.read(max_bytes + 1)
                    if resp.status != 200:
                        # El cuerpo hay que leerlo igual aunque no sirva: dejarlo a medias deja
                        # la conexión sucia y el siguiente fichero lee la cola de este.
                        err = _status_reason(resp.status)
                    elif len(cuerpo) > max_bytes:
                        err = 'too_large'
                    else:
                        datos = cuerpo
                    break
                except Exception as exc:        # pylint: disable=broad-except
                    # Primer intento: la conexión estaba muerta y no se sabía. Segundo: es el
                    # servidor o la red, y entonces sí es un error de este fichero.
                    _close_quiet(conn)
                    conn = None
                    if intento == 2:
                        err = _http_reason(exc)
            yield rel, datos, err
    finally:
        _close_quiet(conn)


def _httplib():
    import http.client                              # noqa: PLC0415
    return http.client


def _close_quiet(conn) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:                               # pylint: disable=broad-except
        pass


def _status_reason(status: int) -> str:
    """Un código de respuesta como la razón que lo explica, igual que :func:`_http_reason`."""
    if status == 403:
        return 'rate_limited'
    if status == 404:
        return 'not_found'
    return 'http_%s' % status
