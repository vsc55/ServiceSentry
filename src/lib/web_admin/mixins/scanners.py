#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The three things the panel watches on its own, in the background.

Service health, certificate expiry and provider secret expiry are not module checks: nobody
configured them, they have no schedule of their own and they exist because the panel is the
only thing in a position to notice. Each is a thread started at boot with its own interval.

They live together because they share a shape - wake up, look, notify if something changed -
and separately from the request handling they interrupt, since a scanner that raises must not
be able to take a page down with it.
"""

class _ScannersMixin:
    """Background scanners for :class:`WebAdmin`."""

    def _start_service_health_monitor(self) -> None:
        """Launch the background service-health notifier (emits service_down / service_up
        on heartbeat transitions).  Leader-gated so replicas don't double-alert; a no-op
        when the instances store is absent.  Enable is read live (services|notify_down)."""
        if getattr(self, '_service_health', None) is not None:
            return
        store = getattr(self, '_service_instances_store', None)
        if store is None:
            return
        import os as _os  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
        from lib.core.health.health import ServiceHealthMonitor  # noqa: PLC0415
        from lib.services.heartbeat import hostname  # noqa: PLC0415
        from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
        _inst_id = f'health-{hostname()}-{_os.getpid()}'

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True   # sole owner
            try:
                poll = int(self._config_section('services').get('health_poll_secs') or 30)
            except (TypeError, ValueError):
                poll = 30
            try:
                return bool(ls.try_acquire('svc_health', _inst_id, host=hostname(),
                                           ttl=max(30, poll * 3)))
            except Exception:  # pylint: disable=broad-except
                return True

        def _emit(kind, **fields):
            _dispatch(self, kind=kind, timestamp=_time.strftime('%Y-%m-%d %H:%M:%S'), **fields)

        self._service_health = ServiceHealthMonitor(
            instances_provider=lambda: store.list_instances(),
            dispatch=_emit,
            config_getter=lambda: self._config_section('services'),
            is_leader=_is_leader,
            dbg=self._dbg,
            text_fn=self._notify_text,
        )
        self._service_health.start(
            poll_getter=lambda: self._config_section('services').get('health_poll_secs', 30))

    def _start_cert_scanner(self) -> None:
        """Launch the background certificate-expiry scanner (emits cert_expiring for
        ssl_cert checks nearing expiry).  Leader-gated; enable read live (certs|notify_expiry)."""
        if getattr(self, '_cert_scanner', None) is not None:
            return
        import os as _os  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
        from lib.core.health.cert_scan import CertExpiryScanner, enumerate_targets  # noqa: PLC0415,E501
        from lib.services.heartbeat import hostname  # noqa: PLC0415
        from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
        _inst_id = f'certscan-{hostname()}-{_os.getpid()}'

        def _host_address(uid):
            store = getattr(self, '_hosts_store', None)
            try:
                return (store.get(uid) or {}).get('address') if store else None
            except Exception:  # pylint: disable=broad-except
                return None

        def _targets():
            try:
                mods = self._modules_facade.read()
            except Exception:  # pylint: disable=broad-except
                return []
            warn = self._config_section('certs').get('warn_days', 21)
            return enumerate_targets(mods, host_address=_host_address, default_warn=warn)

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True
            try:
                return bool(ls.try_acquire('cert_scan', _inst_id, host=hostname(), ttl=3600))
            except Exception:  # pylint: disable=broad-except
                return True

        def _emit(kind, **fields):
            _dispatch(self, kind=kind, timestamp=_time.strftime('%Y-%m-%d %H:%M:%S'), **fields)

        self._cert_scanner = CertExpiryScanner(
            targets_provider=_targets,
            dispatch=_emit,
            config_getter=lambda: self._config_section('certs'),
            is_leader=_is_leader,
            dbg=self._dbg,
            text_fn=self._notify_text,
        )
        self._cert_scanner.start(
            poll_getter=lambda: self._config_section('certs').get('scan_every_secs', 86400))

    def _save_oidc_secret(self, secret: str, expires_at: str = '') -> bool:
        """Persist a freshly minted OIDC client secret (and the expiry Entra granted).

        Used by both the assisted rotation (device-code route) and the unattended one
        (:class:`SecretExpiryScanner`).  ``expires_at`` is stored verbatim so the scanner
        can compute the remaining life; an empty value simply means "unknown"."""
        if not secret:
            return False
        cfg = self._read_config_file(self._CONFIG_FILE) or {}
        cfg.setdefault('oidc', {})
        cfg['oidc']['client_secret'] = secret
        cfg['oidc']['secret_expires_at'] = expires_at or ''
        return bool(self._write_config(cfg))

    def _start_secret_scanner(self) -> None:
        """Launch the background Entra client-secret scanner: warns before the OIDC secret
        expires (``secret_expiring``) and, when ``oidc|secret_auto_rotate`` is on, mints a
        replacement once inside ``oidc|secret_rotate_days`` (``secret_rotated``).

        Unattended rotation authenticates the app **as itself** (client-credentials) and
        therefore only works if the app may modify its own registration in Entra; when it
        can't, rotation fails and the scanner degrades to warning only."""
        if getattr(self, '_secret_scanner', None) is not None:
            return
        import os as _os  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
        from lib.core.health.secret_scan import SecretExpiryScanner  # noqa: PLC0415
        from lib.providers.entraid import auth as _ent_auth, provisioning as _ent_prov  # noqa: PLC0415,E501
        from lib.services.heartbeat import hostname  # noqa: PLC0415
        from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
        _inst_id = f'secretscan-{hostname()}-{_os.getpid()}'

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True
            try:
                return bool(ls.try_acquire('secret_scan', _inst_id, host=hostname(), ttl=3600))
            except Exception:  # pylint: disable=broad-except
                return True

        def _emit(kind, **fields):
            _dispatch(self, kind=kind, timestamp=_time.strftime('%Y-%m-%d %H:%M:%S'), **fields)

        def _rotate():
            """App-only token with the app's CURRENT secret → mint the next one."""
            from lib import APP_NAME                              # noqa: PLC0415
            oidc = self._config_section('oidc')
            tenant = _ent_auth.tenant_from_provider_url(oidc.get('provider_url', '') or '')
            if not tenant:
                raise RuntimeError('cannot derive tenant from oidc|provider_url')
            token = _ent_auth.app_token(tenant, oidc.get('client_id', ''),
                                        oidc.get('client_secret', ''))
            return _ent_prov.add_app_secret(token, oidc.get('client_id', ''),
                                            display_name=f'{APP_NAME} OIDC (auto)')

        def _save(secret, expires_at):
            self._save_oidc_secret(secret, expires_at)
            self._audit('entra_oidc_secret_rotated',
                        detail={'auto': True, 'expires_at': expires_at})

        self._secret_scanner = SecretExpiryScanner(
            config_getter=lambda: self._config_section('oidc'),
            dispatch=_emit,
            rotate_fn=_rotate,
            save_fn=_save,
            is_leader=_is_leader,
            dbg=self._dbg,
            text_fn=self._notify_text,
        )
        self._secret_scanner.start(
            poll_getter=lambda: self._config_section('certs').get('scan_every_secs', 86400))
