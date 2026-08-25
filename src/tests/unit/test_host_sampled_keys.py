#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A device the registry makes a device, and the screens that disagreed about it.

Most machines are watched because somebody configured a check against them. Some are watched
because the REGISTRY says what they are: an SNMP profile with device profiles assigned is
enough, and what the sampler records comes back filed under the host (``host.<uid>/…``) rather
than under any item.

Two screens already knew that and one did not, and the failure was the worst shape a
disagreement can take — not an error, but two answers about one machine, with the useful one
invisible. The fleet column counted those results, so a switch sampled that way turned red. The
device page built its rows from the configured checks alone, so opening that same switch said
"no check points at this device" over four empty tabs. Reported exactly that way: *"ha
terminado la importación y no salen datos, y lo marca como error"*.

So the keys are worked out in ONE place, from what was actually recorded rather than from a
list of which modules sample hosts — a list would be a third thing to keep in step.
"""

from lib.core.hosts.service import host_sampled_keys


class TestWhatAModuleRecordedAboutTheHostItself:

    def test_a_device_sampled_through_the_registry_is_found(self):
        raw = {'watchfuls.snmp': {'host.sw1/metrics': {'status': True}}}
        assert host_sampled_keys(raw, 'sw1') == {'snmp': {'host.sw1': ''}}

    def test_the_rows_of_one_device_are_one_entry(self):
        """A device profile files a row per interface, per volume, per disk. They all belong
        to one thing, and `build_host_status` maps `<base>/<row>` back to it — so the base is
        what has to be in the list, once."""
        raw = {'snmp': {'host.sw1/metrics': {}, 'host.sw1/eth0': {}, 'host.sw1/eth1': {}}}
        assert host_sampled_keys(raw, 'sw1') == {'snmp': {'host.sw1': ''}}

    def test_a_configured_check_is_not_one_of_these(self):
        """Those are found the way they always were, through the module configuration. A key
        that names an item is not a key that names a host."""
        raw = {'snmp': {'srv-uid.check-uid': {}, 'plain-item': {}}}
        assert host_sampled_keys(raw, 'sw1') == {}

    def test_another_machines_results_are_not_this_machines(self):
        raw = {'snmp': {'host.sw1/metrics': {}, 'host.nas/metrics': {}}}
        assert host_sampled_keys(raw, 'nas') == {'snmp': {'host.nas': ''}}

    def test_the_module_is_named_the_way_the_rest_of_the_panel_names_it(self):
        """The status table keys modules as `watchfuls.snmp` and every screen speaks `snmp`.
        Returning the long form would look right and match nothing."""
        raw = {'watchfuls.snmp': {'host.sw1/metrics': {}}}
        assert list(host_sampled_keys(raw, 'sw1')) == ['snmp']

    def test_several_modules_can_each_have_recorded_something(self):
        raw = {'snmp': {'host.sw1/metrics': {}}, 'ping': {'host.sw1': {}}}
        assert set(host_sampled_keys(raw, 'sw1')) == {'snmp', 'ping'}


class TestItSaysNothingRatherThanSomethingWrong:

    def test_nothing_recorded_is_an_empty_answer(self):
        assert host_sampled_keys({}, 'sw1') == {}
        assert host_sampled_keys({'snmp': {}}, 'sw1') == {}

    def test_no_machine_asked_about_is_no_answer(self):
        """Without this the empty string would match the host prefix with nothing after it,
        and every orphaned key in the table would be attributed to a machine that is not one."""
        raw = {'snmp': {'host.sw1/metrics': {}}}
        assert host_sampled_keys(raw, '') == {}
        assert host_sampled_keys(raw, '   ') == {}

    def test_a_status_table_of_the_wrong_shape_does_not_raise(self):
        """It is read from the database and from modules. A cycle is not worth losing over the
        shape of one entry."""
        assert host_sampled_keys(None, 'sw1') == {}
        assert host_sampled_keys({'snmp': 'not a dict'}, 'sw1') == {}
        assert host_sampled_keys({'snmp': {'host.sw1/metrics': 'not a dict'}}, 'sw1') == {
            'snmp': {'host.sw1': ''}}, 'the KEY is what places it; the value is not read here'
