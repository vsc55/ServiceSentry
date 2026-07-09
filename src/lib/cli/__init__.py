#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot CLI management commands (user/group administration + service status/reload).

Wired from ``main.py`` via argparse subcommands. The command handlers live in
:mod:`lib.cli.commands`; they run against a lightweight, headless store context
(:class:`lib.cli.context.CliContext`) — no Flask, no WebAdmin, no daemon threads — and
reuse the canonical operations in :mod:`lib.core.users.service` /
:mod:`lib.core.groups.service` (the same logic the web routes use).
"""
