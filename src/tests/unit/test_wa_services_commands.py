#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The per-service command menu: what it offers, and that it looks like the rest of the panel.

Two separate things are pinned here, and the second is the one that bites.

**The menu entries carry an icon.** Start and Stop sit a centimetre away with one each, so a
text-only dropdown beside them reads as unfinished. The glyph is chosen per COMMAND rather
than per service, because "Reload" means the same thing wherever it appears and must not be
one icon under Monitor and another under Syslog.

**The frontend list must not claim a command the service cannot run.** Which commands a
service offers lives in a hardcoded map in the renderer, while what it actually accepts lives
in that service's ``_apply_command``. Two declarations of one fact, and they have already
drifted — syslog accepts ``clear_status`` as an alias of ``prune`` and the panel never offers
it. That direction is harmless; the other one is not: an entry the backend rejects is a menu
item that fails every time it is pressed. The check below is that direction only, deliberately.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_services_commands.py`` lives in
``tests/integration/test_wa_services_commands.py``."""

import io
import os
import re


SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'services',
                      '_render.html')


def _render() -> str:
    return io.open(RENDER, encoding='utf-8-sig').read()


def _declared() -> dict:
    """``{service: [command, …]}`` as the renderer declares it."""
    m = re.search(r'const _SVC_COMMANDS = \{(.*?)\};', _render(), re.S)
    assert m, 'the per-service command map is gone'
    return {k: re.findall(r"'([^']+)'", v)
            for k, v in re.findall(r'(\w+)\s*:\s*\[([^\]]*)\]', m.group(1))}


def _fn(src: str, name: str) -> str:
    """The body of a top-level JS function in the renderer."""
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _icons() -> dict:
    m = re.search(r'const _SVC_CMD_ICON = \{(.*?)\};', _render(), re.S)
    assert m, 'the per-command icon map is gone'
    return dict(re.findall(r"(\w+)\s*:\s*'([^']+)'", m.group(1)))


class TestEveryEntryHasAnIcon:

    def test_the_menu_renders_one(self):
        assert '_SVC_CMD_ICON[a]' in _render(), (
            'the dropdown entries are text-only again, next to Start/Stop buttons that '
            'both carry an icon')

    def test_every_offered_command_has_one(self):
        icons = _icons()
        missing = sorted({c for cmds in _declared().values() for c in cmds} - set(icons))
        assert not missing, f'commands with no icon: {missing}'

    def test_the_icon_belongs_to_the_command_not_the_service(self):
        """A per-service icon map would let the same command wear two faces."""
        assert not re.search(r'_SVC_CMD_ICON\s*\[\s*meta\.key', _render())

    def test_run_now_does_not_borrow_the_start_glyph(self):
        """It runs one cycle now; it does not start the service. Two controls a centimetre
        apart must not claim the same action."""
        icons = _icons()
        assert 'play' not in icons.get('run_now', ''), \
            'Run Now wears the Start icon — pressing one and meaning the other is the point'


class TestTheMenuOnlyOffersWhatTheServiceAccepts:

    def _accepted(self, service: str) -> set:
        """The actions a service's ``_apply_command`` actually branches on.

        The hook is looked up across the package rather than in one file: services whose
        embedded twin mixes in a manager keep it in ``manager.py``, ipban has no worker
        loop and defines it on the twin itself (``embedded.py``). Where it lives is the
        service's business; that it agrees with the menu is not.
        """
        pkg = os.path.join(SRC, 'lib', 'services', service)
        for name in sorted(os.listdir(pkg)):
            if not name.endswith('.py'):
                continue
            src = io.open(os.path.join(pkg, name), encoding='utf-8-sig').read()
            m = re.search(r'def _apply_command\(.*?\n(?=\n {4}(?:def|#)|\Z)', src, re.S)
            if m:
                break
        else:
            raise AssertionError(f'{service} offers commands but defines no _apply_command')
        body = m.group(0)
        equals = re.findall(r"action == '([^']+)'", body)
        groups = re.findall(r"action in \(([^)]*)\)", body)      # action in ('a', 'b')
        return set(equals) | {a for g in groups for a in re.findall(r"'([^']+)'", g)}

    def test_no_menu_entry_is_rejected_by_its_service(self):
        """An entry the backend does not implement is a button that fails every time. The
        reverse — a command implemented but not offered — is left alone: it is a decision
        about the UI, not a broken control."""
        for service, cmds in _declared().items():
            accepted = self._accepted(service)
            unknown = sorted(set(cmds) - accepted)
            assert not unknown, (
                f'{service} offers {unknown} but its _apply_command only handles '
                f'{sorted(accepted)}')

    def test_the_services_that_offer_commands_implement_the_hook(self):
        """`_accepted` raises if the package has no `_apply_command` at all — a menu with
        nothing behind it."""
        for service in _declared():
            assert self._accepted(service), f'{service} implements no command'

    def test_the_command_is_reachable_from_the_queue(self):
        """The drain looks the hook up on the EMBEDDED object (`getattr(self,
        '_apply_command')`), so defining it on a class the twin does not inherit would
        queue commands nobody ever runs — they would sit claimed and unanswered."""
        emb = io.open(os.path.join(SRC, 'lib', 'services', 'ipban', 'embedded.py'),
                      encoding='utf-8-sig').read()
        assert re.search(r'^    def _apply_command\(', emb, re.M), \
            'ipban has no worker loop, so its hook belongs on the twin itself'


class TestTheDestructiveOnesAskFirst:
    """Prune and Clear status delete things that do not come back, and they sit in the same
    dropdown as Reload — one row apart, same colour, no gap. The only thing between a
    misplaced click and gone data is being asked."""

    def test_they_are_marked_as_destructive(self):
        marked = set(re.findall(r"_SVC_CMD_DESTRUCTIVE = new Set\(\[([^\]]*)\]", _render()))
        assert marked, 'nothing declares which commands destroy something'
        names = set(re.findall(r"'([^']+)'", ' '.join(marked)))
        assert {'clear_status', 'prune'} <= names

    def test_the_handler_confirms_before_sending(self):
        body = _fn(_render(), 'servicesCommand')
        assert '_SVC_CMD_DESTRUCTIVE.has(action)' in body
        assert 'showConfirmModal(' in body
        # The request must not be issued on the way to the modal.
        assert 'apiPost(' not in body, \
            'servicesCommand still sends the command itself — the confirmation would be ' \
            'asked while the deletion was already in flight'

    def test_it_is_the_in_app_modal_not_the_browser_one(self):
        src = _render()
        assert 'confirm(' not in src.replace('showConfirmModal(', ''), \
            'a browser confirm() blocks the page and cannot be styled or translated'

    def test_a_harmless_command_is_not_gated(self):
        """Reload and Run now change nothing that cannot be redone; asking every time would
        teach people to click through the dialog without reading it."""
        marked = re.search(r"_SVC_CMD_DESTRUCTIVE = new Set\(\[([^\]]*)\]", _render()).group(1)
        assert 'reload' not in marked and 'run_now' not in marked

    def test_the_message_names_what_is_being_emptied(self):
        """The same command destroys different things depending on where it is pressed —
        Prune under Syslog drops stored messages, under fail2ban offence counters and the ban
        log. A dialog that does not say what you are about to lose is a speed bump."""
        body = _fn(_render(), 'servicesCommand')
        assert re.search(r"tf\('svc_cmd_confirm_' \+ action,\s*\w+\)", body), \
            'the confirmation takes no argument, so it cannot name the service'

    def test_every_destructive_command_has_its_wording(self):
        marked = re.search(r"_SVC_CMD_DESTRUCTIVE = new Set\(\[([^\]]*)\]", _render()).group(1)
        for lang in ('es_ES', 'en_EN'):
            src = io.open(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'),
                          encoding='utf-8-sig').read()
            for cmd in re.findall(r"'([^']+)'", marked):
                key = f"'svc_cmd_confirm_{cmd}'"
                assert key in src, f'{lang} has no confirmation text for {cmd}'
                line = next(ln for ln in src.splitlines() if ln.strip().startswith(key))
                assert '{}' in line, f'{lang}: {cmd} confirmation names no service'


class TestTheLabelsExist:

    def test_every_command_is_translated(self):
        for lang in ('es_ES', 'en_EN'):
            src = io.open(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'),
                          encoding='utf-8-sig').read()
            for cmd in {c for cmds in _declared().values() for c in cmds}:
                assert f"'svc_cmd_{cmd}'" in src, f'{lang} has no label for {cmd}'
