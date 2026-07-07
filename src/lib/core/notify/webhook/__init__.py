#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Outgoing webhook channel: the sender (``notify``) and the registry of configured
endpoints (``store`` — :class:`WebhooksStore`).  Kept import-light — the dispatcher
pulls the sender lazily.
"""
