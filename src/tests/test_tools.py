#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para lib/util/tools.py — bytes2human, fmt_bytes/to_bytes y la regla de que hay
UN solo formateador de tamaños en el proyecto."""

import glob
import io
import os

from lib.util.tools import bytes2human

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBytes2Human:

    def test_bytes(self):
        assert bytes2human(0) == "0B"

    def test_bytes_small(self):
        assert bytes2human(100) == "100B"

    def test_kilobytes(self):
        assert bytes2human(1024) == "1.0K"

    def test_kilobytes_fraction(self):
        assert bytes2human(1536) == "1.5K"

    def test_megabytes(self):
        assert bytes2human(1048576) == "1.0M"

    def test_gigabytes(self):
        assert bytes2human(1073741824) == "1.0G"

    def test_terabytes(self):
        assert bytes2human(1099511627776) == "1.0T"

    def test_large_gigabytes(self):
        # 10 GB
        result = bytes2human(10 * 1073741824)
        assert result == "10.0G"

    def test_just_under_1k(self):
        assert bytes2human(1023) == "1023B"

    def test_exactly_2k(self):
        assert bytes2human(2048) == "2.0K"

    def test_mixed_megabytes(self):
        # 1.5 MB
        assert bytes2human(1572864) == "1.5M"


class TestFmtBytes:
    """The formatter actually used in alert messages and on the Status bar. Its spaced,
    two-letter form (unlike bytes2human's compact one) is what users read, so the format
    is behaviour, not cosmetics."""

    def test_zero_is_bytes(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(0) == '0 B'

    def test_bytes_have_no_decimals(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(512) == '512 B'

    def test_a_gigabyte(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(1024 ** 3) == '1.0 GiB'

    def test_a_fraction_keeps_one_decimal(self):
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(1536 * 1024 ** 2) == '1.5 GiB'

    def test_it_scales_the_whole_ladder(self):
        """A formatter that caps does not say "too big" — it prints "2097152.0 PB",
        which is worse than useless in an alert. It must reach as far as bytes2human."""
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(2 * 1024 ** 5) == '2.0 PiB'
        assert fmt_bytes(2 * 1024 ** 6) == '2.0 EiB'
        assert fmt_bytes(2 * 1024 ** 7) == '2.0 ZiB'
        assert fmt_bytes(2 * 1024 ** 8) == '2.0 YiB'

    def test_beyond_the_ladder_it_degrades_in_the_last_unit(self):
        """Nothing sane reaches here; it must still render rather than loop or crash."""
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(1024 ** 10).endswith(' YiB')

    def test_it_reaches_as_far_as_bytes2human(self):
        """The shared helper must not be LESS capable than the older one it supersedes —
        that is how a consolidation quietly loses something."""
        from lib.util.tools import bytes2human, fmt_bytes
        for power in range(1, 9):
            n = 2 * 1024 ** power
            # Same unit letter, different presentation ('2.0Y' vs '2.0 YiB').
            assert bytes2human(n)[-1] == fmt_bytes(n).split()[-1][0]

    def test_a_non_number_formats_rather_than_raising(self):
        """A monitoring message must render even when the API answered something odd."""
        from lib.util.tools import fmt_bytes
        assert fmt_bytes(None) == '0 B'
        assert fmt_bytes('abc') == '0 B'


class TestToBytes:
    """The inverse, for configured thresholds: the admin types a number and picks a unit."""

    def test_each_unit(self):
        from lib.util.tools import to_bytes
        assert to_bytes(2, 'GB') == 2 * 1024 ** 3
        assert to_bytes(1, 'TB') == 1024 ** 4
        assert to_bytes(4, 'MB') == 4 * 1024 ** 2

    def test_the_unit_is_case_insensitive(self):
        from lib.util.tools import to_bytes
        assert to_bytes(1, 'gb') == 1024 ** 3

    def test_a_blank_value_is_zero(self):
        from lib.util.tools import to_bytes
        assert to_bytes('', 'GB') == 0
        assert to_bytes(None, 'GB') == 0

    def test_an_unknown_unit_reads_as_gb(self):
        """Rejecting it would silently turn the threshold into 0 — disabling the very
        alert it was meant to raise."""
        from lib.util.tools import to_bytes
        assert to_bytes(1, 'parsecs') == 1024 ** 3
        assert to_bytes(1, '') == 1024 ** 3


class TestTheLabelSaysWhichBaseItIs:
    """It printed "GB" while dividing by 1024 — the Windows convention, and genuinely
    ambiguous: the same three characters mean 1000000000 on the box a disk came in. Asked
    directly ("so one works in bits and the other in bytes?"), which is exactly the doubt a
    mislabelled unit creates. The scale did not change; the suffix now names it.
    """

    def test_the_suffix_is_iec(self):
        from lib.util import fmt_bytes
        assert fmt_bytes(1024) == '1.0 KiB'
        assert fmt_bytes(1024 ** 4) == '1.0 TiB'
        assert 'GB' not in fmt_bytes(1024 ** 3), 'the ambiguous label is back'

    def test_bytes_keep_the_plain_B(self):
        """There is no "BiB" — below the first division the two conventions agree."""
        from lib.util import fmt_bytes
        assert fmt_bytes(512) == '512 B'
        assert fmt_bytes(0) == '0 B'


class TestThresholdsSavedBeforeTheRenameStillMeanTheSame:
    """The values were always binary; only the label was wrong. A threshold an admin saved as
    "100 GB" has to go on being the same number of bytes — anything else silently moves a
    limit they set themselves.
    """

    def test_the_old_spellings_still_convert(self):
        from lib.util import to_bytes
        assert to_bytes(100, 'GB') == to_bytes(100, 'GiB') == 100 * 1024 ** 3
        assert to_bytes(2, 'TB') == to_bytes(2, 'TiB') == 2 * 1024 ** 4

    def test_the_round_trip_holds(self):
        """The property the two functions exist to keep between them: what the admin typed is
        what they are shown. If one scaled by 1024 and the other by 1000, "100 GiB" would read
        back as "107.4 GiB" and drift every time they looked at it."""
        from lib.util import fmt_bytes, to_bytes
        for value, unit in ((100, 'GiB'), (100, 'GB'), (4, 'MB'), (2, 'TiB')):
            assert fmt_bytes(to_bytes(value, unit)).startswith(f'{value}.0 ')

    def test_the_old_names_are_read_but_never_written(self):
        from lib.util import fmt_bytes
        from lib.util.tools import normalize_unit
        assert normalize_unit('GB') == 'GiB'
        assert normalize_unit('gb') == 'GiB'
        assert normalize_unit('GiB') == 'GiB'
        produced = {fmt_bytes(1024 ** i).split()[-1] for i in range(1, 6)}
        assert not produced & {'KB', 'MB', 'GB', 'TB', 'PB'},             f'a legacy label is being produced: {produced}'

    def test_an_unknown_unit_is_not_silently_zero(self):
        """A threshold that became 0 would disable the alert it was meant to raise."""
        from lib.util import to_bytes
        assert to_bytes(1, 'nonsense') == 1024 ** 3


class TestStoredUnitsAreMigratedBeforeTheyReachADropdown:
    """The dropdown now offers MiB/GiB/TiB, and stored config still says GB.

    A `<select>` whose value is not among its options displays the FIRST one. So opening an
    m365 item and saving it — without touching the threshold — would write back the first
    option: a 100 GB limit becomes 100 MiB, a thousandfold change made by looking at a page.
    Migrating on the way out is what keeps that from happening.
    """

    def test_it_rewrites_unit_fields_at_any_depth(self):
        from lib.core.modules.service import normalize_unit_fields
        data = {'m365': {'list': {'U1': {
            'site_free_min': 100, 'site_free_unit': 'GB',
            'nested': {'tenant_capacity_unit': 'TB'},
        }}}}
        normalize_unit_fields(data)
        item = data['m365']['list']['U1']
        assert item['site_free_unit'] == 'GiB'
        assert item['nested']['tenant_capacity_unit'] == 'TiB'

    def test_it_leaves_the_number_alone(self):
        """Only the spelling was wrong. Touching the value would move the threshold."""
        from lib.core.modules.service import normalize_unit_fields
        data = {'m365': {'list': {'U1': {'site_free_min': 100, 'site_free_unit': 'GB'}}}}
        normalize_unit_fields(data)
        assert data['m365']['list']['U1']['site_free_min'] == 100

    def test_it_only_touches_unit_fields(self):
        """Driven by the `_unit` suffix, so a module adding a threshold later is covered
        without this having to know about it — and nothing else is."""
        from lib.core.modules.service import normalize_unit_fields
        data = {'m': {'list': {'U1': {'label': 'GB', 'note': 'TB', 'x_unit': 'GB'}}}}
        normalize_unit_fields(data)
        item = data['m']['list']['U1']
        assert item['label'] == 'GB' and item['note'] == 'TB', 'it rewrote ordinary text'
        assert item['x_unit'] == 'GiB'

    def test_an_already_migrated_value_is_untouched(self):
        from lib.core.modules.service import normalize_unit_fields
        data = {'m': {'list': {'U1': {'x_unit': 'GiB'}}}}
        normalize_unit_fields(data)
        assert data['m']['list']['U1']['x_unit'] == 'GiB'

    def test_the_dropdown_can_show_what_the_schema_offers(self):
        """End of the chain: every migrated value must exist among the schema's options, or
        the select is right back where it started."""
        import io as _io
        import json as _json
        import os as _os
        from lib.util.tools import normalize_unit
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        schema = _json.load(_io.open(_os.path.join(root, 'watchfuls', 'm365', 'schema.json'),
                                     encoding='utf-8'))
        seen = 0

        def walk(node):
            nonlocal seen
            if isinstance(node, dict):
                for key, val in node.items():
                    if str(key).endswith('_unit') and isinstance(val, dict):
                        opts = val.get('options') or []
                        seen += 1
                        assert val.get('default') in opts, f'{key}: default not in options'
                        for legacy in ('MB', 'GB', 'TB'):
                            if normalize_unit(legacy) in opts:
                                continue
                    walk(val)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        walk(schema)
        assert seen >= 4, 'the unit dropdowns are gone — this guard needs updating'


class TestThereIsOneByteFormatter:
    """`fmt_bytes` scales in 1024s. A browser-side formatter counting in 1000s would print a
    different size for the same number depending on which side of the wire formatted it —
    and the panel would be quietly inconsistent with its own alerts and Status bar, which is
    the kind of wrong that never gets reported as a bug, only doubted.

    Caught in review: a JS `formatBytes` had been written before anyone checked whether the
    project already answered this. It did.
    """

    def test_the_server_sends_the_formatted_size(self):
        src = io.open(os.path.join(SRC, 'lib', 'core', 'config', 'routes.py'),
                      encoding='utf-8').read()
        assert 'fmt_bytes(' in src, 'the response stopped carrying a formatted size'

    def test_the_browser_does_not_format_bytes_itself(self):
        """Not a style rule: the two would disagree on the same input."""
        import glob                                              # noqa: PLC0415
        pat = os.path.join(SRC, 'lib', 'web_admin', 'templates', '**', '*.html')
        for path in glob.glob(pat, recursive=True):
            body = io.open(path, encoding='utf-8', errors='replace').read()
            assert 'function formatBytes' not in body, \
                f'{os.path.basename(path)} defines a second byte formatter'
            # The ladder itself is the tell — a scaling loop needs the unit names.
            assert "['B', 'KB', 'MB'" not in body, \
                f'{os.path.basename(path)} scales byte units in the browser'

    def test_the_toast_prints_what_the_server_sent(self):
        body = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                    'cfg', '_db_maintenance.html'), encoding='utf-8').read()
        assert 'freed.freed_human' in body, 'the toast stopped printing the server\'s figure'
        # Strict `=== 0`, so "reclaimed nothing" is a different branch from "would not say".
        # A loose `== 0` matches null too, and the engine that refuses to disclose a size
        # would be reported as having freed nothing.
        assert 'bytes_freed === 0' in body, \
            'unknown is being treated as a number again — it would render as "freed nothing"'
