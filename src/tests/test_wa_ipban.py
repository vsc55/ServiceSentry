#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Internal fail2ban: IpBanManager unit tests + WebAdmin/store integration."""

import time

from lib.security.ipban import IpBanManager
from .conftest import _login


def _mgr_on(store, **cfg):
    m = IpBanManager(store=store)
    base = dict(enabled=True, auth_threshold=5, auth_window=600,
                authz_threshold=30, authz_window=600, durations=[900])
    base.update(cfg)
    m.configure(**base)
    return m


class TestIpBanShared:
    """The offense counters + jail must live in the shared DB — surviving a restart
    and consistent across processes (the two reported design bugs)."""

    def test_counters_survive_restart(self, admin):
        store = admin._ipban_store
        ip = "203.0.113.150"
        m1 = _mgr_on(store, auth_threshold=5)
        for _ in range(4):
            m1.register_offense(ip, "login_failed")
        assert not m1.is_banned(ip)[0]
        # "Restart": a fresh manager on the SAME store keeps the accumulated count,
        # so the 5th offense still trips the ban (memory would have reset to 0).
        m2 = _mgr_on(store, auth_threshold=5)
        assert m2.register_offense(ip, "login_failed") is True
        assert m2.is_banned(ip)[0]

    def test_counter_shared_across_processes(self, admin):
        store = admin._ipban_store
        ip = "203.0.113.151"
        a = _mgr_on(store, auth_threshold=4)      # two independent managers,
        b = _mgr_on(store, auth_threshold=4)      # like two workers on one DB
        a.register_offense(ip, "login_failed")    # count 1
        b.register_offense(ip, "login_failed")    # count 2 (shared)
        a.register_offense(ip, "login_failed")    # count 3
        assert not a.is_banned(ip)[0] and not b.is_banned(ip)[0]
        assert b.register_offense(ip, "login_failed") is True   # 4th (shared) → ban
        a._invalidate_ban_cache()                 # other process sees it within TTL
        assert a.is_banned(ip)[0]

    def test_unban_shared_across_processes(self, admin):
        store = admin._ipban_store
        ip = "203.0.113.152"
        a = _mgr_on(store)
        b = _mgr_on(store)
        a.ban(ip, duration_secs=600)
        b._invalidate_ban_cache()
        assert b.is_banned(ip)[0]
        b.unban(ip)
        a._invalidate_ban_cache()
        assert not a.is_banned(ip)[0]


# ──────────────────────────────────────────────────────────────────────────────
# Core manager
# ──────────────────────────────────────────────────────────────────────────────
class TestIpBanManager:
    def _mgr(self, **cfg):
        m = IpBanManager()
        base = dict(enabled=True, auth_threshold=3, auth_window=600,
                    authz_threshold=5, authz_window=600, durations=[10, 20, 30],
                    permanent_after=3)
        base.update(cfg)
        m.configure(**base)
        return m

    def test_auth_track_bans_at_threshold(self):
        m = self._mgr()
        ip = "203.0.113.5"
        assert not m.is_banned(ip)[0]
        for _ in range(2):
            m.register_offense(ip, "login_failed")
        assert not m.is_banned(ip)[0]         # below threshold (3)
        m.register_offense(ip, "login_failed")
        assert m.is_banned(ip)[0]             # threshold reached → jailed

    def test_authz_track_more_tolerant(self):
        m = self._mgr()
        ip = "198.51.100.9"
        for _ in range(4):                    # authz threshold is 5
            m.register_offense(ip, "forbidden")
        assert not m.is_banned(ip)[0]
        m.register_offense(ip, "forbidden")
        assert m.is_banned(ip)[0]

    def test_escalation_to_permanent(self):
        m = self._mgr()
        ip = "203.0.113.7"
        levels = []
        for _ in range(4):                    # 4 bans: 10s, 20s, 30s, then permanent
            for _ in range(3):
                m.register_offense(ip, "login_failed")
            levels.append(m.list_bans()[0]["permanent"])
        assert levels == [False, False, False, True]

    def test_whitelist_never_bans(self):
        m = self._mgr(extra_whitelist=["10.0.0.0/8"])
        ip = "10.1.2.3"
        for _ in range(10):
            m.register_offense(ip, "login_failed")
        assert not m.is_banned(ip)[0]
        assert m.ban(ip, duration_secs=60) is None      # explicit ban refused too

    def test_loopback_always_whitelisted(self):
        m = self._mgr()
        for _ in range(10):
            m.register_offense("127.0.0.1", "login_failed")
        assert not m.is_banned("127.0.0.1")[0]

    def test_manual_ban_and_unban(self):
        m = self._mgr()
        ip = "192.0.2.50"
        rec = m.ban(ip, duration_secs=0, reason="manual")   # 0 ⇒ permanent
        assert rec and rec["until"] is None
        assert m.is_banned(ip)[0]
        assert m.unban(ip) is True
        assert not m.is_banned(ip)[0]
        assert m.unban(ip) is False                          # already gone

    def test_watchlist_lists_pending_offenders(self):
        m = self._mgr()                       # auth threshold 3, authz 5
        for _ in range(2):
            m.register_offense("203.0.113.30", "login_failed")
        for _ in range(4):
            m.register_offense("198.51.100.40", "forbidden")
        watch = {o["ip"]: o for o in m.list_offenders()}
        assert watch["203.0.113.30"]["total"] == 2
        assert watch["203.0.113.30"]["remaining"] == 1      # 3 - 2
        assert watch["198.51.100.40"]["remaining"] == 1      # 5 - 4
        # Closest-to-ban is sorted first.
        assert m.list_offenders()[0]["remaining"] == 1

    def test_banned_ip_leaves_watchlist(self):
        m = self._mgr()                       # threshold 3
        for _ in range(3):                    # reaches threshold → banned
            m.register_offense("203.0.113.31", "login_failed")
        assert m.is_banned("203.0.113.31")[0]
        assert "203.0.113.31" not in {o["ip"] for o in m.list_offenders()}

    def test_whitelisted_never_in_watchlist(self):
        m = self._mgr(extra_whitelist=["10.0.0.0/8"])
        for _ in range(2):
            m.register_offense("10.1.2.3", "login_failed")
        assert m.list_offenders() == []

    def test_disabled_never_blocks(self):
        m = self._mgr(enabled=False)
        m.ban("203.0.113.1", duration_secs=60)               # ban recorded…
        assert not m.is_banned("203.0.113.1")[0]             # …but disabled ⇒ inert

    def test_expired_ban_stops_blocking(self):
        m = self._mgr(durations=[1])
        ip = "203.0.113.9"
        for _ in range(3):
            m.register_offense(ip, "login_failed")
        assert m.is_banned(ip)[0]
        time.sleep(1.1)
        assert not m.is_banned(ip)[0]


# ──────────────────────────────────────────────────────────────────────────────
# Persistent store round-trip
# ──────────────────────────────────────────────────────────────────────────────
class TestIpBanStore:
    def test_upsert_load_delete(self, admin):
        store = admin._ipban_store
        now = time.time()
        store.upsert("203.0.113.20", {
            "reason": "login_failed", "category": "login_failed", "level": 2,
            "offenses": 7, "banned_at": now, "until": now + 3600,
            "first_seen": now, "by": "system", "detail": "",
        })
        rows = store.load_active(now)
        row = next((r for r in rows if r["ip"] == "203.0.113.20"), None)
        assert row and row["level"] == 2 and row["until"] > now
        assert store.delete("203.0.113.20") is True
        assert not any(r["ip"] == "203.0.113.20" for r in store.load_active(now))

    def test_permanent_survives_load(self, admin):
        store = admin._ipban_store
        now = time.time()
        store.upsert("203.0.113.21", {"reason": "manual", "level": 5, "offenses": 1,
                                      "banned_at": now, "until": None, "first_seen": now,
                                      "by": "admin"})
        rows = store.load_active(now)
        row = next((r for r in rows if r["ip"] == "203.0.113.21"), None)
        assert row and row["until"] is None
        store.delete("203.0.113.21")


# ──────────────────────────────────────────────────────────────────────────────
# WebAdmin integration (gate + offense capture + API)
# ──────────────────────────────────────────────────────────────────────────────
class TestIpBanIntegration:
    _ATTACKER = {"REMOTE_ADDR": "203.0.113.77"}

    def test_manual_ban_blocks_ip(self, admin, client):
        _login(client)
        r = client.post("/api/v1/ipbans", json={"ip": "203.0.113.77", "reason": "manual"})
        assert r.status_code == 200 and r.get_json()["ok"]
        # A request from the banned IP is rejected up-front (before auth).
        blocked = client.get("/login", environ_base=self._ATTACKER)
        assert blocked.status_code == 403
        # The admin (loopback, whitelisted) is unaffected.
        assert client.get("/api/v1/ipbans").status_code == 200

    def test_unban_via_api(self, admin, client):
        _login(client)
        admin._ipban.ban("203.0.113.78", duration_secs=600, reason="manual")
        assert client.get("/login", environ_base={"REMOTE_ADDR": "203.0.113.78"}).status_code == 403
        r = client.delete("/api/v1/ipbans/203.0.113.78")
        assert r.status_code == 200 and r.get_json()["ok"]
        assert client.get("/login", environ_base={"REMOTE_ADDR": "203.0.113.78"}).status_code != 403

    def test_offenses_auto_ban(self, admin, client):
        admin._ipban.configure(auth_threshold=3, auth_window=600)
        ip = {"REMOTE_ADDR": "198.51.100.44"}
        # Unauthenticated hits on a protected API return 401 → 'unauthorized' offenses.
        for _ in range(3):
            assert client.get("/api/v1/users", environ_base=ip).status_code == 401
        # Threshold reached → the IP is now jailed and blocked with 403.
        assert client.get("/api/v1/users", environ_base=ip).status_code == 403

    def test_whitelisted_ip_rejected_by_api(self, admin, client):
        _login(client)
        r = client.post("/api/v1/ipbans", json={"ip": "127.0.0.1"})
        assert r.status_code == 400            # loopback is whitelisted → refused

    def test_watchlist_via_api(self, admin, client):
        admin._ipban.configure(auth_threshold=5, auth_window=600)
        ip = {"REMOTE_ADDR": "198.51.100.77"}
        for _ in range(3):                       # 3 offenses, below threshold (5)
            client.get("/api/v1/users", environ_base=ip)
        _login(client)
        data = client.get("/api/v1/ipbans").get_json()
        watch = {o["ip"]: o for o in data["offenders"]}
        assert "198.51.100.77" in watch
        assert watch["198.51.100.77"]["total"] == 3
        assert watch["198.51.100.77"]["remaining"] == 2      # 5 - 3
        assert not data["bans"]                              # not banned yet

    def test_clear_watchlist_via_api(self, admin, client):
        admin._ipban.configure(auth_threshold=10, auth_window=600)
        ip = {"REMOTE_ADDR": "198.51.100.88"}
        for _ in range(3):
            client.get("/api/v1/users", environ_base=ip)
        _login(client)
        assert any(o["ip"] == "198.51.100.88"
                   for o in client.get("/api/v1/ipbans").get_json()["offenders"])
        r = client.post("/api/v1/ipbans/clear", json={"ip": "198.51.100.88"})
        assert r.status_code == 200 and r.get_json()["cleared"]
        assert not client.get("/api/v1/ipbans").get_json()["offenders"]

    def test_history_via_api(self, admin, client):
        admin._ipban.configure(auth_threshold=10, auth_window=600)
        ip = {"REMOTE_ADDR": "198.51.100.99"}
        for _ in range(2):
            client.get("/api/v1/users", environ_base=ip)
        _login(client)
        hist = client.get("/api/v1/ipbans/history?ip=198.51.100.99").get_json()["history"]
        assert len(hist) == 2
        assert all(h["category"] == "unauthorized" and "ts" in h for h in hist)

    def test_whitelist_crud_and_effect(self, admin, client):
        _login(client)
        r = client.post("/api/v1/ipbans/whitelist",
                        json={"value": "192.168.77.0/24", "description": "Office"})
        assert r.status_code == 200
        entry = r.get_json()["entry"]
        assert entry["value"] == "192.168.77.0/24" and entry["description"] == "Office"
        # The entry records who added it and when.
        assert entry["created_by"] == "admin" and entry["created_at"] > 0
        # Effective immediately: an IP in the range is now whitelisted.
        assert admin._ipban.is_whitelisted("192.168.77.10")
        # Listed + validated (bad value rejected).
        assert client.post("/api/v1/ipbans/whitelist", json={"value": "nope"}).status_code == 400
        wl = client.get("/api/v1/ipbans/whitelist").get_json()["whitelist"]
        listed = next(e for e in wl if e["value"] == "192.168.77.0/24")
        assert listed["created_by"] == "admin" and listed["created_at"] > 0
        # Delete lifts the exemption.
        assert client.delete("/api/v1/ipbans/whitelist/" + entry["uid"]).status_code == 200
        assert not admin._ipban.is_whitelisted("192.168.77.10")

    def test_block_actions(self, admin, client):
        admin._ipban.ban("203.0.113.201", duration_secs=900)
        att = {"REMOTE_ADDR": "203.0.113.201"}
        admin._ipban_services.set_action("web", "page")
        r = client.get("/login", environ_base=att)
        assert r.status_code == 403 and b"error-card" in r.data
        admin._ipban_services.set_action("web", "minimal")
        r = client.get("/login", environ_base=att)
        assert r.status_code == 403 and b"error-card" not in r.data and r.data
        admin._ipban_services.set_action("web", "reject")
        r = client.get("/login", environ_base=att)
        assert r.status_code == 403 and r.data == b""

    def test_per_ban_action_override(self, admin, client):
        _login(client)
        admin._ipban_services.set_action("web", "page")
        admin._ipban.ban("203.0.113.211", duration_secs=900)
        att = {"REMOTE_ADDR": "203.0.113.211"}
        # Override this ban to 'reject' (empty) while the global stays 'page'.
        r = client.post("/api/v1/ipbans/action",
                        json={"ip": "203.0.113.211", "action": "reject"})
        assert r.status_code == 200 and r.get_json()["ok"]
        assert client.get("/login", environ_base=att).data == b""      # reject wins
        # It rides along in the ban listing so the UI can show/edit it.
        bans = {b["ip"]: b for b in client.get("/api/v1/ipbans").get_json()["bans"]}
        assert bans["203.0.113.211"]["block_action"] == "reject"
        # Clearing the override falls back to the global styled page.
        client.post("/api/v1/ipbans/action", json={"ip": "203.0.113.211", "action": ""})
        assert b"error-card" in client.get("/login", environ_base=att).data

    def test_set_action_unknown_ip(self, admin, client):
        _login(client)
        r = client.post("/api/v1/ipbans/action", json={"ip": "203.0.113.212", "action": "page"})
        assert r.status_code == 404

    def test_static_served_when_banned(self, admin, client):
        admin._ipban.ban("203.0.113.202", duration_secs=900)
        r = client.get("/static/css/web_admin.css",
                       environ_base={"REMOTE_ADDR": "203.0.113.202"})
        assert r.status_code != 403       # assets exempt so the styled page renders

    def test_layout_exposes_ipban_config_tab(self, admin, client):
        # fail2ban CONFIG (settings + Exposed services) lives in its own config sub-tab;
        # the operational surface (banned IPs / watchlist / history / whitelist) is a
        # top-level section (dashboard #tab-ipban), not in the config layout.
        _login(client)
        lay = client.get("/api/v1/config/layout").get_json()
        assert "ipban" in {t["id"] for t in lay["tabs"]}           # config sub-tab exists
        by_id = {c["id"]: c for c in lay["cards"]}
        assert by_id["ipban"]["tab"] == "ipban"                    # settings card
        assert by_id["ipban_services"]["tab"] == "ipban"           # Exposed services card
        # the operational cards are NOT part of the config layout
        assert not ({"ipban_manage", "ipban_whitelist", "ipban_history"} & set(by_id))

    def test_banlist_active_only_history_keeps_all(self, admin, client):
        _login(client)
        admin._ipban.ban("203.0.113.90", duration_secs=900)     # active
        admin._ipban.ban("203.0.113.91", duration_secs=1)       # will expire
        time.sleep(1.1)
        # The active list drops the expired ban…
        bans = {b["ip"] for b in client.get("/api/v1/ipbans").get_json()["bans"]}
        assert "203.0.113.90" in bans and "203.0.113.91" not in bans
        # …but the history keeps every ban event.
        log = client.get("/api/v1/ipbans/banlog").get_json()["history"]
        ips = {h["ip"] for h in log if h["event"] == "banned"}
        assert {"203.0.113.90", "203.0.113.91"} <= ips

    def test_banlog_records_escalation_and_unban(self, admin, client):
        _login(client)
        admin._ipban.ban("203.0.113.92", duration_secs=900)
        admin._ipban.ban("203.0.113.92", duration_secs=900)     # escalate → level 2
        admin._ipban.unban("203.0.113.92")
        events = [h["event"] for h in client.get(
            "/api/v1/ipbans/banlog?ip=203.0.113.92").get_json()["history"]]
        assert events == ["unbanned", "escalated", "banned"]     # most recent first

    def test_unban_reason_recorded(self, admin, client):
        _login(client)
        admin._ipban.ban("203.0.113.93", duration_secs=900)
        # Lifting via the API with a reason records it on the 'unbanned' history event.
        assert client.delete(
            "/api/v1/ipbans/203.0.113.93?reason=false%20positive").status_code == 200
        log = client.get("/api/v1/ipbans/banlog?ip=203.0.113.93").get_json()["history"]
        unbanned = next(h for h in log if h["event"] == "unbanned")
        assert unbanned["reason"] == "false positive"


class TestIpBanServiceRegistry:
    """Services declare their ports + supported block actions; the gate reads them."""

    def test_web_service_registered(self, admin, client):
        _login(client)
        svcs = {s["id"]: s for s in client.get("/api/v1/ipbans/services").get_json()["services"]}
        assert "web" in svcs
        assert set(svcs["web"]["supports"]) == {"page", "minimal", "reject", "json"}
        assert svcs["web"]["endpoints"][0]["proto"] == "tcp"

    def test_set_service_action_drives_gate(self, admin, client):
        _login(client)
        r = client.post("/api/v1/ipbans/services/action",
                        json={"service": "web", "action": "reject"})
        assert r.status_code == 200 and r.get_json()["ok"]
        admin._ipban.ban("203.0.113.240", duration_secs=900)
        # web action 'reject' → empty body (no per-ban override set).
        assert client.get("/login", environ_base={"REMOTE_ADDR": "203.0.113.240"}).data == b""

    def test_unsupported_action_refused(self, admin):
        reg = admin._ipban_services
        reg.register(id="syslog", label_key="ipban_svc_syslog",
                     supports=("drop",), default="drop", endpoints=[{"port": 514, "proto": "udp"}])
        # syslog only supports 'drop' — 'page' is dropped, action stays the default.
        assert reg.set_action("syslog", "page") is True
        assert reg.action_for("syslog") == "drop"

    def test_service_action_persists(self, admin):
        admin._ipban_services.set_action("web", "minimal")
        assert admin._ipban_store.service_actions().get("web") == "minimal"
        # A fresh registry on the same store reloads it (survives a restart).
        from lib.security.ipban_services import IpBanServiceRegistry
        reg2 = IpBanServiceRegistry()
        reg2.load_actions(admin._ipban_store.service_actions())
        reg2.register(id="web", label_key="x", supports=("page", "minimal"), default="page")
        assert reg2.action_for("web") == "minimal"

    def test_unknown_service_action_404(self, admin, client):
        _login(client)
        r = client.post("/api/v1/ipbans/services/action",
                        json={"service": "nope", "action": "page"})
        assert r.status_code == 404
