#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic package-descriptor discovery — ONE scanner for every self-describing feature.

Every extensible feature in ServiceSentry works the same way: a package **declares** what
it contributes and generic core code picks it up.  Before this module each feature grew
its own near-identical ``pkgutil.iter_modules`` loop importing a differently-named
submodule (``permissions.py``, ``overview_widget.py``, ``notify_events.py``,
``config_actions.py``…), so adding a feature meant copying a scanner and inventing a file
name.

Now there is a single convention and a single scanner:

* a package declares everything it contributes in its own ``manifest.py``;
* :func:`scan` returns the value of a named constant from every package that declares it.

The manifest holds the **descriptors**.  Heavy implementations (e.g. a widget's data
provider) stay in their own module and are imported into the manifest, so ``manifest.py``
stays a readable list of what the package offers, not a dumping ground::

    # lib/core/credentials/manifest.py
    from .overview_widget import credentials_stat        # heavy provider stays put

    MODULE_PERMISSIONS = {...}
    OVERVIEW_WIDGETS = [{'id': 'credentials', ..., 'stat': credentials_stat}]

A descriptor may therefore bind live Python objects (callables, classes) — which is why
these manifests are Python and not JSON.  Watchful modules are the opposite case: they are
drop-in plugins that ship no core code, so they declare in ``schema.json`` (pure data) and
are discovered by the schema pipeline instead.
"""

from __future__ import annotations

# Package roots that may contribute descriptors (domains, background services, providers).
DEFAULT_ROOTS: tuple[str, ...] = ('lib.core', 'lib.services', 'lib.providers')

#: The per-package manifest module name.
MANIFEST = 'manifest'


def scan(const: str, *, roots: tuple[str, ...] = DEFAULT_ROOTS,
         manifest: str = MANIFEST) -> list[tuple[str, object]]:
    """``[(package_name, value)]`` for every sub-package whose manifest declares *const*.

    A package that has no manifest, or whose manifest does not declare *const*, is simply
    skipped — contributing is always opt-in.  Import errors are swallowed on purpose: one
    broken optional package must never take the panel down; the feature it contributes
    just does not appear.
    """
    import importlib  # noqa: PLC0415
    import pkgutil    # noqa: PLC0415

    out: list[tuple[str, object]] = []
    for root in roots:
        try:
            pkg = importlib.import_module(root)
        except Exception:  # pylint: disable=broad-except
            continue
        for mod in pkgutil.iter_modules(pkg.__path__):
            if not mod.ispkg:
                continue
            try:
                sub = importlib.import_module(f'{root}.{mod.name}.{manifest}')
            except Exception:  # pylint: disable=broad-except
                continue    # no manifest → contributes nothing
            value = getattr(sub, const, None)
            if value is not None:
                out.append((mod.name, value))
    return out


def scan_values(const: str, **kw) -> list:
    """Just the declared values (see :func:`scan`), package names dropped."""
    return [v for _, v in scan(const, **kw)]


def scan_flat(const: str, **kw) -> list:
    """Flatten list/tuple declarations into a single list.

    Most descriptors are declared as a list per package (``NOTIFY_EVENTS``,
    ``OVERVIEW_WIDGETS``, ``CONFIG_ACTIONS``); this concatenates them, leaving ordering /
    normalisation to the caller that knows the feature's rules.
    """
    out: list = []
    for value in scan_values(const, **kw):
        if isinstance(value, (list, tuple)):
            out.extend(value)
        else:
            out.append(value)
    return out


# ── Acciones que un paquete ofrece EN una pantalla ───────────────────────────────────────
#
# Un caso particular de :func:`scan_flat` con dos reglas propias, y las dos salieron de la
# pantalla de Empresas: un descriptor sin `fn` no se dibuja —no habría nada que pulsar— y uno
# cuyo `ready(wa)` dice que no, tampoco. `ready` es de QUIEN declara: qué necesita un conector
# para funcionar lo sabe su paquete, y el día que le haga falta un tercer campo de configuración
# la respuesta cambia en un sitio.
#
# Aquí y no copiado en cada pantalla porque la segunda copia llegó tres días después de la
# primera: Empresas (`ORG_ACTIONS`) y Dispositivos (`DEVICE_ACTIONS`) hacen exactamente esto, y dos
# implementaciones de la misma regla son dos sitios donde arreglar el mismo fallo.

def ready_actions(const: str, wa, **kw) -> list:
    """Los descriptores de *const* que este panel puede ofrecer ahora mismo, ordenados.

    **Sin caché, a propósito.** `ready` lee la configuración, y ésa se edita desde el propio
    panel: una respuesta guardada de por vida dejaría el botón escondido después de poner la
    clave, hasta reiniciar. Son dos o tres descriptores y una lectura de sección.

    Un `ready` que revienta cuenta como «no está puesto». La alternativa es una pantalla que no
    carga porque un proveedor opcional tiene un fallo en una línea, que es la misma decisión que
    toma :func:`scan` al tragarse los errores de importación.
    """
    fuera: list = []
    for pkg, decl in scan(const, **kw):
        for spec in (decl if isinstance(decl, (list, tuple)) else [decl]):
            if not isinstance(spec, dict) or not spec.get('fn'):
                continue
            listo = spec.get('ready')
            if callable(listo):
                try:
                    if not listo(wa):
                        continue
                except Exception:  # pylint: disable=broad-except
                    continue
            fuera.append({'id': str(spec.get('id') or ''), 'package': pkg,
                          'label_key': str(spec.get('label_key') or ''),
                          'tooltip_key': str(spec.get('tooltip_key') or ''),
                          'icon': str(spec.get('icon') or ''),
                          'variant': str(spec.get('variant') or 'secondary'),
                          'perm': str(spec.get('perm') or ''),
                          'fn': str(spec.get('fn') or ''),
                          # Dónde va: en la barra de la lista (por defecto) o dentro de la ficha
                          # de UNA fila. Lo segundo es otro acto — «atar ESTA a una de fuera»— y
                          # su `fn` recibe cuál, así que la pantalla tiene que poder separarlos.
                          'link': bool(spec.get('link')),
                          'order': int(spec.get('order') or 0)})
    return sorted(fuera, key=lambda a: (a['order'], a['label_key'], a['id']))


def declared_by_id(const: str, **kw) -> dict:
    """``{id: descriptor}`` de todo paquete que declare *const*, con su paquete dentro.

    La forma que tienen los catálogos pequeños —de dónde vino una fila, qué iconos y qué texto
    lleva—: descriptores con un `id` y lo justo para dibujarlos. El primero que declara un `id`
    se lo queda, que es la regla de :func:`scan` para todo lo demás.
    """
    out: dict = {}
    for pkg, decl in scan(const, **kw):
        for spec in (decl if isinstance(decl, (list, tuple)) else [decl]):
            if not isinstance(spec, dict):
                continue
            ident = str(spec.get('id') or '').strip()
            if ident and ident not in out:
                out[ident] = dict(spec, id=ident, package=pkg)
    return out
