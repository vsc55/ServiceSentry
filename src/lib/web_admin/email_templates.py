#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML email templates for ServiceSentry notifications.

All styles are inlined so they work across email clients.
Each public function accepts an optional *lang* parameter (e.g. ``'es_ES'``)
and returns a ready-to-send HTML string with the content in that language,
falling back to English when the language is not available.
"""

from __future__ import annotations

import html

# ── Brand colours (Bootstrap 5 palette) ─────────────────────────────────────
_COLORS = {
    'test':     {'bar': '#0d6efd', 'badge_bg': '#cfe2ff', 'badge_fg': '#084298'},
    'down':     {'bar': '#dc3545', 'badge_bg': '#f8d7da', 'badge_fg': '#842029'},
    'warn':     {'bar': '#ffc107', 'badge_bg': '#fff3cd', 'badge_fg': '#664d03'},
    'recovery': {'bar': '#198754', 'badge_bg': '#d1e7dd', 'badge_fg': '#0a3622'},
    'info':     {'bar': '#0dcaf0', 'badge_bg': '#cff4fc', 'badge_fg': '#055160'},
}

# English strings used as the fallback baseline for all templates.
_DEFAULT_STRINGS: dict[str, str] = {
    'footer':          'This notification was sent automatically by ServiceSentry. Do not reply to this email.',
    'view_status':     'View Status Page',
    'badge_test':      'Test',
    'badge_down':      'DOWN',
    'badge_warn':      'WARNING',
    'badge_recovery':  'RECOVERED',
    'badge_info':      'INFO',
    # Test email
    'test_subject':    'ServiceSentry — Test Email',
    'test_title':      'Email notification test',
    'test_body_1':     'This is a test notification sent from {sender}.',
    'test_body_2':     'If you received this message, your email notification settings are configured correctly and working as expected.',
    'test_body_3':     'No action is required. You can dismiss this email.',
    # Alert titles
    'alert_down':      'Service DOWN — {item}',
    'alert_warn':      'Warning — {item}',
    'alert_recovery':  'Service recovered — {item}',
    'alert_info':      'Notice — {item}',
    # Alert detail table
    'alert_intro':     'Details of the service state change:',
    'label_module':    'Module',
    'label_item':      'Item',
    'label_status':    'Status',
    'label_detail':    'Detail',
    'label_timestamp': 'Timestamp',
    # Summary
    'summary_one':     '1 service alert',
    'summary_many':    '{n} service alerts',
    'summary_intro':   'The following service state changes were detected:',
    'summary_ts':      'Timestamp: {ts}',
}


def get_strings(lang: str = '', overrides: 'dict | None' = None) -> dict[str, str]:
    """Return the template string dict for *lang*, merged over the English baseline.

    Parameters
    ----------
    lang:
        BCP-47 language code (e.g. ``'es_ES'``).  Empty string → English.
    overrides:
        Optional ``{key: value}`` dict of admin-configured template strings that
        take precedence over both the baseline and any built-in language overlay.
        Unknown keys are silently ignored.
    """
    # 1. Start from built-in defaults (English)
    base: dict[str, str] = _DEFAULT_STRINGS

    # 2. Merge built-in language overlay (if any)
    if lang:
        try:
            from lib.web_admin.i18n import TRANSLATIONS
            overlay = TRANSLATIONS.get(lang, {}).get('email_tpl', {})
            if overlay:
                base = {**_DEFAULT_STRINGS, **overlay}
        except Exception:
            pass

    # 3. Apply admin-configured overrides (highest priority)
    if overrides:
        custom = {k: v for k, v in overrides.items()
                  if k in _DEFAULT_STRINGS and isinstance(v, str) and v}
        if custom:
            return {**base, **custom}

    return base


# ── Base layout ──────────────────────────────────────────────────────────────

def _wrap(kind: str, title: str, body_html: str, footer_html: str = '',
          strings: dict | None = None) -> str:
    s = strings if strings is not None else _DEFAULT_STRINGS
    c = _COLORS.get(kind, _COLORS['info'])
    badge = s.get(f'badge_{kind}') or kind.upper()
    esc_title = html.escape(title)
    footer_text = html.escape(s.get('footer', _DEFAULT_STRINGS['footer']))
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc_title}</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f6fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
    <tr>
      <td align="center" style="padding:32px 16px">
        <table width="600" cellpadding="0" cellspacing="0" role="presentation"
               style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;
                      box-shadow:0 2px 12px rgba(0,0,0,.08)">

          <!-- colour accent bar -->
          <tr>
            <td style="background:{c['bar']};height:5px;border-radius:8px 8px 0 0;font-size:0;line-height:0">&nbsp;</td>
          </tr>

          <!-- header -->
          <tr>
            <td style="padding:20px 32px 16px;border-bottom:1px solid #e9ecef">
              <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                <tr>
                  <td style="font-size:18px;font-weight:700;color:#212529;letter-spacing:-.3px">
                    ServiceSentry
                  </td>
                  <td align="right">
                    <span style="display:inline-block;font-size:11px;font-weight:700;
                                 background:{c['badge_bg']};color:{c['badge_fg']};
                                 padding:3px 10px;border-radius:20px;letter-spacing:.4px">
                      {badge}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- title row -->
          <tr>
            <td style="padding:20px 32px 0;font-size:15px;font-weight:600;color:#343a40">
              {esc_title}
            </td>
          </tr>

          <!-- body -->
          <tr>
            <td style="padding:12px 32px 24px;font-size:14px;color:#495057;line-height:1.65">
              {body_html}
            </td>
          </tr>

          <!-- optional extra content (table, details, etc.) -->
          {"<tr><td style='padding:0 32px 24px'>" + footer_html + "</td></tr>" if footer_html else ""}

          <!-- footer -->
          <tr>
            <td style="padding:14px 32px;background:#f8f9fa;border-top:1px solid #e9ecef;
                       border-radius:0 0 8px 8px;font-size:11px;color:#6c757d">
              {footer_text}
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ── Status badge helper ──────────────────────────────────────────────────────

def _status_cell(status: str) -> str:
    """Return an inline-styled status badge string for use inside tables."""
    _s = status.lower()
    if _s in ('ok', 'up', 'recovery', 'recovered'):
        bg, fg = '#d1e7dd', '#0a3622'
    elif _s in ('warn', 'warning'):
        bg, fg = '#fff3cd', '#664d03'
    elif _s in ('down', 'error', 'critical'):
        bg, fg = '#f8d7da', '#842029'
    else:
        bg, fg = '#e2e3e5', '#41464b'
    return (f'<span style="display:inline-block;font-size:11px;font-weight:700;'
            f'background:{bg};color:{fg};padding:2px 8px;border-radius:12px;'
            f'letter-spacing:.3px">{html.escape(status.upper())}</span>')


# ── Custom HTML body helper ──────────────────────────────────────────────────

class _SafeDict(dict):
    """dict subclass that leaves unknown {keys} intact instead of raising KeyError."""
    def __missing__(self, key: str) -> str:
        return '{' + key + '}'


def apply_html_override(
    html_tpl: str,
    strings: 'dict | None' = None,
    **kwargs,
) -> str:
    """Substitute ``{variable}`` placeholders in a custom HTML template string.

    Two substitution passes are performed:

    1. Runtime *kwargs* are substituted into the string-key values
       (e.g. ``alert_down = "Service DOWN — {item}"`` → ``"Service DOWN — api.example.com"``).
    2. The resulting string-key values **and** the raw runtime kwargs are all
       substituted into *html_tpl*.

    This means a template can use either ``{alert_down}`` (expands to the
    full localised string) or ``{item}`` (expands to the raw runtime value),
    or both.  Unknown placeholders are left unchanged.
    """
    runtime = _SafeDict(**kwargs)

    # Pass 1: pre-interpolate each string value with runtime kwargs
    expanded: dict[str, str] = {}
    if strings:
        for k, v in strings.items():
            try:
                expanded[k] = v.format_map(runtime)
            except Exception:
                expanded[k] = v

    # Pass 2: runtime kwargs always override to allow {item} etc. directly
    expanded.update(kwargs)

    return html_tpl.format_map(_SafeDict(**expanded))


# Runtime variables available per email type (beyond all string keys).
# All _DEFAULT_STRINGS keys are also available in every template.
HTML_TPL_VARS: dict[str, list[str]] = {
    'test':    ['{sender_name}'],
    'alert':   ['{kind}', '{module}', '{item}', '{status}', '{message}',
                '{timestamp}', '{public_url}'],
    'summary': ['{n}', '{timestamp}', '{public_url}'],
}

# ── Public template functions ────────────────────────────────────────────────

def render_test(sender_name: str = 'ServiceSentry', lang: str = '',
                strings: 'dict | None' = None,
                html_override: 'str | None' = None) -> str:
    """HTML for the test email sent from the web admin configuration panel."""
    if html_override:
        s = strings if strings is not None else get_strings(lang)
        # {sender} is the legacy placeholder used in the test_body_1 string
        return apply_html_override(
            html_override, strings=s,
            sender_name=sender_name, sender=sender_name,
        )
    s = strings if strings is not None else get_strings(lang)
    sender_bold = f'<strong>{html.escape(sender_name)}</strong>'
    body = (
        f'<p>{s["test_body_1"].replace("{sender}", sender_bold)}</p>'
        f'<p>{html.escape(s["test_body_2"])}</p>'
        f'<p style="margin-top:16px;padding:12px 16px;background:#f8f9fa;'
        f'border-left:3px solid #0d6efd;border-radius:0 4px 4px 0;'
        f'font-size:13px;color:#495057">'
        f'{html.escape(s["test_body_3"])}</p>'
    )
    return _wrap('test', s['test_title'], body, strings=s)


def render_alert(
    *,
    kind: str,
    module: str,
    item: str,
    status: str,
    message: str,
    timestamp: str,
    public_url: str = '',
    lang: str = '',
    strings: 'dict | None' = None,
    html_override: 'str | None' = None,
) -> str:
    """HTML for a service status alert.

    Parameters
    ----------
    kind:
        ``'down'``, ``'warn'``, ``'recovery'``, or ``'info'``.
    module:
        Module name (e.g. ``'http_check'``).
    item:
        Item name within the module (e.g. ``'api.example.com'``).
    status:
        Current status string (e.g. ``'DOWN'``, ``'WARN'``, ``'OK'``).
    message:
        Human-readable status message from the check.
    timestamp:
        ISO-8601 timestamp string.
    public_url:
        Optional base URL for the status page link.
    lang:
        BCP-47 language code (e.g. ``'es_ES'``). Falls back to English.
    """
    if html_override:
        s = strings if strings is not None else get_strings(lang)
        return apply_html_override(
            html_override, strings=s,
            kind=kind, module=module, item=item, status=status,
            message=message, timestamp=timestamp, public_url=public_url,
        )
    s = strings if strings is not None else get_strings(lang)
    kind = kind if kind in _COLORS else 'info'
    _title_keys = {
        'down':     'alert_down',
        'warn':     'alert_warn',
        'recovery': 'alert_recovery',
        'info':     'alert_info',
    }
    title_tpl = s.get(_title_keys.get(kind, 'alert_info'), '{item}')
    title = title_tpl.replace('{item}', item)

    label_status = s.get('label_status', 'Status')
    rows = [
        (s.get('label_module',    'Module'),    module),
        (s.get('label_item',      'Item'),      item),
        (label_status,                          None),
        (s.get('label_detail',    'Detail'),    message),
        (s.get('label_timestamp', 'Timestamp'), timestamp),
    ]

    table_rows = ''
    for label, value in rows:
        if value is None and label == label_status:
            cell = _status_cell(status)
        else:
            cell = html.escape(str(value))
        table_rows += (
            f'<tr>'
            f'<td style="padding:8px 12px;font-size:12px;font-weight:600;'
            f'color:#6c757d;white-space:nowrap;vertical-align:top">{html.escape(label)}</td>'
            f'<td style="padding:8px 12px;font-size:13px;color:#212529;'
            f'word-break:break-word">{cell}</td>'
            f'</tr>'
        )

    detail_table = (
        '<table width="100%" cellpadding="0" cellspacing="0" role="presentation" '
        'style="border:1px solid #dee2e6;border-radius:6px;border-collapse:separate;'
        'border-spacing:0;overflow:hidden">'
        f'{table_rows}'
        '</table>'
    )

    link_html = ''
    if public_url:
        _url = html.escape(public_url.rstrip('/') + '/status')
        btn_label = html.escape(s.get('view_status', 'View Status Page'))
        link_html = (
            f'<p style="margin-top:16px;text-align:center">'
            f'<a href="{_url}" style="display:inline-block;padding:9px 20px;'
            f'background:#0d6efd;color:#fff;text-decoration:none;border-radius:5px;'
            f'font-size:13px;font-weight:600">{btn_label} &rarr;</a>'
            f'</p>'
        )

    alert_intro = html.escape(s.get('alert_intro', 'Details of the service state change:'))
    body = f'<p style="margin-top:0">{alert_intro}</p>'
    return _wrap(kind, title, body, detail_table + link_html, strings=s)


def render_summary(
    *,
    items: list[dict],
    timestamp: str,
    public_url: str = '',
    lang: str = '',
    strings: 'dict | None' = None,
    html_override: 'str | None' = None,
) -> str:
    """HTML for a grouped alert summary (multiple items in one email).

    Each element of *items* must have keys: ``module``, ``item``,
    ``status``, ``message``.
    """
    if html_override:
        s = strings if strings is not None else get_strings(lang)
        return apply_html_override(
            html_override, strings=s,
            n=len(items), timestamp=timestamp, ts=timestamp, public_url=public_url,
        )
    s = strings if strings is not None else get_strings(lang)

    col_module = html.escape(s.get('label_module', 'Module'))
    col_item   = html.escape(s.get('label_item',   'Item'))
    col_status = html.escape(s.get('label_status', 'Status'))
    col_detail = html.escape(s.get('label_detail', 'Detail'))

    header_row = (
        '<tr style="background:#f8f9fa">'
        f'<th style="padding:8px 12px;font-size:12px;font-weight:600;color:#495057;'
        f'text-align:left;border-bottom:2px solid #dee2e6">{col_module}</th>'
        f'<th style="padding:8px 12px;font-size:12px;font-weight:600;color:#495057;'
        f'text-align:left;border-bottom:2px solid #dee2e6">{col_item}</th>'
        f'<th style="padding:8px 12px;font-size:12px;font-weight:600;color:#495057;'
        f'text-align:left;border-bottom:2px solid #dee2e6">{col_status}</th>'
        f'<th style="padding:8px 12px;font-size:12px;font-weight:600;color:#495057;'
        f'text-align:left;border-bottom:2px solid #dee2e6">{col_detail}</th>'
        '</tr>'
    )
    body_rows = ''
    has_down = any(i.get('status', '').lower() in ('down', 'error', 'critical') for i in items)
    has_warn = any(i.get('status', '').lower() in ('warn', 'warning') for i in items)
    kind = 'down' if has_down else ('warn' if has_warn else 'info')

    for i, entry in enumerate(items):
        bg = '#ffffff' if i % 2 == 0 else '#f8f9fa'
        body_rows += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:8px 12px;font-size:13px;color:#495057;'
            f'border-bottom:1px solid #dee2e6">{html.escape(entry.get("module",""))}</td>'
            f'<td style="padding:8px 12px;font-size:13px;color:#212529;font-weight:500;'
            f'border-bottom:1px solid #dee2e6">{html.escape(entry.get("item",""))}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #dee2e6">'
            f'{_status_cell(entry.get("status","?"))}</td>'
            f'<td style="padding:8px 12px;font-size:12px;color:#6c757d;word-break:break-word;'
            f'border-bottom:1px solid #dee2e6">{html.escape(entry.get("message",""))}</td>'
            f'</tr>'
        )

    table_html = (
        '<table width="100%" cellpadding="0" cellspacing="0" role="presentation" '
        'style="border:1px solid #dee2e6;border-radius:6px;border-collapse:collapse">'
        f'{header_row}{body_rows}'
        '</table>'
    )

    ts_tpl = s.get('summary_ts', 'Timestamp: {ts}')
    ts_row = (
        f'<p style="margin-top:12px;font-size:12px;color:#6c757d">'
        f'{html.escape(ts_tpl.replace("{ts}", timestamp))}</p>'
    )

    link_html = ''
    if public_url:
        _url = html.escape(public_url.rstrip('/') + '/status')
        btn_label = html.escape(s.get('view_status', 'View Status Page'))
        link_html = (
            f'<p style="margin-top:16px;text-align:center">'
            f'<a href="{_url}" style="display:inline-block;padding:9px 20px;'
            f'background:#0d6efd;color:#fff;text-decoration:none;border-radius:5px;'
            f'font-size:13px;font-weight:600">{btn_label} &rarr;</a>'
            f'</p>'
        )

    n = len(items)
    if n == 1:
        title = s.get('summary_one', '1 service alert')
    else:
        title = s.get('summary_many', '{n} service alerts').replace('{n}', str(n))

    summary_intro = html.escape(s.get('summary_intro', 'The following service state changes were detected:'))
    body = f'<p style="margin-top:0">{summary_intro}</p>'
    return _wrap(kind, title, body, table_html + ts_row + link_html, strings=s)
