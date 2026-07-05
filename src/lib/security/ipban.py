#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service-agnostic internal fail2ban — a progressive per-IP jail shared across
every port-exposing service (the web admin, the syslog receiver, and any future
listener).

Design
------
One :class:`IpBanManager` instance is created once by the core and handed to
every service that faces the network.  Each service only needs two calls:

    banned, retry_after, reason = mgr.is_banned(client_ip)   # gate: reject if True
    mgr.register_offense(client_ip, category)                # feed: count abuse

An *offense* is any abusive event a service observes (a failed login, a CSRF
rejection, a 403 to a section the caller may not touch, a syslog packet from a
non-allowlisted source…).  Offenses accumulate per IP within a trailing window;
crossing the threshold *jails* the IP for an escalating duration (repeat bans
last longer, up to permanent).  Jailed IPs are rejected up-front by every
service, so a banned attacker stops reaching any exposed port.

Two independent tracks with their own thresholds keep a curious authenticated
user from being jailed as fast as an anonymous brute-forcer:

  * ``'auth'``  — pre-auth / anonymous abuse (login, CSRF, bearer, 401, unauth 403)
  * ``'authz'`` — an authenticated session repeatedly hitting forbidden sections

Framework-free and thread-safe.  Persistence and audit are injected as plain
callables (``persist`` / ``notify``) so this module depends on neither the DB nor
Flask; the host wires those to :class:`lib.stores.ipbans.IpBanStore` and the
audit log.
"""

from __future__ import annotations

import ipaddress
import threading
import time as _time
from collections import deque

# Offense category → track.  Unknown categories default to the 'auth' track (the
# stricter one) so a new call-site is fail-safe until explicitly classified.
_CATEGORY_TRACK = {
    'login_failed':    'auth',
    'login_throttled': 'auth',
    'csrf_failed':     'auth',
    'scim_auth_failed': 'auth',
    'unauthorized':    'auth',      # 401 on a protected endpoint (no/again invalid session)
    'forbidden_anon':  'auth',      # 403 with no valid session
    'syslog_drop':     'auth',      # packet/conn from a non-allowlisted source
    'forbidden':       'authz',     # 403 with a valid session (permission denied)
}

_DEFAULT_DURATIONS = (900, 3600, 21600, 86400)   # 15m → 1h → 6h → 24h, then permanent


def _parse_nets(values) -> list:
    """Turn a list / comma-or-space string of IPs / CIDRs into ip_network objects."""
    if isinstance(values, str):
        import re
        values = [v for v in re.split(r'[,\s]+', values) if v]
    nets = []
    for s in (values or ()):
        s = str(s).strip()
        if not s:
            continue
        try:
            nets.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            continue
    return nets


class IpBanManager:
    """Progressive per-IP jail, shared across services.  Thread-safe.

    Config (all runtime-updatable via :meth:`configure`):
      * ``enabled``            — master switch (False ⇒ never bans, never blocks).
      * ``auth_threshold`` / ``auth_window``   — offenses/seconds for the auth track.
      * ``authz_threshold`` / ``authz_window`` — same for the authz (session-403) track.
      * ``durations``          — escalating ban lengths in seconds (per repeat level).
      * ``permanent_after``    — ban level beyond which a ban is permanent (0 = never).
      * ``whitelist``          — IPs/CIDRs that are never counted nor blocked.

    Injected side-effects (optional):
      * ``persist(ip, record | None)`` — upsert a ban row, or delete when record is None.
      * ``notify(action, ip, info)``   — audit hook: action ∈ {'banned','unbanned','ban_escalated'}.
    """

    _OFFENSE_MAX_IPS = 4096      # cap tracked offender IPs (rotating-IP flood guard)
    _BAN_CACHE_TTL = 3.0         # seconds the active-ban snapshot is cached (DB mode)

    def __init__(self, *, persist=None, notify=None, store=None):
        self._lock = threading.RLock()
        self._persist = persist
        self._notify = notify
        # When a store is given, ALL counting/ban state lives in the shared DB so it
        # survives restarts and is consistent across processes; is_banned reads a
        # short-lived cached snapshot to avoid a DB hit per request. Without a store
        # the manager is purely in-memory (lightweight; used by unit tests).
        self._store = store
        self._ban_cache: dict = {}
        self._ban_cache_at = -1e9
        # offenses[ip][track] = deque[timestamp]
        self._offenses: dict[str, dict[str, deque]] = {}
        # history[ip] = deque[{ts, category}] — recent attempts for the detail modal
        # (bounded per IP; survives a ban so a jailed IP's attempts remain inspectable,
        # cleared on unban / clear_offenses).
        self._history: dict[str, deque] = {}
        # jail[ip] = {'until': float|None, 'level': int, 'reason': str,
        #             'category': str, 'banned_at': float, 'by': str,
        #             'first_seen': float, 'offenses': int}
        self._jail: dict[str, dict] = {}
        self._last_gc = 0.0
        # config (defaults; overridden by configure())
        self._enabled = True
        self._auth_threshold = 10
        self._auth_window = 600.0
        self._authz_threshold = 30
        self._authz_window = 600.0
        self._durations = list(_DEFAULT_DURATIONS)
        self._permanent_after = len(_DEFAULT_DURATIONS)   # 5th ban ⇒ permanent
        self._whitelist: list = _parse_nets(['127.0.0.0/8', '::1'])

    # ── configuration ─────────────────────────────────────────────────────────
    def configure(self, *, enabled=None, auth_threshold=None, auth_window=None,
                  authz_threshold=None, authz_window=None, durations=None,
                  permanent_after=None, whitelist=None, extra_whitelist=None) -> None:
        """Update thresholds/whitelist at runtime (called on boot and config save).

        ``whitelist`` replaces the configured list; ``extra_whitelist`` (e.g. the
        reverse-proxy address, loopback) is always merged in so the app can never
        jail its own trusted hops."""
        with self._lock:
            if enabled is not None:
                self._enabled = bool(enabled)
            if auth_threshold is not None:
                self._auth_threshold = max(0, int(auth_threshold))
            if auth_window is not None:
                self._auth_window = max(1.0, float(auth_window))
            if authz_threshold is not None:
                self._authz_threshold = max(0, int(authz_threshold))
            if authz_window is not None:
                self._authz_window = max(1.0, float(authz_window))
            if durations is not None:
                ds = [max(1, int(d)) for d in self._coerce_list(durations)]
                self._durations = ds or list(_DEFAULT_DURATIONS)
            if permanent_after is not None:
                self._permanent_after = max(0, int(permanent_after))
            if whitelist is not None or extra_whitelist is not None:
                base = _parse_nets(whitelist) if whitelist is not None else self._whitelist
                merged = list(base) + _parse_nets(extra_whitelist or [])
                # loopback is always safe to keep
                merged += _parse_nets(['127.0.0.0/8', '::1'])
                # de-dup by string form
                seen, out = set(), []
                for n in merged:
                    if str(n) not in seen:
                        seen.add(str(n)); out.append(n)
                self._whitelist = out

    @staticmethod
    def _coerce_list(values):
        if isinstance(values, str):
            import re
            return [v for v in re.split(r'[,\s]+', values) if v]
        return list(values or ())

    # ── whitelist / helpers ─────────────────────────────────────────────────────
    def is_whitelisted(self, ip: str) -> bool:
        if not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self._whitelist)

    def _track_for(self, category: str) -> str:
        return _CATEGORY_TRACK.get(category, 'auth')

    def _threshold_window(self, track: str) -> tuple[int, float]:
        if track == 'authz':
            return self._authz_threshold, self._authz_window
        return self._auth_threshold, self._auth_window

    # ── query ────────────────────────────────────────────────────────────────────
    def _active_jail(self, now: float) -> dict:
        """The current {ip: ban} map. DB mode: a short-lived cached snapshot of the
        shared table (so a ban from any process is honoured within the TTL, without a
        DB read per request). Memory mode: the in-process jail."""
        if self._store is None:
            return self._jail
        if now - self._ban_cache_at >= self._BAN_CACHE_TTL:
            try:
                self._ban_cache = {b['ip']: b for b in self._store.active_bans(now)}
            except Exception:  # pylint: disable=broad-except
                pass
            self._ban_cache_at = now
        return self._ban_cache

    def _invalidate_ban_cache(self) -> None:
        self._ban_cache_at = -1e9

    def is_banned(self, ip: str) -> tuple[bool, int, str]:
        """Return ``(banned, retry_after_secs, reason)``.  A permanent ban reports a
        conventional large ``retry_after`` (a year).  Whitelisted / disabled ⇒ never."""
        if not self._enabled or not ip or self.is_whitelisted(ip):
            return False, 0, ''
        now = _time.time()
        with self._lock:
            rec = self._active_jail(now).get(ip)
            if not rec:
                return False, 0, ''
            until = rec.get('until')
            if until is None:
                return True, 31_536_000, rec.get('reason', '')
            if not until or now >= until:
                # expired jail term — no longer blocks (a fresh offense can re-jail).
                if self._store is None:
                    rec['until'] = 0.0
                return False, 0, ''
            return True, max(1, int(until - now)), rec.get('reason', '')

    def is_banned_flag(self, ip: str) -> bool:
        """Boolean-only :meth:`is_banned` — the shape non-HTTP services (syslog) want."""
        return self.is_banned(ip)[0]

    # ── offense intake ────────────────────────────────────────────────────────────
    def register_offense(self, ip: str, category: str, *, weight: int = 1,
                         detail: str = '') -> bool:
        """Record an abusive event for *ip*.  Returns True if it triggered a (new or
        escalated) ban.  No-op for whitelisted IPs or when disabled."""
        if not self._enabled or not ip or weight <= 0 or self.is_whitelisted(ip):
            return False
        track = self._track_for(category)
        threshold, window = self._threshold_window(track)
        if threshold <= 0:
            return False
        now = _time.time()
        # ── shared DB backend: count in the DB so every process shares the tally ──
        if self._store is not None:
            with self._lock:
                self._gc(now)           # periodic DB prune (throttled internally)
                if self.is_banned(ip)[0]:
                    return False        # already jailed — don't re-count / escalate
                self._store.log_attempt(ip, now, category)
                count = 0
                for _ in range(weight):
                    count = self._store.bump_offense(ip, track, now, window)
                if count >= threshold:
                    self._ban_locked(ip, category=category, reason=category,
                                     by='system', detail=detail, offenses=count)
                    return True
            return False
        with self._lock:
            self._gc(now)
            per = self._offenses.get(ip)
            if per is None:
                if len(self._offenses) >= self._OFFENSE_MAX_IPS:
                    return False        # flood guard: don't grow the map without bound
                per = self._offenses[ip] = {}
            dq = per.get(track)
            if dq is None:
                dq = per[track] = deque()
            cutoff = now - window
            while dq and dq[0] <= cutoff:
                dq.popleft()
            for _ in range(weight):
                dq.append(now)
            # Attempt history (bounded) for the detail modal — records every offense
            # with its category, independent of the sliding window used for banning.
            hist = self._history.get(ip)
            if hist is None:
                hist = self._history[ip] = deque(maxlen=200)
            hist.append({'ts': now, 'category': category, 'track': track})
            count = len(dq)
            if count >= threshold:
                dq.clear()              # reset the window so we don't re-fire each hit
                self._ban_locked(ip, category=category, reason=category,
                                  by='system', detail=detail, offenses=count)
                return True
        return False

    # ── ban / unban ───────────────────────────────────────────────────────────────
    def ban(self, ip: str, *, duration_secs: int | None = None, reason: str = 'manual',
            by: str = 'system') -> dict | None:
        """Explicitly jail *ip* (manual admin ban or a service's own decision).

        ``duration_secs=None`` follows the escalation ladder; ``0`` ⇒ permanent; a
        positive value forces that exact term.  Whitelisted IPs are refused."""
        if not ip or self.is_whitelisted(ip):
            return None
        with self._lock:
            return self._ban_locked(ip, category=reason, reason=reason, by=by,
                                    forced_duration=duration_secs)

    def _ban_locked(self, ip, *, category, reason, by, detail='', offenses=0,
                    forced_duration=None) -> dict:
        now = _time.time()
        # Prior ban (for the escalation level) comes from the shared store in DB mode,
        # so a repeat offender escalates correctly no matter which process banned it.
        prev = self._store.get_ban(ip) if self._store is not None else self._jail.get(ip)
        level = (prev.get('level', 0) if prev else 0) + 1
        first_seen = prev.get('first_seen', now) if prev else now
        total_off = (prev.get('offenses', 0) if prev else 0) + (offenses or 1)
        if forced_duration is not None:
            until = None if int(forced_duration) <= 0 else now + int(forced_duration)
        else:
            # escalating ladder; permanent once level passes permanent_after (>0)
            if self._permanent_after and level > self._permanent_after:
                until = None
            else:
                idx = min(level - 1, len(self._durations) - 1)
                until = now + self._durations[idx]
        rec = {
            'ip': ip, 'until': until, 'level': level, 'reason': reason,
            'category': category, 'banned_at': now, 'by': by,
            'first_seen': first_seen, 'offenses': total_off, 'detail': detail,
            # Preserve any per-ban block-action override across escalations.
            'block_action': (prev.get('block_action', '') if prev else '') or '',
        }
        if self._store is not None:
            try:
                self._store.upsert(ip, dict(rec))
                self._store.reset_counters(ip)   # fresh count if the ban later expires
                self._store.log_ban_event(       # append-only audit trail
                    ip, 'escalated' if level > 1 else 'banned', rec, now)
            except Exception:  # pylint: disable=broad-except
                pass
            self._invalidate_ban_cache()         # enforce it here immediately
        else:
            self._jail[ip] = rec
            if self._persist:
                try:
                    self._persist(ip, dict(rec))
                except Exception:  # pylint: disable=broad-except
                    pass
        if self._notify:
            try:
                action = 'ban_escalated' if level > 1 else 'banned'
                self._notify(action, ip, dict(rec))
            except Exception:  # pylint: disable=broad-except
                pass
        return dict(rec)

    def unban(self, ip: str, *, by: str = 'system', reason: str | None = None) -> bool:
        """Lift a ban and clear the IP's offense history.  Returns True if it was jailed.

        ``reason`` (why the ban is being lifted) is recorded on the ``unbanned`` history
        event; when omitted the event keeps the original ban reason."""
        if not ip:
            return False
        if self._store is not None:
            prev = self._store.get_ban(ip)          # capture info for the history row
            existed = self._store.delete(ip)
            self._store.clear_offenses(ip)
            if existed:
                rec = dict(prev or {})
                rec['by'] = by
                if reason:
                    rec['reason'] = reason          # the removal reason, not the ban reason
                self._store.log_ban_event(ip, 'unbanned', rec, _time.time())
            self._invalidate_ban_cache()
            if existed and self._notify:
                try:
                    self._notify('unbanned', ip, {'by': by, 'reason': reason or ''})
                except Exception:  # pylint: disable=broad-except
                    pass
            return existed
        with self._lock:
            existed = self._jail.pop(ip, None) is not None
            self._offenses.pop(ip, None)
            self._history.pop(ip, None)
        if existed:
            if self._persist:
                try:
                    self._persist(ip, None)
                except Exception:  # pylint: disable=broad-except
                    pass
            if self._notify:
                try:
                    self._notify('unbanned', ip, {'by': by})
                except Exception:  # pylint: disable=broad-except
                    pass
        return existed

    _BLOCK_ACTIONS = ('page', 'minimal', 'reject', 'json')

    def set_block_action(self, ip: str, action: str) -> bool:
        """Set a per-ban block-action override for a jailed *ip* ('' / invalid ⇒ clear
        the override, so the global default applies). Returns True if the IP is jailed."""
        action = action if action in self._BLOCK_ACTIONS else ''
        if self._store is not None:
            rec = self._store.get_ban(ip)
            if not rec:
                return False
            rec['block_action'] = action
            self._store.upsert(ip, rec)
            self._invalidate_ban_cache()
            return True
        with self._lock:
            rec = self._jail.get(ip)
            if not rec:
                return False
            rec['block_action'] = action
            return True

    def block_action(self, ip: str) -> str:
        """The per-ban block-action override for *ip* ('' = use the global default)."""
        if not ip:
            return ''
        now = _time.time()
        with self._lock:
            rec = self._active_jail(now).get(ip)
        return (rec.get('block_action') or '') if rec else ''

    def clear_offenses(self, ip: str) -> bool:
        """Drop an IP from the watchlist: forget its accumulated offenses + history.
        Does NOT touch an active ban (use :meth:`unban` for that). Returns True if
        the IP had any tracked offenses."""
        if not ip:
            return False
        if self._store is not None:
            return self._store.clear_offenses(ip)
        with self._lock:
            had = self._offenses.pop(ip, None) is not None
            self._history.pop(ip, None)
        return had

    def history(self, ip: str, *, limit: int = 200) -> list[dict]:
        """Recent recorded attempts for *ip* (most recent first): ``{ts, category}``."""
        if self._store is not None:
            return self._store.history(ip, limit=limit)
        with self._lock:
            hist = self._history.get(ip)
            items = list(hist) if hist else []
        items.reverse()
        return items[:max(1, int(limit))]

    # ── state load / listing ──────────────────────────────────────────────────────
    def load(self, records) -> None:
        """Seed the in-memory jail from persisted rows (on boot).  Expired terms are
        kept (for escalation history) but won't block."""
        with self._lock:
            for r in (records or ()):
                ip = r.get('ip')
                if not ip:
                    continue
                self._jail[ip] = {
                    'ip': ip, 'until': r.get('until'), 'level': int(r.get('level', 1)),
                    'reason': r.get('reason', ''), 'category': r.get('category', ''),
                    'banned_at': float(r.get('banned_at', 0) or 0), 'by': r.get('by', 'system'),
                    'first_seen': float(r.get('first_seen', 0) or 0),
                    'offenses': int(r.get('offenses', 0) or 0), 'detail': r.get('detail', ''),
                    'block_action': r.get('block_action', '') or '',
                }

    def list_bans(self, *, active_only: bool = True) -> list[dict]:
        """Snapshot of jailed IPs (active by default), most recent first."""
        now = _time.time()
        if self._store is not None:
            src = self._store.active_bans(now) if active_only else self._store.query(limit=1000)
        else:
            with self._lock:
                src = list(self._jail.values())
        out = []
        for rec in src:
            until = rec.get('until')
            active = until is None or (until and until > now)
            if active_only and not active:
                continue
            d = dict(rec)
            d['active'] = bool(active)
            d['permanent'] = until is None
            d['retry_after'] = (None if until is None
                                else max(0, int(until - now)) if until else 0)
            out.append(d)
        out.sort(key=lambda d: d.get('banned_at', 0), reverse=True)
        return out

    def ban_history(self, *, limit: int = 500, ip: str | None = None) -> list[dict]:
        """Append-only ban lifecycle events (banned / escalated / unbanned), most
        recent first — the audit trail of what was banned, why and for how long, kept
        even after a ban expires. Empty in the in-memory (store-less) mode."""
        if self._store is None:
            return []
        return self._store.ban_history(limit=limit, ip=ip)

    def list_offenders(self, *, min_count: int = 1) -> list[dict]:
        """Watchlist: IPs accumulating offenses in-window but NOT yet jailed — the
        ones "on the way to a ban". For each, the live per-track count, its threshold
        and how many more offenses would trip the ban (``remaining``). Sorted by how
        close the closest track is to its threshold (most imminent first).

        Whitelisted IPs never accrue offenses (short-circuited at intake), so they
        never appear here."""
        now = _time.time()
        if self._store is not None:
            banned = {b['ip'] for b in self._active_jail(now).values()}
            per_ip: dict = {}
            for c in self._store.counters():
                ip, track = c['ip'], c['track']
                if ip in banned:
                    continue
                threshold, window = self._threshold_window(track)
                if threshold <= 0 or (now - float(c['window_start'] or 0)) >= window:
                    continue                       # track disabled or window elapsed
                cnt = int(c['count'])
                if cnt <= 0:
                    continue
                remaining = max(0, threshold - cnt)
                d = per_ip.setdefault(ip, {'ip': ip, 'tracks': {}, 'total': 0,
                                           'remaining': None})
                d['tracks'][track] = {'count': cnt, 'threshold': threshold,
                                      'remaining': remaining}
                d['total'] += cnt
                d['remaining'] = remaining if d['remaining'] is None else min(d['remaining'], remaining)
            out = [d for d in per_ip.values() if d['total'] >= min_count]
            out.sort(key=lambda d: (d['remaining'] if d['remaining'] is not None else 1e9,
                                    -d['total']))
            return out
        with self._lock:
            out = []
            for ip, per in self._offenses.items():
                # Skip IPs with an active ban (they belong in list_bans, not here).
                rec = self._jail.get(ip)
                if rec is not None:
                    until = rec.get('until')
                    if until is None or (until and until > now):
                        continue
                tracks = {}
                total = 0
                closest = None      # smallest 'remaining' across tracks
                for track, dq in per.items():
                    threshold, window = self._threshold_window(track)
                    if threshold <= 0:
                        continue
                    cutoff = now - window
                    cnt = sum(1 for t in dq if t > cutoff)
                    if cnt <= 0:
                        continue
                    remaining = max(0, threshold - cnt)
                    tracks[track] = {'count': cnt, 'threshold': threshold,
                                     'remaining': remaining}
                    total += cnt
                    closest = remaining if closest is None else min(closest, remaining)
                if tracks and total >= min_count:
                    out.append({'ip': ip, 'tracks': tracks, 'total': total,
                                'remaining': closest if closest is not None else None})
            out.sort(key=lambda d: (d['remaining'] if d['remaining'] is not None else 1e9,
                                    -d['total']))
            return out

    # ── housekeeping ──────────────────────────────────────────────────────────────
    def _gc(self, now: float) -> None:
        # Drop stale offense buckets and long-expired jail records (called under lock).
        if now - self._last_gc < 300:
            return
        self._last_gc = now
        if self._store is not None:
            try:
                self._store.prune(now)
            except Exception:  # pylint: disable=broad-except
                pass
            return
        max_window = max(self._auth_window, self._authz_window)
        for ip in [ip for ip, per in self._offenses.items()
                   if all((not dq) or dq[-1] <= now - max_window for dq in per.values())]:
            self._offenses.pop(ip, None)
            # Keep a jailed IP's history (for the modal); drop it only for IPs that
            # are neither jailed nor tracked any more.
            if ip not in self._jail:
                self._history.pop(ip, None)
