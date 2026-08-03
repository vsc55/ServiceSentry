#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config-section actions contributed by a package (self-describing discovery).

A provider declares its buttons as DATA (``CONFIG_ACTIONS``) and web_admin renders them
generically, so no package-specific glue lives in the panel. These tests pin the contract:
the descriptors are discovered, normalised, ordered, and surfaced on the config layout.
"""

from lib.config.config_actions import _normalize, actions_for, discover_config_actions
from lib.config.layout import config_layout
















class TestNothingInMaintenanceDeletesOnTheFirstClick:
    """Every one of these wipes a table. Asked directly — "do these have a confirmation?" —
    and the answer was yes for all six, but nothing was holding it that way: the button is
    declared in a manifest and the handler lives in another package's UI file, so the seventh
    action added is one where the two are never reviewed together.

    Two shapes count, and both are deliberate: a confirm dialog, or a modal that makes you
    CHOOSE what to delete (the history series picker — you cannot arrive at the delete
    without having selected a target).
    """

    def _handlers(self):
        card = next(c for c in config_layout()['cards'] if c['id'] == 'maintenance')
        return [(a['id'], a['fn']) for a in card['actions']
                if a.get('group_label_key') == 'cfg_actions_group_wipe']

    def test_every_wipe_asks_first(self):
        import glob                                                # noqa: PLC0415
        import io as _io                                           # noqa: PLC0415
        import os as _os                                           # noqa: PLC0415
        import re as _re                                           # noqa: PLC0415
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        pat = _os.path.join(root, 'lib', 'web_admin', 'templates', '**', '*.html')
        joined = '\n'.join(_io.open(p, encoding='utf-8', errors='replace').read()
                           for p in glob.glob(pat, recursive=True))
        for act_id, fn in self._handlers():
            m = _re.search(r'(?:async )?function ' + _re.escape(fn) + r'\([^)]*\)\s*\{(.*?)^\}',
                           joined, _re.S | _re.M)
            assert m, f'{act_id}: handler {fn}() does not exist — the button would throw'
            body = m.group(1)
            asks = ('showConfirmModal' in body or 'Confirm(' in body
                    or 'Modal' in body)     # a picker modal: you choose the target first
            assert asks, f'{act_id}: {fn}() deletes without asking'

    def test_the_database_actions_are_not_held_to_it(self):
        """Optimize changes no row and asks nothing on purpose — a prompt there would only
        teach people to click through prompts, right above the ones that matter. Compact does
        ask, because it locks the database while it rewrites."""
        import io as _io                                           # noqa: PLC0415
        import os as _os                                           # noqa: PLC0415
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        body = _io.open(_os.path.join(root, 'lib', 'web_admin', 'templates', 'partials',
                                      'cfg', '_db_maintenance.html'), encoding='utf-8').read()
        assert "warn: null" in body, 'optimize started warning about a lock it does not take'
        assert "warn: 'db_compact_warn'" in body,             'compact stopped warning that it holds the database while it rewrites'


