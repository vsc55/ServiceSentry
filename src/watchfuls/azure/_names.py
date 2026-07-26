#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful: reading Azure's identifiers
#
"""Turning ARM identifiers into something a person can read.

An Azure resource id is a paragraph of path, lower-cased by ARM on the way out, and a
resource *type* is a provider namespace nobody says out loud. A monitoring row has one
line to say what broke, so the whole job of this module is: id → name, group, readable
type, and a stable key.

Pure functions and lookup tables only — nothing here talks to Azure.
"""

# Friendly names for the types people actually run. ARM lower-cases the ids it returns,
# so the original casing ("virtualMachines") cannot be recovered from them — and
# "microsoft.compute/virtualmachines" is not what anyone calls a VM anyway.
_TYPE_NAMES = {
    'microsoft.compute/virtualmachines':                    'Virtual machine',
    'microsoft.compute/virtualmachinescalesets':            'VM scale set',
    'microsoft.compute/disks':                              'Disk',
    'microsoft.storage/storageaccounts':                    'Storage account',
    'microsoft.keyvault/vaults':                            'Key vault',
    'microsoft.network/virtualnetworkgateways':             'VPN gateway',
    'microsoft.network/connections':                        'VPN connection',
    'microsoft.network/virtualnetworks':                    'Virtual network',
    'microsoft.network/networkinterfaces':                  'Network interface',
    'microsoft.network/publicipaddresses':                  'Public IP',
    'microsoft.network/loadbalancers':                      'Load balancer',
    'microsoft.network/applicationgateways':                'Application gateway',
    'microsoft.network/networksecuritygroups':              'Network security group',
    'microsoft.network/azurefirewalls':                     'Firewall',
    'microsoft.network/bastionhosts':                       'Bastion',
    'microsoft.web/sites':                                  'App Service',
    'microsoft.web/serverfarms':                            'App Service plan',
    'microsoft.sql/servers':                                'SQL server',
    'microsoft.sql/servers/databases':                      'SQL database',
    'microsoft.dbformysql/servers':                         'MySQL server',
    'microsoft.dbforpostgresql/servers':                    'PostgreSQL server',
    'microsoft.containerservice/managedclusters':           'Kubernetes cluster',
    'microsoft.containerregistry/registries':               'Container registry',
    'microsoft.operationalinsights/workspaces':             'Log Analytics workspace',
    'microsoft.recoveryservices/vaults':                    'Recovery Services vault',
    'microsoft.documentdb/databaseaccounts':                'Cosmos DB',
    'microsoft.cache/redis':                                'Redis cache',
    'microsoft.apimanagement/service':                      'API Management',
}

# Types that Resource Health does not report on: alert RULES and the like are
# configuration, not running resources, so Azure answers "Unknown — this rule does not
# report health state". Listing them as warnings is pure noise, and it drags the whole
# section amber for nothing.
_NO_HEALTH_PREFIXES = ('microsoft.insights/', 'microsoft.alertsmanagement/',
                       'microsoft.security/', 'microsoft.portal/')


def _resource_type(res_id: str) -> str:
    """``microsoft.compute/virtualmachines`` out of a resource id (ARM lower-cases ids)."""
    parts = res_id.split('/providers/')
    if len(parts) < 2:
        return ''
    seg = parts[-1].split('/')
    return ('/'.join(seg[:2]) if len(seg) >= 2 else seg[0]).lower()


def _resource_group(res_id: str) -> str:
    """The resource group — the one piece of the id worth showing. The full id is a
    paragraph of path that pushes the name and state off the row."""
    seg = res_id.split('/')
    for i, s in enumerate(seg):
        if s.lower() == 'resourcegroups' and i + 1 < len(seg):
            return seg[i + 1]
    return ''


def _type_name(raw_type: str) -> str:
    """A readable type: the friendly name when known, else the id's last segment."""
    if not raw_type:
        return ''
    return _TYPE_NAMES.get(raw_type) or raw_type.rsplit('/', 1)[-1]


def _slug(res_id: str) -> str:
    """A stable, key-safe suffix for a resource id.

    The result key must survive across runs (it is what alert state and silences hang
    off), so it is derived from the id itself — never from its position in the answer,
    which moves as resources come and go.
    """
    out = ''.join(c if c.isalnum() else '_' for c in res_id.lower()).strip('_')
    return out[-120:] or 'resource'
