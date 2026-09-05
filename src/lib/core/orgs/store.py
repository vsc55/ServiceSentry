#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The two tables: who the companies are, and what somebody SAID belongs to each.

**Why ownership is a table and not a column in n places.** The rule — say it where you like, it
inherits, the innermost wins — is ONE rule, and written as an ``org_uid`` column on every table
that can belong to somebody it is n implementations of it and n places to get it wrong. As a
table there is one resolver (:mod:`lib.core.orgs.owners`), and it admits scopes that live in
tables this package has never heard of: a host, a mailbox, a subscription.

**Nothing derived is stored.** What a rack inherits from its room is computed on the way out, so
the day somebody re-parents it there is no stale copy of what it used to inherit — a lie that
outlives the move.
"""

from __future__ import annotations

from lib.db import BaseConnector
from lib.db.rows import Rows
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

_ORG = TableSpec(
    name='org',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        # A short form for badges and elevations, where the full legal name of a company does
        # not fit in a box 200 pixels wide.
        Column('short',       'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_org_name', ('name',)),),
)

_OWNER = TableSpec(
    name='org_owner',
    columns=(
        # One row per ownership somebody DECLARED. Everything else is inherited, and inherited
        # ownership is never written down.
        Column('scope',   'TEXT', nullable=False),      # whatever a package declared
        Column('uid',     'TEXT', nullable=False),      # the thing that belongs to somebody
        Column('org_uid', 'TEXT', nullable=False),
        Column('set_at',  'TEXT', nullable=False, default="''"),
        Column('set_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_org_owner_scope', ('scope', 'uid'), unique=True),
             Index('idx_org_owner_org', ('org_uid',))),
)

SCHEMAS = (_ORG, _OWNER)

#: Where these two tables used to live, when companies were part of the physical inventory.
#: Kept as a pair rather than a rename in the schema because the move is a one-way copy and an
#: installation may be running both processes while it happens: a panel that has not restarted
#: yet still writes to the old name, and the copy below is idempotent on purpose.
_WAS = (('dc_org', 'org'), ('dc_owner', 'org_owner'))


class OrgsStore:
    """The company registry and the ownership table, over one connector.

    One store for both because every question that matters crosses them — "what belongs to this
    company", "whose is this", "what is left on nobody's name when this one goes" — and a caller
    holding two stores would be the one joining them.
    """

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self.orgs = Rows(db, _ORG)
        self.owners = Rows(db, _OWNER)
        self.orgs.bootstrap()
        self.owners.bootstrap()
        self._adopt()

    # ── Coming from the inventory ────────────────────────────────────────────

    def _adopt(self) -> None:
        """Take over ``dc_org``/``dc_owner`` if this installation still has them.

        Copied and not renamed: a rename is one statement that either finds the old table or
        raises, and it has to be right on three engines. A copy into an EMPTY table is the same
        result, is idempotent, and leaves the old rows where they are — which is what makes this
        recoverable if the move turns out to be wrong.

        Failure here is logged by the caller and never fatal. An installation that comes up with
        no companies is one screen short; one that does not come up at all is everything short.
        """
        for old, new in _WAS:
            try:
                if not self._db.table_exists(old):
                    continue
                rows = self._db.fetchall(f'SELECT COUNT(*) FROM {self._db.quote_ident(new)}')
                if rows and int(rows[0][0] or 0):
                    continue                    # already has its own, nothing to adopt
                cols = sorted(self._db.list_columns(old) & self._db.list_columns(new))
                if not cols:
                    continue
                names = ', '.join(self._db.quote_ident(c) for c in cols)
                self._db.execute(
                    f'INSERT INTO {self._db.quote_ident(new)} ({names}) '
                    f'SELECT {names} FROM {self._db.quote_ident(old)}')
                self._db.commit()
            except Exception:                   # pylint: disable=broad-except
                continue

    # ── Who is already called this ───────────────────────────────────────────

    def taken(self, col: str, value: str, skip: str = '') -> str:
        """The uid of the company already using this *value* in *col*, or ``''``.

        Compared **stripped and case-folded**, because two companies called "Amixalan" and
        "amixalan " are two rows and one company: the second one gets created by whoever types
        it a second time without looking, and from then on half the racks are filed under a name
        that does not appear in the dropdown they are looking at.

        Asked BEFORE writing rather than caught after: `org.name` has a unique index — the
        backstop — and an index does not answer in words. What it produces is an
        `IntegrityError`, which reaches a person as a 500 and a stack trace. Reported from the
        screen.

        Empty is never taken: a company with no short form is the normal case, and many of them
        are not a collision — which is also why `short` is checked here and has no unique index.
        """
        want = str(value or '').strip().casefold()
        if not want:
            return ''
        for row in self.orgs.list():
            if str(row.get('uid') or '') == str(skip or ''):
                continue
            if str(row.get(col) or '').strip().casefold() == want:
                return str(row.get('uid') or '')
        return ''

    # ── What was said ────────────────────────────────────────────────────────

    def said(self) -> dict:
        """Every declared ownership, as ``{(scope, uid): org_uid}``.

        One read for the whole picture, because the resolver runs per node and a query per node
        is the shape that makes a room of forty racks take a second to draw.
        """
        return {(str(r['scope']), str(r['uid'])): str(r['org_uid'])
                for r in self.owners.list()}

    def said_of(self, scope: str, uid: str) -> str:
        rows = self.owners.list('scope = ? AND uid = ?', (str(scope or ''), str(uid or '')))
        return str(rows[0]['org_uid']) if rows else ''

    def counts(self) -> dict:
        """``{org_uid: {scope: n}}`` — what each company has on its name, counted in SQL.

        What was SAID and not what is inherited: a site of subsidiary B with forty devices
        inside counts as one site, because the devices do not say it, they inherit it — counting
        them would be counting the same decision forty times.
        """
        sql = (f'SELECT org_uid, scope, COUNT(*) FROM {self._db.quote_ident("org_owner")} '
               f"WHERE org_uid <> '' GROUP BY org_uid, scope")
        out: dict = {}
        for row in (self._db.fetchall(sql) or ()):
            out.setdefault(str(row[0]), {})[str(row[1])] = int(row[2] or 0)
        return out

    # ── …and saying it ───────────────────────────────────────────────────────

    def set_owner(self, scope: str, uid: str, org_uid: str, *, actor: str = '') -> bool:
        """Say who owns something — or, with an empty *org_uid*, stop saying.

        Clearing is not "owned by nobody": it is back to inheriting, which is a different state
        and the one somebody wants when a rack stops being an exception.

        The scope is checked against what packages DECLARE (:mod:`lib.core.orgs.scopes`) rather
        than against a list written here: a list here is one the core would have to edit every
        time a package learns to own something, which is the core naming a domain.
        """
        from lib.core.orgs import scopes as org_scopes    # noqa: PLC0415  (cycle at import)
        scope, uid = str(scope or ''), str(uid or '')
        if not uid or not org_scopes.known(scope):
            return False
        self._db.execute('DELETE FROM org_owner WHERE scope = ? AND uid = ?', (scope, uid))
        if str(org_uid or ''):
            self._db.execute(
                'INSERT INTO org_owner (scope, uid, org_uid, set_at, set_by) '
                'VALUES (?, ?, ?, ?, ?)',
                (scope, uid, str(org_uid), BaseStore._now(), str(actor or '')))
        self._db.commit()
        self.owners._stamp()                    # noqa: SLF001  (its own table's stamp)
        return True

    def forget_scope(self, scope: str, uid: str) -> None:
        """Drop the ownership rows of something being deleted.

        Not a foreign key: this table deliberately spans scopes that live in different tables,
        and some of them are not in this database at all.
        """
        self._db.execute('DELETE FROM org_owner WHERE scope = ? AND uid = ?',
                         (str(scope or ''), str(uid or '')))
        self._db.commit()
        self.owners._stamp()                    # noqa: SLF001

    def forget_org(self, org_uid: str) -> None:
        """Un-file everything that was on a company's name, because the company is going.

        What was hers stops being on anybody's name — it does NOT get deleted, and it does not
        inherit from her either, since she no longer exists. Anything under something that still
        says an owner keeps inheriting that; the rest goes back to unclaimed, which is the state
        an installation starts in and the one every screen already draws.
        """
        self._db.execute('DELETE FROM org_owner WHERE org_uid = ?', (str(org_uid or ''),))
        self._db.commit()
        self.owners._stamp()                    # noqa: SLF001
