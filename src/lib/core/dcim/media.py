#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where the pictures live: floor plans, and later the catalogue's elevations.

A folder under ``var_dir``, the way the MIB library is a folder under ``var_dir`` — and for the
same reason. These are files somebody uploaded: they are not rows, they do not belong in a
database that is backed up as SQL, and a room's plan is a JPEG of a drawing that an architect
sent in 2019.

**The record holds a NAME, never a path.** ``dc_room.plan`` is ``a1b2c3….png`` and this module
is the only thing that turns one into a place on a disk. That is not tidiness: the MIB catalogue
shipped a path traversal of exactly this shape, and the fix that holds is the one where a path
can only be *built* here, from a name that was minted here.

**A stored name is not the name that was uploaded.** What arrives is
``Plano Sala 2 (definitivo) FINAL.png`` — spaces, parentheses, accents, and on a bad day
``../../etc/cron.d/x``. What is stored is a fresh identifier plus the extension the CONTENT
turned out to have. The original travels beside it, in the database, for the human who wants to
know what the file was called.

**The type is decided by what is INSIDE**, not by the extension. An extension is a claim by
whoever uploaded it; the first bytes of a PNG, a JPEG, a GIF, a WebP or an SVG are not. An
uploaded ``.png`` that is really a shell script is refused rather than stored under a name that
makes it look like an image.

Three rules the panel already lives by, applied here:

* **Nothing is ever written outside the folder** (`confined`), belt-and-braces on top of the
  name check — a symlink out of the directory is the case a name check cannot see.
* **Size is capped before anything is read**, because "read it and then decide" is how a
  request fills a disk.
* **It goes in the backup.** A plan that does not come back with a restore is a plan somebody
  loses the day they need it most, and the file is the only copy — the database holds a name.
"""

from __future__ import annotations

import io
import os
import re

from lib.core.uids import new_uid

#: Where they go, under ``var_dir``. Beside the MIB library, not inside anything of the panel's.
FOLDER = 'dcim_media'

#: What may be stored, by what the CONTENT says it is: extension → the bytes it must start with.
#: SVG is text and has no magic number, so it is matched on its opening tag after whitespace —
#: which is also why it is the one that needs the sanitising note below.
SIGNATURES = (
    ('.png',  b'\x89PNG\r\n\x1a\n'),
    ('.jpg',  b'\xff\xd8\xff'),
    ('.gif',  b'GIF87a'),
    ('.gif',  b'GIF89a'),
    ('.webp', b'RIFF'),                          # …plus 'WEBP' at offset 8, checked below
)

#: Uploaded images are capped before they are read. Two megabytes is a generous floor plan and a
#: long way from what a request can be made to swallow.
MAX_BYTES = 2 * 1024 * 1024

#: De dónde vino un fichero, y en qué subcarpeta vive. `library` es lo que trajo una importación
#: —mil doscientas imágenes de alzado que se vuelven a bajar con un botón— y `own` es lo que
#: alguien subió aquí: la foto del armario que montó el electricista, el manual que mandó el
#: distribuidor. Lo segundo no está en ningún otro sitio.
#:
#: Es la misma línea que el catálogo traza con `source`, y de ella cuelga lo que hoy no se puede
#: hacer: guardar lo propio sin arrastrar ochocientos megas de biblioteca, y mirar la carpeta y
#: saber qué se perdería.
BUCKETS = ('own', 'library')

#: A stored name: the uid this module minted, and an extension from the list above. Anything
#: that does not match this shape never becomes a path.
#:
#: `.bin` es lo que acuña `keep()` para un adjunto —un manual, un firmware—: lo que hay dentro no
#: se mira, y por eso el nombre del disco no lleva la extensión de verdad. Aquí tiene que estar o
#: `read` y `forget` no reconocerían sus propios ficheros.
#:
#: Y el prefijo de la subcarpeta es **opcional** a propósito: los nombres planos de una
#: instalación que ya existe se siguen leyendo, así que nadie tiene que mover nada para recibir
#: esto. Lo nuevo nace con prefijo; lo viejo sigue donde está.
_NAME_RE = re.compile(
    r'^(?:(?:own|library)/)?[0-9a-f]{8}[0-9a-f-]{20,30}\.(png|jpg|gif|webp|svg|bin)$')


def where(var_dir: str, configured: str = '') -> str:
    """Which folder this setting resolves to — without touching the disk.

    Split from :func:`folder` because ASKING where something goes is not the same as going
    there: the Configuration screen asks so the empty box can show which path that turns out
    to be, and a GET that paints a screen has no business leaving a directory behind — least
    of all one that may never be used.
    """
    path = str(configured or '').strip()
    if path:
        return path
    return os.path.join(var_dir, FOLDER) if var_dir else ''


def folder(var_dir: str, configured: str = '') -> str:
    """The directory, created on demand. Empty when there is nowhere to put one.

    *configured* wins when it is set — the setting is `web_admin|dcim_media_dir`, and it is
    passed IN rather than read here: this module has no config and no Flask, which is what lets
    a test point it at a temporary folder in one line.

    Empty falls back to ``<var_dir>/dcim_media``, which is the sane default and is why the
    setting can stay empty on every install that does not care.
    """
    path = where(var_dir, configured)
    if not path:
        return ''
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return ''
    return path


def confined(base_dir: str, name: str) -> str | None:
    """The path of *name* inside *base_dir*, or ``None`` if it would not be strictly inside.

    Belt-and-braces on top of :func:`is_name`: a name can be checked, and a symlink pointing out
    of the directory cannot. Same shape as the MIB library's guard, and for the same reason —
    that is where this panel learned it.

    The base is resolved once (it is ours and it is stable); the target is joined and normalised
    **lexically**, and only resolved when it exists, which is the only case where a symlink has
    anywhere to point.
    """
    if not base_dir or not name:
        return None
    base = os.path.realpath(base_dir)
    target = os.path.normpath(os.path.join(base, name))
    if os.path.exists(target):
        target = os.path.realpath(target)
    nbase, ntarget = os.path.normcase(base), os.path.normcase(target)
    if ntarget != nbase and not ntarget.startswith(nbase + os.sep):
        return None
    return target


def is_name(name: str) -> bool:
    """Whether *name* is one this module minted. Nothing else ever becomes a path."""
    return bool(_NAME_RE.match(str(name or '')))


def kind_of(data: bytes) -> str:
    """The extension the CONTENT says it is, or ``''``.

    By content and not by the name, because the name is a claim by whoever uploaded the file. A
    ``.png`` that is really a shell script gets refused here instead of being stored under a
    name that makes it look like a picture.
    """
    blob = bytes(data or b'')
    if not blob:
        return ''
    for ext, magic in SIGNATURES:
        if blob.startswith(magic):
            if ext == '.webp' and blob[8:12] != b'WEBP':
                continue
            return ext
    head = blob[:512].lstrip()
    if head.startswith(b'<?xml') or head.startswith(b'<svg'):
        return '.svg' if b'<svg' in blob[:2048].lower() else ''
    return ''


def _mint(var_dir: str, ext: str, bucket: str, configured: str) -> tuple:
    """Un nombre nuevo y su ruta, en la subcarpeta que le toca. ``(nombre, ruta, error)``.

    La subcarpeta se crea aquí: pedirle a quien instala que la haga a mano es pedirle que se
    entere de que existe.
    """
    base = folder(var_dir, configured)
    if not base:
        return '', '', 'dcim_media_no_dir'
    cesta = bucket if bucket in BUCKETS else 'own'
    try:
        os.makedirs(os.path.join(base, cesta), exist_ok=True)
    except OSError:
        return '', '', 'dcim_media_no_dir'
    name = f'{cesta}/{new_uid()}{ext}'
    path = confined(base, name)
    if not path:
        return '', '', 'dcim_media_no_dir'
    return name, path, ''


def save(var_dir: str, data: bytes, configured: str = '', bucket: str = 'own') -> tuple:
    """Store *data* and hand back ``(name, error)``.

    The name is minted here — a fresh uid plus the extension the content turned out to have —
    so what ends up in a record can never be something a request chose. What the file was
    *called* is the caller's to keep beside it; this is the identity.
    """
    blob = bytes(data or b'')
    if not blob:
        return '', 'dcim_media_empty'
    if len(blob) > MAX_BYTES:
        return '', 'dcim_media_too_big'
    ext = kind_of(blob)
    if not ext:
        return '', 'dcim_media_not_an_image'
    name, path, err = _mint(var_dir, ext, bucket, configured)
    if err:
        return '', err
    try:
        with io.open(path, 'wb') as fh:
            fh.write(blob)
    except OSError:
        return '', 'dcim_media_write_failed'
    return name, ''


def keep(var_dir: str, data: bytes, limit: int = 0, configured: str = '',
         bucket: str = 'own') -> tuple:
    """Guardar un fichero **que no tiene por qué ser una imagen**. ``(nombre, error)``.

    Un manual, una hoja de características, un zip de firmware. Aquí no se mira lo que hay dentro
    —lo útil es abierto, y una lista de tipos permitidos se queda corta cada semana— y lo que hace
    que eso sea seguro es cómo sale: **siempre como descarga**, con tipo genérico y sin dejar que
    el navegador adivine. Este panel no renderiza nunca un fichero subido.

    La extensión es `.bin` a propósito: lo que el fichero se llamaba se guarda aparte, como
    etiqueta. Si el nombre del disco llevara la extensión de verdad, un servidor mal configurado
    delante podría decidir servirlo por su cuenta — y esa decisión no es suya.
    """
    blob = bytes(data or b'')
    if not blob:
        return '', 'dcim_media_empty'
    if len(blob) > (int(limit) if limit else MAX_BYTES):
        return '', 'dcim_media_too_big'
    name, path, err = _mint(var_dir, '.bin', bucket, configured)
    if err:
        return '', err
    try:
        with io.open(path, 'wb') as fh:
            fh.write(blob)
    except OSError:
        return '', 'dcim_media_write_failed'
    return name, ''


def read(var_dir: str, name: str, configured: str = '', limit: int = 0) -> tuple:
    """``(bytes, error)`` for a stored file.

    *limit* porque un adjunto no es una imagen: el tope de aquí son dos megas y un manual son
    treinta. Sin él, lo que se devolvería sería un PDF cortado — que se abre y está roto, y no
    hay ningún error que lo diga.
    """
    if not is_name(name):
        return b'', 'dcim_media_unknown'
    path = confined(folder(var_dir, configured), str(name))
    if not path or not os.path.isfile(path):
        return b'', 'dcim_media_unknown'
    try:
        with io.open(path, 'rb') as fh:
            return fh.read((int(limit) if limit else MAX_BYTES) + 1), ''
    except OSError:
        return b'', 'dcim_media_unknown'


def forget(var_dir: str, name: str, configured: str = '') -> bool:
    """Delete one, if it is one of ours. A name that is not is not an error: it is a record
    pointing at nothing, which is the state after a restore of a database without its files."""
    if not is_name(name):
        return False
    path = confined(folder(var_dir, configured), str(name))
    if not path or not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def content_type(name: str) -> str:
    """What to serve it as — from the stored NAME, which this module minted and whose extension
    was decided by the content when it arrived. Never from anything a request said."""
    ext = os.path.splitext(str(name or ''))[1].lower()
    return {'.png': 'image/png', '.jpg': 'image/jpeg', '.gif': 'image/gif',
            '.webp': 'image/webp', '.svg': 'image/svg+xml'}.get(ext, 'application/octet-stream')


def every(var_dir: str, configured: str = '', bucket: str = '') -> list:
    """Every stored file's name — what a backup takes, and what an orphan check reads.

    Mira la raíz **y las dos subcarpetas**: la raíz porque ahí siguen los ficheros de una
    instalación anterior a la separación, y las subcarpetas porque es donde nace todo lo nuevo. Un
    repaso de huérfanos que solo mirara una de las dos borraría lo que no encuentra.

    *bucket* acota a una: es lo que permite guardar **solo lo propio** —lo que no se puede volver
    a descargar— sin arrastrar ochocientos megas de biblioteca.
    """
    base = folder(var_dir, configured)
    if not base:
        return []
    fuera = []
    sitios = [''] + ([bucket] if bucket in BUCKETS else list(BUCKETS))
    for cesta in sitios:
        if cesta and bucket and cesta != bucket:
            continue
        ruta = os.path.join(base, cesta) if cesta else base
        try:
            nombres = os.listdir(ruta)
        except OSError:
            continue
        for n in nombres:
            nombre = f'{cesta}/{n}' if cesta else n
            if is_name(nombre):
                fuera.append(nombre)
    return sorted(fuera)
