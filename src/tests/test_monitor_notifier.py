#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the monitor's cycle-scoped MonitorNotifier: routing by the notifications
matrix, grouped Telegram (emoji + summary), a single digest Email, and per-event
Webhooks."""

import pytest

from lib.core.notify.monitor_notifier import MonitorNotifier


class _FakeWA:
    """Minimal dispatcher `wa` contract."""
    _CONFIG_FILE = 'config.json'

    def __init__(self, cfg):
        self._cfg = cfg
        self.webhooks = [{'id': '1', 'name': 'wh', 'enabled': True, 'url': 'http://x'}]

    def _read_config_file(self, _f):
        return self._cfg

    def _dbg(self, *a, **k):
        pass

    def _load_webhooks(self, *, decrypt=True):
        return self.webhooks

    def _config_section(self, name):
        return self._cfg.get(name, {})


def _cfg(**matrix):
    base = {
        'notifications': {
            'telegram_on_down': True, 'telegram_on_recovery': True, 'telegram_on_warn': False,
            'email_on_down': True, 'email_on_recovery': False, 'email_on_warn': False,
            'webhook_on_down': True, 'webhook_on_recovery': False, 'webhook_on_warn': False,
        },
        'telegram': {'token': 't', 'chat_id': 'c', 'group_messages': True},
        'email': {'enabled': True, 'provider': 'smtp', 'subject_prefix': '[SS]', 'lang': 'en_EN'},
    }
    base['notifications'].update(matrix)
    return base


@pytest.fixture()
def sent(monkeypatch):
    """Capture every channel send; the real senders are stubbed out."""
    rec = {'tg': [], 'email': [], 'webhook': []}
    monkeypatch.setattr('lib.providers.telegram.send_telegram',
                        lambda token, chat, text, **k: (rec['tg'].append(text), (True, 200, 'ok'))[1])
    monkeypatch.setattr('lib.core.notify.email.notify._dispatch',
                        lambda cfg, *, subject, body_html, recipients: (
                            rec['email'].append((subject, body_html)), (True, 'sent'))[1])
    monkeypatch.setattr('lib.core.notify.webhook.notify.send_all',
                        lambda wa, **kw: (rec['webhook'].append(kw), (True, 'ok'))[1])
    return rec


def _add_three(n):
    n.add('down', 'ping', 'host1', 'ping down')
    n.add('recovery', 'pve', 'host2', 'pve back')
    n.add('warn', 'disk', 'host3', 'disk warn')


class TestRouting:

    def test_matrix_selects_channels_per_kind(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg()))
        _add_three(n)
        n.flush(public_url='https://ss.example')
        # telegram: down + recovery enabled (warn off) → one grouped message
        assert len(sent['tg']) == 1
        # email: only down enabled → one digest email
        assert len(sent['email']) == 1
        # webhook: only down enabled, per-event → one call
        assert len(sent['webhook']) == 1

    def test_nothing_enabled_sends_nothing(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg(telegram_on_down=False, telegram_on_recovery=False,
                                         email_on_down=False, webhook_on_down=False)))
        _add_three(n)
        res = n.flush()
        assert res == {} and not any(sent.values())

    def test_flush_clears_the_buffer(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg()))
        n.add('down', 'ping', 'h', 'x')
        n.flush()
        assert not n.has_pending()
        n.flush()                       # second flush: nothing buffered
        assert len(sent['tg']) == 1     # not sent again


class TestTelegramGrouping:

    def test_grouped_message_has_sections_lines_and_summary(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg()))
        _add_three(n)                                    # down/ping + recovery/pve (warn off)
        n.flush(public_url='https://ss.example')
        assert len(sent['tg']) == 1                      # one grouped message
        msg = sent['tg'][0]
        assert '❎' in msg and '✅' in msg               # down + recovery icons
        assert 'Issues' in msg and 'Recovered' in msg    # the two sections
        assert msg.index('Issues') < msg.index('Recovered')
        assert 'disk warn' not in msg                    # warn alert not routed to telegram
        assert 'ping down' in msg and 'pve back' in msg
        assert 'Summary' in msg and '2 new message' in msg
        assert 'https://ss.example/status' in msg

    def test_ungrouped_sends_one_message_per_line_plus_summary(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg()))          # group off:
        n._wa._cfg['telegram']['group_messages'] = False
        _add_three(n)
        n.flush()
        # 2 alerts routed to telegram + 1 summary line = 3 messages
        assert len(sent['tg']) == 3


class TestEmailDigest:

    def test_single_digest_lists_every_routed_alert(self, sent):
        # route down + recovery + warn all to email
        n = MonitorNotifier(_FakeWA(_cfg(email_on_recovery=True, email_on_warn=True)))
        _add_three(n)
        n.flush()
        assert len(sent['email']) == 1
        subject, body = sent['email'][0]
        assert subject == '[SS] host1: 3 alert(s)' or 'alert' in subject
        assert 'ping' in body and 'pve' in body and 'disk' in body   # all rows present


class TestWebhookPerEvent:

    def test_one_call_per_alert(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg(webhook_on_recovery=True, webhook_on_warn=True)))
        _add_three(n)
        n.flush()
        assert len(sent['webhook']) == 3
        kinds = sorted(c['kind'] for c in sent['webhook'])
        assert kinds == ['down', 'recovery', 'warn']


class TestEmailGrouping:

    def test_digest_splits_issues_and_recovered(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg(email_on_recovery=True, email_on_warn=True)))
        n.add('down', 'cpu', 'PVE02', 'CPU 95%')
        n.add('recovery', 'ntp', 'NS1', 'ntp ok')
        n.flush()
        _subject, body = sent['email'][0]
        assert 'Issues' in body and 'Recovered' in body
        assert body.index('Issues') < body.index('Recovered')   # issues zone first

    def test_digest_groups_rows_by_item(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg(email_on_recovery=True)))
        n.add('recovery', 'cpu', 'PVE04', 'CPU ok')
        n.add('recovery', 'ram_swap', 'PVE04', 'RAM ok')   # same item → one item cell
        n.flush()
        _subject, body = sent['email'][0]
        assert body.count('>PVE04<') == 1   # grouped: item shown once for its two rows


class TestPlainText:

    def test_plain_strips_telegram_markdown(self):
        from lib.core.notify.monitor_notifier import _plain
        assert _plain('CPU (*NS1*) 90% \\[host]') == 'CPU (NS1) 90% [host]'

    def test_email_body_has_no_markdown(self, sent):
        n = MonitorNotifier(_FakeWA(_cfg()))
        n.add('down', 'ntp', 'NS1', 'NTP: *NS1* offset high')   # module msg is Telegram-formatted
        n.flush()
        _subject, body = sent['email'][0]
        assert '*NS1*' not in body and 'NS1' in body
