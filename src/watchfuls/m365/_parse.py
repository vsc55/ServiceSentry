#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful: reading what Graph answers
#
"""The report CSVs.

Graph answers usage questions with a **CSV report**, not JSON — so a number a threshold
can be compared against has to be dug out of a spreadsheet whose headers vary slightly
between reports and sometimes carry a BOM.

Byte formatting and unit conversion are NOT here: they are generic, and they live in
:mod:`lib.util.tools` (``fmt_bytes`` / ``to_bytes``) so nothing has to reinvent them.
"""

import csv
import io


def _csv_col(text: str, column: str):
    """``(rows, index)`` for *column* in a report CSV — the header lookup every reader here
    needs, done once.  ``index`` is -1 when the column is absent.

    Graph writes a BOM on some reports and spells a few headers slightly differently
    between them, so an exact match is tried first and a case-insensitive substring second.
    """
    rows = list(csv.reader(io.StringIO(text or '')))
    if len(rows) < 2:
        return rows, -1
    header = [h.strip().lstrip('﻿') for h in rows[0]]
    try:
        return rows, header.index(column)
    except ValueError:
        return rows, next((i for i, h in enumerate(header) if column.lower() in h.lower()), -1)


def _csv_int(row: list, idx: int) -> int:
    """One cell as an int (0 when missing or not a number).  The reports write integers as
    floats often enough (``1.0``) that ``int(...)`` alone would raise."""
    if idx < 0 or idx >= len(row):
        return 0
    try:
        return int(float(row[idx] or 0))
    except (TypeError, ValueError):
        return 0


def _csv_sum(text: str, column: str) -> int:
    """Sum of *column* across a report's data rows (0 if absent).

    The counterpart of :func:`_csv_max`, and the two are NOT interchangeable — which one is
    right depends on what the rows are. In a per-DAY report (tenant storage over ``D7``) the
    rows are the same quantity measured repeatedly, so summing would multiply it by seven.
    In a per-SITE report (site usage detail) each row is a different site, and the sum is the
    tenant's total.
    """
    rows, idx = _csv_col(text, column)
    if idx < 0:
        return 0
    return sum(_csv_int(r, idx) for r in rows[1:])


def _csv_max(text: str, column: str) -> int:
    """Largest integer value of *column* across a report CSV's data rows (0 if
    absent).  Tolerant of a BOM / slight header variations.

    The MAX rather than the last row: these reports cover a period (``D7``) and the rows
    are days, so the peak is the number worth alerting on.
    """
    rows = list(csv.reader(io.StringIO(text or '')))
    if len(rows) < 2:
        return 0
    header = [h.strip().lstrip('﻿') for h in rows[0]]
    try:
        idx = header.index(column)
    except ValueError:
        idx = next((i for i, h in enumerate(header) if column.lower() in h.lower()), -1)
    if idx < 0:
        return 0
    best = 0
    for r in rows[1:]:
        if idx < len(r):
            try:
                best = max(best, int(float(r[idx] or 0)))
            except (TypeError, ValueError):
                pass
    return best
