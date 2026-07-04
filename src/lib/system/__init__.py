#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local OS introspection layer.

Everything that reads the local machine, split in two concerns:

* **execution** — *how* a command runs locally: :mod:`lib.system.exe`
  (local/remote dispatch; the SSH transport itself lives in
  :mod:`lib.hosts.ssh_client`);
* **metric collectors** — *what* is read from the host: :mod:`lib.system.mem`
  / :mod:`lib.system.mem_info` (cross-platform RAM/SWAP via psutil) and the
  OS-specific collectors under :mod:`lib.system.linux` (RAID, thermal).

Kept import-light on purpose (no eager paramiko/psutil): the heavy submodules
are imported by whoever needs them.  Convenience symbols (``Exec``, ``Mem`` …)
remain re-exported from the package root :mod:`lib`.
"""
