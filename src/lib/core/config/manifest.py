#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the config domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_config',
    'order': 190,
    'permissions': (
        {'flag': 'config_view', 'roles': ('editor',)},  # read config.json
        {'flag': 'config_edit', 'roles': ('editor',)},  # write config.json
        # Its own flag, granted to nobody by default, rather than riding on config_edit:
        # compacting takes the database offline for as long as the rewrite lasts (VACUUM FULL
        # locks every table on PostgreSQL; OPTIMIZE TABLE rebuilds on InnoDB). Editing a
        # setting and freezing the panel are not the same authority, and the roles that need
        # the first should not silently acquire the second.
        {'flag': 'db_maintenance', 'roles': ()},        # optimize / compact the database
    ),
}


# Database maintenance lives in Config → General → Maintenance, beside the data wipes but
# NOT among them: these two reclaim and re-measure, they never delete a record. The section
# groups them apart for exactly that reason — the two kinds of action there have opposite
# consequences, and a row of identical red buttons said otherwise.
CONFIG_ACTIONS = [
    {'section': 'maintenance', 'id': 'db_optimize',
     'label_key': 'db_optimize', 'tooltip_key': 'db_optimize_tt',
     'desc_key': 'db_optimize_desc',
     'icon': 'bi-speedometer2', 'variant': 'primary', 'order': 1,
     'group_label_key': 'cfg_actions_group_db', 'perm': 'db_maintenance',
     'fn': '_dbOptimize'},
    {'section': 'maintenance', 'id': 'db_compact',
     'label_key': 'db_compact', 'tooltip_key': 'db_compact_tt',
     'desc_key': 'db_compact_desc',
     'icon': 'bi-file-zip', 'variant': 'warning', 'order': 2,
     'group_label_key': 'cfg_actions_group_db', 'perm': 'db_maintenance',
     'fn': '_dbCompact'},
    # With the DELETIONS and not with the two above, which is where it belongs by what it
    # does rather than by which package ships it: those two reclaim space and re-measure and
    # destroy no record, this one removes readings. Grouping it with them would have put a
    # delete under the heading that says "these never delete anything" — the exact confusion
    # the two groups exist to prevent, and the guard for it caught this.
    #
    # It opens on what it FOUND rather than on a confirmation: the number is the decision,
    # and a red button over an unknown quantity is one nobody should press.
    {'section': 'maintenance', 'id': 'db_orphans',
     'label_key': 'db_orphans', 'tooltip_key': 'db_orphans_tt',
     'desc_key': 'db_orphans_desc',
     'icon': 'bi-eraser', 'variant': 'danger', 'order': 60,
     'button_key': 'act_wipe', 'group_label_key': 'cfg_actions_group_wipe',
     'perm': 'db_maintenance', 'fn': '_dbOrphans'},
]


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import webhooks_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'webhooks', 'icon': 'bi-broadcast', 'label_key': 'overview_webhooks',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 80,
     'perms': {'any': ['config_view', 'config_edit']}, 'nav': {'tab': '#tab-config'},
     'stat': webhooks_stat,
     'view': {'kind': 'stat', 'icon': 'bi-broadcast', 'label_key': 'overview_webhooks',
              'accent': 'purple', 'data_url': '/api/v1/overview/widget/webhooks'}},
]


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'config_saved', 'severity': 'info'},
    # Maintenance reclaims space and re-measures; it destroys no record. Muted on purpose —
    # painting it red would make the colour mean "maintenance" rather than "data is gone",
    # and then it would mean nothing.
    {'key': 'db_optimized', 'severity': 'muted'},
    {'key': 'db_compacted', 'severity': 'muted'},
    # …and this one is NOT muted: it is the one action here that removes readings, and "why
    # is there no history before Tuesday" is a question this line answers.
    {'key': 'db_orphans_purged', 'severity': 'warning'},
]
