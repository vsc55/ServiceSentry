#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backup domain: making a copy of this installation, and putting it back.

Where each thing lives, so the next reader does not have to grep for it:

* ``archive`` — what an archive IS: where it lives, how it is laid out, how a value goes in
  and comes back. The bottom of the package; it imports no sibling.
* ``parts`` — what a copy can hold, and which tables each part means. The vocabulary the copy
  and the restore both read, so neither can disagree with the other about `core`.
* ``create`` / ``restore`` — the two directions. Rows out through the connector, rows in.
* ``verify`` — a copy against its own checksums. Its own module because it is its own grant.
* ``locks`` — the ``.lock`` sidecar that keeps one copy whatever retention decides.
* ``service`` — the shelf: which copies exist, how big, from which build, and removing one.
* ``folders`` — the directory picker behind the backup-dir SETTING. Not backup code at all;
  it lives here because that field is the only thing it serves.
* ``schedule`` — pure functions for *when* a copy is due and which ones survive retention.
* ``runner`` — the thread, the tick and the lease. ``jobs`` — the copies and restores somebody
  is standing there waiting for, polled by job id.
* ``routes`` — the archives' endpoints. ``routes_schedule`` — the tasks and profiles, which
  are their own decision with their own permission.
* ``tasks_store`` / ``profiles_store`` — their rows. ``manifest`` — the domain's permissions
  and audit events.

Everything except the two `routes` modules is Flask-free: they are handed connectors and
paths, and they answer with data.
"""
