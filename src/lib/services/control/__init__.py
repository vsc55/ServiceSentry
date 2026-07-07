#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Services control plane — the cross-service coordination stores.

Shared by every service (monitoring / syslog / events) and the WebAdmin Services tab,
so they live at the services-subsystem level rather than in any one service:

* ``commands``  — :class:`~lib.services.control.commands.ServiceCommandsStore`  (queued start/stop commands)
* ``instances`` — :class:`~lib.services.control.instances.ServiceInstancesStore` (heartbeat/liveness rows)
* ``leader``    — :class:`~lib.services.control.leader.ServiceLeaderStore`       (single-owner leases)
"""
