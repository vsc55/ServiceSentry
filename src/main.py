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

"""Module Main."""


import argparse
import os
import sys

from lib.config import load_config


def compute_app_dirs(dir_base: str, is_dev: bool, path_config) -> 'tuple[str, str]':
    """Resolve the (config_dir, var_dir) pair from primitive inputs.

    The single source of this convention, shared by the standalone services
    (monitor / syslog / events) and the web panel so they always
    agree on where config.json and the database live:
      * ``--path`` / ``SS_CONFIG_DIR`` wins for the config dir;
      * a dev checkout (``src`` in the path) keeps both dirs together;
      * otherwise the platform's standard locations are used.
    """
    if path_config:
        config_dir = path_config
    elif is_dev:
        config_dir = os.path.normpath(os.path.join(dir_base, '../data/'))
    else:
        config_dir = '/etc/ServiSesentry/'

    if is_dev:
        var_dir = config_dir
    elif sys.platform == 'win32':
        var_dir = os.path.join(
            os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'ServiSesentry'
        )
    else:
        var_dir = '/var/lib/ServiSesentry/'
    return config_dir, var_dir


def _resolve_app_dirs(args) -> 'tuple[str, str]':
    """``compute_app_dirs`` for the CLI run modes (web / syslog), keyed off args."""
    dir_base = os.path.dirname(os.path.abspath(__file__))
    return compute_app_dirs(dir_base, 'src' in dir_base, getattr(args, 'path', None))


def _match_lang(raw):
    """Map a raw lang/locale string to a supported code, or ``None``.

    Accepts an exact code (``es_ES``) or a two-letter prefix (``es``,
    ``es_ES.UTF-8`` → ``es_ES``)."""
    from lib.i18n import SUPPORTED_LANGS  # noqa: WPS433
    if not raw:
        return None
    raw = str(raw).replace('-', '_')
    if raw in SUPPORTED_LANGS:
        return raw
    by_prefix = {code.split('_')[0].lower(): code for code in SUPPORTED_LANGS}
    return by_prefix.get(raw.split('_')[0].strip().lower()[:2])


def _os_locale() -> str:
    """The OS locale string (``locale.getlocale`` then the POSIX env vars)."""
    raw = ''
    try:
        import locale  # noqa: WPS433
        raw = locale.getlocale()[0] or ''
    except Exception:  # pylint: disable=broad-except
        raw = ''
    return raw or os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') \
        or os.environ.get('LANG') or ''


def _argv_lang():
    """The ``--lang``/``-l`` value from the raw command line (the CLI help is
    built before argparse parses), or ``None``."""
    argv = sys.argv[1:]
    for i, tok in enumerate(argv):
        if tok in ('--lang', '-l') and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith('--lang='):
            return tok.split('=', 1)[1]
    return None


def _banner_lang(config_dir: str | None = None, override=None) -> str:
    """UI language for console banners.  Priority: explicit *override*
    (``--lang``/``SS_LANG``) → ``config.json`` (bootstrap) → the default.  The
    web server itself prefers the DB-aware language (see :meth:`WebAdmin._t`)."""
    from lib.i18n import DEFAULT_LANG  # noqa: WPS433
    lang = _match_lang(override)
    if lang:
        return lang
    if config_dir:
        try:
            cfg = load_config(config_dir)
            lang = _match_lang(cfg.get_conf(['web_admin', 'lang'], None))
            if lang:
                return lang
        except Exception:  # pylint: disable=broad-except
            pass
    return DEFAULT_LANG


def _cli_lang() -> str:
    """Language for the CLI ``--help`` text, resolved *before* argparse runs (so
    it cannot use config — which is itself a CLI arg).  Priority: ``--lang`` →
    ``SS_LANG`` → the OS locale → the default language."""
    from lib.i18n import DEFAULT_LANG  # noqa: WPS433
    for raw in (_argv_lang(), os.environ.get('SS_LANG'), _os_locale()):
        lang = _match_lang(raw)
        if lang:
            return lang
    return DEFAULT_LANG


def _lib_version() -> str:
    """Project version (``lib.__version__``), with a safe fallback."""
    try:
        from lib import __version__  # noqa: WPS433
        return __version__
    except Exception:  # pylint: disable=broad-except
        return '0.0.0'


def _log_level_choices():
    """Accepted ``--log-level`` values (the same the config UI offers)."""
    from lib.debug import Debug  # noqa: WPS433
    return list(getattr(Debug, 'CONFIG_LEVELS', ('off', 'debug', 'info', 'warning', 'error')))


def start_web(args):
    """Start the web administration server.

    Reads web_admin settings from ``config.json`` and launches a Flask
    server for browser-based configuration editing.
    """
    config_dir, var_dir = _resolve_app_dirs(args)
    lang = _banner_lang(config_dir, getattr(args, 'lang', None))
    try:
        from lib.web_admin import WebAdmin  # noqa: WPS433 – conditional import
    except ImportError:
        from lib.i18n import translate  # noqa: WPS433
        print(translate(lang, 'web_flask_required'))
        print("       " + translate(lang, 'web_flask_hint'))
        sys.exit(1)


    # First-run credentials only: env > config.json bootstrap (never the DB).
    # All other web_admin options — including the bind host/port — come from the
    # effective config (DB ← config.json), read below from the WebAdmin itself so
    # config.json is never consulted for editable settings.
    cfg = load_config(config_dir)
    username = os.environ.get('SS_USERNAME') or cfg.get_conf(['web_admin', 'username'], 'admin')
    password = os.environ.get('SS_PASSWORD') or cfg.get_conf(['web_admin', 'password'], 'admin')

    modules_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchfuls')
    admin = WebAdmin(config_dir, str(username), str(password), var_dir,
                     modules_dir=modules_dir)
    if getattr(args, 'log_level', None):
        admin.debug.set_from_config(args.log_level)   # CLI overrides the config level

    # Bind host/port from the effective config (the DB is the single source);
    # CLI overrides win.
    _wa_cfg = (admin._read_config_file(admin._CONFIG_FILE) or {}).get('web_admin') or {}
    host = getattr(args, 'web_host', None) or _wa_cfg.get('host') or WebAdmin.DEFAULT_HOST
    port = getattr(args, 'web_port', None) or _wa_cfg.get('port') or WebAdmin.DEFAULT_PORT

    # --lang (CLI/env) overrides the banner language; otherwise the web admin's
    # effective (DB-aware) language is used.
    from lib.i18n import translate  # noqa: WPS433
    blang = _match_lang(getattr(args, 'lang', None)) or admin._default_lang
    print(translate(blang, 'banner_web'))
    print(f"  {translate(blang, 'banner_url')} http://{host}:{port}")
    print(f"  {translate(blang, 'banner_config')} {config_dir}")
    if username == 'admin' and password == 'admin':
        print("  ⚠  " + translate(blang, 'web_default_creds'))
        print("     " + translate(blang, 'web_default_creds_hint'))
    print("  " + translate(blang, 'web_press_ctrlc'))
    print()

    admin.run(host=str(host), port=int(port), debug=getattr(args, 'verbose', False))


def _run_standalone(desc, args) -> int:
    """Launch a standalone service (``--monitor`` / ``--syslog`` / ``--events``).

    Resolves the config/var dirs like :func:`start_web`, prints the service banner,
    then hands off to the package's ``run_standalone`` (discovered via
    :func:`lib.services.discover_standalone_services`) — so adding a standalone
    service needs no edit here, only its package's ``STANDALONE`` descriptor +
    ``service.run_standalone``.
    """
    import importlib  # noqa: WPS433
    from lib.i18n import translate  # noqa: WPS433

    config_dir, var_dir = _resolve_app_dirs(args)
    modules_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchfuls')
    lang = _banner_lang(config_dir, getattr(args, 'lang', None))
    print(translate(lang, desc['banner']))
    print(f"  {translate(lang, 'banner_config')} {config_dir}")
    print("  " + translate(lang, 'web_press_ctrlc'))
    print()

    runner = importlib.import_module(f"lib.services.{desc['key']}.service").run_standalone
    return runner(args, config_dir, var_dir, modules_dir)


def arg_check_dir_path(path):
    """
    Check if the provided path is a valid directory path.

    Args:
        path (str): The directory path to check.

    Returns:
        str: The valid directory path if it exists, otherwise an empty string.

    Raises:
        argparse.ArgumentTypeError: If the provided path is not a valid directory.
    """
    if not path:
        return ''
    elif os.path.isdir(path):
        return path
    else:
        raise argparse.ArgumentTypeError(f"{path} is not a valid path")


def arg_check_timer(timer_check: str) -> int:
    """
    Validates that the provided timer_check argument is a positive integer.

    Args:
        timer_check: The timer value string to validate.

    Returns:
        The validated timer value as integer.

    Raises:
        argparse.ArgumentTypeError: If the timer_check is not a positive integer.
    """
    # 0 is valid: it selects a single pass (``--monitor -t 0``), per the CLI help.
    if timer_check.isnumeric():
        return int(timer_check)
    raise argparse.ArgumentTypeError(f"{timer_check} is not a valid timer")


def _env_str(name: str, default=None):
    """Environment fallback for a string CLI argument."""
    v = os.environ.get(name)
    return v if v not in (None, '') else default


def _env_bool(name: str, default: bool = False) -> bool:
    """Environment fallback for a boolean (store_true) CLI argument."""
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default=None):
    """Environment fallback for an integer CLI argument."""
    v = os.environ.get(name)
    if v in (None, ''):
        return default
    try:
        return int(v)
    except ValueError:
        return default


def args_init() -> argparse.Namespace:
    """Initialize and parse command-line arguments.

    Every argument falls back to an ``SS_*`` environment variable (handy for
    Docker, where flags are awkward): e.g. ``SS_WEB=true``, ``SS_WEB_PORT=8080``,
    ``SS_CONFIG_DIR=/config``, ``SS_VERBOSE=1``, ``SS_NOCOLOR=1``.  Config.json
    fields use ``SS_*`` env vars too (e.g. ``SS_USERNAME``, ``SS_CHECK_INTERVAL``,
    ``SS_TELEGRAM_TOKEN``).  The standard ``NO_COLOR`` env var is also honoured.

    Returns:
        argparse.Namespace: The parsed command-line arguments.
    """
    from lib.i18n import translate  # noqa: WPS433
    lang = _cli_lang()

    def _h(key):
        return translate(lang, key)

    class _Formatter(argparse.HelpFormatter):
        # Localise argparse's own "usage: " prefix; its remaining built-in strings
        # ("the following arguments…", error texts) come from gettext and stay in
        # English.
        def _format_usage(self, usage, actions, groups, prefix):
            return super()._format_usage(
                usage, actions, groups,
                prefix if prefix is not None else _h('cli_usage_prefix'))

    ap = argparse.ArgumentParser(
        prog='ServiceSentry',
        description=_h('cli_description'),
        epilog=_h('cli_epilog'),
        allow_abbrev=False,
        add_help=False,                  # add our own -h so its help text is translatable
        formatter_class=_Formatter,
    )
    ap._optionals.title = _h('cli_opts')
    ap.add_argument(
        '-h', '--help', action='help', default=argparse.SUPPRESS,
        help=_h('cli_help'),
    )
    ap.add_argument(
        '-V', '--version', action='version',
        version=f'%(prog)s {_lib_version()}',
        help=_h('cli_version'),
    )
    ap.add_argument(
        '-l', '--lang',
        default=_env_str('SS_LANG', None),
        metavar='CODE',
        dest='lang',
        help=_h('cli_lang'),
    )
    ap.add_argument(
        '--log-level',
        default=_env_str('SS_LOG_LEVEL', None),
        choices=_log_level_choices(),
        metavar='LEVEL',
        dest='log_level',
        help=_h('cli_log_level'),
    )

    ap.add_argument(
        '-v', '--verbose',
        default=_env_bool('SS_VERBOSE', False),
        action="store_true",
        dest="verbose",
        help=_h('cli_verbose'),
    )
    ap.add_argument(
        '--nocolor', '--no-color',
        default=_env_bool('SS_NOCOLOR', False) or bool(os.environ.get('NO_COLOR')),
        action="store_true",
        dest="nocolor",
        help=_h('cli_nocolor'),
    )
    ap.add_argument(
        '-p', '--path',
        default=_env_str('SS_CONFIG_DIR', None),
        type=arg_check_dir_path,
        metavar='DIR',
        dest="path",
        help=_h('cli_path'),
    )

    # Service monitor — run with --monitor (continuous; -t 0 = a single pass). The
    # default mode when no role flag is given is the web panel (see the dispatch).
    monitor_group = ap.add_argument_group(_h('cli_group_monitor'))
    monitor_group.add_argument(
        '--monitor',
        default=_env_bool('SS_MONITOR', False),
        action="store_true",
        dest="monitor_mode",
        help=_h('cli_monitor'),
    )
    monitor_group.add_argument(
        '-c', '--clear',
        default=_env_bool('SS_CLEAR', False),
        action="store_true",
        dest="clear_status",
        help=_h('cli_clear'),
    )
    monitor_group.add_argument(
        '-t', '--timer',
        default=_env_int('SS_TIMER', None),
        type=arg_check_timer,
        metavar='SECONDS',
        dest="timer_check",
        help=_h('cli_timer'),
    )

    # Web admin arguments
    web_group = ap.add_argument_group(_h('cli_group_web'))
    web_group.add_argument(
        '--web',
        default=_env_bool('SS_WEB', False),
        action="store_true",
        dest="web_mode",
        help=_h('cli_web'),
    )
    web_group.add_argument(
        '--web-host',
        default=_env_str('SS_WEB_HOST', None),
        metavar='HOST',
        dest="web_host",
        help=_h('cli_web_host'),
    )
    web_group.add_argument(
        '--web-port',
        default=_env_int('SS_WEB_PORT', None),
        type=int,
        metavar='PORT',
        dest="web_port",
        help=_h('cli_web_port'),
    )

    # Syslog receiver (standalone) — run only the syslog listener, sharing the DB.
    syslog_group = ap.add_argument_group(_h('cli_group_syslog'))
    syslog_group.add_argument(
        '--syslog',
        default=_env_bool('SS_SYSLOG', False),
        action="store_true",
        dest="syslog_mode",
        help=_h('cli_syslog'),
    )
    syslog_group.add_argument(
        '--syslog-host',
        default=_env_str('SS_SYSLOG_HOST', None),
        metavar='HOST',
        dest="syslog_host",
        help=_h('cli_syslog_host'),
    )
    syslog_group.add_argument(
        '--syslog-port',
        default=_env_int('SS_SYSLOG_PORT', None),
        type=int,
        metavar='PORT',
        dest="syslog_port",
        help=_h('cli_syslog_port'),
    )

    # Event processor (standalone) — run only the decoupled event worker.
    events_group = ap.add_argument_group(_h('cli_group_events'))
    events_group.add_argument(
        '--events',
        default=_env_bool('SS_EVENTS', False),
        action="store_true",
        dest="events_mode",
        help=_h('cli_events'),
    )
    return ap.parse_args()

if __name__ == "__main__":
    _args = args_init()
    if getattr(_args, 'nocolor', False):
        from lib.debug import Debug as _Debug
        _Debug.set_color(False)
    # Standalone service modes (--monitor/--syslog/--events), discovered from the
    # service packages so there is no per-service branch here; mutually exclusive,
    # and the default (no mode flag) is the web administration panel.
    from lib.services import discover_standalone_services  # noqa: WPS433
    for _desc in discover_standalone_services():
        if getattr(_args, _desc['dest'], False):
            sys.exit(_run_standalone(_desc, _args))
    start_web(_args)
