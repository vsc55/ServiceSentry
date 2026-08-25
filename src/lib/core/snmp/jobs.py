#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the SNMP package runs in the background, for the jobs screen.

Two kinds, and they live in two different modules because they are two different pieces of
work: compiling a MIB tree walks a directory of source files, and testing a profile talks to
a device. This translates both into the one shape the screen reads — here rather than in
either of them, because neither should have to know that a screen listing jobs exists.
"""

from __future__ import annotations


def live(_wa) -> list:
    """Every MIB compile and every profile test this process has in flight."""
    return _compiles() + _tests()


def _compiles() -> list:
    try:
        from .mibs.admin import _compile_jobs      # noqa: PLC0415
    except Exception:                              # pylint: disable=broad-except
        return []
    out = []
    for jid, job in list(_compile_jobs.items()):
        failed = bool(job.get('failed')) and not job.get('compiled')
        out.append({
            'id': jid, 'kind': 'mib_compile',
            'label': str(job.get('current') or ''),
            'detail': str(job.get('phase') or ''),
            'state': ('failed' if failed or job.get('result_ok') is False else 'done')
                     if job.get('done') else 'running',
            'started': float(job.get('_started') or 0),
            'done': int(job.get('completed') or 0), 'total': int(job.get('total') or 0),
            'error': str(job.get('message') or ''),
            # What it is on now, and what did not make it. A compile of three thousand files
            # has no useful checklist while it runs — the bar is the answer — but the ones
            # that FAILED are the reason anybody opens it.
            'steps': ([{'state': 'running', 'text': str(job.get('current') or '')}]
                      if job.get('current') and not job.get('done') else [])
                     + [{'state': 'failed', 'text': str(f)}
                        for f in (job.get('failed') or ())],
        })
    return out


def _tests() -> list:
    try:
        from .actions import _test_jobs            # noqa: PLC0415
    except Exception:                              # pylint: disable=broad-except
        return []
    out = []
    for jid, job in list(_test_jobs.items()):
        steps = getattr(job.get('steps'), 'steps', None) or []
        result = job.get('result') or {}
        done = len([s for s in steps if str(getattr(s, 'state', '') or
                                            (s.get('state') if isinstance(s, dict) else ''))
                    not in ('', 'running', 'pending')])
        out.append({
            'id': jid, 'kind': 'snmp_test',
            'label': str(getattr(job.get('steps'), 'host', '') or ''),
            'detail': '',
            'state': ('done' if result.get('ok') else 'failed') if job.get('done')
                     else 'running',
            'started': float(job.get('_started') or 0),
            'done': done, 'total': len(steps),
            'error': '' if result.get('ok') else str(result.get('message') or ''),
            'steps': [_step_of(s) for s in steps],
        })
    return out


#: The test's own step vocabulary, as the words the jobs screen colours.
_TEST_STATE = {'ok': 'ok', 'pass': 'ok', 'fail': 'failed', 'error': 'failed',
               'running': 'running', 'pending': 'pending'}


def _step_of(step) -> dict:
    """One step of a profile test, whichever shape it is kept in."""
    get = (step.get if isinstance(step, dict) else lambda k, d=None: getattr(step, k, d))
    return {'state': _TEST_STATE.get(str(get('state', '') or ''), ''),
            'text': str(get('label', '') or get('name', '') or get('text', '') or '')}
