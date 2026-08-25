#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Javier Pastor (aka VSC55)
# <jpastor at cerebelum dot net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
""" Base class for modules. """

import concurrent.futures
import json
import os
from enum import Enum

import lib
from lib.config import ConfigTypeReturn
from lib.debug import DebugLevel
from lib.modules import ReturnModuleCheck
from lib.util.dict_files_path import DictFilesPath
from lib.modules.discovery.schemas import SchemaDiscovery
from lib.modules.host_binding import HostBinding
from lib.core.object_base import ObjectBase

# What is left here is what a check needs from its base: the run loop, config resolution,
# the module's own messages, and emitting a result. Scanning every module's schema.json moved
# to discovery/schemas.py — it answers questions ABOUT modules and needs no instance — and
# reaching the machine an item is bound to moved to host_binding.py.

__all__ = ['ModuleBase']

# Cache of a module's translated ``messages`` section, keyed by (module_dir, name, lang).
# Watchfuls are re-instantiated every cycle, so the cache must not live on the instance.
_MODULE_MSG_CACHE: dict = {}


class ModuleBase(SchemaDiscovery, HostBinding, ObjectBase):
    """ Base class for modules. """

    def __init__(self, obj_monitor, name=None):
        if not isinstance(obj_monitor, lib.Monitor):
            raise ValueError('Type not valid, only Monitor valid type.')

        self._monitor = obj_monitor
        if name:
            self._name_module = name
        else:
            self._name_module = __name__

        # Set var's
        self.paths = None
        self.dict_return = None

        # Init Var's
        self._init_var()

    #: The machine this run is about, or '' for the whole configuration.
    #:
    #: A check runs for everything the module has, and that is right for a cycle: the
    #: scheduler is asking "what is the state of the installation". It is the wrong answer to
    #: "collect this device now", which is about ONE machine and used to poll the other
    #: thirty-nine to get there — minutes of somebody else's devices for a number the operator
    #: asked about one of theirs, and a run that could not finish because a device three racks
    #: away was not answering.
    #:
    #: Set on the INSTANCE by whoever asks (`Monitor.check_module(only_host=…)`), never on the
    #: monitor: two runs may be in flight in one process and a scope on the shared object would
    #: be one run narrowing the other's.
    _host_scope = ''

    @property
    def host_scope(self) -> str:
        """The uid this run is narrowed to, or ''."""
        return str(getattr(self, '_host_scope', '') or '').strip()

    def _item_collections(self) -> set:
        """The module's own item collections, as its schema declares them.

        Everything else at the top of a schema is a `__dunder__` declaration; what is left is
        where the items live (`list` for most, `servers` for SNMP). Read from the schema and
        not from a list in the core, which would be the core naming a module's shape.
        """
        schema = getattr(self, 'ITEM_SCHEMA', None)
        if not isinstance(schema, dict):
            return set()
        return {k for k in schema if not str(k).startswith('__')}

    def _init_var(self):
        """ Initialize the variables of the module. """
        self.paths = DictFilesPath()
        self.dict_return = ReturnModuleCheck()

    def check(self):
        """ Check the module and return the result. """
        self.debug.debug_obj(self.name_module, self.dict_return.list, "Data Return")

    def report_progress(self, detail: str = '', *, step: str = '', scope: str = '',
                        n: int = 0, total: int = 0, state: str = '') -> None:
        """Say what this module is doing right now, to whoever is watching.

        Only somebody who pressed a button is ever listening (the infrastructure section's
        "collect now" installs the sink; a scheduler cycle does not), so this costs an
        attribute lookup the rest of the time and is safe to call from anywhere in a check.

        *detail* is the sentence — what is happening at this instant. *step* is the PHASE it
        belongs to, and repeating the same *step* keeps the same line: a run that reports
        "reading" forty times draws one line whose counter moves, not forty lines. *n* and
        *total* are that phase's progress when the module knows them.

        *scope* is WHICH THING the phase is about, and it is what makes the line safe under a
        module that works on several at once. This module samples its devices in a thread
        pool, so without it four machines wrote "reading 7/24, reading 3/24, reading 19/24"
        into the same line: a counter that jumps backwards, and that freezes at whatever the
        last thread happened to write. Reported exactly that way — a finished run showing a
        green tick beside "3/24" of a machine nobody had asked about.

        *state* is how a phase ENDED — ``'done'`` or ``'fail'`` — and it is the one word here
        the core owns, because it is the only thing about a phase the core has to draw rather
        than print: a tick or a cross. Without it a phase only ends when the same *scope*
        starts another one, so the LAST phase of anything spins for ever: reported from the
        screen as a device sitting at "reading the metrics 24/24" with a spinner beside it,
        having finished minutes earlier. And a phase that failed had no way to say so at all,
        so a device refusing connections looked exactly like one still working.

        All the rest is the module's own words. A core vocabulary of steps would fit whichever
        module was in front of whoever wrote it and be a lie for the other twenty — so the
        core draws the phases it is given, in the order they arrive, and names none of them.
        """
        mon = getattr(self, '_monitor', None)
        report = getattr(mon, 'report_progress', None)
        if report is None:
            return
        try:
            report(self.name_module, str(detail or ''), step=str(step or ''),
                   scope=str(scope or ''), n=int(n or 0), total=int(total or 0),
                   state=str(state or ''))
        except TypeError:
            # An older monitor that only knows the sentence. The phase is a nicety; losing
            # the progress line entirely because of it would not be.
            try:
                report(self.name_module, str(detail or ''))
            except Exception:  # pylint: disable=broad-except
                pass
        except Exception:  # pylint: disable=broad-except
            pass

    def run_parallel(self, items, check_fn, error_prefix: str) -> None:
        """Run ``check_fn(key, value)`` over ``items`` in a thread pool.

        ``items`` is an iterable of ``(key, value)`` pairs; the per-item check
        records its own result.  On an unhandled exception the item is logged
        and marked failed with a standard message.  Worker count comes from the
        module's ``threads`` setting.  Shared by the watchfuls whose check loop
        follows the ``submit(fn, key, value)`` contract.
        """
        workers = max(1, self.module_default('threads', self.module_field_default('threads')))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(check_fn, k, v): k for k, v in items}
            # What every module can say without being asked: how many of its things are done.
            # A module with forty checks is forty minutes of silence otherwise, and the one
            # place that knows the count is the loop that owns it.
            total, done = len(futures), 0
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                done += 1
                self.report_progress(f'{done}/{total} — {self.item_label(key) or key}')
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    label = self.item_label(key)
                    self._debug(f"{error_prefix}: {label} - Exception: {exc}", DebugLevel.error)
                    self.dict_return.set(key, False, f'{error_prefix}: {label} - *Error: {exc}* 💥')

    @property
    def name_module(self) -> str:
        """ Name of the module. """
        return self._name_module

    @property
    def db(self):
        """Shared DB connector, for modules that declare their own tables.

        Returns the monitor's :class:`lib.db.BaseConnector` (the same one the
        core stores use), or ``None`` when unavailable.  Declare tables with a
        module-level ``discover_db_tables()`` — see ``lib.db.module_tables``.
        """
        return getattr(self._monitor, 'db', None)

    @property
    def _default_threads(self) -> int:
        """ Default number of threads for parallel processing. """
        return self.module_field_default('threads')

    def _module_schema_defaults(self) -> dict:
        """``__module__`` schema defaults for THIS module (cached per instance).

        Read straight from the module's ``schema.json`` so module_default() can
        fall back to a module's own declared default (e.g. dns timeout 5)."""
        cache = self.__dict__.get('_mod_sch_defaults')
        if cache is not None:
            return cache
        defaults: dict = {}
        base = getattr(self._monitor, 'dir_modules', None) if self.is_monitor_exist else None
        name = (self.name_module or '').split('.')[-1]
        if base and name:
            try:
                with open(os.path.join(base, name, 'schema.json'), encoding='utf-8') as _f:
                    defaults = ModuleBase._schema_defaults(json.load(_f).get('__module__', {}))
            except (OSError, ValueError):
                defaults = {}
        self.__dict__['_mod_sch_defaults'] = defaults
        return defaults

    def module_default(self, field: str, fallback=0):
        """Resolve a module-level config field via the item → module → global
        chain, deciding by PRESENCE in the saved module config:

        * key **absent** (module never saved / field just added) → the module's
          own ``__module__`` schema default;
        * key **present with a value** → that value;
        * key **present but blank/0** (user cleared it) → the global
          ``Configuration > Modules`` value (config.json ``modules|<field>``).

        Generic for ``threads``, ``timeout`` and any future ``modules|*`` global.

        The result takes the TYPE of the fallback, so a float field (cpu's `interval`, ntp's
        `max_offset`) is not quietly truncated to an int — 0.5 s of sampling became 0, which
        is a different measurement, not a rounder one."""
        def _int(val, default):
            cast = type(default) if isinstance(default, (int, float))                 and not isinstance(default, bool) else int
            try:
                return cast(val)
            except (TypeError, ValueError):
                try:
                    return cast(default)
                except (TypeError, ValueError):
                    return 0

        schema_default = self._module_schema_defaults().get(field, fallback)
        mod_cfg = self.get_conf() if self.is_monitor_exist else {}
        if not isinstance(mod_cfg, dict) or field not in mod_cfg:
            return _int(schema_default, fallback)              # new / never saved
        v = mod_cfg.get(field)
        # Only a truly BLANK value (null / empty string) inherits the global —
        # an explicit 0 is a real value, not "unset".
        if v not in (None, ''):
            return _int(v, schema_default)                     # explicit value (incl 0)
        cfg = getattr(self._monitor, 'config', None) if self.is_monitor_exist else None
        glob = cfg.get_conf(['modules', field], None) if cfg is not None else None
        if glob in (None, ''):
            return _int(schema_default, fallback)
        return _int(glob, schema_default)

    @property
    def is_probe(self) -> bool:
        """True when this run is a test and nothing it produces will be kept.

        For work that exists ONLY to feed the history. Metric sampling reads every value
        of every profile a device has, and its answer is a graph: in a probe that is
        hundreds of round trips thrown away — against the device somebody is waiting on,
        with the panel showing "testing…" until the last one comes back. A check is the
        opposite: proving that it answers IS the test.
        """
        # `is True` and not truthiness: a test double answers yes to everything it is asked,
        # and a run that quietly believes it is a rehearsal is one that skips real work.
        return getattr(self._monitor, 'is_probe', False) is True if self.is_monitor_exist else False

    @property
    def is_monitor_exist(self) -> bool:
        """ Check if the Monitor object exists and is valid. """
        return bool(self._monitor and isinstance(self._monitor, lib.Monitor))

    @property
    def is_enabled(self) -> bool:
        """ Check if the module is enabled in the configuration. """
        return self.get_conf('enabled', self.module_field_default('enabled'))

    def send_message(self, message, status=None, item='', severity='', kind=''):
        """
        Bridge function to the send_message function of the Monitor object, checking if the
        Monitor is defined and valid before sending the data.

        ``item`` is the friendly name of the thing this alert is about (host/service/…);
        it fills the notification digest's Item column for ad-hoc sends.  ``severity='warning'``
        routes a non-OK alert as a ``warn`` (soft threshold breach) rather than ``down``.

        ``kind`` says this failure is a KIND of its own — one the module DECLARES as a notify
        event, so it gets a row in the routing matrix. The monitor decides whether it may be
        used (it has to be registered, and it never survives a recovery); here it is only
        carried, because a module naming a kind the core has never heard of is a module
        talking to itself.
        """
        if self.is_monitor_exist:
            # Pass the watchful's name so the notification digest can fill its Module column.
            self._monitor.send_message(message, status, module=self.name_module, item=item,
                                       severity=severity, kind=kind)
        else:
            self.debug.print(
                f">> {self.name_module} > send_message: Error, Monitor is not defined!!",
                DebugLevel.error
            )

    # ── i18n for check messages ────────────────────────────────────────────────
    def _notify_lang(self) -> str:
        """The system notification language (global ``notifications|lang`` …), read from the
        monitor's full config — so a check message is built in the configured language."""
        from lib.core.notify.formatting import notify_lang  # noqa: PLC0415
        cfg = getattr(getattr(self._monitor, 'config', None), 'data', None)
        return notify_lang(cfg if isinstance(cfg, dict) else {})

    def _module_lang_section(self, section: str, lang: str = '') -> dict:
        """This module's *section* dict, from its own ``lang/<lang>.json`` (requested
        language wins, ``en_EN`` fills gaps). Used for ``messages`` and any module-specific
        map (e.g. m365 ``health_states``). Cached per (module, language, section).

        The notification language unless *lang* says otherwise — see :meth:`_msg`."""
        from lib.i18n import DEFAULT_LANG  # noqa: PLC0415
        lang = lang or self._notify_lang()
        base = getattr(self._monitor, 'dir_modules', None) if self.is_monitor_exist else None
        if not isinstance(base, str):
            base = None
        name = (self.name_module or '').split('.')[-1]
        ck = (base, name, lang, section)
        cached = _MODULE_MSG_CACHE.get(ck)
        if cached is not None:
            return cached
        out: dict = {}
        if base and name:
            lang_dir = os.path.join(base, name, 'lang')
            for lc in (lang, DEFAULT_LANG):        # requested first, then default fills gaps
                if not lc:
                    continue
                try:
                    with open(os.path.join(lang_dir, f'{lc}.json'), encoding='utf-8') as fh:
                        data = json.load(fh)
                except (OSError, ValueError):
                    continue
                for k, v in (data.get(section) or {}).items():
                    out.setdefault(k, v)
        _MODULE_MSG_CACHE[ck] = out
        return out

    def _module_messages(self, lang: str = '') -> dict:
        """This module's ``messages`` dict, in the notification language or in *lang*."""
        return self._module_lang_section('messages', lang)

    def _msg(self, key: str, *args, lang: str = '') -> str:
        """Translate a check message: an admin text override
        (``notif_text_overrides[lang]['mod:<module>:<key>']``) wins, else this module's
        ``lang/*.json`` ``messages`` section.  ``{}`` placeholders are filled positionally by
        *args*; an unknown key falls back to the key itself.

        The system NOTIFICATION language by default, which is right for what this mostly
        produces: a message sent to a channel, read by whoever the installation sends things
        to. *lang* overrides it for the sentences that are not that — a progress line is read
        by the person watching the screen right now, in the language they chose
        (:meth:`watcher_lang`).
        """
        from lib.core.notify.formatting import text_override, _fill  # noqa: PLC0415
        cfg = getattr(getattr(self._monitor, 'config', None), 'data', None)
        cfg = cfg if isinstance(cfg, dict) else {}
        name = (self.name_module or '').split('.')[-1]
        lang = lang or self._notify_lang()
        text = (text_override(cfg, lang, f'mod:{name}:{key}')
                or self._module_messages(lang).get(key, key))
        return _fill(text, args)   # {} sequential + {0}/{1}… indexed (reorderable in overrides)

    def watcher_lang(self) -> str:
        """The language of whoever is watching this run, or ``''`` when nobody is.

        A progress line is the one thing a module produces for a PERSON standing in front of
        the screen, and that person picked a language in the panel. The notification language
        is a property of the installation and is the wrong answer here — reported from the
        screen as a Spanish dialog with "Reading the metrics" inside it.

        Installed by the executor for the duration of a watched batch, exactly like the
        progress sink, so a scheduler cycle has none and nothing changes for it.
        """
        return str(getattr(getattr(self, '_monitor', None), '_progress_lang', '') or '')

    def get_conf(
            self,
            find_key=None,
            default_val=None,
            select_module: str = None,
            str_split: str = None,
            r_type: ConfigTypeReturn = ConfigTypeReturn.STR
        ):
        """
        Function bridge with the get_conf function of the Monitor object, checking
        if the Monitor object is defined before requesting the data.

        :param find_key: Key or list of keys to find in the configuration. If it is a string
                         and str_split is defined, it will be split using str_split as separator.
        :param default_val: Default value to return if the configuration does not exist or
                            is incorrect.
        :param select_module: Name of the module in which to search for the find_key parameter. 
                              If none is defined, we will search in the configuration of the 
                              current module.
        :param str_split: Character to use to split find_key if passed as a string.
        :param r_type: Return type.
        :return:
        """
        if default_val is None:
            default_val = {}

        if self.is_monitor_exist:
            if not select_module:
                select_module = self.name_module

            if select_module:
                if find_key is None:
                    return self._monitor.config_modules.get_conf(select_module, default_val)

                keys_list = self._monitor.config_modules.convert_find_key_to_list(
                    find_key,
                    str_split
                )
                keys_list.insert(0, select_module)
                got = self._monitor.config_modules.get_conf(
                    keys_list, default_val, str_split=str_split,
                    r_type=r_type
                )
                # A narrowed run sees only the items bound to its machine, and it is applied
                # HERE because this is the one place all twenty modules ask through. Every one
                # of them enumerates its items the same way — `self.get_conf('list', {})` —
                # so the alternative is twenty modules each learning what a scope is, and the
                # nineteenth to get it right is a module that silently polls the whole fleet.
                #
                # Only the collection itself: reading one item's field (`['list', k, 'label']`)
                # is a module asking about something it has already chosen.
                if (self.host_scope and len(keys_list) == 2
                        and keys_list[1] in self._item_collections()
                        and isinstance(got, dict)):
                    return {k: v for k, v in got.items()
                            if isinstance(v, dict)
                            and str(v.get('host_uid') or '').strip() == self.host_scope}
                return got

        if find_key or default_val:
            return default_val
        return []

    def get_conf_in_list(
            self,
            opt_find,
            key_name_module: str,
            def_val=None,
            key_name_list: str = "list"
        ):
        """
        Get the data we want to search for from the 'list' section of the module configuration.

        :param opt_find: Option to search for.
        :param key_name_module: Name of the module from which we want to obtain the 'list' section.
        :param def_val: Default value if the option we are looking for does not exist.
        :param key_name_list: Key of the configuration where the list is stored where we will 
                              search.
        :return: Value obtained from the configuration.
        """
        match opt_find:
            case Enum():
                find_key = [opt_find.name]
            case str():
                find_key = [opt_find]
            case list():
                find_key = opt_find.copy()
            case int() | float():
                find_key = [str(opt_find)]
            case tuple():
                find_key = list(opt_find)
            case _:
                raise TypeError(f"opt_find is not valid type ({type(opt_find)})!")

        if key_name_module:
            find_key.insert(0, key_name_module)
            find_key.insert(0, key_name_list)
        value = self.get_conf(find_key, def_val)
        return value

    def get_status(self, key_name_module: str, def_val=None):
        """
        Get the status of a module.

        :param key_name_module: Name of the module for which to get the status.
        :param def_val: Default value if the status does not exist.
        :return: Status of the module.
        """
        if def_val is None:
            def_val = {}
        if not self.is_monitor_exist:
            return def_val
        return self._monitor.status.get_conf(key_name_module, def_val)

    def get_status_find(self, opt_find: str, key_name_module: str, def_val=None):
        """ Get the status of a module for a specific option."""
        if def_val is None:
            def_val = {}
        if not self.is_monitor_exist:
            return def_val
        return self.get_status(key_name_module).get(opt_find, def_val)

    def item_label(self, key: str) -> str:
        """Friendly display label for a ``list`` item key (the stored key is an
        opaque UID after the key→uid unification), falling back to the key.
        Use it in debug/log messages so they show the human name, not the UID."""
        try:
            item = (self.get_conf('list', {}) or {}).get(key)
            if isinstance(item, dict):
                lbl = str(item.get('label') or '').strip()
                if lbl:
                    return lbl
        except Exception:  # pylint: disable=broad-except
            pass
        return key

    def check_status(self, status, module, module_sub_key):
        """ Comprobamos el status del modulo y sub modulo. """
        if self.is_monitor_exist:
            return self._monitor.check_status(status, module, module_sub_key)

    def _resolved_item(self, key: str) -> dict:
        """Item config for *key* with any referenced host merged in (no-op when inline).

        Cached per check cycle — the monitor builds a fresh instance each cycle, so the
        cache cannot go stale, and a module that reads the same item from several checks
        resolves it once instead of once per check.

        Was a byte-for-byte copy in three modules (datastore, proxmox, web); nothing in it
        is module-specific.
        """
        cache = self.__dict__.setdefault('_resolved_items', {})
        if key not in cache:
            raw = self.get_conf(['list', key], {})
            cache[key] = self.resolve_host(raw) if isinstance(raw, dict) else {}
        return cache[key]

    def _emit(self, key: str, status: bool, message: str, other: dict = None,
              severity: str = None, name: str = None, change_msg: str = None,
              kind: str = '') -> None:
        """Record a result and notify ONLY on a status change.

        The pairing of :meth:`ReturnModuleCheck.set` with :meth:`check_status` +
        :meth:`send_message` is what makes a watchful report continuously but alert once:
        every cycle records the current state, and a notification goes out only when that
        state actually flipped.  Getting the pairing wrong is how a module either spams a
        message per cycle or records a result nobody is told about — which is why it lives
        here rather than being rewritten per module (it had been copied, byte for byte,
        into four of them).

        The ``name`` shown in the alert is the ITEM's label, so a multi-item module says
        "web-01" rather than the internal result key.  Result keys are ``<item>/<detail>``
        by convention, so the item is the segment before the first ``/``.

        Pass ``name`` explicitly when that derivation does not fit: several modules build a
        friendlier one — a fallback chain (``label`` → host → key), a composed string
        (``"disk1 - /dev/sda"``), or a different field entirely (the process name).  That
        variety is exactly why they each grew their own copy of this pairing; the override
        lets them keep the name they want without also re-implementing the notify gate.

        ``change_msg`` switches the gate to :meth:`check_status_custom`, which fires when
        the REASON changes as well as when the status does — so a failure that mutates
        ("connection refused" → "timeout") alerts again instead of staying quiet under an
        unchanged "still down".  Pass the internal reason string, not the display message;
        the comparison is against ``other_data['message']`` of the stored result, so a
        module using this must keep putting that reason there.

        ``severity='warning'`` marks a non-OK result as an aviso (amber in the UI) instead
        of a hard error — a threshold approached rather than a thing that is down.  It is
        passed to BOTH the recorded result and the notification: the ``send_msg=False``
        here disables the monitor's own digest path, so this explicit ``send_message`` is
        the only notification, and dropping the severity there made a warning arrive as a
        hard ``down`` while the UI painted it amber.
        """
        if name is None:
            name = (self.get_conf(['list', str(key).split('/')[0], 'label'], '') or '').strip()
        self.dict_return.set(key, status, message, False, other or {}, severity, name=name)
        changed = (self.check_status_custom(status, key, change_msg) if change_msg is not None
                   else self.check_status(status, self.name_module, key))
        if changed:
            self.send_message(message, status, item=name, severity=severity or '', kind=kind)

    def check_status_custom(self, status, key, status_msg):
        """
        Comprueba cambio de estado incluyendo cambio de mensaje de error.
        Se usa cuando además de comprobar el cambio de estado, necesitamos detectar
        si el mensaje de error ha cambiado.
        """
        return_status = self.check_status(status, self.name_module, key)
        if status or return_status:
            return return_status
        msg_old = self.get_status_find(key, self.name_module).get("other_data", {}).get("message", '')
        return True if str(status_msg) != str(msg_old) else return_status

    def fail_streak(self, key: str, failed: bool) -> int:
        """Update and return the consecutive-failure count for *key*.

        The counter backs ``alert``-style thresholds (declare DOWN only after N
        consecutive failed cycles).  It is persisted in the monitor's status
        store (the ``check_state`` DB table) — NOT on the instance and NOT in a
        module-level dict — because: the monitor builds a fresh Watchful every
        cycle (instance state resets), and the systemd one-shot mode runs each
        cycle in a fresh process (module-level state resets too).  The DB
        survives both.

        Stored under ``[module][key]['fail_count']``, next to the item's
        ``status``.  Setting a changed value flags the monitor so the state is
        persisted even when no status flipped this cycle.
        """
        cur = 1 if failed else 0
        if not self.is_monitor_exist:
            return cur
        try:
            path = [self.name_module, key, 'fail_count']
            prev = int(self._monitor.status.get_conf(path, 0) or 0)
            cur = prev + 1 if failed else 0
            if cur != prev:
                self._monitor.status.set_conf(path, cur)
                self._monitor._status_counts_dirty = True  # noqa: SLF001 — monitor-owned flag
            return cur
        except Exception:  # pylint: disable=broad-except
            return cur

    def _debug(self, msg: str, level: DebugLevel = DebugLevel.debug):
        """ Helper de debug para plugins. """
        self.debug.print(f">> PlugIn >> {self.name_module} >> {msg}", level)

    @staticmethod
    def _parse_conf_int(value, default, min_val=1):
        """ Parsea un valor de configuración como entero con validación. """
        value = str(value).strip()
        if not value or not value.isnumeric() or int(value) < min_val:
            return int(default)
        return int(value)

    @staticmethod
    def _parse_conf_float(value, default, min_val=0):
        """ Parsea un valor de configuración como float con validación. """
        value = str(value).strip()
        try:
            fval = float(value)
        except (ValueError, TypeError):
            return float(default)
        return fval if fval > min_val else float(default)

    @staticmethod
    def _parse_conf_str(value, default=''):
        """ Parsea un valor de configuración como string. """
        value = str(value).strip()
        return value if value else str(default)

    @staticmethod
    def _run_cmd(cmd, return_str_err: bool = False, return_exit_code: bool = False):
        """
        Run the command we pass and read what it returns.

        :param cmd: Command to execute.
        :param return_str_err: True to return stdout and stderr, False to return only stdout.
        :param return_exit_code: True to return the exit code, False to not return it.
        :return: The result of the command execution.
        """

        result = lib.Exec.execute(command=cmd)
        stdout = result.out or ''
        stderr = result.err or ''
        exit_code = result.code

        if return_str_err and return_exit_code:
            return stdout, stderr, exit_code

        if return_str_err and not return_exit_code:
            return stdout, stderr

        if not return_str_err and return_exit_code:
            return stdout, exit_code

        return stdout
