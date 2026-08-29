#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host connection-profile catalog (lib/core/hosts/profiles.py)."""

from lib.core.hosts.profiles import (
    core_profiles,
    host_profiles_catalog,
    module_host_collections,
    module_host_fields,
    module_host_multiple,
    profile_sampled_modules,
)


class TestCatalog:

    def test_protocols_discovered(self):
        cat = host_profiles_catalog()
        # The annotated modules contribute their protocols.  'db' is NOT here:
        # datastore's DB endpoint is address-only (it stays an editable per-check
        # field, like web's 'url'), so it carries no configurable profile.
        for proto in ('snmp', 'ssh', 'icmp', 'tls', 'ntp'):
            assert proto in cat, proto

    def test_snmp_profile_carries_the_device_identity(self):
        """SNMP is a property of the DEVICE, like SSH: its address, its port, and who you
        have to be to ask it anything.  Carrying only the address made every check re-enter
        the same community, and made the panel's own screens ask for it again.

        The field METADATA comes from the module's own schema — options, show_when, the
        secret flag — so the host form renders v3 exactly as the module tab does, without
        core holding a second copy of what an SNMP credential looks like."""
        cat = host_profiles_catalog()
        snmp = cat['snmp']
        assert snmp['module'] == 'snmp'
        assert snmp['address_field'] == 'host'
        names = [f['name'] for f in snmp['fields']]
        assert names[0] == 'host'
        assert {'port', 'version', 'community', 'device_profiles'} <= set(names)
        assert {'snmpv3_username', 'snmpv3_auth_key', 'snmpv3_priv_key'} <= set(names)
        # How long we wait and how often we retry is not WHO the device is: it stays on
        # the check, or two entries for one box would migrate into two hosts.
        assert 'timeout' not in names and 'retries' not in names
        by_name = {f['name']: f for f in snmp['fields']}
        assert by_name['community'].get('secret') is True
        assert by_name['version'].get('options') == ['1', '2c', '3']
        assert by_name['snmpv3_auth_key'].get('show_when') == {'version': ['3']}
        assert by_name['device_profiles'].get('multi') is True

    def test_ssh_is_core_builtin(self):
        # SSH is a property of the server itself, so the core owns it: the
        # catalog always exposes ssh as a built-in profile (module '__host__'),
        # overriding any module-declared ssh.
        cat = host_profiles_catalog()
        assert cat['ssh']['module'] == '__host__'
        assert cat['ssh'].get('builtin') is True
        assert cat['ssh']['address_field'] == 'ssh_host'   # fed from host.address
        names = [f['name'] for f in cat['ssh']['fields']]
        assert 'ssh_key_string' in names                   # inline private key support
        for fn in ('ssh_password', 'ssh_key_string'):
            f = next(x for x in cat['ssh']['fields'] if x['name'] == fn)
            assert f.get('sensitive') or f.get('secret')
        # Auth-method selector (password / file / text), defaulting to password.
        meth = next(x for x in cat['ssh']['fields'] if x['name'] == 'ssh_auth_method')
        assert meth['default'] == 'password'
        assert set(meth['options']) == {'password', 'file', 'text'}
        # The credential fields are gated by the method.
        for fn, m in (('ssh_password', 'password'), ('ssh_key', 'file'), ('ssh_key_string', 'text')):
            f = next(x for x in cat['ssh']['fields'] if x['name'] == fn)
            assert f.get('show_when', {}).get('ssh_auth_method') == [m]

    def test_datastore_db_endpoint_is_not_a_profile(self):
        # datastore's DB endpoint ('host') is an editable per-check field (like
        # web's 'url'), not a host-owned profile — so it never auto-hides when a
        # server is bound (SSH-tunnelled DBs may target a different box).
        cat = host_profiles_catalog()
        assert 'db' not in cat

    def test_module_host_specs_preserves_datastore_ssh(self):
        # The migration relies on the module's own __host_profile__ (not the
        # catalog) so datastore's ssh tunnel fields are still recognised.
        from lib.core.hosts.profiles import module_host_specs
        specs = module_host_specs()
        protos = {p for p, _, _ in specs.get('datastore', [])}
        assert 'ssh' in protos   # the ssh tunnel is the host-owned profile

    def test_module_host_fields(self):
        m = module_host_fields()
        assert 'host' in m['ping']
        # Host-owned = the address only (per-protocol settings live on the
        # check now — there is no Credentials section anymore).
        assert m['ssl_cert'] == ['host']
        # SNMP host-owns its identity as well as its address (see the catalog test):
        # the device is who you authenticate to, not a setting of each check.
        assert {'host', 'community', 'version', 'device_profiles'} <= set(m['snmp'])
        # web hides nothing: 'url' stays visible so one host (a reverse proxy)
        # can carry several FQDNs — blank url falls back to the host address.
        assert 'web' not in m or 'url' not in m['web']
        # datastore host-owns ONLY the ssh tunnel; 'host' (the DB endpoint) stays
        # an editable per-check field so an SSH-tunnelled DB can target another
        # box (docker/internal), and the per-DB creds stay on the check too.
        assert 'ssh_host' in m['datastore']
        assert 'host' not in m.get('datastore', [])
        assert 'password' not in m['datastore'] and 'user' not in m['datastore']

    def test_module_host_multiple(self):
        # Multiple checks per host is opt-in via __host_multiple__ in the schema.
        m = module_host_multiple()
        assert m.get('datastore') is True   # mysql + postgres on one server
        assert m.get('web') is True         # several URLs on one host
        assert m.get('ssl_cert') is True    # several TLS services / ports
        assert m.get('ping') is False       # one ping per host
        assert m.get('ntp') is False and m.get('snmp') is False
        assert m.get('dns') is True         # host-aware: query via SSH from a host

    def test_module_host_multi_bind(self):
        # One check binding to several hosts is opt-in via __host_multiple_bind__.
        from lib.core.hosts.profiles import module_host_multi_bind
        m = module_host_multi_bind()
        assert m.get('proxmox') is True     # cluster: one check spans member nodes
        assert m.get('ping') is False       # single-host check
        assert m.get('datastore') is False  # several checks per host, but one host each

    def test_module_member_fields(self):
        # A multi-bind module may declare a per-node member field (__member_field__).
        from lib.core.hosts.profiles import module_member_fields
        m = module_member_fields()
        assert m.get('keepalived') == 'priority'   # keepalived's per-node weight
        assert 'proxmox' not in m                  # proxmox uses the node <select>
        assert 'ping' not in m

    def test_module_status_render(self):
        # Status-card decorations are opt-in via __status_render__ (discovered).
        from lib.core.hosts.profiles import module_status_render
        m = module_status_render()
        assert m.get('web') == [{'type': 'badge', 'field': 'code', 'prefix': 'HTTP '}]
        fs = m.get('filesystemusage')
        assert fs and fs[0]['type'] == 'bar' and fs[0]['value'] == 'used'
        assert 'ping' not in m                     # no decoration declared

    def test_module_host_collections(self):
        m = module_host_collections()
        # Every host-centric module exposes a host-capable item collection, so the
        # host picker appears on ALL module items (not just those with inline
        # connection fields).
        for mod in ('ups', 'cpu', 'dns', 'ram_swap', 'web', 'ping', 'ssl_cert',
                    'ntp', 'datastore', 'process', 'raid', 'service_status',
                    'temperature', 'hddtemp', 'filesystemusage'):
            assert m.get(mod) == ['list'], f'{mod}: {m.get(mod)}'
        # snmp binds at the 'servers' level; its nested 'checks' never binds.
        assert m.get('snmp') == ['servers']

    def test_missing_dir_is_empty(self, tmp_path):
        assert host_profiles_catalog(str(tmp_path / 'nope')) == {}
        assert module_host_fields(str(tmp_path / 'nope')) == {}
        assert module_host_collections(str(tmp_path / 'nope')) == {}



class TestWhatMakesAHostADevice:
    """A connection profile can say that carrying it IS the monitoring.

    A switch, a router or a UPS read over SNMP has no check and no module item: the device
    profiles assigned to it are what gets collected every cycle. Anything asking "what would
    run against this machine" has to be able to answer that BEFORE the first cycle, which is
    exactly when it is asked — and the only answer available until now was what had already
    been recorded, which for a device that has never been sampled is nothing.

    Reported from the screen: a NAS whose module item had just been removed offered to collect
    its ping and left out the collection, so the button that exists to take the first sample
    was the one thing that could not take it.
    """

    def test_a_host_with_device_profiles_is_sampled_by_the_module_that_declared_them(self):
        assert profile_sampled_modules(
            {'profiles': {'snmp': {'cred_uid': 'c', 'device_profiles': 'grp_synology'}}}
        ) == {'snmp'}

    def test_the_field_is_read_in_both_shapes_it_is_stored_in(self):
        """Edited as chips, stored as text — and both reach here."""
        assert profile_sampled_modules(
            {'profiles': {'snmp': {'device_profiles': ['a', 'b']}}}) == {'snmp'}
        assert profile_sampled_modules(
            {'profiles': {'snmp': {'device_profiles': 'a, b'}}}) == {'snmp'}

    def test_the_profile_alone_is_not_enough(self):
        """A community with nothing assigned to it is a device somebody can ASK things of,
        not one anybody is charting: `devices_to_sample` skips it, so this must too, or the
        collection would offer a module that then samples nothing."""
        for empty in ('', '   ', [], ['  '], None):
            assert profile_sampled_modules(
                {'profiles': {'snmp': {'community': 'public', 'device_profiles': empty}}}
            ) == set(), empty

    def test_a_profile_that_declares_no_such_field_never_counts(self):
        """SSH is a way IN, not a collection. Reading "has a profile" as "is sampled" would
        put every machine with credentials on it into every collection."""
        assert profile_sampled_modules(
            {'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': 'x'}}}) == set()

    def test_a_record_with_nothing_to_go_on(self):
        for host in ({}, None, {'profiles': None}, {'profiles': 'nope'}, {'profiles': {}}):
            assert profile_sampled_modules(host) == set(), host

    def test_the_declared_field_is_the_one_the_module_actually_parses(self):
        """The declaration and the sampler must name the SAME field. They are two files —
        the core reads `samples_when` to decide what to offer, and SNMP reads the field
        itself to decide what to walk — so a rename on one side would produce a button that
        offers a collection nobody runs, with nothing raising anywhere.
        """
        from lib.core.snmp.manifest import HOST_PROFILE          # noqa: PLC0415
        from lib.core.snmp.profiles import assigned              # noqa: PLC0415
        field = HOST_PROFILE['samples_when']
        assert field in {f['name'] for f in HOST_PROFILE['fields']}, (
            'it declares a field the profile does not have')
        assert assigned({field: 'grp_x'}) == ['grp_x'], (
            'the sampler does not read the field the declaration names')
        assert not assigned({field: ''})

    def test_it_is_carried_by_the_catalogue_and_not_invented_here(self):
        core = core_profiles()
        assert core['snmp']['samples_when'] == 'device_profiles'
        assert not core['ssh']['samples_when']


class TestAMachineInMaintenanceStillHasAPast:
    """Reported from the screen: a switch put into maintenance opened onto four empty tabs.

    A host in maintenance has its checks skipped, so the cycle after that prunes every key the
    module stopped returning — and for a device sampled through the REGISTRY (an SNMP profile
    on the host record, no check item behind it) that is all of them. The page worked out what
    a device is made of from the live state alone, so there was nothing left to build a row
    out of.

    The history is kept for exactly this — `purge_maintenance_states` says so in as many
    words — it was simply unreachable from that page.
    """

    UID = 'abc123'

    def _keys(self, series):
        from lib.core.hosts import service as svc                # noqa: PLC0415
        return svc.host_recorded_keys(series, self.UID)

    def _series(self, module, key):
        return {'module': module, 'key': key, 'last_ts': 1, 'last_status': True,
                'last_data': {}}

    def test_what_the_history_remembers_about_the_device_itself(self):
        got = self._keys([self._series('snmp', f'host.{self.UID}/eth0'),
                          self._series('snmp', f'host.{self.UID}/metrics')])
        assert got == {'snmp': {f'host.{self.UID}': ''}}

    def test_the_base_key_and_not_the_row(self):
        """`build_host_status` maps `<base>/<row>` back to it, which is what makes one entry
        stand for a device's whole table."""
        got = self._keys([self._series('snmp', f'host.{self.UID}/Drive 1'),
                          self._series('snmp', f'host.{self.UID}/Drive 2')])
        assert list(got['snmp']) == [f'host.{self.UID}']

    def test_another_machine_is_another_machine(self):
        assert self._keys([self._series('snmp', 'host.other/eth0')]) == {}

    def test_and_a_series_that_names_a_CHECK_is_not_one(self):
        """A configured check is found the other way round, through the module config. A key
        that is not `host.<uid>` names an item, and claiming it here would put somebody else's
        check on this device's page."""
        assert self._keys([self._series('ping', 'my-check'),
                           self._series('ping', 'my-check/latency')]) == {}

    def test_nothing_at_all_is_not_a_crash(self):
        for bad in (None, [], [None], ['nonsense'], [{}], [{'key': None}]):
            assert self._keys(bad) == {}, bad

    def test_it_answers_the_same_shape_as_the_live_one(self):
        """The two are read into the same `bound` map, one after the other. A different shape
        would be a page that half works, on precisely the machines nobody is watching."""
        from lib.core.hosts import service as svc                # noqa: PLC0415
        live = svc.host_sampled_keys(
            {'snmp': {f'host.{self.UID}/eth0': {'status': True}}}, self.UID)
        assert self._keys([self._series('snmp', f'host.{self.UID}/eth0')]) == live

    def test_and_the_two_screens_that_lost_the_device_ask_for_it(self):
        """Los dos, estén donde estén.

        Contado en el PAQUETE y no dentro de `routes.py`: el armado del mapa se mudó a
        `service.py` cuando una segunda sección necesitó la misma topología, y una guarda que
        cuenta apariciones en un fichero deja de guardar en cuanto el código que vigila se
        mueve — en silencio, pasando. Lo que importa es que haya dos llamantes, no en qué
        fichero están.
        """
        import io as _io, os as _os                              # noqa: PLC0415
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        infra = _os.path.join(root, 'lib', 'core', 'infra')
        total = 0
        for _name in sorted(_os.listdir(infra)):
            if not _name.endswith('.py'):
                continue
            with _io.open(_os.path.join(infra, _name), encoding='utf-8') as fh:
                total += fh.read().count('host_recorded_keys(')
        assert total == 2, (
            'the device page and the map both lose a machine in maintenance without it')


class TestAutoMeansAsk:
    """`auto` on a host's OS is a question, and the machine had already answered it.

    A device answering SNMP has said what it runs — `sysDescr` on every agent, and a
    `lsb_release` extend where somebody set one up — and the panel was throwing that away and
    guessing. The guess is worse than it sounds: `auto` on a host whose kind is neither local
    nor remote resolved to the PANEL's platform, so a Synology came out as whatever the server
    happens to run.
    """

    def _st(self, **facts):
        return {'snmp': {'host.abc/metrics': {'other_data': {'_attrs': facts}}}}

    def _said(self, status):
        from lib.core.hosts.resolve import reported_os                # noqa: PLC0415
        return reported_os(status, 'abc')

    def test_what_the_device_says_is_read(self):
        assert self._said(self._st(sys_generic={'description': 'Linux nas-01 5.10 x86_64'})) \
            == 'linux'

    def test_a_module_that_KNOWS_beats_one_that_describes(self):
        """`sysDescr` is a sentence with the platform somewhere in it; an `extend` running
        `lsb_release` is an answer. Both are declared roles, so this reads a ROLE and never a
        module — nothing in the core knows what SNMP is."""
        got = self._said(self._st(ucd_extend={'os': 'Debian GNU/Linux 12'},
                                  sys_generic={'description': 'Linux nas 5.10'}))
        assert got == 'linux'

    def test_and_a_sentence_is_read_as_a_sentence(self):
        """"Debian GNU/Linux 12" has the word that matters in the middle. Read as a prefix it
        was OTHER, which reads as "a platform this panel has no word for" and is not what the
        machine said."""
        from lib.util.os_detect import canonical_os                   # noqa: PLC0415
        assert canonical_os('Debian GNU/Linux 12') == 'linux'
        assert canonical_os('Hardware: Intel64 … Windows Version 10.0') == 'windows'
        # …and a one-word answer still never depends on what else its name contains.
        assert canonical_os('win32') == 'windows' and canonical_os('linux') == 'linux'

    def test_a_switch_describes_itself_and_it_is_still_not_an_OS(self):
        """It answers perfectly well, and none of the words this panel has fits. Writing one
        down would be deciding something nobody decided."""
        for said in ('RouterOS CCR2004-16G-2S+ 7.23.3 (stable)',
                     'LGS528 28-Port Gigabit Managed Switch'):
            assert self._said(self._st(sys_generic={'description': said})) == ''

    def test_nothing_said_is_nothing_answered(self):
        assert self._said({}) == ''
        assert self._said(self._st(sys_generic={'name': 'nas-01'})) == ''
        assert self._said(self._st()) == ''

    def test_a_setting_somebody_chose_is_never_overruled(self):
        from lib.core.hosts.resolve import resolve_os                 # noqa: PLC0415
        assert resolve_os('windows', False, reported='Linux nas 5.10') == 'windows'

    def test_and_it_is_asked_BEFORE_the_old_guess(self):
        """The old ladder is what produced the wrong answer: on a host that is neither local
        nor remote it returns this process's platform."""
        from lib.core.hosts.resolve import resolve_os                 # noqa: PLC0415
        assert resolve_os('auto', False, reported='Linux nas 5.10') == 'linux'
        assert resolve_os('auto', True, remote_auto='auto',
                          reported='Linux nas 5.10') == 'linux'
        # …and with nothing said, unchanged.
        assert resolve_os('auto', True, remote_auto='auto') == 'auto'

    def test_the_whole_fleet_is_scanned_and_only_the_askers_are_answered(self):
        """The scan is not the rule. Every machine is read — the OS is one of three facts that
        come out of one pass, and skipping the ones with a chosen OS would mean a switch
        somebody pinned also lost its manufacturer. What a setting protects is the ANSWER: it
        lands only where nobody has chosen."""
        from lib.core.infra import service as infra                   # noqa: PLC0415
        st = self._st(sys_generic={'description': 'Linux nas 5.10'})
        hosts = [{'uid': 'abc', 'os': 'auto'}, {'uid': 'zzz', 'os': 'windows'}]
        said = infra.fleet_identity(st, hosts)
        assert said['abc']['os'] == 'linux'
        assert infra.fleet_identity(st, [{'uid': 'nobody'}]) == {}

    def test_and_it_reaches_the_screen_beside_the_setting(self):
        """The setting stays the setting — it reads `auto`, because that is what it is — with
        the answer it stands for beside it."""
        from lib.core.hosts import service as svc                     # noqa: PLC0415
        hosts = [{'uid': 'abc', 'os': 'auto'}, {'uid': 'z', 'os': 'windows'}]
        svc.enrich_hosts(hosts, {}, {}, {'abc': {'os': 'linux'}, 'z': {'os': 'linux'}})
        assert hosts[0]['os_auto'] == 'linux'
        assert hosts[1]['os_auto'] == '', 'it overwrote a chosen setting'
        from lib.core.infra import service as infra                   # noqa: PLC0415
        assert 'os_auto' in infra._HOST_FIELDS, 'it never leaves the server'


class TestWhoMadeIt:
    """Marca y modelo — the same trick as the OS, on the two facts beside it.

    A device says who made it: the vendor MIB it answers IS the answer, and a profile that
    matches on that tree is the only thing in the product that knows the tree belongs to
    MikroTik. So the profile declares the brand beside the match and the core carries it —
    nothing in `lib/core` has ever heard of a manufacturer, which is the same rule that keeps
    module names out of it.
    """

    def _sources(self):
        from lib.core.infra import service as infra                   # noqa: PLC0415
        from lib.core.snmp import profiles as P                       # noqa: PLC0415
        cat = P.catalog()
        return infra.sources_of({}, {'snmp': {pid: P.history_source(pr, 'es_ES')
                                              for pid, pr in cat.items()}})

    def _said(self, **by_source):
        return {'snmp': {'host.abc/metrics': {'other_data': {'_attrs': by_source}}}}

    def _one(self, status, sources=None):
        from lib.core.infra import service as infra                   # noqa: PLC0415
        return infra.fleet_identity(status, [{'uid': 'abc'}],
                                    self._sources() if sources is None else sources)['abc']

    def test_a_profile_declares_who_it_speaks_for(self):
        from lib.core.snmp import profiles as P                       # noqa: PLC0415
        cat = P.catalog()
        assert P.brand_of(cat['mikrotik_routeros'])['name'] == 'MikroTik'
        # …and it survives normalisation, which is where `optional` first died: written in
        # five files and read by nobody.
        assert cat['mikrotik_routeros']['brand']['logo'] == 'mikrotik'
        assert P.brand_of(cat['sys_generic']) == {}, 'a standard MIB has no maker'

    def test_a_brand_may_not_be_a_path_or_a_style(self):
        """The logo reaches a URL and the colour a `style`. Both are read out of a FILE."""
        from lib.core.snmp import profiles as P                       # noqa: PLC0415
        for bad in ('../../config', 'a/b', 'HTTP://x', 'x.svg'):
            assert 'logo' not in P.brand_of({'brand': {'name': 'X', 'logo': bad}})
        for bad in ('red; background:url(x)', '#12', 'javascript:1'):
            assert 'color' not in P.brand_of({'brand': {'name': 'X', 'color': bad}})
        assert P.brand_of({'brand': {'logo': 'x'}}) == {}, 'a mark with no name is not a brand'

    def test_the_device_that_was_recognised_says_which_model(self):
        got = self._one(self._said(mikrotik_routeros={'model': 'CCR2004-1G-12S'},
                                   sys_generic={'description': 'RouterOS'}))
        assert (got['brand']['name'], got['model']) == ('MikroTik', 'CCR2004-1G-12S')

    def test_and_what_is_PLUGGED_IN_does_not_answer_for_the_box(self):
        """One registry entry fronts several pieces of equipment: a NAS and the UPS plugged
        into it both answer "model", and only the UPS answers "vendor". Taking each fact from
        wherever it appeared made a DS1821+ manufactured by APC."""
        got = self._one(self._said(synology_system={'model': 'DS1821+'},
                                   synology_ups={'model': 'Smart-UPS 1500', 'vendor': 'APC'}))
        assert got['brand']['name'] == 'Synology'
        assert got['model'] == 'DS1821+'
        assert got['vendor'] == 'Synology', 'the UPS answered for the NAS'

    def test_nor_does_a_DISK(self):
        """A Synology files a model per drive. A scan that took them would answer "this
        machine is a WD40EFRX" — so a result about a ROW is not a fact about the box."""
        st = self._said(synology_system={'model': 'DS1821+'})
        st['snmp']['host.abc/Drive 1'] = {'other_data': {
            '_row': 'Drive 1', '_attrs': {'synology_disks': {'model': 'WD40EFRX'}}}}
        assert self._one(st)['model'] == 'DS1821+'

    def test_a_machine_nobody_recognises_keeps_its_own_word(self):
        """No vendor MIB and a maker no table lists. A name with no mark is still an answer,
        and inventing "unknown" for it would throw away the one thing it said."""
        got = self._one(self._said(ucd_extend={'vendor': 'Placas Pepe SL',
                                               'model': 'Caja 3'}))
        assert got['brand'] == {'name': 'Placas Pepe SL'}
        assert got['model'] == 'Caja 3'

    def test_and_one_it_DOES_recognise_gets_the_mark(self):
        got = self._one(self._said(ucd_extend={'vendor': 'Dell Inc.',
                                               'model': 'PowerEdge R640'}))
        assert got['brand']['name'] == 'Dell' and got['brand']['logo'] == 'dell'
        assert got['model'] == 'PowerEdge R640'

    def test_and_one_that_says_nothing_says_nothing(self):
        """Absent rather than present-and-empty: a machine that has answered its name and
        nothing else has said nothing about what it IS, and an entry full of blanks is a row
        every screen then has to test before drawing."""
        from lib.core.infra import service as infra                   # noqa: PLC0415
        assert infra.fleet_identity(self._said(sys_generic={'name': 'sw-01'}),
                                    [{'uid': 'abc'}], self._sources()) == {}

    def test_it_reaches_the_screen(self):
        from lib.core.hosts import service as svc                     # noqa: PLC0415
        from lib.core.infra import service as infra                   # noqa: PLC0415
        hosts = [{'uid': 'abc'}]
        svc.enrich_hosts(hosts, {}, {}, {'abc': {'vendor': 'MikroTik', 'model': 'CCR2004',
                                                 'brand': {'name': 'MikroTik'}}})
        assert hosts[0]['model'] == 'CCR2004'
        row = infra.fleet_row(hosts[0])
        assert row['brand'] == {'name': 'MikroTik'} and row['vendor'] == 'MikroTik'
        # A dict either way: a screen that has to test for null before asking for a name is a
        # screen with two shapes to draw.
        assert infra.fleet_row({'uid': 'x'})['brand'] == {}

    def test_a_profile_that_speaks_for_nobody_says_what_it_can_RECOGNISE(self):
        """The other half, and the one that makes a plain server work. `ucd_extend` reads DMI,
        which answers "HP", "Dell Inc.", "QEMU" — and the profile that reads DMI is the thing
        that knows what DMI answers, so the table is THERE. The same table in the core would be
        a list of manufacturers."""
        from lib.core.infra import service as infra                   # noqa: PLC0415
        src = self._sources()
        assert src['ucd_extend']['brands'], 'the table did not survive the trip'
        assert infra.brand_said('Hewlett-Packard', src)['logo'] == 'hp'
        assert infra.brand_said('HP', src)['logo'] == 'hp', 'one rack, two spellings'
        assert infra.brand_said('Dell Inc.', src)['name'] == 'Dell'
        assert infra.brand_said('Nobody Ltd', src) == {}
        assert infra.brand_said('', src) == {}

    def test_and_a_machine_nobody_MADE_still_says_what_it_is(self):
        """Half a fleet is virtual, and "QEMU" under a maker's heading is the truth about a
        virtual machine — it was made by nobody."""
        got = self._one(self._said(ucd_extend={'vendor': 'QEMU', 'model': 'Standard PC'}))
        assert got['brand']['name'] == 'QEMU' and got['brand'].get('logo')

    def test_each_card_says_who_IT_is_about(self):
        """A device page draws one card per thing that answered, and the card of an HP is a
        card about an HP — heading it "Equipo" is the one word on it that carries no
        information. Declared where the profile IS a maker's, read off the device where it is
        not, and the screen is told which so it knows whether to head the card with the maker
        or with the profile's own better word ("RouterOS")."""
        from lib.core.infra import service as infra                   # noqa: PLC0415
        rows = [{'module': 'snmp', 'row': '', 'name': 'x', 'data': {'_attrs': {
            'ucd_extend': {'vendor': 'HP', 'model': 'HP EliteDesk 800 G5'},
            'mikrotik_routeros': {'model': 'CRS310'},
            'sys_generic': {'description': 'Linux pve01'}}}}]
        attrs = infra.attributes(rows, self._sources())
        by_source = {a['source']: a for a in attrs}
        assert by_source['ucd_extend']['source_brand']['logo'] == 'hp'
        assert by_source['ucd_extend']['source_brand_said'] is True, 'it was read, not declared'
        assert by_source['mikrotik_routeros']['source_brand']['name'] == 'MikroTik'
        assert by_source['mikrotik_routeros']['source_brand_said'] is False
        assert by_source['sys_generic']['source_brand'] == {}

    def test_and_the_card_about_the_BOX_comes_first(self):
        """It used to be the standard MIB leading, which put the card naming a machine's
        contact address above the one naming the machine. Reported from the screen."""
        from lib.core.infra import service as infra                   # noqa: PLC0415
        rows = [{'module': 'snmp', 'row': '', 'name': 'x', 'data': {'_attrs': {
            'sys_generic': {'description': 'RouterOS CRS310'},
            'mikrotik_routeros': {'model': 'CRS310'}}}}]
        order = []
        for a in infra.attributes(rows, self._sources()):
            if a['source'] not in order:
                order.append(a['source'])
        assert order == ['mikrotik_routeros', 'sys_generic'], order

    def test_a_chassis_table_is_about_the_CHASSIS(self):
        """Reported from the screen: the Linksys had no maker and no model anywhere.

        Its model, serial, firmware and hardware revision are columns of the unit table, so
        every one of them was filed against a ROW — and a fact about a row is not a fact about
        the machine, which is the rule that keeps a NAS from being called a WD40EFRX. So a
        switch that answers all four showed none of them. `of_device` is exactly this case and
        the profile had never said so: the rows fold into one fact about the box.
        """
        from lib.core.snmp import profiles as P                       # noqa: PLC0415
        lks = P.catalog()['linksys_switch']
        folded = {m['key'] for m in lks['metrics'] if m.get('of_device')}
        assert folded == {'lks_model', 'lks_serial', 'lks_firmware', 'lks_hardware'}, folded
        got = self._one(self._said(linksys_switch={'model': 'LGS528', 'serial': 'X1'}))
        assert got['brand']['name'] == 'Linksys' and got['model'] == 'LGS528'

    def test_the_UPS_plugged_into_a_NAS_says_who_made_IT(self):
        """The NAS reads it over USB and reports the manufacturer verbatim: "American Power
        Conversion", which is APC written out in full and matches nothing. The profile that
        READS a string is the thing that knows what that string says."""
        from lib.core.infra import service as infra                   # noqa: PLC0415
        src = self._sources()
        assert infra.brand_said('American Power Conversion', src)['name'] == 'APC'
        assert infra.brand_said('EATON 5PX', src)['name'] == 'Eaton'
        # …and the card is the UPS's, not the NAS's: the maker of what is PLUGGED IN never
        # answers for the box (see the test above), so the two cards say different things.
        rows = [{'module': 'snmp', 'row': '', 'name': 'nas', 'data': {'_attrs': {
            'synology_system': {'model': 'DS1821+'},
            'synology_ups': {'vendor': 'American Power Conversion'}}}}]
        by = {a['source']: a for a in infra.attributes(rows, src)}
        assert by['synology_ups']['source_brand']['name'] == 'APC'
        assert by['synology_ups']['source_brand_said'] is True
        assert by['synology_system']['source_brand']['name'] == 'Synology'

    def test_a_fact_only_the_profile_can_name_arrives_named(self):
        """Reported from the screen as three lines reading `attr_mt_active_fan`.

        A fact filed under a ROLE is named by the core, in every language and with the same
        word whoever answered it. One filed under the profile's own metric key has no such
        word — so the recorder falls back to the key, and the key is an internal name. The
        profile had "Ventilador activo" written two lines from the OID and nothing carried it.

        Only the ones with no role, and that is the whole rule: a profile does not get to
        rename "Model" for its own devices.
        """
        from lib.core.infra import service as infra                   # noqa: PLC0415
        src = self._sources()
        assert src['mikrotik_routeros']['attrs']['mt_active_fan']
        assert 'model' not in src['mikrotik_routeros']['attrs'], 'it renamed a role'
        rows = [{'module': 'snmp', 'row': '', 'name': 'sw', 'data': {'_attrs': {
            'mikrotik_routeros': {'mt_active_fan': 'n/a', 'model': 'CRS310'}}}}]
        by = {a['key']: a['label'] for a in infra.attributes(rows, src)}
        assert by['mt_active_fan'], 'the profile\'s own word did not travel'
        assert by['model'] == '', 'the core names a role, in every language'

    def test_and_a_profile_does_not_get_to_rename_what_the_core_names(self):
        """Both are translated — the profile's label is read in the reader's language too — so
        the reason is not i18n. It is that "Modelo" must be the same word on the disk of a NAS
        and on the chassis of a switch, and a per-profile wording is how it stops being."""
        from lib.core.snmp import profiles as P                       # noqa: PLC0415
        said = P.history_source({'id': 'x', 'metrics': [
            {'key': 'model', 'oid': '1.2.3.0', 'kind': 'text', 'role': 'model',
             'label': 'Modelito'},
            {'key': 'x_quirk', 'oid': '1.2.4.0', 'kind': 'text', 'label': 'Rareza'}]}, 'es_ES')
        assert said['attrs'] == {'x_quirk': 'Rareza'}

    def test_a_measurement_nobody_grouped_belongs_to_its_module(self):
        """Reported from the screen: a button on the measurements rail with a count and no
        word on it.

        Grouping by SOURCE is a device-profile idea. A ping, a certificate and a disk check
        declare none, so all nine of them landed in one family with an empty heading — which
        is the one entry on an index that cannot be looked anything up in.

        The module is the answer, and it is the same rule the sourced ones follow: grouped by
        whatever produced them. Its own name, out of its own lang file, so the core still ships
        no string naming a module.
        """
        from lib.core.infra import service as infra                   # noqa: PLC0415
        rows = [{'module': 'ping', 'key': 'k', 'name': 'n', 'row': '',
                 'data': {'latency': 0.02}},
                {'module': 'snmp', 'key': 'host.x', 'name': 'n', 'row': 'eth0',
                 'data': {'if_in': 10}}]
        fields = {'ping': {'latency': {'label': 'Latencia', 'unit': 'ms'}},
                  'snmp': {'if_in': {'label': 'Entrada', 'source': 'if_generic',
                                     'source_label': 'Interfaces de red'}}}
        by = {m['module']: m for m in infra.metrics(rows, fields, {'ping': 'Ping ICMP'})}
        assert (by['ping']['source'], by['ping']['source_label']) == ('ping', 'Ping ICMP')
        # …and a module that groups its own is untouched: the profile still names it.
        assert by['snmp']['source_label'] == 'Interfaces de red'
        # …and with no name to hand, the module's key beats a blank.
        plain = infra.metrics(rows, fields)[0]
        assert plain['source_label'] == 'ping'

    def test_the_core_holds_no_list_of_manufacturers(self):
        """The whole point. If a name is ever spelled in the core's CODE, the next
        manufacturer is a code change instead of a file.

        Code and not prose: the comments explain the rule by naming the equipment it was
        written for ("a NAS and the UPS plugged into it"), and a guard that reads those trips
        over the sentence describing itself. Parsed rather than grepped, so a docstring is
        told from a string literal by what it IS and not by a regular expression.
        """
        import ast, os                                                # noqa: PLC0415,E401
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        makers = ('mikrotik', 'linksys', 'synology', 'routeros')
        guilty = []
        for base, _dirs, files in os.walk(os.path.join(root, 'lib', 'core')):
            for name in files:
                if not name.endswith('.py') or '__pycache__' in base:
                    continue
                path = os.path.join(base, name)
                with open(path, encoding='utf-8') as fh:
                    tree = ast.parse(fh.read())
                docs = set()
                for node in ast.walk(tree):
                    body = getattr(node, 'body', None)
                    if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                            and isinstance(body[0].value, ast.Constant) \
                            and isinstance(body[0].value.value, str):
                        docs.add(id(body[0].value))
                words = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                            and id(node) not in docs:
                        words.append(node.value)
                    elif isinstance(node, ast.Name):
                        words.append(node.id)
                    elif isinstance(node, ast.Attribute):
                        words.append(node.attr)
                text = ' '.join(words).lower()
                guilty += [(path, m) for m in makers if m in text]
        assert not guilty, guilty
