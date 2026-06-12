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
                if collection == '__i18n__':
                    continue  # handled separately below
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
