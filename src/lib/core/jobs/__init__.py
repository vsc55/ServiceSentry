#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this process is doing right now, and nobody could see.

A panel that polls forty machines, copies a database, compiles a MIB tree and tests a
profile does all four in background threads — and until this package there was nowhere to
look at them. Each one kept its own dict of jobs in its own module, each with its own
shape, each polled by the one screen that started it. Start a collection, navigate away,
and the work carried on with no way back to it; start a backup from another tab and the
first tab never knew.

**The core names nobody.** A package that runs work in the background declares it in its
own manifest (``BACKGROUND_JOBS``) and this one collects whatever is declared, exactly the
way permissions, overview widgets and notify events already work (:mod:`lib.discovery`).
Adding a fifth kind of job is a line in that package's manifest, not an edit here.

What a declaration hands back is described in :func:`lib.core.jobs.service.live`.
"""
