#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification routes: Telegram, Email, Webhook, Templates."""

from . import templates


def register(app, wa):
    """Register all notification sub-routes."""
    templates.register(app, wa)
