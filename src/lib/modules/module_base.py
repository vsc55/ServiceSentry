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

import importlib
import json
import os
import sys
from enum import Enum

import lib.tools
from lib import os_detect
from lib.config import ConfigTypeReturn
from lib.debug import DebugLevel
from lib.dict_files_path import DictFilesPath
from lib.modules import ReturnModuleCheck
from lib.object_base import ObjectBase

__all__ = ['ModuleBase']


class ModuleBase(ObjectBase):
    """ Base class for modules. """

    # Number of threads that will be used in the modules for parallel processing as default value.
    _DEFAULT_THREADS = 5
    _DEFAULT_ENABLED = True

    # Per-item field schema for the module's collections.
    # Override in subclasses to declare which fields each item supports.
    # Format: { 'collection_key': { field: default_value, … } }
    # Example: { 'list': { 'enabled': True, 'code': 200 } }
    ITEM_SCHEMA: dict[str, dict] = {}

    # Classmethods exposed as web actions via /api/watchfuls/<module>/<action>.
    # Override in subclasses to whitelist callable classmethods.
    WATCHFUL_ACTIONS: frozenset[str] = frozenset()

    # Optional Python packages required by this watchful.
    # Override in subclasses to a non-empty list when an import fails so that
    # discover_schemas() can mark the module as unavailable in the UI and
    # display a "pip install <pkg>" hint instead of the normal controls.
    MISSING_DEPS: list[str] = []

    # Optional packages whose absence degrades (but does not break) this watchful.
    # The module remains functional without them but the UI shows a warning badge
    # so users know that some features or backends may be unavailable.
    PARTIAL_DEPS: list[str] = []

    @staticmethod
    def _schema_defaults(collection: dict) -> dict:
        """Extract default values from an enriched ``ITEM_SCHEMA`` collection.

        Supports both the simple format (``{field: value}``) and the rich
        format (``{field: {default: value, type: ..., ...}}``).
        """
        defaults: dict = {}
        for k, v in collection.items():
            if k.startswith('__'):
                continue
            if isinstance(v, dict) and 'default' in v:
                val = v['default']
                defaults[k] = list(val) if isinstance(val, list) else val
            else:
                defaults[k] = list(v) if isinstance(v, list) else v
        return defaults

    @classmethod
    def discover_secret_fields(cls, watchfuls_dir: str | None = None) -> set[str]:
        """Return the set of field names every module flags as secret/sensitive.

        Lets the core protect module credentials (encrypt at rest, mask in API
        responses, redact in audit) without hardcoding any module-specific
        field names — modules declare ``"secret": true`` / ``"sensitive": true``
        in their schema.json and the core discovers them here.  One level of
        ``sub_collection`` nesting is inspected too.
        """
        secret_fields: set[str] = set()

        def _scan(fields: dict) -> None:
            for fkey, meta in fields.items():
                if not isinstance(meta, dict):
                    continue
                if meta.get('secret') or meta.get('sensitive'):
                    secret_fields.add(fkey)
                if meta.get('type') == 'sub_collection' and isinstance(meta.get('fields'), dict):
                    _scan(meta['fields'])

        try:
            for coll_fields in cls.discover_schemas(watchfuls_dir).values():
                if isinstance(coll_fields, dict):
                    _scan(coll_fields)
        except Exception:  # pylint: disable=broad-except
            pass
        return secret_fields

    @classmethod
    def discover_schemas(cls, watchfuls_dir: str | None = None) -> dict[str, dict]:
        """Scan the *watchfuls* package and return the aggregated schemas.

        Returns a flat dict keyed ``"module_name|collection"`` whose values
        are the per-item field metadata declared by each module's
        ``ITEM_SCHEMA``.  For folder-based modules (new style) the per-field
        ``label_i18n`` and the top-level ``__i18n__`` entry are built by
        merging ``schema.json``, ``info.json`` and ``lang/*.json`` so that
        the Python class stays clean.

        When *watchfuls_dir* is ``None`` the directory is resolved
        relative to this file (``../../watchfuls``).
        """
        if watchfuls_dir is None:
            watchfuls_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'watchfuls')
            )

        schemas: dict[str, dict] = {}
        if not os.path.isdir(watchfuls_dir):
            return schemas

        # Ensure the parent of watchfuls is on sys.path so
        # ``import watchfuls.<name>`` works.
        parent = os.path.dirname(watchfuls_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        # Collect package-based module names (folder with __init__.py).
        entries: list[str] = []
        for entry in sorted(os.listdir(watchfuls_dir)):
            if entry.startswith('_'):
                continue
            entry_path = os.path.join(watchfuls_dir, entry)
            if (os.path.isdir(entry_path) and
                    os.path.isfile(os.path.join(entry_path, '__init__.py'))):
                entries.append(entry)

        for mod_name in entries:
            fq = f'watchfuls.{mod_name}'
            mod_dir = os.path.join(watchfuls_dir, mod_name)
            try:
                mod = importlib.import_module(fq)
            except Exception:                           # pragma: no cover
                continue
            watchful_cls = getattr(mod, 'Watchful', None)
            if watchful_cls is None:
                continue

            # Read schema.json from disk on every call so changes take effect
            # without a server restart (bypasses the module-level import cache).
            schema_path = os.path.join(mod_dir, 'schema.json')
            if os.path.isfile(schema_path):
                try:
                    with open(schema_path, encoding='utf-8') as _f:
                        item_schema = json.load(_f)
                except Exception:                       # pragma: no cover
                    item_schema = getattr(watchful_cls, 'ITEM_SCHEMA', None)
            else:
                item_schema = getattr(watchful_cls, 'ITEM_SCHEMA', None)
            if not item_schema or not isinstance(item_schema, dict):
                continue
            info = cls._load_module_info(mod_dir)
            lang_data = cls._load_module_langs(mod_dir)

            supported_platforms = getattr(watchful_cls, 'SUPPORTED_PLATFORMS', None)
            platform_unsupported = (
                isinstance(supported_platforms, (list, tuple)) and
                sys.platform not in supported_platforms
            )
            missing_deps  = list(getattr(watchful_cls, 'MISSING_DEPS',  None) or [])
            partial_deps  = list(getattr(watchful_cls, 'PARTIAL_DEPS',  None) or [])

            for collection, fields in item_schema.items():
                if collection in ('__i18n__', '__host_profile__', '__host_multiple__'):
                    # __i18n__ handled separately; __host_profile__/__host_multiple__
                    # are host-binding metadata (read from ITEM_SCHEMA), not
                    # renderable collections.
                    continue
                col_fields = dict(fields)
                # Merge label_i18n from lang files.
                # Sub-collection fields (type='sub_collection') are rendered as
                # nested collections, not as scalar form fields, so they do not
                # receive label_i18n here (their title comes from lang.collections).
                if lang_data:
                    for field_key, field_meta in list(col_fields.items()):
                        if (isinstance(field_meta, dict) and 'type' in field_meta
                                and field_meta.get('type') != 'sub_collection'):
                            label_i18n = {
                                lc: ld['labels'][field_key]
                                for lc, ld in lang_data.items()
                                if field_key in ld.get('labels', {})
                            }
                            if label_i18n:
                                col_fields[field_key] = {**field_meta, 'label_i18n': label_i18n}
                # Mark fields whose supported_platforms excludes the current platform.
                for _fk, _fm in list(col_fields.items()):
                    if _fk.startswith('__'):
                        continue
                    if isinstance(_fm, dict) and 'supported_platforms' in _fm:
                        _fplats = _fm['supported_platforms']
                        if isinstance(_fplats, (list, tuple)) and sys.platform not in _fplats:
                            col_fields[_fk] = {**_fm, '__unsupported__': True}
                if platform_unsupported:
                    col_fields['__unsupported__'] = True
                # Missing optional dependencies — mark module as unavailable and
                # carry the package list so the UI can show an install hint.
                if missing_deps:
                    col_fields['__unsupported__'] = True
                    col_fields['__missing_deps__'] = missing_deps
                # Partial dependencies — module still works but some features/backends
                # are degraded. Only set when not already fully disabled.
                elif partial_deps:
                    col_fields['__partial_deps__'] = partial_deps
                # Per-option dependency check: cross-reference each field's
                # options_deps dict with the set of unavailable packages so the
                # UI can disable specific select options instead of the whole module.
                _unavail = set(missing_deps + partial_deps)
                if _unavail:
                    for _fk, _fm in list(col_fields.items()):
                        if _fk.startswith('__'):
                            continue
                        if not (isinstance(_fm, dict) and 'options_deps' in _fm):
                            continue
                        _disabled = {
                            opt: pkg
                            for opt, pkg in _fm['options_deps'].items()
                            if pkg in _unavail
                        }
                        if _disabled:
                            col_fields[_fk] = {**_fm, 'options_disabled': _disabled}
                schemas[f'{mod_name}|{collection}'] = col_fields

                # Register sub-collection schemas.
                # Any field with type='sub_collection' in a collection is itself a
                # nested item collection.  Its item schema is registered under
                # 'mod|collection|sub_key' so the JS _schemaKeyOf() helper can find
                # it at paths like 'snmp|servers|router_1|checks'.
                for _sc_key, _sc_val in list(col_fields.items()):
                    if _sc_key.startswith('__') or not isinstance(_sc_val, dict):
                        continue
                    if _sc_val.get('type') != 'sub_collection':
                        continue
                    _sub_fields = dict(_sc_val)
                    # Apply label_i18n to the sub-collection's own item fields.
                    if lang_data:
                        for _sf_key, _sf_meta in list(_sub_fields.items()):
                            if (isinstance(_sf_meta, dict) and 'type' in _sf_meta
                                    and _sf_meta.get('type') != 'sub_collection'):
                                _lbl_i18n = {
                                    lc: ld['labels'][_sf_key]
                                    for lc, ld in lang_data.items()
                                    if _sf_key in ld.get('labels', {})
                                }
                                if _lbl_i18n:
                                    _sub_fields[_sf_key] = {**_sf_meta, 'label_i18n': _lbl_i18n}
                    if missing_deps:
                        _sub_fields['__unsupported__'] = True
                        _sub_fields['__missing_deps__'] = missing_deps
                    schemas[f'{mod_name}|{collection}|{_sc_key}'] = _sub_fields

            _module_key = f'{mod_name}|__module__'

            # Propagate declared UI capabilities (legacy — kept for compatibility).
            #   WATCHFUL_UI: frozenset[str] = frozenset({'file_manager', ...})
            _ui_caps = getattr(watchful_cls, 'WATCHFUL_UI', None)
            if _ui_caps and _module_key in schemas:
                schemas[_module_key]['__ui__'] = sorted(_ui_caps)

            # Propagate toolbar button declarations so the dashboard renders them
            # generically without any module-specific logic.  A module opts in by:
            #   WATCHFUL_TOOLBAR: tuple[dict, ...] = (
            #       {'icon': 'bi-...', 'label_key': '...', 'onclick': 'jsFnName'},
            #   )
            _toolbar = getattr(watchful_cls, 'WATCHFUL_TOOLBAR', None)
            if _toolbar and _module_key in schemas:
                schemas[_module_key]['__toolbar__'] = [
                    {k: str(v) for k, v in btn.items()} for btn in _toolbar
                ]

            # Build __i18n__ entry.
            if info or lang_data:
                icon = info.get('icon', '\U0001f4e6')
                _skip = {'pretty_name', 'labels'}
                i18n = {
                    lc: {
                        'pretty_name': ld.get('pretty_name', mod_name),
                        'icon': icon,
                        **{k: v for k, v in ld.items() if k not in _skip},
                    }
                    for lc, ld in lang_data.items()
                }
                if i18n:
                    schemas[f'{mod_name}|__i18n__'] = i18n

        return schemas

    @staticmethod
    def _load_module_info(module_dir: str) -> dict:
        """Load ``info.json`` from a folder-based module directory."""
        path = os.path.join(module_dir, 'info.json')
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as fh:
                return json.load(fh)
        return {}

    @staticmethod
    def _load_module_langs(module_dir: str) -> dict[str, dict]:
        """Load all ``lang/*.json`` files from a folder-based module directory."""
        lang_dir = os.path.join(module_dir, 'lang')
        result: dict[str, dict] = {}
        if not os.path.isdir(lang_dir):
            return result
        for fname in sorted(os.listdir(lang_dir)):
            if fname.endswith('.json') and not fname.startswith('_'):
                lang_code = fname[:-5]
                with open(os.path.join(lang_dir, fname), encoding='utf-8') as fh:
                    result[lang_code] = json.load(fh)
        return result

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

    def _init_var(self):
        """ Initialize the variables of the module. """
        self.paths = DictFilesPath()
        self.dict_return = ReturnModuleCheck()

    def check(self):
        """ Check the module and return the result. """
        self.debug.debug_obj(self.name_module, self.dict_return.list, "Data Return")

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

    def resolve_host(self, item: dict) -> dict:
        """Merge a referenced host's connection over a check item.

        Host-centric config: an item (or, for SNMP, a server) may carry a
        ``host_uid`` instead of inline connection fields.  When it does, this
        looks the host up in the monitor's host registry and returns a NEW dict
        = the item with the host's address + the relevant per-protocol
        credential profile(s) merged in (host values win, since the UI hides the
        inline connection fields when a host is bound).  Items without a
        ``host_uid`` — the classic inline config — are returned unchanged, so
        the two styles coexist.

        Which fields come from the host is declared by the module's
        ``__host_profile__`` in schema.json::

            "__host_profile__": {"key": "snmp", "address_field": "host",
                                 "fields": ["host","port","community", ...]}

        ``__host_profile__`` may also be a LIST of such specs for modules that
        need several protocols (e.g. datastore: an ``ssh`` tunnel + a ``db``
        profile).  Only specs with an ``address_field`` receive the host
        address; the rest contribute their profile fields only.
        """
        if not isinstance(item, dict):
            return item
        host_uid = str(item.get('host_uid') or '').strip()
        if not host_uid:
            return item
        store = getattr(self._monitor, '_hosts_store', None)
        if store is None:
            return item
        try:
            host = store.get(host_uid)
        except Exception:  # pylint: disable=broad-except
            return item
        if not host:
            return item

        specs = (getattr(self, 'ITEM_SCHEMA', None) or {}).get('__host_profile__')
        if isinstance(specs, dict):
            specs = [specs]
        if not isinstance(specs, list):
            return item

        profiles = host.get('profiles') or {}
        is_remote = str(host.get('kind') or 'local').strip().lower() == 'remote'
        conn: dict = {}
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            # The SSH connection only applies to a remote host; a local host is
            # reached directly, so its (stale) ssh profile must not activate a
            # tunnel / command-bridge.
            if spec.get('key') == 'ssh' and not is_remote:
                continue
            addr_field = spec.get('address_field')
            # The host address fills the address_field ONLY when the check does
            # not already carry its own value.  A visible address_field (e.g.
            # web's 'url') can thus be overridden per check — needed when one
            # host (a reverse proxy) serves several FQDNs — while hidden ones
            # (snmp 'host', ssh 'ssh_host') stay blank and always take the host.
            if (addr_field and host.get('address')
                    and not str(item.get(addr_field) or '').strip()):
                conn[addr_field] = host['address']
            prof = profiles.get(spec.get('key')) or {}
            if isinstance(prof, dict):
                # Only non-empty values of fields the schema DECLARES as
                # host-owned override the item.  Stale profile keys (left over
                # after a schema evolution moved a field back to the check —
                # e.g. ssl_cert's port) must not clobber per-check values.
                declared = set(spec.get('fields') or [])
                conn.update({k: v for k, v in prof.items()
                             if k in declared and k != addr_field and v not in (None, '')})
        resolved = {**item, **conn}
        # Expose the host's OS so modules that run OS-specific commands can
        # branch on it.  'auto' on a LOCAL host resolves to this process's
        # platform; on a remote host it stays 'auto' (resolved over SSH by the
        # consumer when needed).
        host_os = str(host.get('os') or 'auto').strip().lower()
        if host_os == 'auto' and not is_remote:
            host_os = os_detect.local_os()
        resolved['host_os'] = host_os
        resolved['host_kind'] = 'remote' if is_remote else 'local'
        # A host in maintenance: skip every check bound to it this cycle.  We
        # mark it disabled (modules already skip disabled items) and leave a
        # marker for any caller that wants to report the maintenance state.
        if host.get('maintenance'):
            resolved['enabled'] = False
            resolved['_host_maintenance'] = True
        return resolved

    # ── Host-aware command execution ─────────────────────────────────────────
    def host_os(self, item: dict) -> str:
        """Canonical OS for an item: the bound host's OS, else this machine's."""
        if isinstance(item, dict) and item.get('host_os'):
            return str(item['host_os']).strip().lower()
        return os_detect.local_os()

    @staticmethod
    def host_cmd_for(item: dict, cmds: dict, default_os: str = 'linux') -> str:
        """Pick the command for the item's OS from ``{os: cmd}`` (falls back to
        the *default_os* entry, then any).  Returns '' when *cmds* is empty."""
        os_ = str((item or {}).get('host_os') or os_detect.local_os()).lower()
        return cmds.get(os_) or cmds.get(default_os) or next(iter(cmds.values()), '')

    def host_exec(self, item: dict, cmd: str, *, timeout: int = 15) -> tuple:
        """Run *cmd* for a check item and return ``(stdout, stderr, exit_code)``.

        Where it runs depends on the item's bound host (set by
        :meth:`resolve_host`):

          * ``host_kind == 'remote'`` → over SSH on the host, reusing the host's
            stored SSH connection (``ssh_*`` fields merged into the item);
          * otherwise (a local host or a classic inline item) → locally.

        Never raises; transport/exec failures come back as
        ``('', <error>, -1)``.
        """
        if not isinstance(item, dict) or not cmd:
            return '', 'invalid item or command', -1
        if str(item.get('host_kind') or '').strip().lower() == 'remote':
            from lib import ssh_client  # noqa: PLC0415
            if not ssh_client.HAS_PARAMIKO:
                return '', 'paramiko is not installed', -1
            address = str(item.get('ssh_host') or '').strip()
            if not address:
                return '', 'remote host has no address', -1
            client = None
            try:
                client = ssh_client.connect_host(item, address, timeout=timeout)
                return ssh_client.run_command(client, cmd, timeout=timeout)
            except Exception as exc:  # pylint: disable=broad-except
                return '', f'SSH error: {exc}', -1
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # pylint: disable=broad-except
                        pass
        # Local / inline — run through the shell so pipes, globs and ';' behave
        # the same as on the remote SSH path (the local Exec helper uses
        # shlex.split, which would not interpret them).  The command is built
        # from module code/schema (never raw user input), so shell=True is safe.
        import subprocess  # noqa: PLC0415
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True,  # noqa: S602
                                 text=True, timeout=timeout)
            return (res.stdout or ''), (res.stderr or ''), res.returncode
        except Exception as exc:  # pylint: disable=broad-except
            return '', str(exc), -1

    @property
    def _default_threads(self) -> int:
        """ Default number of threads for parallel processing. """
        return self._DEFAULT_THREADS

    @property
    def is_monitor_exist(self) -> bool:
        """ Check if the Monitor object exists and is valid. """
        return bool(self._monitor and isinstance(self._monitor, lib.Monitor))

    @property
    def is_enabled(self) -> bool:
        """ Check if the module is enabled in the configuration. """
        return self.get_conf('enabled', self._DEFAULT_ENABLED)

    def send_message(self, message, status=None):
        """
        Bridge function to the send_message function of the Monitor object, checking if the
        Monitor is defined and valid before sending the data.
        """
        if self.is_monitor_exist:
            self._monitor.send_message(message, status)
        else:
            self.debug.print(
                f">> {self.name_module} > send_message: Error, Monitor is not defined!!",
                DebugLevel.error
            )

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
                return self._monitor.config_modules.get_conf(
                    keys_list, default_val, str_split=str_split,
                    r_type=r_type
                )

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
