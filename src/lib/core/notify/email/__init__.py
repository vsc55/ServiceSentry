#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E-mail notification channel: the SMTP/Graph sender (``notify``) and the i18n
HTML/text templates (``templates``).  Kept import-light — the dispatcher pulls
these lazily, so importing this package does not drag in ``smtplib`` / ``requests``.
"""
