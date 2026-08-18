#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" Lib package. """

# One build per commit: the semantic version stays 0.0.1 until there are real releases, and
# the counter after '+' is semver build metadata.  It MUST match the newest section heading
# in CHANGELOG.md — tests/test_version_changelog.py fails the build when they drift, because
# a version that lies about what is running is worse than no version at all.
__version__ = '0.0.1+build.80'

# The product's name, in ONE place. Everything that SIGNS something with it reads it from here:
# the pages, the emails, the Teams cards, the User-Agent, the diagnostics report. It was spelt
# out in fifty-odd string literals across twenty-eight files, so renaming meant finding all of
# them and noticing none was a translated sentence or somebody else's lookup key.
#
# Two kinds of occurrence deliberately do NOT read this, and a guard
# (`tests/unit/test_app_name.py`) knows about both:
#
#   * **identifiers registered in another system** — the Entra app display names in
#     `providers/entraid/declarations.py` (already a single source of their own) and the
#     Proxmox role and user in `watchfuls/proxmox/provision.py`. Those are looked up BY name in
#     a tenant we do not own: deriving them here would mean a rename silently stops finding the
#     app it registered last year and registers a second one beside it.
#   * **translated prose** (`lib/i18n/lang/*.py`), where the name sits inside a sentence that
#     has to be re-read in every language when it changes anyway.
#
# Declared ABOVE the submodule imports below, like `__version__`: a module imported while this
# package is still initialising can still read it.
APP_NAME = 'ServiceSentry'

from lib.util.dict_files_path import DictFilesPath
from lib.system.exe import Exec, ExecResult
from lib.system.mem import Mem
from lib.system.mem_info import MemInfo
from lib.services.monitoring.monitor import Monitor
from lib.core.object_base import ObjectBase

__all__ = [
    '__version__',
    'APP_NAME',
    'ObjectBase',
    'DictFilesPath',
    'Monitor',
    'Exec',
    'ExecResult',
    'Mem',
    'MemInfo'
]
