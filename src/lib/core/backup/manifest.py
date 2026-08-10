#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions and audit events the backup domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_backup',   # i18n key for the role-editor group heading
    'order': 150,                   # after audit (140): both are administration, not operation
    'permissions': (
        # Reading the list is separate from making one: a copy costs disk and reads every
        # table, so "can see what copies exist" is not "can make another".
        {'flag': 'backup_view',    'roles': ()},
        {'flag': 'backup_create',  'roles': ()},
        # Downloading is its OWN flag and not part of view. A copy leaves the machine as one
        # file that holds every credential in the install: whoever may fetch it holds the
        # install, which is a bigger grant than reading a list of names and dates.
        {'flag': 'backup_download', 'roles': ()},
        # Restoring overwrites tables wholesale — including users and roles, which is to say
        # it can hand the panel to whoever the copy says owns it.
        {'flag': 'backup_restore', 'roles': ()},
        {'flag': 'backup_delete',  'roles': ()},
    ),
}


AUDIT_EVENTS = [
    {'key': 'backup_created',  'severity': 'success'},
    {'key': 'backup_deleted',  'severity': 'danger'},
    {'key': 'backup_restored', 'severity': 'danger'},
    # Downloading is audited at the same weight as deleting, and for the same reason: the file
    # holds the whole install, so "who took a copy off this machine, and when" is a question
    # the log has to be able to answer.
    {'key': 'backup_downloaded', 'severity': 'warning'},
    # Making a folder from the picker. Muted: it creates an empty directory and
    # nothing else — the line exists so the trail explains where a path came from.
    {'key': 'backup_dir_created', 'severity': 'muted'},
]
