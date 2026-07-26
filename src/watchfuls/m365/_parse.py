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
