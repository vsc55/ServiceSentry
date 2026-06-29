#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web administration package for ServiceSentry.

``WebAdmin`` is exposed lazily (PEP 562): importing a lightweight submodule such
as :mod:`lib.i18n` — which the Flask-free notification subsystem
(:mod:`lib.notify`) pulls for e-mail templates — must NOT drag in the whole
Flask app.  ``from lib.web_admin import WebAdmin`` keeps working on demand.
"""

__all__ = ['WebAdmin']


def __getattr__(name):
    if name == 'WebAdmin':
        from lib.web_admin.app import WebAdmin  # noqa: PLC0415
        return WebAdmin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
