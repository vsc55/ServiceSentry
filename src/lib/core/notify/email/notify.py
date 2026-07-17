#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Email notification module for WebAdmin.

Three providers are supported:
  - smtp        — standard SMTP with optional STARTTLS/SSL (no extra deps)
  - microsoft365 — Microsoft Graph API via client-credentials OAuth2
  - gmail        — Gmail REST API via OAuth2 refresh-token flow

``requests`` (always present in this project) is used for the API providers.
Values in the config dict are expected to be already decrypted
(``wa._read_config_file`` handles decryption).
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from lib.config.spec import cfg_get
from lib.debug import DebugLevel
from lib.core.object_base import ObjectBase
from lib.i18n import translate

try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


def send(wa, subject: str, body_html: str,
         recipients: list[str] | None = None) -> tuple[bool, str]:
    """Send email using the stored (decrypted) config. Returns (ok, message)."""
    cfg = wa._config_section('email')
    from lib.core.notify.formatting import notify_lang  # noqa: PLC0415
    lang = notify_lang(wa._read_config_file(wa._CONFIG_FILE) or {})
    return _dispatch(cfg, subject, body_html, recipients, lang=lang)


def _dispatch(cfg: dict, subject: str, body_html: str,
              recipients: list[str] | None, lang: str = '') -> tuple[bool, str]:
    if not cfg.get('enabled'):
        return False, translate(lang, 'email_disabled')
    provider = cfg_get(cfg, 'email|provider')
    if isinstance(recipients, str):
        rcpts = _parse_recipients(recipients)
    elif recipients is None:                    # only None falls back to the raw config
        rcpts = _parse_recipients(cfg.get('recipients', ''))
    else:
        rcpts = list(recipients)                # explicit (possibly empty) list wins as-is
    if not rcpts:
        return False, translate(lang, 'email_no_recipients')
    prefix = (cfg.get('subject_prefix') or '').strip()
    full_subject = f'{prefix} {subject}'.strip() if prefix else subject
    if provider == 'smtp':
        return _send_smtp(cfg, full_subject, body_html, rcpts, lang)
    if provider == 'microsoft365':
        return _send_ms365(cfg, full_subject, body_html, rcpts, lang)
    if provider == 'gmail':
        return _send_gmail(cfg, full_subject, body_html, rcpts, lang)
    return False, translate(lang, 'email_unknown_provider', provider)


def _parse_recipients(raw: str) -> list[str]:
    return [e.strip() for e in raw.replace(';', ',').split(',') if e.strip()]


def _send_smtp(cfg: dict, subject: str, body_html: str,
               recipients: list[str], lang: str = '') -> tuple[bool, str]:
    host = (cfg.get('smtp_host') or '').strip()
    if not host:
        return False, translate(lang, 'email_smtp_no_host')
    port = cfg_get(cfg, 'email|smtp_port', falsy=True)
    use_ssl = cfg_get(cfg, 'email|smtp_use_ssl')
    use_tls = cfg_get(cfg, 'email|smtp_use_tls') and not use_ssl
    username  = (cfg.get('smtp_username') or '').strip()
    password  = cfg.get('smtp_password') or ''
    from_email = (cfg.get('from_email') or '').strip()
    from_name  = cfg_get(cfg, 'email|from_name', falsy=True).strip()
    ObjectBase.debug.print(
        f"> Email/SMTP >> connecting {host}:{port} ssl={use_ssl} tls={use_tls} "
        f"to {len(recipients)} recipient(s)", DebugLevel.debug)

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f'{from_name} <{from_email}>' if from_name else from_email
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    try:
        ctx = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, context=ctx) as srv:
                if username:
                    srv.login(username, password)
                srv.sendmail(from_email, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port) as srv:
                if use_tls:
                    srv.starttls(context=ctx)
                if username:
                    srv.login(username, password)
                srv.sendmail(from_email, recipients, msg.as_string())
        return True, translate(lang, 'email_ok_smtp')
    except Exception as exc:
        return False, str(exc)


def _send_ms365(cfg: dict, subject: str, body_html: str,
                recipients: list[str], lang: str = '') -> tuple[bool, str]:
    if not _HAS_REQUESTS:
        return False, translate(lang, 'email_ms365_no_requests')
    tenant_id     = (cfg.get('ms365_tenant_id') or '').strip()
    client_id     = (cfg.get('ms365_client_id') or '').strip()
    client_secret = (cfg.get('ms365_client_secret') or '').strip()
    from_email    = (cfg.get('from_email') or '').strip()
    if not all([tenant_id, client_id, client_secret, from_email]):
        return False, translate(lang, 'email_ms365_missing')
    # The Graph client (token + sendMail) lives in the Entra ID provider — no direct
    # Microsoft calls from here. Imported after the requests guard above.
    from lib.providers.entraid import auth, mail  # noqa: PLC0415
    try:
        token = auth.app_token(tenant_id, client_id, client_secret)
        mail.send_mail(token, from_email, {
            'subject': subject,
            'body': {'contentType': 'HTML', 'content': body_html},
            'toRecipients': [{'emailAddress': {'address': r}} for r in recipients],
        })
        return True, translate(lang, 'email_ok_ms365')
    except Exception as exc:
        return False, str(exc)


def _send_gmail(cfg: dict, subject: str, body_html: str,
                recipients: list[str], lang: str = '') -> tuple[bool, str]:
    if not _HAS_REQUESTS:
        return False, translate(lang, 'email_gmail_no_requests')
    import base64
    client_id     = (cfg.get('gmail_client_id') or '').strip()
    client_secret = (cfg.get('gmail_client_secret') or '').strip()
    refresh_token = (cfg.get('gmail_refresh_token') or '').strip()
    from_email    = (cfg.get('from_email') or '').strip()
    from_name     = cfg_get(cfg, 'email|from_name', falsy=True).strip()
    if not all([client_id, client_secret, refresh_token, from_email]):
        return False, translate(lang, 'email_gmail_missing')
    try:
        token_r = _req.post(
            'https://oauth2.googleapis.com/token',
            data={
                'grant_type':    'refresh_token',
                'client_id':     client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token,
            },
            timeout=10,
        )
        token_r.raise_for_status()
        token = token_r.json()['access_token']

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f'{from_name} <{from_email}>' if from_name else from_email
        msg['To'] = ', '.join(recipients)
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        send_r = _req.post(
            'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
            json={'raw': raw},
            headers={'Authorization': f'Bearer {token}'},
            timeout=15,
        )
        send_r.raise_for_status()
        return True, translate(lang, 'email_ok_gmail')
    except Exception as exc:
        return False, str(exc)
