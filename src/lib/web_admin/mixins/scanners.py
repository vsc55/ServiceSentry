#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The four things the panel watches on its own, in the background.

Service health, certificate expiry, provider secret expiry and cabling drift are not module
checks: nobody configured them, they have no schedule of their own and they exist because
the panel is the only thing in a position to notice. Each is a thread started at boot with
its own interval, and each takes a lease first so that a deployment with several replicas
has one of them doing the work rather than all of them doing it badly.

They live together because they share a shape - wake up, look, notify if something changed -
and separately from the request handling they interrupt, since a scanner that raises must not
be able to take a page down with it.
"""

class _ScannersMixin:
    """Background scanners for :class:`WebAdmin`."""

    def _hold_scanner_lease(self, key: str, inst_id: str) -> None:
        """Remember which lease a scanner takes, so :meth:`stop_background` can give it back."""
        held = getattr(self, '_scanner_leases', None)
        if held is None:
            held = self._scanner_leases = {}
        held[key] = inst_id

    def _scan_every(self, section: str, key: str, default: int, floor: int) -> int:
        """A scanner's interval in seconds, as its loop reads it (never below *floor*)."""
        try:
            return max(floor, int(self._config_section(section).get(key) or default))
        except (TypeError, ValueError):
            return default

    def _alert_state(self, scope: str):
        """What an expiry scanner has already announced, kept in ``health_alerts`` so a
        restart or a lease move does not announce it all again. In memory when the table
        cannot be built (no connector)."""
        from lib.core.health.alert_state import AlertState  # noqa: PLC0415
        db = getattr(self, '_db_connector', None)
        if db is not None:
            try:
                return AlertState(db, scope=scope)
            except Exception:  # pylint: disable=broad-except
                pass
        return AlertState(scope=scope)

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
        self._hold_scanner_lease('svc_health', _inst_id)

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
        self._hold_scanner_lease('cert_scan', _inst_id)

        def _device_address(uid):
            store = getattr(self, '_devices_store', None)
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
            return enumerate_targets(mods, device_address=_device_address, default_warn=warn)

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True
            # The lease is renewed once per scan, so it must outlive the interval between two
            # (it was a flat hour against a daily scan: every replica took its turn, each with
            # its own idea of what had already been said).
            every = self._scan_every('certs', 'scan_every_secs', 86400, 3600)
            try:
                return bool(ls.try_acquire('cert_scan', _inst_id, host=hostname(),
                                           ttl=every * 3))
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
            state=self._alert_state('cert'),
        )
        self._cert_scanner.start(
            poll_getter=lambda: self._config_section('certs').get('scan_every_secs', 86400))

    def _start_cable_scanner(self) -> None:
        """Launch the background cabling scanner: warns when a declared cable's ports stop
        matching what the devices report over LLDP (``cable_moved``) and when two racked
        machines see each other with no cable declared between them (``cable_undeclared``).

        Leader-gated, enable read live (``dcim|notify_cabling``). **Discovery proposes**: this
        writes nothing to the inventory — what is declared is what a person declared, and the
        scanner exists so they are not told six months later by a torch and a cable tie.

        What has already been announced lives in `dc_drift`, a table rather than a dict, because
        the process that scans today is not the one that scans tomorrow — see that module.
        """
        if getattr(self, '_cable_scanner', None) is not None:
            return
        import os as _os  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
        from lib.core.dcim.drift import DriftStore  # noqa: PLC0415
        from lib.core.health.cable_scan import CableDriftScanner, DEFAULT_EVERY  # noqa: PLC0415
        from lib.services.heartbeat import hostname  # noqa: PLC0415
        from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
        _inst_id = f'cablescan-{hostname()}-{_os.getpid()}'
        self._hold_scanner_lease('cable_scan', _inst_id)

        def _check():
            """Lo mismo que la pestaña de cableado, pero de TODA la instalación.

            La pantalla acota por armario y por lo que ese lector puede ver; aquí no hay lector
            —es el sistema— así que se mira entero. Sin las aristas no se contesta: `checked`
            falso significa «no se ha podido preguntar», y el explorador lo distingue de «no hay
            nada» para no desdecirse en la vuelta siguiente.
            """
            from lib.core.dcim import service as dcim_svc  # noqa: PLC0415
            store = getattr(self, '_dcim_store', None)
            if store is None:
                return {}
            items = store.items.list()
            nombres = {}
            for it in items:
                ru = str(it.get('rack_uid') or '')
                if ru and ru not in nombres:
                    nombres[ru] = str((store.racks.get(ru) or {}).get('name') or '')
                it['rack_name'] = nombres.get(ru, '')
            armar = getattr(self, '_infra_topology', None)
            if not callable(armar):
                return {}
            edges = (armar(self._DEFAULT_LANG, evidence=False) or {}).get('edges') or []
            return dcim_svc.cable_check(store.cables.list(), items, edges)

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True
            try:
                cada = int(self._config_section('dcim').get('cable_scan_every_secs')
                           or DEFAULT_EVERY)
            except (TypeError, ValueError):
                cada = DEFAULT_EVERY
            try:
                # El arriendo dura más que una vuelta — si no, el que explora lo pierde entre
                # dos y cada pod se turna: cada uno con su propia idea de lo que ya dijo.
                return bool(ls.try_acquire('cable_scan', _inst_id, host=hostname(),
                                           ttl=max(600, cada * 3)))
            except Exception:  # pylint: disable=broad-except
                return True

        def _emit(kind, **fields):
            _dispatch(self, kind=kind, timestamp=_time.strftime('%Y-%m-%d %H:%M:%S'), **fields)

        try:
            estado = DriftStore(self._db_connector)
        except Exception:  # pylint: disable=broad-except
            self._cable_scanner = None
            return
        self._cable_scanner = CableDriftScanner(
            check_provider=_check,
            state=estado,
            dispatch=_emit,
            config_getter=lambda: self._config_section('dcim'),
            is_leader=_is_leader,
            dbg=self._dbg,
            text_fn=self._notify_text,
        )
        self._cable_scanner.start(
            poll_getter=lambda: self._config_section('dcim').get('cable_scan_every_secs',
                                                                 DEFAULT_EVERY))

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
        self._hold_scanner_lease('secret_scan', _inst_id)

        def _is_leader():
            ls = getattr(self, '_service_leader_store', None)
            if ls is None:
                return True
            every = self._scan_every('certs', 'scan_every_secs', 86400, 3600)
            try:
                return bool(ls.try_acquire('secret_scan', _inst_id, host=hostname(),
                                           ttl=every * 3))
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
            state=self._alert_state('secret'),
        )
        self._secret_scanner.start(
            poll_getter=lambda: self._config_section('certs').get('scan_every_secs', 86400))

    def stop_background(self) -> None:
        """Stop every thread the panel started on its own: the scanners and the backup runner.

        Each loop holds the instance through its closures, so an instance whose threads are
        left running is never freed. Safe to call twice and on a half-built instance.

        The references are dropped (the ``_start_*`` guards test them, so keeping them made a
        restart impossible) and the scanners' leases are given back, so another replica takes
        over now instead of when the lease runs out."""
        for name in ('_service_health', '_cert_scanner', '_cable_scanner', '_secret_scanner',
                     '_backup_runner'):
            worker = getattr(self, name, None)
            if worker is None:
                continue
            try:
                worker.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            setattr(self, name, None)
        held = getattr(self, '_scanner_leases', None) or {}
        self._scanner_leases = {}
        ls = getattr(self, '_service_leader_store', None)
        if ls is not None:
            for key, inst_id in held.items():
                try:
                    ls.release(key, inst_id)
                except Exception:  # pylint: disable=broad-except
                    pass
