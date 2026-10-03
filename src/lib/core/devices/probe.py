#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Device-side support for the Servers "test" feature.

What is specific to devices is resolving an **unsaved** device: the modal tests what the admin
has typed, which by definition is not in the store yet.  Running the module's check itself
is not a device matter at all and lives in
:mod:`lib.modules.check_runner` — it moved there because the module pages needed the same
runner and were importing it from this domain package, which put a generic layer's
dependency on one domain.

Deliberately NOT re-exported from here.  A convenience import would keep the runner looking
like device code and let the next caller reach for it at this address, which is how it ended
up here in the first place.
"""

from __future__ import annotations


class ProbeDevicesStore:
    """Return a (possibly unsaved draft) device for its uid, else delegate.

    Lets the Servers modal test an edited/new device without first persisting it.
    """

    def __init__(self, draft: dict | None, real):
        self._draft = draft or None
        self._real = real

    def get(self, uid, **kw):
        if self._draft and uid == self._draft.get('uid'):
            return self._draft
        return self._real.get(uid, **kw) if self._real is not None else None
