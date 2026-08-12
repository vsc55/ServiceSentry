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
        # Checking a copy against its own checksums. Separate from `view` because it is not
        # reading a list: it walks every member of a multi-gigabyte archive and hashes it, so
        # it is minutes of disk and CPU that anybody who can see the section could otherwise
        # start, as often as they liked.
        {'flag': 'backup_verify',  'roles': ()},
        {'flag': 'backup_create',  'roles': ()},
        # Downloading is its OWN flag and not part of view. A copy leaves the machine as one
        # file that holds every credential in the install: whoever may fetch it holds the
        # install, which is a bigger grant than reading a list of names and dates.
        {'flag': 'backup_download', 'roles': ()},
        # Restoring overwrites tables wholesale — including users and roles, which is to say
        # it can hand the panel to whoever the copy says owns it.
        {'flag': 'backup_restore', 'roles': ()},
        {'flag': 'backup_delete',  'roles': ()},
        # The SCHEDULE, which is a different decision from taking a copy: who says how often
        # this install is protected, and for how long its copies are kept. It rode on
        # `backup_create` and `backup_delete`, and those are about archives — a task edited to
        # run monthly instead of daily destroys no file and quietly reduces the protection,
        # and deleting a task stops the copies without deleting a single one.
        #
        # "Run now" is deliberately NOT here: running a task makes a copy, which is
        # `backup_create` — the same thing the Create button does, and one grant should not be
        # two ways to the same result.
        {'flag': 'backup_schedule', 'roles': ()},
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
    # A schedule changing is worth a line: a task edited to run monthly instead of daily is a
    # decision somebody made, and the copies that stop appearing are its consequence.
    {'key': 'backup_task_saved', 'severity': 'warning'},
    {'key': 'backup_task_deleted', 'severity': 'danger'},
    # A shared retention profile changing is a schedule change made in several places at once:
    # every task that follows it now keeps a different amount of history. Same weight as editing
    # one task, because that is what it is — times however many follow it, which the line names.
    {'key': 'backup_profile_saved', 'severity': 'warning'},
    {'key': 'backup_profile_deleted', 'severity': 'warning'},
    # Locking a copy and unlocking it, under one key. The interesting case is somebody removing
    # a protection another person put there, and one key keeps both sides of that in a single
    # filter — the detail says which way it went.
    {'key': 'backup_locked', 'severity': 'warning'},
    # The one-off carry-over of the pre-task settings. Muted because nothing was decided here —
    # but recorded, because a task nobody created appearing in the list needs an explanation.
    {'key': 'backup_task_migrated', 'severity': 'muted'},
    # Checking a copy. Muted when it passes is not an option: the interesting case is
    # the one that did not, and a single severity keeps both findable in one filter.
    {'key': 'backup_verified', 'severity': 'warning'},
    # A size ceiling, not the calendar, decided what survives — which means the policy asks for
    # more history than there is room for, and the copies lost are ones the rules wanted to
    # keep. Warning and not muted: it is a decision somebody should get to revisit rather than
    # discover later as a gap in the history.
    {'key': 'backup_budget_exceeded', 'severity': 'warning'},
]

NOTIFY_EVENTS = [
    # Off by default like every dynamic key in the matrix: an operator who wants to hear about
    # a full backup folder says so, and one who does not is not woken by it.
    {'key': 'backup_budget_exceeded', 'source': 'backup',
     'label_key': 'notif_event_backup_budget', 'matrix': True, 'order': 80},
]
