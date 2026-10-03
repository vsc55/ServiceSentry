#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the devices domain contributes (the device registry — see :mod:`lib.discovery`)."""


# ── What a device IS ─────────────────────────────────────────────────────────────────────
#
# The registry holds servers, but it also holds a NAS, a switch, a UPS and whatever else
# answers on the network — the section was called "Servers" while the SNMP catalogue beside
# it shipped profiles for Mikrotik, Linksys and two makes of UPS.
#
# So a device says what it is, and the panel stops guessing. Declared here rather than in the
# store because it is a vocabulary, not a schema detail: the icon a row wears, the way a
# fleet is grouped, and one day what a discovery run proposes after asking a device over
# SNMP (`detect_profiles` already knows how to ask).
#
# It is a PROPERTY and deliberately not a section: everything the panel does with an entry —
# address, credential, profiles, maintenance, tags, the checks bound to it — is the same
# whichever of these it is, and splitting by type would force a decision at creation time
# that is often wrong. A NAS *is* a server; a hypervisor is both.
#
# `''` (unset) is always allowed and is what every existing device has: making people
# classify a fleet before they can save anything would be a worse form than none.
#
# **Y la lista ya no está aquí.** Eran once escritas en una tupla —servidor,
# hipervisor, NAS, conmutador…— y sólo se podían cambiar con un commit, así que lo que no cabía
# en ellas se quedaba «sin clasificar»: un punto de acceso, un teléfono IP, una controladora de
# riego. Ahora son filas de la tabla `device_type` y se editan desde el panel. Todo lo de arriba
# sigue valiendo: sigue siendo una PROPIEDAD y no una sección, y «sin clasificar» sigue siendo
# una respuesta.
#
# De aquellas once queda una semilla en `lib/core/devices/stores/types.py::SEED`, que se usa el día
# se crea la tabla y cuando alguien pide «añadir las básicas». **Nada las lee en caliente**: lo
# que decide si una clase existe es la tabla, y una guarda lo comprueba.


MODULE_PERMISSIONS = {
    'group': 'perm_group_devices',
    'order': 160,
    'permissions': (
        {'flag': 'devices_view',   'roles': ('editor', 'viewer')},  # view the servers tab
        {'flag': 'devices_add',    'roles': ()},                    # add modules/checks to a server
        {'flag': 'devices_edit',   'roles': ('editor',)},           # edit servers / device-bound checks
        {'flag': 'devices_delete', 'roles': ()},                    # delete servers
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import coverage_stat, server_list_rows, servers_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'servers', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 30,
     'perms': {'any': ['devices_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-infra'},
     'stat': servers_stat,
     'view': {'kind': 'stat', 'icon': 'bi-hdd-network-fill', 'label_key': 'overview_servers',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/servers'}},
    {'id': 'coverage', 'icon': 'bi-pie-chart', 'label_key': 'overview_coverage',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 100,
     'perms': {'any': ['devices_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-infra'},
     'stat': coverage_stat,
     'view': {'kind': 'stat', 'icon': 'bi-pie-chart-fill', 'label_key': 'overview_coverage',
              'accent': 'green', 'data_url': '/api/v1/overview/widget/coverage'}},
    {'id': 'servers_list', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 170,
     'perms': {'any': ['devices_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-infra'},
     'rows': server_list_rows,
     'view': {'kind': 'table', 'icon': 'bi-hdd-network', 'title_key': 'overview_servers',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/servers_list',
              'empty_key': 'device_monitor_none',
              # Compound severity filter: a level (warning/error) with a =/≥ operator, device
              # type (virtual/physical), and a maintenance checkbox that unions in devices in
              # maintenance. Levels with ``op:True`` show the =/≥ selector.
              'filter': {'kind': 'severity', 'store': 'srvf', 'param': 'f', 'maintenance': True,
                         'levels': [
                  {'v': '',        'label_key': 'all'},
                  {'v': 'warning', 'label_key': 'status_warning', 'op': True,
                   'badge': {'color': '#d97706', 'bg': 'rgba(245,158,11,.18)'}},
                  {'v': 'error',   'label_key': 'device_status_error', 'op': True,
                   'badge': {'color': '#dc3545', 'bg': 'rgba(220,53,69,.16)'}},
                  {'v': 'virtual', 'label_key': 'device_virtual',
                   'badge': {'color': '#0dcaf0', 'bg': 'rgba(13,202,240,.16)'}},
                  {'v': 'physical', 'label_key': 'device_physical'},
              ]},
              'columns': [
                  {'key': 'name',    'label_key': 'col_server',        'sortable': True, 'cell': 'device_name'},
                  {'key': 'status',  'label_key': 'col_device_status',   'sortable': True, 'cell': 'device_status'},
                  {'key': 'checks',  'label_key': 'col_checks',        'sortable': True, 'cell': 'device_checks'},
                  {'key': 'modules', 'label_key': 'col_device_modules',  'sortable': True, 'cell': 'device_modules'},
              ]}},
]


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'device_cloned', 'severity': 'success'},
    {'key': 'device_created', 'severity': 'success'},
    {'key': 'device_deleted', 'severity': 'danger'},
    {'key': 'device_ssh_tested', 'severity': 'muted'},
    {'key': 'device_test_check', 'severity': 'muted'},
    {'key': 'device_tested', 'severity': 'muted'},
    {'key': 'device_updated', 'severity': 'info'},
    # Soltar un dispositivo del sitio del que se importó. `info` y no `muted`: desde ese momento
    # deja de refrescarse y lo mantiene esta casa, y eso se pregunta meses después, cuando
    # alguien nota que un nombre ya no cuadra con el del inventario de al lado.
    {'key': 'device_unlinked', 'severity': 'info'},
    # Las clases de dispositivo que añade esta casa. `info` las tres, y no `muted`: cambian cómo
    # se clasifica la flota entera —el desplegable, el filtro, el icono— y quitar una es una
    # decisión que sólo se puede tomar cuando no la lleva nadie. «¿Desde cuándo hay una clase
    # que se llama así?» se pregunta meses después, mirando por qué un filtro no cuadra.
    {'key': 'device_type_created', 'severity': 'info'},
    {'key': 'device_type_updated', 'severity': 'info'},
    {'key': 'device_type_deleted', 'severity': 'info'},
    {'key': 'devices_migrated', 'severity': 'info'},
]


# ── What of this package can belong to a company ─────────────────────────────────────────
#
# A machine belongs to somebody whether or not it is bolted into a rack: a VM, a VIP, a laptop
# on a desk. The scope lived in the inventory's list of owner scopes, which said that a device
# with no rack was the inventory's business — it is not; the registry is here.
#
# No `chain`: a device has no container to inherit from. It belongs to whoever was told about it,
# and to nobody otherwise — which is the honest answer and the one every screen already draws.
ORG_SCOPES = ({'scope': 'device', 'label_key': 'orgs_scope_device'},)
