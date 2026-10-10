#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - the brand, as the panel reads it.
#
"""The name the panel shows and where each brand picture is — for the templates and routes."""

from __future__ import annotations

import os

from lib.core.brand import service as brand_svc


class _BrandMixin:
    """``_brand_name()``, ``_brand_src(slot)``, ``_brand_mime(slot)``, ``_brand_own(slot)``."""

    def _brand_meta(self) -> dict:
        store = getattr(self, '_brand_store', None)
        return store.meta() if store is not None else {}

    def _brand_name(self) -> str:
        """The name to show: ``SS_BRAND_NAME`` when the deployment fixed it, else what was saved
        in Configuración › Marca, else the product's. The stored config never carries env, so
        the override is laid over it here, as everywhere the web reads a field."""
        sec = dict(self._config_section('brand') if hasattr(self, '_config_section') else {})
        ov = getattr(self, '_env_override_values', None) or {}
        if 'brand|name' in ov:
            sec['name'] = ov['brand|name']
        return brand_svc.display_name({'brand': sec})

    def _brand_own(self, slot: str) -> bool:
        """Whether a slot shows the installation's own picture rather than the shipped one."""
        return slot in self._brand_meta()

    def _brand_mime(self, slot: str) -> str:
        own = self._brand_meta().get(slot)
        if own:
            return own['mime']
        return brand_svc.MIME.get(brand_svc.default_kind(slot), 'application/octet-stream')

    def _brand_src(self, slot: str) -> str:
        """The URL of a slot's picture, versioned: by its ``sha`` when it is the installation's
        own, by the shipped file's date when it is not. Either way a browser may keep it for a
        year and still ask again the moment it changes."""
        own = self._brand_meta().get(slot)
        if own:
            v = own['sha'][:16]
        else:
            try:
                v = 'd%d' % int(os.path.getmtime(brand_svc.default_file(slot)))
            except OSError:
                v = 'd0'
        return f'/brand/{slot}?v={v}'
