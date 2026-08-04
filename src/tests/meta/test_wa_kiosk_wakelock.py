#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A wall display that goes to sleep is not a wall display.

The Overview's fullscreen (kiosk) mode exists to be left running on a monitor so people can
glance at it. That promise is broken by the operating system, not by the panel: ten minutes
of no keyboard and the screen dims, the screensaver starts, the session locks — and whatever
went down at 3 a.m. was never on screen for anyone to see.

Kiosk mode now takes a **screen wake lock** while it is up. What these guards pin is the part
that is easy to get wrong and impossible to notice by looking at it:

* **the lock is re-taken when the page becomes visible again.** The browser releases it on its
  own whenever the page is hidden — another tab, a minimised window — and never takes it back.
  Without the ``visibilitychange`` handler the screen keeps itself awake exactly until the
  first tab switch, and then quietly stops, which is the worst kind of failure: the mode still
  *looks* enabled;
* **leaving says so.** Both exits — the button and pressing Esc out of fullscreen — release
  the lock, so a panel nobody is watching is not holding someone's laptop awake;
* **it never fails silently.** The Wake Lock API needs a secure context, and a self-hosted
  panel is usually reached over plain ``http://`` on a LAN, where ``navigator.wakeLock`` is
  simply undefined. Failing quietly there would leave someone convinced their screen is pinned
  awake while it sleeps every night, so that case warns.

Static guards over the Overview render partial, in the same spirit as the rest of the panel's
UI tests.
"""

import io
import os
import re

from tests.helpers import _fn

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'overview',
                      '_render.html')


def _src() -> str:
    return io.open(RENDER, encoding='utf-8-sig').read()


class TestTheScanItself:
    """If these fail the guards below are meaningless, not the feature."""

    def test_the_partial_is_found(self):
        assert os.path.isfile(RENDER), f'overview render partial not at {RENDER}'

    def test_the_kiosk_toggle_is_still_there(self):
        assert 'function _dwToggleKiosk(' in _src(), \
            'the kiosk toggle was renamed — these guards need updating with it'


class TestKioskHoldsTheScreenAwake:

    def test_entering_kiosk_takes_the_lock(self):
        body = _fn(_src(), '_dwToggleKiosk')
        entering = body.split('} else {')[0]
        assert '_kioskWakeLockOn(' in entering, \
            'kiosk mode starts without asking for a wake lock — the screen will sleep'

    def test_the_lock_is_a_screen_lock(self):
        assert "wakeLock.request('screen')" in _src(), \
            "the only wake lock type that keeps a display on is 'screen'"

    def test_leaving_kiosk_releases_it(self):
        body = _fn(_src(), '_dwToggleKiosk')
        leaving = body.split('} else {')[1]
        assert '_kioskWakeLockOff(' in leaving, \
            'leaving kiosk keeps the machine awake for a screen nobody is watching'

    def test_escaping_fullscreen_releases_it_too(self):
        """Esc leaves fullscreen without going through the toggle."""
        src = _src()
        hook = src.split('_onFsChange = ()')[1].split('};')[0]
        assert '_kioskWakeLockOff(' in hook, \
            'pressing Esc drops the kiosk styling but keeps holding the wake lock'


class TestTheLockSurvivesBeingHidden:
    """The one that cannot be seen by reading the happy path."""

    def test_visibility_change_re_acquires(self):
        src = _src()
        assert "addEventListener('visibilitychange'" in src, \
            ('nothing re-takes the wake lock: the browser drops it when the page is hidden '
             'and never takes it back, so the display sleeps after the first tab switch')
        handler = src.split("addEventListener('visibilitychange'")[1]
        assert '_kioskWakeLockOn(' in handler

    def test_it_only_re_acquires_while_still_in_kiosk(self):
        handler = _src().split("addEventListener('visibilitychange'")[1][:400]
        assert 'ss-kiosk' in handler, \
            'the re-acquire does not check kiosk is still on — it would pin the screen awake ' \
            'long after the user left fullscreen'

    def test_the_re_acquire_does_not_nag(self):
        """The warning belongs to the moment kiosk starts, not to every tab switch."""
        handler = _src().split("addEventListener('visibilitychange'")[1][:400]
        assert re.search(r'_kioskWakeLockOn\(\s*true\s*\)', handler), \
            'the silent re-acquire passes no quiet flag — every tab switch would raise a toast'


class TestItNeverFailsSilently:

    def test_an_unavailable_api_warns(self):
        """Plain http:// on a LAN — the usual way a self-hosted panel is reached."""
        body = _fn(_src(), '_kioskWakeLockOn')
        assert 'navigator.wakeLock' in body
        assert 'dashboard_wakelock_insecure' in body, \
            'no wake lock support and no warning: the screen sleeps and nobody knows why'

    def test_a_refused_lock_warns(self):
        body = _fn(_src(), '_kioskWakeLockOn')
        assert 'dashboard_wakelock_failed' in body, \
            'a refused request (power saving) is swallowed'

    def test_every_message_is_translated(self):
        from lib.i18n.lang import en_EN, es_ES
        for key in ('dashboard_wakelock_insecure', 'dashboard_wakelock_failed',
                    'dashboard_wakelock_fallback'):
            assert key in en_EN.LANG, f'{key} missing from en_EN'
            assert key in es_ES.LANG, f'{key} missing from es_ES'


class TestTheFallbackForPlainHttp:
    """Without a secure context the API is gone, so playback stands in for it."""

    def test_the_api_is_still_preferred(self):
        body = _fn(_src(), '_kioskWakeLockOn')
        assert body.index('navigator.wakeLock') < body.index('_kioskNoSleepOn'), \
            'the fallback is reached before the real API — it must be the second choice'

    def test_the_fallback_runs_when_the_api_is_missing(self):
        assert '_kioskNoSleepOn(' in _fn(_src(), '_kioskWakeLockOn'), \
            'no fallback on plain http://: the wall display just sleeps'

    def test_it_announces_itself(self):
        assert 'dashboard_wakelock_fallback' in _fn(_src(), '_kioskWakeLockOn'), \
            'a best-effort workaround that claims nothing is worse than the warning it replaced'

    def test_the_clip_keeps_producing_frames(self):
        """A static canvas stops emitting, and a stalled stream stops counting as playback."""
        body = _fn(_src(), '_kioskNoSleepOn')
        assert 'captureStream' in body
        assert 'setInterval' in body, \
            'nothing redraws the canvas: the stream stalls and the screen sleeps anyway'

    def test_the_clip_is_muted_and_looping(self):
        body = _fn(_src(), '_kioskNoSleepOn')
        assert 'muted = true' in body, 'an unmuted clip would be blocked by autoplay policy'
        assert 'loop = true' in body

    def test_it_is_rendered_not_hidden(self):
        """`display:none` would stop the browser counting it as playing — the whole point."""
        body = _fn(_src(), '_kioskNoSleepOn')
        assert "className = 'ss-nosleep'" in body
        css = io.open(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'),
                      encoding='utf-8-sig').read()
        block = css.split('.ss-nosleep')[1].split('}')[0]
        assert 'display: none' not in block and 'visibility: hidden' not in block, \
            'the keep-awake clip is hidden outright, which stops it working'

    def test_leaving_stops_it(self):
        body = _fn(_src(), '_kioskWakeLockOff')
        assert '_kioskNoSleepOff(' in body, \
            'the clip keeps playing after kiosk mode ends — a hidden video running forever'

    def test_stopping_releases_the_camera_stream_and_timer(self):
        body = _fn(_src(), '_kioskNoSleepOff')
        assert 'clearInterval' in body, 'the redraw timer outlives the video'
        assert '.stop()' in body, 'the media stream track is never stopped'
        assert '.remove()' in body, 'the video element is left in the DOM'
