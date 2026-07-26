#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Azure region **display names**, as a fallback for the region picker.

The public status filter is a substring match against the announcement text, and Azure
writes regions there the way they read in the portal ("West Europe"), not as resource
ids ("westeurope") — so this list holds display names.

The picker prefers the live list from the subscription (``/locations``), which is
authoritative and reflects what that subscription may actually use. This one exists
because the public feed needs **no credentials at all**: an item may legitimately have
none, and a field with no suggestions would then be the common case. It will drift as
Azure opens regions; that is acceptable for a suggestion list you can still type over.
"""

AZURE_REGIONS = (
    # Americas
    'Brazil South', 'Brazil Southeast',
    'Canada Central', 'Canada East',
    'Central US', 'East US', 'East US 2', 'North Central US', 'South Central US',
    'West Central US', 'West US', 'West US 2', 'West US 3',
    'Mexico Central',
    # Europe
    'France Central', 'France South',
    'Germany North', 'Germany West Central',
    'Italy North',
    'North Europe', 'Norway East', 'Norway West',
    'Poland Central',
    'Spain Central',
    'Sweden Central', 'Sweden South',
    'Switzerland North', 'Switzerland West',
    'UK South', 'UK West',
    'West Europe',
    # Middle East and Africa
    'Israel Central',
    'Qatar Central',
    'South Africa North', 'South Africa West',
    'UAE Central', 'UAE North',
    # Asia Pacific
    'Australia Central', 'Australia Central 2', 'Australia East', 'Australia Southeast',
    'Central India', 'South India', 'West India',
    'East Asia', 'Southeast Asia',
    'Japan East', 'Japan West',
    'Korea Central', 'Korea South',
    'Malaysia West',
    'New Zealand North',
)
