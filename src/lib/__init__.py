#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" Lib package. """

# One build per commit: the semantic version stays 0.0.1 until there are real releases, and
# the counter after '+' is semver build metadata.  It MUST match the newest section heading
# in CHANGELOG.md — tests/test_version_changelog.py fails the build when they drift, because
# a version that lies about what is running is worse than no version at all.
__version__ = '0.0.1+build.32'

from lib.util.dict_files_path import DictFilesPath
from lib.system.exe import Exec, ExecResult
from lib.system.mem import Mem
from lib.system.mem_info import MemInfo
from lib.services.monitoring.monitor import Monitor
from lib.core.object_base import ObjectBase

__all__ = [
    '__version__',
    'ObjectBase',
    'DictFilesPath',
    'Monitor',
    'Exec',
    'ExecResult',
    'Mem',
    'MemInfo'
]
