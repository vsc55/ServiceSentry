#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host/OS interaction layer.

Everything that touches the machine being monitored, split in two concerns:

* **execution / transport** — *how* a command runs: :mod:`lib.system.exe`
  (local/remote dispatch) and :mod:`lib.system.ssh_client` (SSH transport);
* **metric collectors** — *what* is read from the host: :mod:`lib.system.mem`
  / :mod:`lib.system.mem_info` (cross-platform RAM/SWAP via psutil) and the
  OS-specific collectors under :mod:`lib.system.linux` (RAID, thermal).

Kept import-light on purpose (no eager paramiko/psutil): the heavy submodules
are imported by whoever needs them.  Convenience symbols (``Exec``, ``Mem`` …)
remain re-exported from the package root :mod:`lib`.
"""
