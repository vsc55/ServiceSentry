#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is there a newer release than the one running?

The one thing in this domain that reaches outside the machine, which is why it is its own
module. Two rules follow from that:

* **it never happens on its own.** No poll, no check at boot, no request while the page paints.
  A monitoring panel is the kind of software that gets installed on a segregated network by
  somebody who would rather it did not talk to anybody, and "it phoned github.com and I never
  asked it to" is a bug report you cannot argue with. It runs when a person presses a button.
* **it cannot cost anything.** A short timeout, one request, no redirect chasing, and any
  failure is an answer on screen — not an exception, not a retry, and never a page that hangs
  because a firewall is dropping the packets rather than refusing them.

The comparison is a pure function and lives here too, because it is the half that is actually
easy to get wrong.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from lib import APP_NAME
from lib.config.spec import cfg_default

# The releases API of the repository this is built from, read from the ONE registry of defaults
# rather than written here as well: the config screen shows this value greyed behind the empty
# box and "restore default" restores it, and a second copy in code is how those two come to
# disagree about where the panel is going to connect.
#
# Read from the registry and never from anything downloaded: the panel must not learn where to
# look for its own updates from a server it just talked to.
DEFAULT_URL = cfg_default('web_admin|update_check_url')

TIMEOUT = 6.0

_SEMVER_RE = re.compile(r'(\d+)\.(\d+)\.(\d+)')
_BUILD_RE = re.compile(r'\+build\.(\d+)')


def parse_version(value: str) -> dict:
    """`'0.0.1+build.61'` → `{'semver': (0, 0, 1), 'build': 61}`.

    Tolerant of the shapes a release tag arrives in — `v1.2.3`, `1.2.3`, `release-1.2.3` — and
    of nonsense, which answers `None` for the parts it could not read rather than raising. A
    version string that cannot be parsed is a reason to say "cannot tell", never a reason for
    the diagnostics page to fail.
    """
    text = str(value or '')
    m = _SEMVER_RE.search(text)
    b = _BUILD_RE.search(text)
    return {'raw': text,
            'semver': tuple(int(g) for g in m.groups()) if m else None,
            'build': int(b.group(1)) if b else None}


def compare(current: str, latest: str) -> dict:
    """Is *latest* newer than *current*, and can we even tell?

    Three answers, not two. The third is the honest one and the reason this is not a `>`:

    * `newer` — the published release has a higher semantic version;
    * `current` — this build is at or above it;
    * `unknown` — one of the two could not be parsed, or both carry the same semantic version.

    That last case is this project's normal state, not an edge case: the semantic version
    deliberately stays at `0.0.1` while the build counter moves, and **build metadata does not
    participate in precedence** — semver says so, and a release tag carries none of it anyway.
    Answering "up to date" there would be a guess dressed as a fact, on the one screen whose
    entire job is to not do that.
    """
    cur, new = parse_version(current), parse_version(latest)
    if cur['semver'] is None or new['semver'] is None:
        return {'status': 'unknown', 'current': cur['raw'], 'latest': new['raw'],
                'reason': 'unparsable'}
    if new['semver'] > cur['semver']:
        return {'status': 'newer', 'current': cur['raw'], 'latest': new['raw']}
    if new['semver'] < cur['semver']:
        return {'status': 'current', 'current': cur['raw'], 'latest': new['raw']}
    return {'status': 'unknown', 'current': cur['raw'], 'latest': new['raw'],
            'reason': 'same_semver'}


def fetch_latest(url: str = '', timeout: float = TIMEOUT) -> dict:
    """Ask the releases API for the newest published release.

    Answers `{'ok': bool, ...}` and never raises: every way this fails — no route, DNS gone,
    a proxy returning HTML, rate limiting, a body that is not JSON — is a sentence for the
    operator, and none of them is a reason for a 500 on the page they opened *because*
    something is wrong.
    """
    target = str(url or DEFAULT_URL)
    if not target.startswith('https://'):
        # Refused rather than followed: this is a URL from configuration, and downgrading the
        # one request the panel makes about its own updates is not a thing to be talked into.
        return {'ok': False, 'error': 'insecure_url', 'url': target}
    req = urllib.request.Request(target, headers={
        'Accept': 'application/vnd.github+json',
        # An API that rate-limits by client wants to know who is asking; an unnamed request
        # is the one that gets throttled first.
        'User-Agent': f'{APP_NAME}-diagnostics',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 (https only)
            body = resp.read(1 << 20)                                   # a release doc, not a file
        data = json.loads(body.decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as exc:
        # A 404 from `/releases/latest` is not a broken endpoint: that path answers with the
        # newest PUBLISHED release and excludes drafts and prereleases, so a repository whose
        # only release is either of those has nothing to return. Reported as its own answer —
        # "nothing published yet" — because "HTTP 404" sends somebody to check the URL, which
        # is the one thing that is not wrong.
        if int(exc.code) == 404:
            return {'ok': False, 'error': 'no_releases', 'url': target}
        return {'ok': False, 'error': 'http', 'status': int(exc.code), 'url': target}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'ok': False, 'error': 'unreachable', 'detail': str(exc)[:200], 'url': target}
    except ValueError:
        return {'ok': False, 'error': 'not_json', 'url': target}
    if not isinstance(data, dict):
        return {'ok': False, 'error': 'not_json', 'url': target}
    return {
        'ok': True,
        'tag': str(data.get('tag_name') or ''),
        'name': str(data.get('name') or ''),
        'published_at': str(data.get('published_at') or ''),
        'html_url': str(data.get('html_url') or ''),
        'url': target,
    }
