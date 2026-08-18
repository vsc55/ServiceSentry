#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the world says about the versions this install is running.

Two questions the machine cannot answer about itself — *is there a newer release of this
package* and *does the version installed have a known vulnerability* — and therefore the
second thing in this domain that reaches outside. It follows the same two rules as
:mod:`update`, for the same reasons:

* **it never happens on its own.** No poll, no check at boot, and nothing while the page
  paints. The diagnostics page is opened by somebody on a segregated network precisely when
  something is already wrong, and a page that contacts pypi.org because it was opened is a bug
  report you cannot argue with. It runs when a person presses a button, and the button is
  audited.
* **it cannot cost anything.** Short timeouts, a bounded number of connections, no redirect
  chasing, and every failure is a sentence on screen rather than an exception — including the
  partial ones: a package PyPI does not answer for is one unknown cell, not a lost report.

**Two sources, two shapes.** PyPI has no batch endpoint, so "newest published" is one small
request per package, run in a small pool. OSV.dev does have one, so every vulnerability
question travels in a single request — which is also why the vulnerability half keeps working
on an install where pypi.org is blocked and the other half does not.

The package list is built HERE from the lock and the installed set. Never taken from the
request: a client that could name the packages could make this panel query an outside service
for anything it liked, and "the diagnostics page as an open proxy" is not a trade worth making
for a list the server already has.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import urllib.error
import urllib.request

from lib import APP_NAME

# Both are asked over HTTPS or not at all: these answers decide what an operator upgrades, and
# a downgraded request is one somebody else gets to answer.
PYPI_URL = 'https://pypi.org/pypi/{name}/json'
OSV_BATCH_URL = 'https://api.osv.dev/v1/querybatch'

TIMEOUT = 6.0
# PyPI's per-project document carries EVERY release and every file in it: `cryptography` is
# 3.1 MB of it. A cap of one megabyte truncated eight of the forty packages here, and a
# truncated body is not JSON — so they reported `not_json` and the table said "—" for the
# biggest, most interesting packages in the lock while looking like a clean answer.
MAX_BODY = 16 << 20
# Enough to keep forty small requests short, low enough that a panel does not open a fan of
# connections at somebody's proxy. The pool is the reason this is a button and not a page load.
WORKERS = 8
# A name that reaches PyPI as a path segment. Anything outside it is not a package name, and
# the check is here rather than at the call site because this module builds the URL.
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
_NUM_RE = re.compile(r'\d+')

# The package's page on PyPI, pinned to the version being announced — where the release, its
# description and its links are. Built HERE from two strings and never read out of the answer:
# PyPI also carries a `project_urls` map with whatever the project chose to put in it, and
# rendering one of those as a link somebody clicks inside the panel would let the package
# choose the destination. This way there is nothing from outside to validate.
PYPI_PROJECT_URL = 'https://pypi.org/project/{name}/{version}/'


# Where an advisory is written up. Same source that answered the question — OSV serves a page
# per identifier, GHSA, PYSEC and CVE alike — so a count somebody cannot act on becomes a list
# they can read. Built here for the same reason the PyPI link is: the identifier arrives from
# the network, and a URL assembled in the browser from whatever came back is a destination
# somebody else gets to choose.
OSV_VULN_URL = 'https://osv.dev/vulnerability/{vid}'
# What an advisory identifier looks like. It becomes a path segment, so anything else is not one.
_ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9._-]{2,63}$')


def project_url(name: str, version: str) -> str:
    """Where to read about a release: its own page on PyPI, which always exists."""
    return PYPI_PROJECT_URL.format(name=name, version=version) if (name and version) else ''


def advisory_url(vid: str) -> str:
    """Where an advisory is written up, or empty for an identifier that is not one."""
    return OSV_VULN_URL.format(vid=vid) if _ID_RE.match(str(vid or '')) else ''


# ── How bad each one is ──────────────────────────────────────────────────────
#
# The batch answers identifiers and nothing else, so severity is one more request per DISTINCT
# advisory — the record, not the package. Distinct is what makes it affordable: the same
# advisory lands on several packages and is fetched once.
#
# **Nothing here is this panel's opinion.** Either the database published a rating and that is
# what is shown, or it published a CVSS vector and the base score is the arithmetic the
# standard defines for it. A severity invented here would be a number somebody has to trust,
# on the page whose whole job is not to produce those.

OSV_VULN_API = 'https://api.osv.dev/v1/vulns/{vid}'
# A ceiling on the second round of requests. Reaching it means an install with sixty distinct
# advisories, where the column is not the thing to fix first.
MAX_DETAILS = 60

# CVSS 3.x base metrics, as the specification weights them.
_CVSS_W = {
    'AV': {'N': 0.85, 'A': 0.62, 'L': 0.55, 'P': 0.2},
    'AC': {'L': 0.77, 'H': 0.44},
    'UI': {'N': 0.85, 'R': 0.62},
    'C': {'H': 0.56, 'L': 0.22, 'N': 0.0},
    'I': {'H': 0.56, 'L': 0.22, 'N': 0.0},
    'A': {'H': 0.56, 'L': 0.22, 'N': 0.0},
}
# Privileges required is the one metric that depends on scope: a changed scope means the
# privilege was worth more.
_CVSS_PR = {False: {'N': 0.85, 'L': 0.62, 'H': 0.27},
            True: {'N': 0.85, 'L': 0.68, 'H': 0.50}}
# The qualitative bands, and the order the screen sorts by.
RATINGS = ('none', 'low', 'moderate', 'high', 'critical')


def _roundup(value: float) -> float:
    """One decimal, always upward — the specification's own rounding.

    Defined on integers on purpose: `math.ceil(x * 10) / 10` disagrees with the published
    scores on the vectors where the product lands a floating-point hair below a tenth.
    """
    scaled = int(round(value * 100000))
    if scaled % 10000 == 0:
        return scaled / 100000.0
    return (scaled // 10000 + 1) / 10.0


def cvss_score(vector: str):
    """The CVSS 3.x base score of a vector string, or None when it is not one.

    Arithmetic from the published metrics, not a judgement: the vector says what the exposure
    is and the specification says what that scores.
    """
    text = str(vector or '')
    if not text.upper().startswith('CVSS:3'):
        return None
    parts = {}
    for chunk in text.split('/')[1:]:
        key, _sep, val = chunk.partition(':')
        parts[key.strip().upper()] = val.strip().upper()
    try:
        changed = parts['S'] == 'C'
        av, ac, ui = (_CVSS_W['AV'][parts['AV']], _CVSS_W['AC'][parts['AC']],
                      _CVSS_W['UI'][parts['UI']])
        pr = _CVSS_PR[changed][parts['PR']]
        conf, integ, avail = (_CVSS_W['C'][parts['C']], _CVSS_W['I'][parts['I']],
                              _CVSS_W['A'][parts['A']])
    except KeyError:
        return None
    iss = 1.0 - ((1.0 - conf) * (1.0 - integ) * (1.0 - avail))
    impact = (7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed
              else 6.42 * iss)
    if impact <= 0:
        return 0.0
    exploitability = 8.22 * av * ac * pr * ui
    total = impact + exploitability
    return _roundup(min(total * 1.08 if changed else total, 10.0))


def rating_of(score) -> str:
    """A base score as the band the specification names it by."""
    if score is None:
        return ''
    if score <= 0:
        return 'none'
    if score < 4.0:
        return 'low'
    if score < 7.0:
        return 'moderate'
    if score < 9.0:
        return 'high'
    return 'critical'


def _published_rating(record: dict) -> str:
    """The rating the database itself published, when it publishes one.

    GitHub advisories carry it; PYSEC records do not. Preferred over the computed band because
    it is the source's own answer — the panel is reporting what is known, not grading it.
    """
    raw = str(((record or {}).get('database_specific') or {}).get('severity') or '').lower()
    return 'moderate' if raw == 'medium' else (raw if raw in RATINGS else '')


def advisory_details(vid: str, timeout: float = TIMEOUT) -> dict:
    """How bad one advisory is, and what it is about, from its own record.

    Never raises: this runs for every distinct identifier and a column that could not be
    filled is a dash, not a failed check.
    """
    url = advisory_url(vid)
    if not url:
        return {'ok': False, 'error': 'bad_id'}
    req = urllib.request.Request(OSV_VULN_API.format(vid=vid), headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 (https only)
            body = resp.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            return {'ok': False, 'error': 'too_large'}
        record = json.loads(body.decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'error': 'http', 'status': int(exc.code)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'ok': False, 'error': 'unreachable', 'detail': str(exc)[:200]}
    except ValueError:
        return {'ok': False, 'error': 'not_json'}
    score = None
    vector = ''
    for entry in ((record or {}).get('severity') or []):
        got = cvss_score((entry or {}).get('score')) if isinstance(entry, dict) else None
        if got is not None and (score is None or got > score):
            score, vector = got, str(entry.get('score') or '')
    published = _published_rating(record)
    return {'ok': True,
            # The other names this same vulnerability goes by. A GHSA and a PYSEC entry for one
            # flaw is the norm, not the exception, and counting both says twice as much is
            # wrong as there is.
            'aliases': [str(a) for a in ((record or {}).get('aliases') or []) if a],
            # The published rating wins; the computed band is the fallback for the records
            # that carry a vector and no word for it.
            'severity': published or rating_of(score),
            'published': bool(published),
            'score': score,
            'vector': vector,
            'summary': str((record or {}).get('summary') or '')[:300]}


def advisory_details_many(ids, timeout: float = TIMEOUT) -> dict:
    """`{id: {...}}` for every DISTINCT identifier, asked in parallel and bounded."""
    wanted = sorted({str(i) for i in (ids or []) if i})[:MAX_DETAILS]
    if not wanted:
        return {}
    out: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(advisory_details, v, timeout): v for v in wanted}
        for fut in concurrent.futures.as_completed(futures):
            vid = futures[fut]
            try:
                out[vid] = fut.result()
            except Exception as exc:      # pylint: disable=broad-except
                out[vid] = {'ok': False, 'error': 'unreachable', 'detail': str(exc)[:200]}
    return out


def _headers() -> dict:
    # An API that rate-limits by client wants to know who is asking; the unnamed request is the
    # first one throttled.
    return {'Accept': 'application/json', 'User-Agent': f'{APP_NAME}-diagnostics'}


def version_key(value: str) -> tuple | None:
    """A version as something comparable, or None when it cannot be read.

    Deliberately not PEP 440. The question here is "is this behind the newest published one",
    asked of a diagnostics page, and the honest failure is **unknown** — so the numeric parts
    are compared and anything else (`2.0.0rc1`, a date-shaped version, a local segment) that
    does not parse cleanly answers None and shows as "cannot tell" rather than as a verdict
    somebody would act on.
    """
    parts = _NUM_RE.findall(str(value or ''))
    return tuple(int(p) for p in parts[:4]) if parts else None


def compare(installed: str, latest: str) -> str:
    """`behind` / `current` / `unknown` — three answers, and the third is not a failure."""
    a, b = version_key(installed), version_key(latest)
    if a is None or b is None:
        return 'unknown'
    return 'behind' if b > a else 'current'


def latest_version(name: str, timeout: float = TIMEOUT) -> dict:
    """The newest version PyPI publishes for one package.

    Answers `{'ok': bool, …}` and never raises: forty of these run together, and one package
    that 404s (a private wheel, a rename) or one proxy that returns HTML must cost its own cell
    and nothing else.
    """
    if not _NAME_RE.match(str(name or '')):
        return {'ok': False, 'error': 'bad_name'}
    req = urllib.request.Request(PYPI_URL.format(name=name), headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 (https only)
            # One byte past the cap, so hitting it is DETECTED rather than parsed as a
            # truncated document — "the answer did not fit" and "the answer was not JSON" send
            # somebody to two different places.
            body = resp.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            return {'ok': False, 'error': 'too_large'}
        data = json.loads(body.decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as exc:
        # 404 is an ANSWER: the package is not on PyPI at all, which is true of a private or
        # renamed one and is not a fault of the check.
        return {'ok': False, 'error': 'not_found' if int(exc.code) == 404 else 'http',
                'status': int(exc.code)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'ok': False, 'error': 'unreachable', 'detail': str(exc)[:200]}
    except ValueError:
        return {'ok': False, 'error': 'not_json'}
    info = (data or {}).get('info') or {}
    newest = str(info.get('version') or '')
    return {'ok': True, 'latest': newest, 'url': project_url(name, newest)}


def latest_versions(names, timeout: float = TIMEOUT) -> dict:
    """`{name: {...}}` for every DISTINCT name, asked in parallel and bounded.

    Distinct because the caller's rows can name one package twice — this process's version and
    another container's — and "what is the newest release" has one answer for both. Asked twice
    it was two requests to pypi.org for one cell.
    """
    names = sorted({str(n) for n in (names or []) if n})
    if not names:
        return {}
    out: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(latest_version, n, timeout): n for n in names}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                out[name] = fut.result()
            except Exception as exc:      # pylint: disable=broad-except
                # The pool must not be able to raise into the route: this whole module's
                # contract is that a failure is a value.
                out[name] = {'ok': False, 'error': 'unreachable', 'detail': str(exc)[:200]}
    return out


def vulnerabilities(pairs, timeout: float = TIMEOUT) -> dict:
    """Known advisories for `[(name, installed_version), …]`, in ONE request.

    OSV.dev answers a batch, which is why the vulnerability half survives what the PyPI half
    does not: it is a single connection, so a slow link costs one wait rather than forty.

    The batch reply carries IDs only — which is exactly the shape of the question, "how many
    known vulnerabilities affect what is installed". A count with the identifiers behind it is
    something an operator can look up; a severity this panel decided on its own is something
    they would have to trust.

    Answers `{'ok': bool, 'by_pin': {(name, version): [ids]}, …}`. A package with no installed
    version is not asked about: the question is about what is RUNNING, and a missing package
    cannot be vulnerable.

    Keyed by the PIN and not by the name, because the caller asks about three lists and the
    third one exists precisely to carry the packages another container runs at a *different*
    version. Keyed by name, the second answer for `urllib3` overwrote the first — and since the
    other containers' list is asked last, what overwrote this process's own row was always
    somebody else's. A clean 2.2.1 was drawn carrying 1.26.0's advisory, and the reverse (the
    vulnerable one reported clean because a newer container answered after it) is the same bug
    with the worse ending.
    """
    queries, pins = [], []
    for name, version in (pairs or []):
        if not name or not version:
            continue
        queries.append({'package': {'name': str(name), 'ecosystem': 'PyPI'},
                        'version': str(version)})
        pins.append((str(name), str(version)))
    if not queries:
        return {'ok': True, 'by_pin': {}, 'asked': 0}
    payload = json.dumps({'queries': queries}).encode('utf-8')
    req = urllib.request.Request(OSV_BATCH_URL, data=payload,
                                 headers={**_headers(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 (https only)
            body = resp.read(4 << 20)
        data = json.loads(body.decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'error': 'http', 'status': int(exc.code)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'ok': False, 'error': 'unreachable', 'detail': str(exc)[:200]}
    except ValueError:
        return {'ok': False, 'error': 'not_json'}
    results = (data or {}).get('results')
    if not isinstance(results, list):
        return {'ok': False, 'error': 'not_json'}
    by_pin: dict = {}
    # Positional: the batch answers in the order it was asked. A reply of a different length is
    # not something to line up as best we can — the association would be silently wrong, and
    # naming the wrong package as vulnerable is worse than saying the check could not be done.
    if len(results) != len(pins):
        return {'ok': False, 'error': 'length_mismatch'}
    for pin, res in zip(pins, results):
        ids = [str(v.get('id') or '') for v in ((res or {}).get('vulns') or [])
               if isinstance(v, dict)]
        # Filtered to what an identifier can be, here rather than where it is rendered: it
        # arrives from the network and it ends up in a URL and on a screen.
        by_pin[pin] = sorted(i for i in ids if _ID_RE.match(i))
    return {'ok': True, 'by_pin': by_pin, 'asked': len(queries)}


def collapse_aliases(ids, details) -> dict:
    """`{identifier: the one it is reported under}` — one vulnerability, one entry.

    A single flaw routinely carries a GHSA entry, a PYSEC entry and a CVE number, and the batch
    reports each identifier it knows. Counted straight, `pip` looks like two advisories and the
    total says twice as much is wrong as there is — on a screen whose entire purpose is a
    number somebody can believe.

    The one kept is the entry that published a severity where there is one, then alphabetical
    so the choice is stable between runs rather than a function of which thread answered first.
    """
    known = {str(i) for i in (ids or []) if i}
    parent = {i: i for i in known}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for vid in sorted(known):
        for alias in ((details.get(vid) or {}).get('aliases') or []):
            if alias in known:
                a, b = find(vid), find(str(alias))
                if a != b:
                    parent[max(a, b)] = min(a, b)
    groups: dict = {}
    for vid in known:
        groups.setdefault(find(vid), []).append(vid)
    out = {}
    for members in groups.values():
        members.sort(key=lambda v: (0 if (details.get(v) or {}).get('published') else 1, v))
        for member in members:
            out[member] = members[0]
    return out


def _grade(detail) -> dict:
    """The three fields a row carries about how bad one advisory is.

    Empty when the record could not be read: an unknown severity is a dash on the screen, and
    guessing one would be this panel grading a vulnerability it never saw. Empty, but the SAME
    five keys — a dict whose shape depends on whether the request worked is one the reader has
    to test twice, and the half that forgets reads `undefined` as "computed by us".
    """
    got = detail or {}
    if not got.get('ok'):
        return {'severity': '', 'score': None, 'published': False, 'vector': '', 'summary': ''}
    return {'severity': str(got.get('severity') or ''),
            'score': got.get('score'),
            # Whether the word came from the database or from its own vector. The screen says
            # so, because "GitHub calls this moderate" and "its CVSS vector scores 8.0" are
            # two different claims and they do disagree.
            'published': bool(got.get('published')),
            'vector': str(got.get('vector') or ''),
            'summary': str(got.get('summary') or '')}


def check(rows, timeout: float = TIMEOUT) -> dict:
    """Both questions for the dependency table, merged onto the rows it already has.

    Takes the rows the local collector produced — name, required, installed — so the two halves
    of the table cannot disagree about which packages exist. The answer carries only what the
    network added, and the browser merges it back on by name AND version: the page keeps
    working with the local half alone, which is what it shows before anybody presses the
    button.

    The rows may hold one package twice — this process's version and another container's — so
    every association in here is by the pin. The row it lands on is not the only thing that
    depends on it: the totals count DISTINCT advisories and packages, because one flaw on two
    versions of one package is one finding.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get('name')]
    names = [r['name'] for r in rows]
    latest = latest_versions(names, timeout)
    vulns = vulnerabilities([(r['name'], r.get('installed') or '') for r in rows], timeout)
    out_rows, behind, unknown = [], 0, 0
    # By name AND version, the way it was asked: the rows can hold the same package twice when
    # another container of this installation runs a different one of it.
    by_pin = (vulns.get('by_pin') or {}) if vulns.get('ok') else {}
    # One more round, over the DISTINCT identifiers rather than the rows: the same advisory
    # routinely lands on several packages.
    every_id = {i for ids in by_pin.values() for i in ids}
    details = advisory_details_many(every_id, timeout)
    # One vulnerability, one entry: the batch reports every identifier it knows, and a GHSA
    # plus a PYSEC entry for the same flaw is the norm.
    under = collapse_aliases(every_id, details)
    also: dict = {}
    for vid, keeper in under.items():
        if vid != keeper:
            also.setdefault(keeper, []).append(vid)
    for row in rows:
        name = row['name']
        installed = str(row.get('installed') or '')
        got = latest.get(name) or {}
        newest = str(got.get('latest') or '') if got.get('ok') else ''
        state = compare(installed, newest) if newest else 'unknown'
        if state == 'behind':
            behind += 1
        elif state == 'unknown':
            unknown += 1
        # Each identifier with where it is written up and how bad it is, together. Two parallel
        # lists — ids here, links there — is the same positional association the batch reply
        # already taught us not to make: one of them gets filtered somewhere and the row points
        # at the wrong advisory.
        kept = sorted({under.get(i, i) for i in (by_pin.get((name, installed)) or [])})
        ids = [{'id': i, 'url': advisory_url(i), 'aliases': sorted(also.get(i) or []),
                **_grade(details.get(i))} for i in kept]
        out_rows.append({'name': name,
                         # Where to read about it: the package's page on PyPI for that
                         # version. Per row, because the version is per row.
                         'url': str(got.get('url') or '') if got.get('ok') else '',
                         # The version this row was ASKED about, carried back beside the
                         # answer: the screen says "3.4.9 → 3.5.0", and pairing the two in the
                         # browser from a second list is how they come to disagree.
                         'installed': installed,
                         'latest': newest, 'state': state,
                         'error': '' if got.get('ok') else str(got.get('error') or ''),
                         'vulns': ids, 'vuln_count': len(ids)})
    return {
        'ok': True,
        'rows': out_rows,
        'behind': behind,
        'unknown': unknown,
        # The vulnerability half reports its own outcome: it is one request against a different
        # service, so "PyPI answered and OSV did not" is a real state and a table that showed
        # zero advisories for it would be stating something nobody checked.
        'vulns_ok': bool(vulns.get('ok')),
        'vulns_error': '' if vulns.get('ok') else str(vulns.get('error') or ''),
        # How many were actually ASKED about. Without it a column of zeros and a column
        # nobody checked look identical, and "no advisories" is exactly the answer somebody
        # should be able to disbelieve until the screen says how it was reached.
        'vuln_asked': int(vulns.get('asked') or 0) if vulns.get('ok') else 0,
        # DISTINCT, not a sum over the rows. The same flaw affecting two versions of one package
        # — this process's and another container's — is one advisory in one package, and adding
        # the rows up says twice as much is wrong as there is. Which is the complaint
        # `collapse_aliases` exists for, arriving by the other door.
        'vuln_total': len({v['id'] for r in out_rows for v in r['vulns']}),
        'vuln_packages': len({r['name'] for r in out_rows if r['vuln_count']}),
    }
