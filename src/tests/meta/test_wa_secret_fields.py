#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A stored secret is not a login, and the browser must not be told that it is.

Reported from the panel: **Firefox offers to save a login on every reload — user `1`, password
`public`.** Those are the SNMP version and the community string of a monitored device. The
password manager had found an `<input type="password">`, taken the nearest field for a
username, and decided the page was a sign-in form.

The prompt is the harmless half. The other half is that the same machinery **fills** those
fields: a saved password pasted into a community box is a value about to be sent to a device,
and saved from there into the configuration. A panel's secrets — community strings, webhook
signing keys, API tokens, an LDAP bind password used to test a bind — are not this site's
credentials, and nothing that treats them as such can be right.

So a secret is masked by the stylesheet on a plain text input, which no manager recognises,
and the browser's own field type is kept **only** as the fallback where that masking is not
supported: losing the masking would be far worse than the prompt it avoids. That trade is what
this file pins, in both directions — a fallback that never triggers would be a fallback nobody
noticed had stopped working, and a masking applied without checking would show secrets in
clear on an older browser.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
CTL = os.path.join(TPL, 'partials', 'core', '_field_ctl.html')
CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')


def _read(path):
    return io.open(path, encoding='utf-8-sig').read()


# Where a password input is the right answer: these ARE this site's credentials, and a browser
# offering to remember them is doing its job.
_REAL_LOGINS = (
    os.path.join('templates', 'login.html'),
    os.path.join('account', '_page.html'),          # change my own password
    os.path.join('modals', '_items.html'),          # reset a user's password
    os.path.join('modals', '_user.html'),           # create a user
)


def _templates():
    for root, _dirs, files in os.walk(TPL):
        for f in files:
            if f.endswith('.html'):
                yield os.path.join(root, f)


class TestASecretIsNotACredential:

    def test_nothing_but_a_real_login_writes_a_password_input(self):
        """Hand-written `type="password"` is the thing that summoned the doorhanger. The
        renderer decides now, because the decision depends on what the browser supports."""
        offenders = []
        for path in _templates():
            if any(path.endswith(tail) or tail in path for tail in _REAL_LOGINS):
                continue
            for i, line in enumerate(_read(path).splitlines(), 1):
                if 'type="password"' in line and not line.lstrip().startswith('//'):
                    offenders.append(f'{os.path.relpath(path, SRC)}:{i}')
        assert not offenders, (
            'a secret written as a password input — use secretInput(): ' + ', '.join(offenders))

    def test_the_real_logins_still_are_password_inputs(self):
        """The guard above must not be satisfiable by masking everything: this site's own
        sign-in and password changes are exactly where the manager should work."""
        for tail in _REAL_LOGINS:
            hits = [p for p in _templates() if p.endswith(tail) or tail in p]
            assert hits, f'{tail} is gone — this guard needs re-aiming'
            assert any('type="password"' in _read(p) for p in hits), tail


class TestTheMaskingNeverDegrades:

    def test_it_asks_the_browser_before_relying_on_it(self):
        """`-webkit-text-security` is what hides the value. Applied blind, a browser without
        it shows every secret in the panel in clear."""
        body = _read(CTL)
        assert 'CSS.supports' in body and 'text-security' in body

    def test_without_it_the_field_is_a_password_input_again(self):
        """The prompt is noise; an unmasked secret is not. The fallback is the whole reason
        this can be done at all."""
        body = _read(CTL)
        i = body.index('function secretInput')
        fn = body[i:body.index('\n}', i)]
        assert "'text' : 'password'" in fn.replace('"', "'")

    def test_the_class_only_goes_on_where_it_works(self):
        """A class that masks nothing on a browser that ignores it would look identical in the
        markup and be a plaintext field on screen."""
        body = _read(CTL)
        i = body.index('function secretInput')
        fn = body[i:body.index('\n}', i)]
        assert 'SS_TEXT_SECURITY ?' in fn and 'ss-masked' in fn

    def test_the_stylesheet_carries_the_masking(self):
        css = _read(CSS)
        assert re.search(r'\.ss-masked\s*\{[^}]*-webkit-text-security:\s*disc', css, re.S)

    def test_the_name_is_not_taken(self):
        """`.ss-secret` already means something else — the MFA shared secret printed for
        somebody to type into a phone. Two rules of one name is one of them not applying."""
        css = _read(CSS)
        assert '.ss-secret {' in css and 'text-security' not in css.split('.ss-secret {')[1][:200]


class TestTheOtherManagersAreToldToo:

    def test_the_field_opts_out_by_every_name_they_read(self):
        """1Password, LastPass and Bitwarden do not read `autocomplete`; they read their own
        attributes, and they are the ones that paste a vault entry into a community string."""
        body = _read(CTL)
        for attr in ('autocomplete="off"', 'data-1p-ignore', 'data-lpignore', 'data-bwignore'):
            assert attr in body, attr

    def test_every_masked_field_gets_them(self):
        """Both shapes come out of the one function, so neither can be given the attributes
        and the other forgotten."""
        body = _read(CTL)
        i = body.index('function secretInput')
        fn = body[i:body.index('\n}', i)]
        assert 'SS_SECRET_ATTRS' in fn
        assert fn.count('<input') == 1, 'two inputs is two places to forget one attribute'

    def test_the_callers_do_not_write_their_own(self):
        """A second `autocomplete` on the same tag is ignored by the parser, so a caller
        setting one is a caller believing something that is not happening."""
        for path in _templates():
            body = _read(path)
            if 'secretInput(' not in body:
                continue
            for i, line in enumerate(body.splitlines(), 1):
                if 'secretInput(' in line:
                    assert 'autocomplete=' not in line, f'{os.path.relpath(path, SRC)}:{i}'
