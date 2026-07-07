#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared query-arg parsing for the syslog routes (messages + drops)."""

from flask import request


def _int_arg(name, default=None):
    v = request.args.get(name, '')
    if v == '' or v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _multi_arg(name):
    """All non-empty string values for a repeated query arg (multi-select)."""
    return [v.strip() for v in request.args.getlist(name) if v.strip()]


def _multi_int_arg(name):
    """All integer values for a repeated query arg (multi-select)."""
    out = []
    for v in request.args.getlist(name):
        s = (v or '').strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except (TypeError, ValueError):
            pass
    return out


def _syslog_filters():
    """Filter dict shared by the list and stats endpoints. hostname/app/facility/
    severity accept multiple values (Ctrl+click multi-select in the UI)."""
    return {
        'source':   request.args.get('source', '').strip(),
        'host':     request.args.get('host', '').strip(),
        'hostname': _multi_arg('hostname'),
        'app':      _multi_arg('app'),
        'facility': _multi_int_arg('facility'),
        'severity': _multi_int_arg('severity'),
        'severity_max': _int_arg('severity_max'),
        'since':    _int_arg('since'),
        'until':    _int_arg('until'),
        'q':        request.args.get('q', '').strip(),
    }
