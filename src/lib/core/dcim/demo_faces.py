#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's own catalogue models: what they are, their faces and where each port is.

The demo cannot lean on whatever catalogue an installation happens to have imported, so it
brings its own models — maker «Demo». Each is a fictitious model of a real class of equipment,
and its data is what a real one of that class has: its U and depth, its size and weight, what it
draws, its ports by name and type, its bays, its dates of sale and support.

Their pictures —front, rear and the views of the inside— are drawn by `demo_draw` and kept as
SVG files in ``data/demo/faces/`` (``<key>.front.svg``, ``<key>.rear.svg``,
``<key>.<view id>.svg``), so they can be looked at and versioned. Every port and bay is placed by
the same line that draws it, so the cable leaves from where the socket is drawn; a test checks
the files are what the drawing code makes (``python -m lib.core.dcim.demo_draw`` writes them).
"""

from __future__ import annotations

import io
import os

from lib.core.dcim import demo_draw

#: Where the pictures are.
FACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'demo', 'faces')

#: The device models: key → (model, role, U, full depth). A 0U strip and the devices of a room
#: take no U: their size is their own (`WIDTH_MM`, `HEIGHT_MM`).
MODELS = {
    'server':   ('DM-R2 Server 2U', 'server', 2, True),
    'gpu':      ('DM-G2 GPU Server 2U', 'server', 2, True),
    'node':     ('DM-N1 Half-width Node', 'server', 1, True),
    'storage':  ('DM-S4 Storage Array', 'storage', 4, True),
    'tor':      ('DM-S48 Switch 48p', 'switch', 1, False),
    'access':   ('DM-S24 Switch 24p', 'switch', 1, False),
    'core':     ('DM-C32 Core Switch', 'switch', 2, False),
    'router':   ('DM-RT1 Router', 'router', 1, False),
    'cpe':      ('DM-CPE Carrier Router', 'router', 1, False),
    'firewall': ('DM-FW1 Firewall', 'firewall', 1, False),
    'patch':    ('DM-PP24 Patch Panel', 'patch_panel', 1, False),
    'fiber':    ('DM-FP24 Fiber Panel', 'fiber_panel', 1, False),
    'console':  ('DM-CS16 Console Server', 'console', 1, False),
    'kvm':      ('DM-KVM8 KVM', 'kvm', 1, False),
    'mini':     ('DM-MINI Mini PC', 'server', 1, False),
    # The power of every rack: the vertical strips of its channels, by the feed they take, the
    # 1U strip of a small rack, and the UPS on the floor beside one.
    'pdu0u16':  ('DM-PDU0-16 Metered PDU 0U 16 A', 'pdu', 0, False),
    'pdu0u32':  ('DM-PDU0-32 Metered PDU 0U 32 A', 'pdu', 0, False),
    'pdu0u3p':  ('DM-PDU0-3P Switched PDU 0U 3-phase', 'pdu', 0, False),
    'pdu1u':    ('DM-PDU1-16 PDU 1U 16 A', 'pdu', 1, False),
    'ups1k5':   ('DM-UPS1500 UPS 1.5 kVA', 'ups', 2, True),
    'ups3k':    ('DM-UPS3000 UPS 3 kVA', 'ups', 2, True),
    'ups6k':    ('DM-UPS6000 UPS 6 kVA', 'ups', 4, True),
    # What closes, tidies and holds in a rack.
    'blank':    ('DM-BP1 Blanking Panel 1U', 'blank', 1, False),
    'cablemgr': ('DM-CM1 Cable Manager 1U', 'blank', 1, False),
    'shelf':    ('DM-SH1 Shelf 1U', 'shelf', 1, False),
    # And what is on a desk, a ceiling or a wall of the offices.
    'pc':       ('DM-PC5 Desktop PC', 'pc', 0, False),
    'phone':    ('DM-IP4 IP Phone', 'phone', 0, False),
    'ap':       ('DM-AP7 Access Point', 'ap', 0, False),
    'camera':   ('DM-CAM4 Dome Camera', 'camera', 0, False),
    'display':  ('DM-DS55 Display 55"', 'display', 0, False),
    'printer':  ('DM-MFP4 Multifunction Printer', 'printer', 0, False),
}

#: The cabinets: key → (model, U, outer width, outer depth, outer height, form factor).
RACKS = {
    'rack612': ('DM-RK42-612 Server Rack 42U 600×1200', 42, 600, 1200, 2000, '4-post-cabinet'),
    'rack810': ('DM-RK42-810 Network Rack 42U 800×1000', 42, 800, 1000, 2000,
                '4-post-cabinet'),
    'rack610': ('DM-RK42-610 Rack 42U 600×1000', 42, 600, 1000, 2000, '4-post-cabinet'),
    'rack608': ('DM-RK24-608 Rack 24U 600×800', 24, 600, 800, 1200, '4-post-cabinet'),
    'wall12':  ('DM-WM12-645 Wall Cabinet 12U 600×450', 12, 600, 450, 635, 'wall-cabinet'),
}

#: The modules —what slides into a device's bay, as a piece one buys to replace, often with
#: ports of its own—: key → (model, catalogue kind, the kind of the part it becomes, size).
MODULES = {
    'psu800':  ('DM-PSU800 800 W Power Supply', 'psu', 'psu', '800 W'),
    'psu2000': ('DM-PSU2000 2000 W Power Supply', 'psu', 'psu', '2000 W'),
    'psu500':  ('DM-PSU500 500 W Power Supply', 'psu', 'psu', '500 W'),
    'psu1100': ('DM-PSU1100 1100 W Power Supply', 'psu', 'psu', '1100 W'),
    'psu400':  ('DM-PSU400 400 W Power Supply', 'psu', 'psu', '400 W'),
    'pcm':     ('DM-PCM1100 Power & Cooling Module', 'psu', 'psu', '1100 W'),
    'fansrv':  ('DM-FAN60 Server Fan Module', 'fan', 'fan', ''),
    'fantray': ('DM-FT40 Fan Tray', 'fan', 'fan', ''),
    'ocp25':   ('DM-OCP25-2 OCP 3.0 Adapter 2×25 GbE', 'nic', 'nic', '2 × 25 GbE'),
    'ctrl':    ('DM-S4-CTRL Storage Controller', 'module', 'module', ''),
    'sfp10sr': ('DM-SFP10-SR SFP+ 10GBASE-SR', 'transceiver', 'transceiver', '10 Gbps'),
    'sfp10lr': ('DM-SFP10-LR SFP+ 10GBASE-LR', 'transceiver', 'transceiver', '10 Gbps'),
}

#: The components —what goes inside, with no port of its own—: key → (model, kind, size).
COMPONENTS = {
    'rdimm32':  ('DM-RD5-32 32 GB DDR5-4800 RDIMM', 'memory', '32 GB'),
    'rdimm64':  ('DM-RD5-64 64 GB DDR5-5600 RDIMM', 'memory', '64 GB'),
    'sodimm16': ('DM-SD5-16 16 GB DDR5-5600 SODIMM', 'memory', '16 GB'),
    'cpu32':    ('DM-X32 32-core Server CPU', 'cpu', ''),
    'nvme192':  ('DM-NV3-1T9 1.92 TB NVMe U.2 SSD', 'ssd', '1.92 TB'),
    'ssd480':   ('DM-SA3-480 480 GB SATA SSD', 'ssd', '480 GB'),
    'hdd8t':    ('DM-HD7-8T 8 TB SAS HDD', 'disk', '8 TB'),
    'm2boot':   ('DM-M2-480 480 GB M.2 NVMe SSD', 'ssd', '480 GB'),
    'gpu24':    ('DM-L24 Inference GPU 24 GB', 'gpu', '24 GB'),
    'bbu':      ('DM-SCAP Cache Supercapacitor', 'battery', ''),
}

#: Each tree of the catalogue and its keys, in the order the demo installs them.
TREES = (('device-types', tuple(MODELS)), ('rack-types', tuple(RACKS)),
         ('module-types', tuple(MODULES)), ('component-types', tuple(COMPONENTS)))


def tree_of(key: str) -> str:
    """The catalogue tree a demo model belongs to."""
    return next(t for t, keys in TREES if key in keys)


def every() -> list:
    """Every demo model's key, of every tree."""
    return [k for _t, keys in TREES for k in keys]


def name_of(key: str) -> str:
    """A demo model's name, whatever its tree."""
    for tabla in (MODELS, RACKS, MODULES, COMPONENTS):
        if key in tabla:
            return tabla[key][0]
    raise KeyError(key)


#: The devices that are not 19 inches wide: the half-width node and carrier router, the mini
#: PC, a 0U strip, and what is on a desk or a ceiling.
WIDTH_MM = {'node': demo_draw.HALF, 'cpe': demo_draw.HALF, 'mini': demo_draw.MINI,
            'pdu0u16': 56.0, 'pdu0u32': 56.0, 'pdu0u3p': 56.0,
            'pc': 290.0, 'phone': 210.0, 'ap': 230.0, 'camera': 140.0, 'display': 1232.0,
            'printer': 420.0}
#: And how tall the ones with no U are drawn: a 0U strip is as long as its cabinet's frame.
HEIGHT_MM = {'pdu0u16': 1780.0, 'pdu0u32': 1780.0, 'pdu0u3p': 1780.0, 'pc': 95.0,
             'phone': 190.0, 'ap': 230.0, 'camera': 140.0, 'display': 710.0, 'printer': 460.0}


def _life(launched, end_of_sale, eol, attach='', maintenance='', security='', renewal=''):
    """The life-cycle dates, in the order the model's sheet shows them. A passive panel has
    no patches and no support contract: only when it came out, stopped being sold, and the
    end of its system warranty."""
    out = {'launched': launched, 'end_of_sale': end_of_sale, 'eol': eol}
    for k, v in (('last_contract_attach', attach), ('end_of_maintenance', maintenance),
                 ('end_of_security', security), ('last_contract_renewal', renewal)):
        if v:
            out[k] = v
    return out


def _phys(w, h, d, kg, typical=0, peak=0, warranty=0):
    out = {'width_mm': w, 'height_mm': h, 'depth_mm': d, 'weight': kg, 'weight_unit': 'kg'}
    if typical:
        out['typical_power_w'] = typical
    if peak:
        out['max_power_w'] = peak
    if warranty:
        out['warranty_years'] = warranty
    return out


#: What a model's sheet says beyond its ports: its part number, how it is powered, and its
#: `extra` —size, weight, power, warranty, the dates of its life, what its class is measured
#: by—. Each set of figures is what a real model of its class has; the dates are spread so the
#: catalogue has models current, ending soon and already out of support.
SPECS = {
    'server': {
        'part_number': 'DM-R2-24SFF-2S', 'power_type': 'internal',
        'extra': dict(_phys(434, 86.8, 750, 28.6, 450, 760, 3),
                      sockets_max=2, memory_type='DDR5 RDIMM', memory_max_gb=4096,
                      drive_bays=24, management='BMC · IPMI 2.0 · Redfish',
                      **_life('2023-02-14', '2027-12-31', '2030-12-31', '2028-12-31',
                              '2030-12-31', '2030-12-31', '2030-09-30'))},
    'gpu': {
        'part_number': 'DM-G2-8GPU-2S', 'power_type': 'internal',
        'extra': dict(_phys(434, 86.8, 800, 31.5, 1200, 1850, 3),
                      sockets_max=2, memory_type='DDR5 RDIMM', memory_max_gb=3072,
                      drive_bays=8, gpu_slots=8, management='BMC · IPMI 2.0 · Redfish',
                      **_life('2024-09-10', '2028-09-30', '2031-09-30', '2029-09-30',
                              '2031-09-30', '2031-09-30', '2031-06-30'))},
    'node': {
        'part_number': 'DM-N1-HW-1S', 'power_type': 'internal',
        'extra': dict(_phys(215, 42.8, 600, 7.4, 210, 420, 3),
                      sockets_max=1, memory_type='DDR5 RDIMM', memory_max_gb=1024,
                      drive_bays=2, management='BMC · IPMI 2.0 · Redfish',
                      **_life('2022-06-01', '2026-06-30', '2029-06-30', '2027-06-30',
                              '2029-06-30', '2029-06-30', '2029-03-31'))},
    'storage': {
        'part_number': 'DM-S4-24LFF-DC', 'power_type': 'internal',
        'extra': dict(_phys(447, 176, 700, 41.0, 520, 880, 5),
                      drive_bays=24, management='HTTPS · SSH · SNMP v3',
                      **_life('2021-04-20', '2025-04-30', '2028-04-30', '2026-04-30',
                              '2028-04-30', '2028-04-30', '2028-01-31'))},
    'tor': {
        'part_number': 'DM-S48-P4X', 'power_type': 'internal',
        'extra': dict(_phys(440, 44, 420, 6.9, 370, 1650, 5),
                      switching_gbps=176, poe_budget_w=1440,
                      **_life('2022-03-01', '2027-03-31', '2032-03-31', '2028-03-31',
                              '2032-03-31', '2031-03-31', '2031-12-31'))},
    'access': {
        'part_number': 'DM-S24-4X', 'power_type': 'internal',
        'extra': dict(_phys(440, 44, 250, 3.4, 32, 48, 5),
                      switching_gbps=128,
                      **_life('2020-11-02', '2025-10-31', '2030-10-31', '2026-10-31',
                              '2030-10-31', '2029-10-31', '2030-07-31'))},
    'core': {
        'part_number': 'DM-C32-48X4C', 'power_type': 'internal',
        'extra': dict(_phys(440, 88, 480, 14.8, 420, 780, 5),
                      switching_gbps=1760,
                      **_life('2021-09-15', '2026-09-30', '2031-09-30', '2027-09-30',
                              '2031-09-30', '2030-09-30', '2031-06-30'))},
    'router': {
        'part_number': 'DM-RT1-8G4X', 'power_type': 'internal',
        'extra': dict(_phys(440, 44, 440, 7.3, 140, 320, 1),
                      throughput_gbps=20,
                      **_life('2017-05-02', '2022-10-31', '2027-03-31', '2023-10-31',
                              '2026-10-31', '2026-04-30', '2026-07-31'))},
    'cpe': {
        'part_number': 'DM-CPE-8G2X', 'power_type': 'internal',
        'extra': dict(_phys(215, 44, 230, 2.1, 24, 40, 2),
                      throughput_gbps=10,
                      **_life('2023-05-10', '2028-05-31', '2033-05-31', '2029-05-31',
                              '2033-05-31', '2032-05-31', '2033-02-28'))},
    'firewall': {
        'part_number': 'DM-FW1-16G8S4X', 'power_type': 'internal',
        'extra': dict(_phys(440, 44, 480, 8.4, 190, 310, 3),
                      throughput_gbps=20, management='HTTPS · SSH · SNMP v3',
                      **_life('2023-10-03', '2028-10-31', '2033-10-31', '2029-10-31',
                              '2033-10-31', '2033-10-31', '2033-07-31'))},
    'patch': {
        'part_number': 'DM-PP24-C6A-S', 'is_powered': 0,
        'extra': dict(_phys(482.6, 44, 120, 1.3, warranty=25),
                      **_life('2019-01-15', '2029-12-31', '2044-01-15'))},
    'fiber': {
        'part_number': 'DM-FP24-LCU-OS2', 'is_powered': 0,
        'extra': dict(_phys(482.6, 44, 280, 2.2, warranty=25),
                      **_life('2020-02-03', '2030-12-31', '2045-02-03'))},
    'console': {
        'part_number': 'DM-CS16-LTE', 'power_type': 'internal',
        'extra': dict(_phys(440, 44, 300, 3.9, 22, 36, 2),
                      management='HTTPS · SSH · SNMP v3',
                      **_life('2015-03-02', '2021-12-31', '2026-06-30', '2022-12-31',
                              '2024-12-31', '2025-12-31', '2025-09-30'))},
    'kvm': {
        'part_number': 'DM-KVM8-17L', 'power_type': 'internal',
        'extra': dict(_phys(482.6, 44, 470, 14.2, 30, 45, 2),
                      display='17" TFT · 1280 × 1024',
                      **_life('2019-09-16', '2024-09-30', '2027-09-30', '2025-09-30',
                              '2027-09-30', '2026-12-31', '2027-06-30'))},
    'mini': {
        'part_number': 'DM-MINI-U7', 'power_type': 'external',
        'extra': dict(_phys(177, 44, 180, 1.3, 18, 90, 3),
                      memory_type='DDR5 SODIMM', memory_max_gb=96, drive_bays=1,
                      **_life('2024-01-08', '2026-12-31', '2029-12-31', '2027-06-30',
                              '2029-12-31', '2029-12-31', '2029-09-30'))},
}

def _rack(w, d, h, kg, max_kg, mounting, doors, **more):
    """A cabinet's sheet: its outer size, its 19-inch frame and what it carries."""
    return dict({'width': 19, 'starting_unit': 1, 'desc_units': False,
                 'outer_width': w, 'outer_depth': d, 'outer_height': h, 'outer_unit': 'mm',
                 'mounting_depth': mounting, 'weight': kg, 'max_weight': max_kg,
                 'weight_unit': 'kg', 'warranty_years': 10, 'doors': doors}, **more)


#: The rest of the catalogue, in the same shape: the cabinets, the power, the passive pieces,
#: the devices of the offices, the modules and the components. Again what a real one of each
#: class has, and again dates spread between current, ending soon and past.
SPECS.update({
    # ── The cabinets ──
    'rack612': {
        'part_number': 'DM-RK42-612-B',
        'extra': dict(_rack(600, 1200, 2000, 128, 1500, 1000,
                            'front: perforated 80 % · rear: split perforated 80 %',
                            static_load_kg=1500, dynamic_load_kg=1000, ip_rating='IP20',
                            side_panels='lockable, removable', colour='RAL 9005'),
                      **_life('2018-03-01', '2028-12-31', '2038-12-31'))},
    'rack810': {
        'part_number': 'DM-RK42-810-N',
        'extra': dict(_rack(800, 1000, 2000, 118, 1300, 800,
                            'front: perforated 80 % · rear: split perforated 80 %',
                            static_load_kg=1300, dynamic_load_kg=900, ip_rating='IP20',
                            cable_management='2 × vertical ducts 150 mm, finger cable guides',
                            colour='RAL 9005'),
                      **_life('2018-03-01', '2028-12-31', '2038-12-31'))},
    'rack610': {
        'part_number': 'DM-RK42-610-B',
        'extra': dict(_rack(600, 1000, 2000, 105, 1200, 800,
                            'front: perforated 80 % · rear: perforated 80 %',
                            static_load_kg=1200, dynamic_load_kg=800, ip_rating='IP20',
                            colour='RAL 9005'),
                      **_life('2016-05-02', '2026-06-30', '2036-06-30'))},
    'rack608': {
        'part_number': 'DM-RK24-608-B',
        'extra': dict(_rack(600, 800, 1200, 62, 800, 600,
                            'front: perforated 80 % · rear: perforated 80 %',
                            static_load_kg=800, dynamic_load_kg=500, ip_rating='IP20',
                            castors='4, two with brake', colour='RAL 9005'),
                      **_life('2019-09-02', '2029-12-31', '2039-12-31'))},
    'wall12': {
        'part_number': 'DM-WM12-645-G',
        'extra': dict(_rack(600, 450, 635, 24, 60, 360,
                            'front: toughened glass, lockable · rear: solid, wall-fixed',
                            form_mount='wall', ip_rating='IP20', colour='RAL 7035'),
                      **_life('2017-02-01', '2025-12-31', '2035-12-31'))},
    # ── The power ──
    'pdu0u16': {
        'part_number': 'DM-PDU0-16-M24', 'power_type': 'internal',
        'extra': dict(_phys(56, 1780, 52, 4.8, 8, 12, 2),
                      input='230 V~ 16 A 1-phase', max_load_w=3680, outlets_total=24,
                      metering='per inlet, ±1 %', management='HTTPS · SSH · SNMP v3',
                      **_life('2021-06-01', '2026-12-31', '2031-12-31', '2027-06-30',
                              '2031-12-31', '2030-12-31', '2031-06-30'))},
    'pdu0u32': {
        'part_number': 'DM-PDU0-32-M24', 'power_type': 'internal',
        'extra': dict(_phys(56, 1780, 56, 6.2, 9, 14, 2),
                      input='230 V~ 32 A 1-phase', max_load_w=7360, outlets_total=24,
                      metering='per bank, ±1 %', management='HTTPS · SSH · SNMP v3',
                      **_life('2021-06-01', '2026-12-31', '2031-12-31', '2027-06-30',
                              '2031-12-31', '2030-12-31', '2031-06-30'))},
    'pdu0u3p': {
        'part_number': 'DM-PDU0-3P32-S24', 'power_type': 'internal',
        'extra': dict(_phys(56, 1780, 64, 8.9, 12, 18, 3),
                      input='400 V 3~ 32 A', max_load_w=22080, outlets_total=24,
                      metering='per outlet, ±1 %', switching='per outlet',
                      management='HTTPS · SSH · SNMP v3',
                      **_life('2023-02-01', '2029-12-31', '2034-12-31', '2030-06-30',
                              '2034-12-31', '2033-12-31', '2034-06-30'))},
    'pdu1u': {
        'part_number': 'DM-PDU1-16-B12', 'power_type': 'internal',
        'extra': dict(_phys(482.6, 44, 200, 2.1, 1, 2, 2),
                      input='230 V~ 16 A 1-phase', max_load_w=3680, outlets_total=12,
                      **_life('2016-04-04', '2023-12-31', '2026-12-31', '2024-06-30',
                              '2026-06-30', '2026-06-30', '2026-03-31'))},
    'ups1k5': {
        'part_number': 'DM-UPS1500-RT2U', 'power_type': 'internal',
        'extra': dict(_phys(438, 86, 470, 24.0, 35, 90, 2),
                      topology='line-interactive', va_rating=1500, watt_rating=1350,
                      battery='4 × 12 V 9 Ah VRLA, hot-swap', runtime_half_load_min=17,
                      management='NMC · HTTPS · SNMP v3',
                      **_life('2018-09-03', '2024-06-30', '2027-03-31', '2025-06-30',
                              '2027-03-31', '2027-03-31', '2026-12-31'))},
    'ups3k': {
        'part_number': 'DM-UPS3000-OL2U', 'power_type': 'internal',
        'extra': dict(_phys(438, 86, 630, 33.5, 120, 260, 3),
                      topology='on-line double conversion', va_rating=3000, watt_rating=2700,
                      battery='6 × 12 V 9 Ah VRLA, hot-swap', runtime_half_load_min=14,
                      management='NMC · HTTPS · SNMP v3',
                      **_life('2022-01-10', '2028-12-31', '2032-12-31', '2029-06-30',
                              '2032-12-31', '2032-12-31', '2032-09-30'))},
    'ups6k': {
        'part_number': 'DM-UPS6000-OL4U', 'power_type': 'internal',
        'extra': dict(_phys(438, 174, 680, 61.0, 260, 540, 3),
                      topology='on-line double conversion', va_rating=6000, watt_rating=6000,
                      battery='16 × 12 V 9 Ah VRLA, hot-swap', runtime_half_load_min=11,
                      management='NMC · HTTPS · SNMP v3',
                      **_life('2022-01-10', '2028-12-31', '2032-12-31', '2029-06-30',
                              '2032-12-31', '2032-12-31', '2032-09-30'))},
    # ── What closes, tidies and holds ──
    'blank': {
        'part_number': 'DM-BP1-TL', 'is_powered': 0,
        'extra': dict(_phys(482.6, 44, 12, 0.3, warranty=10),
                      material='ABS, tool-less clips',
                      **_life('2015-01-12', '2030-12-31', '2040-12-31'))},
    'cablemgr': {
        'part_number': 'DM-CM1-5D', 'is_powered': 0,
        'extra': dict(_phys(482.6, 44, 90, 0.9, warranty=10),
                      material='steel, 5 D-rings and brush strip',
                      **_life('2015-01-12', '2030-12-31', '2040-12-31'))},
    'shelf': {
        'part_number': 'DM-SH1-500V', 'is_powered': 0,
        'extra': dict(_phys(482.6, 44, 500, 3.2, warranty=10),
                      max_load_kg=25, mounting='front posts (cantilever)',
                      **_life('2015-01-12', '2030-12-31', '2040-12-31'))},
    # ── The devices of the offices ──
    'pc': {
        'part_number': 'DM-PC5-SFF-U5', 'power_type': 'internal',
        'extra': dict(_phys(292, 95, 290, 4.6, 22, 180, 3),
                      memory_type='DDR5 SODIMM', memory_max_gb=64, drive_bays=1,
                      management='vPro-class out-of-band',
                      **_life('2023-04-03', '2026-06-30', '2028-06-30', '2026-12-31',
                              '2028-06-30', '2028-06-30', '2028-03-31'))},
    'phone': {
        'part_number': 'DM-IP4-G', 'power_type': 'poe',
        'extra': dict(_phys(210, 190, 180, 1.1, 4, 7, 2),
                      poe_class='802.3af class 2', display='4.3" colour',
                      **_life('2019-06-03', '2024-12-31', '2027-03-31', '2025-06-30',
                              '2026-12-31', '2027-03-31', '2026-12-31'))},
    'ap': {
        'part_number': 'DM-AP7-4X4', 'power_type': 'poe',
        'extra': dict(_phys(230, 50, 230, 1.0, 18, 25, 5),
                      poe_class='802.3at (PoE+)', radios='2.4 / 5 / 6 GHz, 4×4 MIMO',
                      throughput_gbps=18,
                      **_life('2024-10-01', '2029-12-31', '2034-12-31', '2030-06-30',
                              '2034-12-31', '2034-12-31', '2034-09-30'))},
    'camera': {
        'part_number': 'DM-CAM4-IR28', 'power_type': 'poe',
        'extra': dict(_phys(140, 110, 140, 0.6, 5, 9, 3),
                      poe_class='802.3af class 3', resolution='4 MP · 2688 × 1520',
                      ir_range_m=30, ip_rating='IP67 · IK10',
                      **_life('2022-03-01', '2027-12-31', '2030-12-31', '2028-06-30',
                              '2030-12-31', '2030-12-31', '2030-09-30'))},
    'display': {
        'part_number': 'DM-DS55-UHD', 'power_type': 'internal',
        'extra': dict(_phys(1232, 710, 58, 15.8, 95, 180, 3),
                      display='55" 3840 × 2160, 500 cd/m², 18/7', vesa='400 × 400',
                      **_life('2021-09-01', '2026-03-31', '2029-03-31', '2026-09-30',
                              '2029-03-31', '2029-03-31', '2028-12-31'))},
    'printer': {
        'part_number': 'DM-MFP4-A4C', 'power_type': 'internal',
        'extra': dict(_phys(420, 460, 470, 28.0, 450, 1100, 1),
                      speed_ppm=40, duplex='yes', scanner='single-pass duplex ADF',
                      **_life('2020-02-03', '2024-12-31', '2027-01-31', '2025-06-30',
                              '2026-12-31', '2027-01-31', '2026-10-31'))},
    # ── The modules ──
    'psu800': {
        'part_number': 'DM-PSU800-P', 'power_type': 'internal', 'size': '800 W',
        'extra': dict(_phys(86, 40, 185, 0.9, 80, 880, 3),
                      form_factor='CRPS', efficiency='80+ Platinum',
                      **_life('2023-02-14', '2027-12-31', '2030-12-31'))},
    'psu2000': {
        'part_number': 'DM-PSU2000-T', 'power_type': 'internal', 'size': '2000 W',
        'extra': dict(_phys(106, 40, 240, 1.4, 200, 2200, 3),
                      form_factor='CRPS', efficiency='80+ Titanium',
                      **_life('2024-09-10', '2028-09-30', '2031-09-30'))},
    'psu500': {
        'part_number': 'DM-PSU500-P', 'power_type': 'internal', 'size': '500 W',
        'extra': dict(_phys(60, 40, 185, 0.7, 50, 550, 3),
                      form_factor='CRPS', efficiency='80+ Platinum',
                      **_life('2022-06-01', '2026-06-30', '2029-06-30'))},
    'psu1100': {
        'part_number': 'DM-PSU1100-AC', 'power_type': 'internal', 'size': '1100 W',
        'extra': dict(_phys(85, 40, 200, 1.1, 110, 1210, 5),
                      form_factor='CRPS', efficiency='80+ Platinum',
                      **_life('2021-09-15', '2027-03-31', '2032-03-31'))},
    'psu400': {
        'part_number': 'DM-PSU400-AC', 'power_type': 'internal', 'size': '400 W',
        'extra': dict(_phys(82, 40, 180, 0.8, 40, 440, 1),
                      form_factor='CRPS', efficiency='80+ Gold',
                      **_life('2017-05-02', '2022-10-31', '2027-03-31'))},
    'pcm': {
        'part_number': 'DM-PCM1100-S4', 'power_type': 'internal', 'size': '1100 W',
        'extra': dict(_phys(90, 168, 330, 4.2, 120, 1210, 5),
                      efficiency='80+ Platinum', fans=2,
                      **_life('2021-04-20', '2025-04-30', '2028-04-30'))},
    'fansrv': {
        'part_number': 'DM-FAN60-HS', 'power_type': 'internal',
        'extra': dict(_phys(64, 40, 56, 0.15, 4, 18, 3),
                      rpm=16800, cfm=42, **_life('2022-06-01', '2027-12-31', '2031-09-30'))},
    'fantray': {
        'part_number': 'DM-FT40-F2B', 'power_type': 'internal',
        'extra': dict(_phys(48, 37, 120, 0.3, 6, 22, 5),
                      rpm=21000, cfm=26, **_life('2017-05-02', '2027-03-31', '2032-03-31'))},
    'ocp25': {
        'part_number': 'DM-OCP25-2SFP28', 'power_type': 'internal', 'size': '2 × 25 GbE',
        'extra': dict(_phys(76, 11.5, 115, 0.12, 10, 16, 3),
                      interface='OCP NIC 3.0', ports=2, link_speed='25 Gbps',
                      connector='SFP28',
                      **_life('2023-02-14', '2027-12-31', '2030-12-31'))},
    'ctrl': {
        'part_number': 'DM-S4-CTRL-10G', 'power_type': 'internal',
        'extra': dict(_phys(282.6, 82, 480, 3.6, 60, 95, 5),
                      host_ports='4 × 10 GbE SFP+', cache_gb=32,
                      management='HTTPS · SSH · SNMP v3',
                      **_life('2021-04-20', '2025-04-30', '2028-04-30'))},
    'sfp10sr': {
        'part_number': 'DM-SFP10-SR-MM', 'power_type': 'internal', 'size': '10 Gbps',
        'extra': dict(_phys(14, 8.5, 56.5, 0.02, 0.8, 1, 5),
                      form_factor='SFP+', link_speed='10 Gbps', wavelength_nm=850,
                      distance_m=400, fibre='OM3 / OM4 multimode', connector='LC duplex',
                      **_life('2016-03-01', '2030-12-31', '2035-12-31'))},
    'sfp10lr': {
        'part_number': 'DM-SFP10-LR-SM', 'power_type': 'internal', 'size': '10 Gbps',
        'extra': dict(_phys(14, 8.5, 56.5, 0.02, 1.0, 1.5, 5),
                      form_factor='SFP+', link_speed='10 Gbps', wavelength_nm=1310,
                      distance_m=10000, fibre='OS2 single-mode', connector='LC duplex',
                      **_life('2016-03-01', '2030-12-31', '2035-12-31'))},
    # ── The components ──
    'rdimm32': {
        'part_number': 'DM-RD5-32G4800', 'size': '32 GB',
        'extra': dict(_phys(133.35, 31.25, 3.8, 0.03, warranty=5),
                      ddr='DDR5', form_factor='DIMM', module_type='RDIMM', speed_mts=4800,
                      pc_rating='PC5-38400 · DDR5-4800', cl=40, ranks=2, voltage_v=1.1,
                      ecc='yes', **_life('2023-01-10', '2027-06-30', '2030-12-31'))},
    'rdimm64': {
        'part_number': 'DM-RD5-64G5600', 'size': '64 GB',
        'extra': dict(_phys(133.35, 31.25, 3.8, 0.035, warranty=5),
                      ddr='DDR5', form_factor='DIMM', module_type='RDIMM', speed_mts=5600,
                      pc_rating='PC5-44800 · DDR5-5600', cl=46, ranks=2, voltage_v=1.1,
                      ecc='yes', **_life('2024-06-03', '2028-06-30', '2031-12-31'))},
    'sodimm16': {
        'part_number': 'DM-SD5-16G5600', 'size': '16 GB',
        'extra': dict(_phys(69.6, 30, 3.8, 0.01, warranty=5),
                      ddr='DDR5', form_factor='SODIMM', module_type='UDIMM', speed_mts=5600,
                      pc_rating='PC5-44800 · DDR5-5600', cl=46, ranks=1, voltage_v=1.1,
                      ecc='no', **_life('2023-09-04', '2026-12-31', '2028-12-31'))},
    'cpu32': {
        'part_number': 'DM-X32-2400',
        'extra': dict(_phys(77.5, 7, 56.5, 0.09, 220, 270, 3),
                      segment='server', sockets_max=2, cores=32, threads=64, base_ghz=2.4,
                      turbo_ghz=3.6, tdp_w=270, cache_l3_mb=96, memory_type='DDR5 RDIMM',
                      memory_channels=8, memory_max_gb=4096, ecc='yes', pcie_gen=5,
                      pcie_lanes=80, **_life('2023-01-10', '2027-06-30', '2030-12-31'))},
    'nvme192': {
        'part_number': 'DM-NV3-1T92-U2', 'size': '1.92 TB',
        'extra': dict(_phys(69.85, 15, 100.45, 0.13, 8, 14, 5),
                      form_factor='U.2', interface='NVMe', interface_detail='PCIe 4.0 x4',
                      endurance_tbw=3500, nand='TLC', encryption='AES-XTS-256',
                      **_life('2022-05-02', '2027-03-31', '2029-12-31'))},
    'ssd480': {
        'part_number': 'DM-SA3-480-25', 'size': '480 GB',
        'extra': dict(_phys(69.85, 7, 100, 0.05, 1.5, 3, 5),
                      form_factor='2.5"', interface='SATA', interface_detail='SATA 6 Gb/s',
                      endurance_tbw=876, nand='TLC',
                      **_life('2020-03-02', '2025-06-30', '2027-03-31'))},
    'hdd8t': {
        'part_number': 'DM-HD7-8T-SAS', 'size': '8 TB',
        'extra': dict(_phys(101.6, 26.1, 147, 0.7, 7, 11, 5),
                      form_factor='3.5"', interface='SAS', rpm=7200,
                      interface_detail='SAS 12 Gb/s', cache='256 MB',
                      encryption='AES-256', **_life('2020-06-01', '2025-06-30', '2028-06-30'))},
    'm2boot': {
        'part_number': 'DM-M2-480-2280', 'size': '480 GB',
        'extra': dict(_phys(22, 3.6, 80, 0.008, 3, 6, 5),
                      form_factor='M.2 2280', interface='NVMe', interface_detail='PCIe 4.0 x4',
                      endurance_tbw=876, nand='TLC',
                      **_life('2022-05-02', '2027-03-31', '2029-12-31'))},
    'gpu24': {
        'part_number': 'DM-L24-LP', 'size': '24 GB',
        'extra': dict(_phys(168, 68.9, 18.5, 0.4, 60, 72, 3),
                      interface='PCIe x16', tdp_w=72, cooling='passive',
                      **_life('2024-09-10', '2028-09-30', '2031-09-30'))},
    'bbu': {
        'part_number': 'DM-SCAP-S4',
        'extra': dict(_phys(90, 40, 30, 0.12, warranty=5),
                      voltage_v=9.6, holdup='cache to flash in < 60 s',
                      **_life('2021-04-20', '2025-04-30', '2028-04-30'))},
})

#: The power cord each model takes, by the inlet it has: a 2000 W supply is a C20 and is fed
#: by a C19 cord; everything else by the C13 of a rack PDU.
CORD = {'iec-60320-c20': 'c19-c20'}


def ports_of(key: str) -> tuple:
    """``(ports, port_list, port_map)`` of a demo model, in the catalogue's own shapes: the
    counts by family and type, the ports by name in the order the device has them, and where
    each one is on its face (``front``, ``rear`` or ``v:<view id>``), as a fraction of it."""
    d = demo_draw.draw(key)
    caras = [(n, c) for n, c in (('front', d['front']), ('rear', d['rear'])) if c is not None]
    caras += [('v:' + vid, cara) for vid, _n, cara in d['views']]
    cuentas: dict = {}
    lista: dict = {}
    sitio: dict = {}
    for nombre_cara, cara in caras:
        for fam, name, typ, x, y, extra in cara.ports:
            cuentas.setdefault(fam, {})
            cuentas[fam][typ] = cuentas[fam].get(typ, 0) + 1
            lista.setdefault(fam, []).append(dict({'name': name, 'type': typ}, **extra))
            sitio['%s|%s' % (fam, name)] = {'f': nombre_cara, 'x': round(x / cara.w, 4),
                                            'y': round(y / cara.h, 4)}
    return cuentas, lista, sitio


def inlet_of(key: str) -> str:
    """The type of the model's first power inlet, or ``''``."""
    for p in ports_of(key)[1].get('power-ports') or ():
        return str(p.get('type') or '')
    return ''


def views_of(key: str) -> list:
    """``[(view id, name key, file name)]``: the model's inside views and their pictures."""
    return [(vid, nombre, '%s.%s.svg' % (key, vid))
            for vid, nombre, _c in demo_draw.draw(key)['views']]


def files_of(key: str) -> list:
    """The names of every picture a model has: a module or a component has no rear."""
    caras = ['%s.front.svg' % key]
    if demo_draw.draw(key)['rear'] is not None:
        caras.append('%s.rear.svg' % key)
    return caras + [f for _v, _n, f in views_of(key)]


def _read(name: str) -> str:
    path = os.path.join(FACES_DIR, name)
    if not os.path.isfile(path):
        return ''
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()


def face(key: str, side: str) -> str:
    """The SVG of one face of a model (``front`` / ``rear``), or ``''`` if it has none."""
    return _read('%s.%s.svg' % (key, side))


def view(key: str, vid: str) -> str:
    """The SVG of one inside view of a model."""
    return _read('%s.%s.svg' % (key, vid))
