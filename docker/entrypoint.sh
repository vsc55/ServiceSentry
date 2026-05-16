#!/bin/sh
set -e

# ── Bootstrap: write env vars into config.json before starting ───────────────
# Only variables that are explicitly set are applied; unset vars leave the
# existing config.json value untouched.  Uses os.replace() for atomic writes
# so concurrent starts (web + worker sharing the same volume) are safe.
python3 - <<'PYEOF'
import json, os, pathlib, tempfile

CONFIG_FILE = pathlib.Path('/etc/ServiSesentry/config.json')
CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

try:
    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
except (json.JSONDecodeError, OSError):
    cfg = {}

def _env(key, cast=str):
    """Return cast(env[key]) or None if the variable is unset / empty for non-str types."""
    v = os.environ.get(key)
    if v is None or (v == '' and cast is not str):
        return None
    if cast is bool:
        return v.lower() in ('1', 'true', 'yes')
    try:
        return cast(v)
    except (ValueError, TypeError):
        return None

wa = cfg.setdefault('web_admin', {})
tg = cfg.setdefault('telegram', {})
dm = cfg.setdefault('daemon',   {})

# web_admin settings
_WA_MAP = {
    'WA_USERNAME':            ('username',            str),
    'WA_PASSWORD':            ('password',            str),
    'WA_LANG':                ('lang',                str),
    'WA_DARK_MODE':           ('dark_mode',           bool),
    'WA_SECURE_COOKIES':      ('secure_cookies',      bool),
    'WA_REMEMBER_ME_DAYS':    ('remember_me_days',    int),
    'WA_AUDIT_MAX_ENTRIES':   ('audit_max_entries',   int),
    'WA_PUBLIC_STATUS':       ('public_status',       bool),
    'WA_STATUS_REFRESH_SECS': ('status_refresh_secs', int),
    'WA_STATUS_LANG':         ('status_lang',         str),
    'WA_PROXY_COUNT':         ('proxy_count',         int),
}
for env_key, (cfg_key, cast) in _WA_MAP.items():
    v = _env(env_key, cast)
    if v is not None:
        wa[cfg_key] = v

# Telegram settings
for env_key, cfg_key in (
    ('TELEGRAM_TOKEN',   'token'),
    ('TELEGRAM_CHAT_ID', 'chat_id'),
):
    v = _env(env_key)
    if v is not None:
        tg[cfg_key] = v

v = _env('TELEGRAM_GROUP_MESSAGES', bool)
if v is not None:
    tg['group_messages'] = v

# Daemon settings
v = _env('CHECK_INTERVAL', int)
if v is not None:
    dm['timer_check'] = v

# Atomic write — safe even when web and worker start concurrently
tmp = tempfile.NamedTemporaryFile(
    mode='w', dir=CONFIG_FILE.parent, delete=False, suffix='.tmp'
)
try:
    json.dump(cfg, tmp, indent=4)
    tmp.close()
    os.replace(tmp.name, str(CONFIG_FILE))
except Exception:
    os.unlink(tmp.name)
    raise
PYEOF

# ── Start the service ─────────────────────────────────────────────────────────
case "${SERVICE_ROLE}" in
  web)
    set -- --web \
           --web-host "${WEB_HOST:-0.0.0.0}" \
           --web-port "${WEB_PORT:-8080}"
    ;;
  worker)
    set -- --daemon
    ;;
  *)
    echo "ERROR: SERVICE_ROLE must be 'web' or 'worker' (got: '${SERVICE_ROLE}')" >&2
    exit 1
    ;;
esac

[ "${VERBOSE:-false}" = "true" ] && set -- "$@" --verbose

exec python3 main.py "$@"
