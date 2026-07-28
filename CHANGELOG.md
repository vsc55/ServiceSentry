# Changelog

All notable changes to **ServiceSentry** are documented in this file.

> **Versioning.** Every commit publishes a build — `0.0.1+build.N` — and its section holds
> **only what that commit changed**. `src/lib/__init__.py::__version__` declares the same
> build, and `tests/test_version_changelog.py` fails when the two drift. The semantic version
> deliberately stays at `0.0.1`: the counter is build metadata, so it does not spend numbers
> we will want for real releases. This changes once releases begin.

## [0.0.1+build.26] - 2026-07-28

### Added
- **The credential catalogue can be read four ways.** The table answers "what have I got" and
  nothing else; two questions sit on top of the same data and it cannot answer either.
  **Cards** give a credential the shape the rest of the panel gives an entity, with the two
  facts you actually chase one by — its type and the identity inside it — at a glance.
  **Grouped by type** separates animals the table interleaves: an SSH identity reaches a
  machine, a tenant app registration is an application with consented permissions and no host
  behind it, and sorting by the Type column only mixes them into one list.
- **"Who uses them" is the view that was missing.** A credential's consumers are not part of
  the credential — they live in the hosts store and inside every module's config — so until
  now the only way to see them was to open one credential and click its Usage tab, which
  answers "can I delete THIS one" and never "what is this catalogue full of". Seen whole it
  answers the question that rots a credential store: a secret nobody references is a secret
  nobody rotates, and it stays valid. Those rows are marked and the banner counts them.
- The orphan count is computed over the **whole catalogue**, not the page on screen — a count
  that shrank as you paged through would be worse than no count at all. The rows keep the sort
  the table header decides: floating the unused ones to the top reads well and would silently
  override the order the user chose.
- New endpoint `GET /api/v1/credentials/usage` — every credential's references in one pass.
  The scan walks every host profile and every module check whichever way it is asked, so
  asking per credential repeats one walk N times to answer N slices of the same result. The
  per-credential route now delegates to it, so the two cannot drift apart. Same permission
  gate, which is also exactly what opens the Credentials section.

### Changed
- The action buttons came out of the table spec into one helper every view composes: the
  `credentials_*` permissions are asked in exactly one place, and a guard fails if a view
  wires `deleteCred` itself — a view assembling its own buttons is a view free to offer Delete
  to somebody who may not press it.
- Switching to a grouped view clears the selection. Those views draw no checkboxes, so
  carrying one into them would leave the bulk bar armed over rows that are no longer on
  screen.
- **A table's view mode is now restored by the table itself.** The persistence layer had a
  hardcoded `tc.sessions.view` line, so every table that grew a preference beside its columns
  had to come and edit that function; a spec now declares both directions (`persistExtra` /
  `applyExtra`) and the loop calls them. Sessions moved onto it with no change in behaviour.
- `_entityCard` accepts an accent by NAME (`accentClass`), so a section's colour stays written
  down once in the CSS instead of being re-typed as a gradient in JavaScript.

### Fixed
- The usage fetch does not retry itself after a failure. It runs from the render and redraws
  when it lands, so an error would have been a request → redraw → request loop against a
  server already saying no; the failed state carries its own Retry instead.

## [0.0.1+build.25] - 2026-07-28

### Added
- **Services can be read four ways.** It is a control surface, so its layouts differ in what
  they put in the subject position: **cards** (what it had — one per service, everything in
  view), **service table** (one row each: state, instances, last heartbeat, actions — the
  fastest answer to "what is running", and the one that survives a deployment growing to a
  dozen services), **fleet** (one row per INSTANCE across every service) and **compact** (one
  line each, for when you are not reading but acting and want the button, not the biography).
- **The fleet view is the point.** An instance was only ever visible inside the card of its
  own service, so the fleet could be read one service at a time and never as a whole — which
  hides the two failures a multi-container install has and a single-container one does not: a
  follower that stopped reporting while the leader carries on, so the service still says
  RUNNING and the redundancy is quietly gone; and a container left behind on an older version,
  which no per-service card can show because drift is only visible when the versions sit side
  by side. It flags that drift explicitly, computed across the whole fleet rather than per row.
- It deliberately offers no start/stop: those act on a SERVICE and this view is not showing
  services, so a button per row would invite pressing it against the row you happen to be
  looking at.
- **It sorts by state, then by identity — never by the heartbeat.** The first version sorted by
  newest heartbeat, which reads well and is unusable: the timestamp is the most volatile field
  in the row, so instances ticking at similar intervals overtook each other on every poll and
  the table moved under the cursor. A list that reorders itself on a timer cannot be read and
  cannot be clicked. State changes only when something happened, so a row jumping to the top is
  the news rather than noise; below that the order is service and host, which do not move at
  all. Guarded: the comparator may not touch a heartbeat field.
- Switching view redraws what is on screen rather than re-fetching. Every view reads the same
  payload, and a request to answer a question about presentation would also race the poll
  timer that was about to fetch anyway.

### Changed
- The action buttons came out of the card footer into one helper every view composes. That is
  not tidiness: `services_control` is now asked in exactly one place, and a guard fails if a
  view wires its own control call — a view assembling its own buttons is a view free to offer
  Stop to somebody who may not press it.
- The header — totals, switcher, Refresh — is drawn by the dispatcher rather than by each
  view, so it cannot drift apart between layouts and a view is only ever responsible for its
  rows. The totals count instances as well as services: on a multi-container install those are
  different facts and the second is the one that moves.

## [0.0.1+build.24] - 2026-07-28

### Added
- **The Microsoft 365 and Azure table widgets can be added to the Overview more than once**,
  each configured on its own. One card cannot answer "how is Microsoft 365" — that question is
  really several, and wanting storage next to MFA coverage next to licence capacity is the
  normal case rather than an exotic one. The mechanism was already built and never switched on:
  instance ids carry a `:N` suffix, the scope and level are stored per instance, and the add bar
  keeps offering a widget whose declaration says `multi`. What was missing was the declaration.
- **A usage ring, opt-in per instance.** Any module widget can now draw one where the module
  publishes a fraction worth drawing, toggled per instance so two cards of the same kind can sit
  side by side with and without it. Declared for site and tenant storage, OneDrive, Secure Score,
  licence capacity, MFA coverage and unused licences.
- The same bargain as the module pages: the MODULE decides which two measurements are a fraction
  and hands them over already divided; the core divides nothing and knows no metric name — there
  is a guard that fails if one appears. The ring takes its colour from the entry's own state
  rather than from a threshold of its own, because a card the module called a warning must not
  carry a green ring.
- Two places it deliberately does NOT appear. At the aggregate scope, because storage, a score,
  licences and MFA coverage cannot be added together and a ring there would be a number with no
  question behind it. And where a total is missing, because a ring computed without one is a
  confident-looking 0% — a card is the worst place to put one.
- On a card the ring replaces the icon rather than joining it: they occupy the same slot, and
  showing both says less about each in the same width.

### Fixed
- **A published default layout lost every widget's configuration.** `normalize_layout()` kept
  only geometry, so an admin arranging the Overview and publishing it as the org default handed
  everyone the right boxes showing the wrong things — the scope and level filters were dropped on
  the way. It carries them now, along with the new ring toggle. The bug predates this work; it
  only became visible once a widget could exist twice with different settings.

## [0.0.1+build.23] - 2026-07-28

### Fixed
- **A full audit of every line anchor in the documentation: 15 of 74 pointed at the wrong
  code.** Three were out of range after `app.py` lost 700 lines — the only kind the guard can
  see, and what started the audit. The other twelve were inside their files and therefore
  invisible to it: `ThreadPoolExecutor` per module, the mtime cache-buster, `MAX_CONTENT_LENGTH`,
  `_csrf_protect`, `reconcile_table`, `_apply_incremental`, `_apply_rebuild`, `_type_map`, the
  history downsampling query, the `global|log_level` field, and the two permission decorators,
  each landing on unrelated lines. The prettiest one: the SNMP MIB-source warnings are still on
  **line 110**, but of `mib_admin.py` rather than `__init__.py` — right number, wrong file,
  guard content.
- **Stale file names in prose.** `NOTIFY_EVENTS` has not lived in a `notify_events.py` for some
  time — each package declares it in its `manifest.py` — and four documents still named the old
  file, in nine places. `explica-seguridad.md` named `test_wa_saml.py`, which is
  `test_providers_saml.py`. Both predate this work.
- **File listings that had fallen behind.** The architecture tree was missing six `entraid`
  modules (`device_flow`, `cred_link`, `sections`, `teams`, `tab_sso`, `sso_routes`) and still
  said the config domain had no mixin, which stopped being true one build ago.
  What the guard checks is that the line exists, is not blank, and matches the number written in
  the link text — all of which passed for months while the anchors pointed at unrelated code. A
  line anchor rots silently whenever content moves inside a file that stays long enough; only a
  file getting *shorter* makes it detectable, which is why the rest had to be read by hand.
- **A test that could only ever fail on somebody else's machine.** The favicon guard rebuilt
  the icon and compared it byte-for-byte with the committed `.ico`, and `zlib.compress` is not
  a stable function across implementations: this machine ships zlib-ng, the CI runner ships
  stock zlib, and the two emit different — equally valid, here even equally long — DEFLATE for
  identical scanlines. Only the 48px image diverged, being the only one with enough entropy for
  the two to choose differently.
- The consequence is what makes it worth recording: the icon was generated here, so locally the
  comparison was true **by construction** — green every time, no matter what. It was not missed
  among four thousand tests; it was impossible to fail on this machine and certain to fail on
  any other, and it had been red in CI since the commit that added the icon.
- It compares **images** now: the ICO directory is walked, each PNG's IHDR read and its IDAT
  decompressed, and the geometry and pixels compared. What the generator decides is the shape
  and the colour; which DEFLATE encoding those end up in is the compressor's business. Verified
  both ways — forcing a different compression level makes bytes differ and the test pass (the
  CI failure, reproduced locally), while changing the shield colour makes it fail naming the
  pixels. A second test states the sizes separately, because a pixel mismatch and a missing
  size read very differently to whoever hits them.

## [0.0.1+build.22] - 2026-07-28

### Changed
- **Entra ID provisioning split by flow**, 683 lines down to 226. Each protocol needed things
  none of the others do, and they were sharing a file: `provision_saml.py` (the token-signing
  certificate, the SSO mode, the reply URL and the claim mapping — none of which OIDC or
  app-only monitoring ever touch), `provision_scim.py` (the one flow that runs the other way:
  Entra pushes users INTO ServiceSentry, so what it creates is the token Entra will present to
  us), `app_permissions.py` (granting an existing app what it is missing) and `app_secrets.py`
  (adding a secret without invalidating the previous one, which is what makes a rotation safe
  while the old value is still in use). What remains is the app registration the other flows
  start from.
- **`app_permissions.py` is named to pair with `permissions.py`, not to merge into it.** That
  module already says why: it is read-only and stdlib-only so the monitoring daemon can import
  it cheaply, and it names `provisioning` as its write counterpart. Moving the granting code in
  there would have broken exactly the property its docstring exists to protect — so the two ends
  are now visible from their names instead of from a comment.
- Callers name the new homes: `entraid/routes.py` and the tests reach `app_secrets.add_app_secret`,
  `provision_saml.provision_saml2_app` and the rest directly. Nothing is re-exported from
  `provisioning` to spare them.

### Fixed
- **Tests were making real calls to Microsoft.** They patch `requests` on the module that uses
  it, and moving a function moved which module that is — so the patch stopped applying and the
  request went out, failing with Graph's own `IDX14100: JWT is not well formed`. Two of them
  now patch both modules the flow legitimately crosses, with the reason written beside it: the
  granting code calls `resource_sp`, which stays in `provisioning`.

## [0.0.1+build.21] - 2026-07-28

### Changed
- **`WebAdmin` handed four concerns to mixins**, 1809 lines down to 1119. The class already
  composed eleven domain mixins, so what was left in the file was everything that is *not* a
  domain — and four groups of it came out cleanly:
  - `mixins/stores.py` — building each domain's store at startup: which backend, which
    connector, what to do when the database is not up yet, and the order they have to come up
    in. A boot concern sitting in the middle of a class whose job is serving requests.
  - `lib/core/config/mixin.py` — reading the configuration, turning it into attributes,
    re-applying it on save, and overlaying the environment. It went to the config **domain**,
    not to `web_admin/mixins`, and the domain-layout guard is what said so: `core/config/
    routes.py` already calls `_read_config_file`, `_write_config` and `_apply_config_on_save`,
    so this is that domain's glue, and its package was missing exactly the `mixin.py` every
    other domain has. The `SS_*` overlay stays in it rather than moving into
    `ConfigManager.read()` on purpose: a value fixed by env must reach the editor marked
    **locked**, and a read that had already blended saved with env could not tell the two apart.
  - `mixins/scanners.py` — the three things the panel watches on its own: service health,
    certificate expiry, provider secret expiry. Nobody configured them and they have no
    schedule; they exist because the panel is the only thing in a position to notice.
  - `mixins/embed.py` — `frame-ancestors` and the session cookie's `SameSite`, which are two
    decisions that have to be made together. Allow the embed without the cookie and the iframe
    shows an eternally logged-out page; change the cookie without meaning to and the session
    travels cross-site everywhere.
- The other three joined the guard's list of glue that belongs to no domain, each with its
  reason written down: they serve EVERY domain, so filing one under a single package would make
  the rest import from something they have nothing to do with — which is the coupling that
  guard exists to prevent.
- Nothing outside changed: `WebAdmin`'s attribute surface is identical, 195 attributes, none
  added and none lost. The eleven domain mixins were already the precedent — these four simply
  stopped being the exception.
- One name did leave `app.py`, on purpose. `BUILTIN_ROLE_PERMISSIONS` was imported there and
  never used — it read as dead until the tests importing it *through* `app.py` failed. It lives
  in `lib.core.permissions`, which is where those tests now name it: an import that exists only
  so somebody else can reach it through you is a re-export, and this codebase asks for the real
  address instead.

## [0.0.1+build.20] - 2026-07-28

### Changed
- **`ModuleBase` gave up two things that were never about a check.** At 1115 lines it held the
  scanner that reads every watchful's `schema.json` and builds the catalogues the panel renders
  from (225 lines in one method, ~320 with its helpers) and the resolution of the machine an
  item is bound to — address, protocol profile, credential, operating system, and therefore
  which command (~240). Neither needs a monitor or an instance to mean anything. What is left,
  537 lines, is what a check actually needs from its base: the run loop, config resolution, the
  module's own messages, and emitting a result.
- The scanner moved into `lib/modules/discovery/`, **the package that already existed for
  exactly it**: that package's own docstring says it is "kept apart from the module framework
  itself (module_base / dict_return_check)", and `credential_schemas.py` documents itself as
  merged by `ModuleBase.discover_schemas` — the package had grown up around a function that
  never moved in.
- Both are mixed back into `ModuleBase`, so every call site is untouched: watchfuls keep
  calling `self.host_exec` and `ModuleBase._schema_defaults`, and lib keeps calling
  `ModuleBase.discover_schemas`. That is composition rather than a convenience re-export — the
  class genuinely provides them, which is why this move needed no caller changes at all.

### Fixed
- **A scanner that moved one directory deeper and quietly returned nothing.**
  `discover_schemas` derives its default directory by counting `..` from its own file, and a
  missing directory is not an error to it — it returns an empty catalogue. So the move did not
  break loudly: it stopped finding the modules, and surfaced half a dozen files away as
  `KeyError: 'ping|list'`. The path is no longer counted at all: it is **searched** — walk up
  for the first ancestor holding both `lib/` and `watchfuls/` — so it survives this file moving
  anywhere inside `lib/`, which is precisely what broke it. A block comment at the definition
  says why, and three guards put the failure at the cause: the catalogue is not empty, it
  contains every discovered module, and the derived path agrees with an explicit one — that
  last because a wrong derivation can point at some other directory that happens to exist.

## [0.0.1+build.19] - 2026-07-28

### Changed
- **The Ping watchful moved ICMP into its own file**, 332 lines down to 200. `client.py` holds
  the echo request, the echo reply and the socket that carries them — written by hand rather
  than shelling out to the system `ping`, because parsing another program's localised,
  per-platform output to learn a round-trip time is a worse contract than building the packet
  ourselves. The check keeps what a lost packet MEANS: how many attempts, which threshold.
- It was under the 350-line limit and split anyway, on request. The guard is a smoke alarm for
  a file that has stopped being one thing, not a target to refactor towards — ping was simply
  two things at 332 lines rather than one at 400.
- The move exposed a reference that only worked by accident of being in the same file:
  `_build_icmp_packet` called `Watchful._icmp_checksum` by the composed class's name, from
  inside it. Correct before, broken the moment the method moved to a mixin, and it now calls
  the class that actually defines it.

## [0.0.1+build.18] - 2026-07-28

### Changed
- **The service-status watchful split**, 389 lines down to 215: discovery and its five
  per-init parsers — systemd, OpenRC, SysV, launchd and Windows SC, each answering
  differently, with the dispatch picking by platform — moved to `actions.py`. What remains is
  the check and the service commands behind it.
- With it, **`_INIT_SPLIT_PENDING` is empty.** It began as snmp 1596, proxmox 1087,
  datastore 1052, dns 719 and service_status 389, and every one came off it as it was split —
  the only direction that list is allowed to move. The largest `__init__.py` in the repo is now
  `ping`, at 332: under the line, and left alone.

## [0.0.1+build.17] - 2026-07-28

### Changed
- **The DNS watchful split five ways**, 719 lines down to 214. `client.py` holds the four ways
  of asking a question — straight through the socket for A/AAAA/PTR, dnspython for everything
  else, PowerShell's Resolve-DnsName on Windows (where python.exe's own queries are commonly
  firewall-blocked while the OS DNS client resolves fine), and dig/nslookup over SSH when the
  question has to be asked from a bound host rather than from here. `deps.py` holds the lazy
  dnspython loader, `tables.py` the record-type knowledge, `defaults.py` the parsed schema, and
  `actions.py` discovery — including the zone transfer that turns "add a check per record" into
  a selection.
- **The patch that could not take, again**, and this time it had been living in a test fixture:
  the autouse fixture forcing the non-Windows path set the flag on the package while the
  resolvers read their own bound copy, so it reached only part of the module and the Windows
  branch was never really excluded where it mattered. Read as an attribute now, one place to
  patch, and the fixture says why.
- `service_status` (389) is the last module left on the pending-split list.

### Added
- A guard that no file under `watchfuls/dns/` may be named after a dnspython submodule
  (`resolver`, `zone`, `query`, `rdatatype`, `exception`). The monitor registers that package
  as `sys.modules['dns']`, so `import dns.resolver` finds the watchful; the loader works around
  it, but a file with one of those names would be a second, quieter collision waiting for
  whoever added it. It is why the resolvers are in `client.py`, and the guard fails with that
  explanation rather than leaving the next person to rediscover it. A second test keeps the
  forbidden list tied to what the loader actually imports.

## [0.0.1+build.16] - 2026-07-28

### Changed
- **The Datastore watchful split seven ways.** Its `__init__.py` was 1052 lines and is now 97.
  `engines.py` holds the ten conversations — MySQL/MariaDB, PostgreSQL, MSSQL, MongoDB,
  Redis/Valkey, Elasticsearch/OpenSearch, InfluxDB, Memcached — each answering "are you alive"
  and "what databases do you have" its own way; both halves stay together because both are the
  same kind of knowledge, and splitting ping from list would put two halves of one driver in
  two files. `checks.py` decides which backend to ask and what the answer means, and knows
  nothing about any of them. `tunnel.py` is the local listener that forwards over SSH, so the
  ten drivers never learn they are not talking to localhost. `actions.py` is what the panel
  invokes, `deps.py` is which client library is actually installed, and `tables.py` the default
  ports, display names and config vocabulary that all three read and none of them owns.
- **A patch that could not take.** The optional-dependency flags were reached with
  `from .deps import _PSYCOPG2`, which copies the value: setting it on one module left every
  other consumer looking at the old one, so a test disabling a backend disabled it only where
  it happened to look. They are read as attributes now — one place to patch, and the tests
  stopped needing a different target per module.
- `_pkey_from_string` went with the tunnel that uses it, and `_DEFAULT_PORTS` with the table it
  belongs to; the tests name both at their real address rather than through a re-export.
- The pending-split list is down to `dns` (719) and `service_status` (389).

## [0.0.1+build.15] - 2026-07-28

### Changed
- **The Proxmox watchful split five ways, by the same rule as SNMP.** Its `__init__.py` was
  1087 lines answering five separate questions, and now answers one. `client.py` holds the
  HTTPS conversation — request, connect, and the failover between configured nodes, which
  exists because a cluster with a dead node must still be able to answer about itself.
  `checks.py` holds the family of questions about cluster health: quorum, per-node status and
  maintenance, Ceph, network interfaces, pending updates, storage, and the privilege check
  that runs first because "cannot read that" is a more useful answer than a cluster with no
  nodes. `actions.py` holds what the panel invokes. `page.py` holds the Overview widget.
  `provision.py` holds the flows that WRITE to the cluster — creating the monitoring user,
  its role and its API token over SSH, and repairing privileges — which are deliberately not
  read-only actions and are audited; they run `pvesh` over SSH rather than through the REST
  API because the credential they create is the one the API would have needed.
- `__init__.py` keeps 201 lines: the class, the loop over items and the dispatch to one check.
  Verified the same way as SNMP — the attribute surface before and after is identical: 77
  attributes, none added, none lost, all five actions still resolve.
- `PveError` moved with the transport that raises it, so a test that caught it now imports it
  from `watchfuls.proxmox.client`. Nothing is re-exported from `__init__` to hide that.
- The layout guard caught its own success: with proxmox down to 201 lines, the test that keeps
  the pending-split list honest failed until proxmox was taken off it. Two of the four
  originally listed are done; `datastore` (1052), `dns` (719) and `service_status` (389)
  remain.

## [0.0.1+build.14] - 2026-07-28

### Changed
- **The SNMP watchful stopped being three subsystems in one file.** Its `__init__.py` was 1596
  lines, of which about six hundred never checked anything: they upload a MIB, compile raw
  ASN.1, import a folder from GitHub or a file from a URL, and answer for the contents — a
  small file manager with a background job runner. Another hundred and fifty were the SNMP
  conversation itself. Split by the question each part answers, not by size: `mib_admin.py`
  (the catalogue, joining the `mib_resolver`/`mib_catalog` it already had), `client.py` (GET
  and WALK, and the pysnmp guard), `actions.py` (discovery and audit detail) and `defaults.py`
  (the parsed schema), leaving 259 lines that are the module itself — the class, the loop over
  items and the dispatch to one check. The class is composed from those by inheritance, so
  from the outside nothing changed: same 76 attributes, same 16 actions, same signatures.
- **Those file names are now the convention**, written down in the watchful guide with the
  line at ~350 lines, and enforced: a module whose `__init__.py` grows past it fails, with the
  four not yet split listed explicitly in a list that may only shrink. Nothing is re-exported
  from `__init__` to soften the move — a convenience import would leave the code looking like
  it never moved, and the next caller would reach for it in the wrong place.
- **The SNMP path-traversal regression tests now attack the actions, not the helpers.** Seven
  of them called `_safe_mib_filename` and `_confined_path` directly from the central security
  file, which proved the allowlist works but not that the file operations use it — a new
  operation that forgot the guard would have left every one of them green. They moved next to
  the code they name, and the security suite keeps the stronger half: `upload_mib`,
  `delete_mib` and `get_raw_mib_details` fed traversal payloads, asserting nothing is written,
  removed or read outside the MIB directory. Writing it that way turned up that `upload_mib`
  does not reject `../../../etc/passwd` at all — it takes the basename first, so the payload is
  defused into `passwd` and lands inside `raw/` like any other name. The defence is sound; the
  test now pins containment, which is the property that actually matters.

## [0.0.1+build.13] - 2026-07-28

### Changed
- **Credentials is a section of its own, not a sub-tab of Infrastructure.** It went there when
  the catalogue was reusable SSH identities — genuinely a host concern, and the comment
  justifying the move said so. That stopped being true: half of it is now Entra ID app
  registrations, reached by tenant with no host behind them, and the flows built around them
  (rotate a secret, grant and consent the roles an app is missing) never touch a machine. Two
  structural reasons on top of the population: its neighbours there, Servers and Clusters, are
  things you MONITOR, while a credential is the secret you reach other things WITH; and its
  consumers are spread across hosts, modules and providers alike, so hanging it off any one of
  them asserted a belonging that was not real. Not moved back to Access either — that is users,
  groups, roles and sessions, meaning who may enter the panel, and these are machine identities
  the panel uses on its way out.
- It keeps its own permissions, so nothing changes about who sees it. What did change: holding
  only `credentials_view` no longer reveals Infrastructure, which would now be an empty tab.

### Fixed
- The Credentials overview widget navigated to the wrong place. It declared `#tab-access` long
  after the tab had left Access, then looked for a sub-tab that lived inside a third pane — and
  a dead target is worse than a missing one, because Bootstrap activates nothing and reports
  nothing, so the click just did not work and left no error to follow.

## [0.0.1+build.12] - 2026-07-28

### Added
- **A module page can be read four ways, and the layouts belong to the core.** A module
  contributes a top-level section by declaring `__page__` and answering with a fixed shape —
  sections of rows, each with a state, a message and whatever the check measured. Because the
  shape is fixed, the layouts are core furniture: **board** (one tile per section, then only
  the rows needing attention), **sections and detail** (a narrow list beside the chosen
  section at full width), **table** (one row per check across every section, for triage) and
  the **stacked cards** it had. Microsoft 365 and Azure get all four from the same code, and a
  module contributing a page tomorrow gets them without writing any front-end at all.
- A filter and an "only problems" switch came with them, both **per page**: wanting the table
  for Azure and the board for M365 at the same time is normal, and one shared setting would
  make each visit undo the other. Switching view redraws what is on screen — refreshing a
  module page queries Microsoft, so a layout switch that re-fetched would charge the reader
  for a decision about presentation.
- **A usage ring per row**, where the module declares one. `section.chart = {used, total}`
  names two measurements; the core divides and draws. No metric name lives in the core — the
  same arrangement as `group_by`, which says which measurement is worth grouping on without
  saying what any of them mean. Declared today for site storage, tenant and OneDrive storage,
  Secure Score, licence capacity and MFA coverage.
- Where a row has no total, an **empty ring** is drawn rather than nothing, with a tooltip
  naming the measurement that is missing. A silent absence sends the reader off the page to
  find out why — which is exactly what happened with OneDrive, whose "whole" is a limit
  nobody had configured.

- **Five new Microsoft 365 checks**, each answering a question the panel can and an admin
  usually cannot, because each lives in a report nobody opens twice a year:
  **MFA coverage** (how much of the directory has *registered* it — a policy that requires it
  and a directory that has registered it are different facts), **unused licences** (accounts
  holding a licence and not signing in: not a fault, a bill — and it names WHICH licences,
  because "10 of 11 idle" is a number without an answer; an account holding two idle licences
  wastes two, since the total that costs money counts licences, not people), **privileged
  roles** (how many
  Global Administrators exist), **domains** (one left unverified stops receiving mail) and
  **service messages** (Microsoft's own deadlines for retirements and breaking changes — a
  different question from whether a service is down).
- All five are **off by default**, like every other optional check in the module. Turning them
  on for existing installs would have started calling Graph with permissions not yet consented,
  and in some cases alerting: a tenant with six Global Administrators and a threshold of five
  would begin warning without anyone asking it to.
- The Graph roles they need are declared, so the credential editor's **Check permissions**
  reports them as missing and **Fix permissions** grants and consents them on the app that
  already exists — same client id, same prior grants, no re-registration.
- **Licence capacity now reports one row per SKU**, the way service health already reported one
  per service. The numbers behind the verdict — units owned, units taken — were computed and
  thrown away, leaving a single row that said "4 SKUs" and could not answer the only question
  worth asking: which one is filling up. Note the consequence: alerts are now per SKU, so two
  exhausted SKUs are two warnings rather than one.

### Changed
- **Running one check on demand moved out of the hosts domain.** The runner behind the Servers
  "test" button and every module page's live refresh had lived in `lib/core/hosts/probe.py`,
  because that is where it was needed first — so the generic module layer depended on one
  domain to run a module. It is `lib/modules/check_runner.py` now, beside its main caller;
  `probe.py` keeps resolving an unsaved host, which is the part that really is about hosts, and
  deliberately does not re-export the runner: a convenience import would keep it looking like
  host code and the next caller would reach for it there again. That address is not a detail —
  the severity bug below survived precisely because a decision about the module result contract
  was sitting in a file nobody opens when they change what a check emits.
- **Microsoft 365 stopped shipping its own page renderer.** It had begun as a copy of the
  core's and then stopped tracking it — by the time anyone looked, the core had grown grouping
  by measurement and the copy had not. It was not a different design, it was an older one, so
  the copy was deleted rather than a fourth renderer written beside it. The mechanism for a
  module to ship one remains; a guard now notices when a module uses it, because a second
  implementation deserves a conversation rather than appearing quietly.

### Fixed
- The board's tiles had no edges, so it was not clear which item an icon belonged to. They
  dropped the card border and pushed the state badge to the far right — the furthest point
  from the number it qualifies and the nearest to the next tile's label, which is what the
  eye then paired it with. The border is back and the badge leads its figure, aligned under
  the label, so each tile reads as one column of label, state and count.
- The "only problems" switch did nothing to the board's tiles: they were drawn from the
  unfiltered list, so in the view where the switch has the least left to hide it also appeared
  to do nothing at all.
- A metrics badge, and five others across clusters and servers, used `text-bg-light` — light
  background and dark text whatever the theme is. The CSS-trap guard now bans it alongside
  `table-light`.
- **The same check reported amber or red depending on who ran it.** A module page has two
  halves — the monitor's last stored result and a live refresh — and the live one rebuilds each
  result field by field from a list that never included `severity`. So a soft threshold breach
  (unused licences, a quota near its limit) arrived indistinguishable from a hard failure and
  the page painted the row, its section badge and its ring red, while the stored half of the
  very same check painted them amber. Not a Microsoft 365 fault: it hit every module with a
  warning state, and the "test this credential" button in Servers too. The projection stopped
  being a hand-kept list: it is checked against what the result contract writes, so the next
  field added has to be carried or excluded on purpose rather than falling out by omission —
  `name` was already going the same way.
- The usage ring coloured itself from a fixed "fuller is worse" scale, so a row the check had
  called a warning could carry a red ring — two signals disagreeing about one record. It takes
  the row's own state now: the check decides, the ring draws.
- The MFA check asked Graph for `userRegistrationFeatureSummary` as a plain segment. It is an
  OData function with required parameters, so the answer was `400 Resource not found for the
  segment` — a check that could never have worked. It counts from `userRegistrationDetails`,
  the GA report, instead: more calls, and impossible to be wrong about.
- The two panes of the sections-and-detail layout started at different heights, so the list's
  first entry sat level with the detail's title and the halves read as unrelated. Both headers
  come from one class with a fixed height now: with different content on each side, matching
  padding would only align them by luck.

## [0.0.1+build.11] - 2026-07-27

### Added
- **Status can be read four ways.** It is a monitoring surface, so the layouts differ in how
  fast they answer "what is broken right now" — and the card grid answers it slowly: you
  scroll past everything green to find the two that are not. Three more sit beside it behind
  a switcher: **summary** (the totals first, then modules ordered worst-first, with an "only
  problems" switch), **check table** (one row per CHECK rather than per module — module,
  check, reason, value against threshold, all comparable on one line, and the view that
  survives three hundred checks), and **heatmap** (one tile per check, a wall you take in at
  once; hover names it, clicking opens its reason). The card grid stays as the fourth,
  unsorted, because it is the baseline the others are compared against.
- The summary spends page on a module in proportion to what it has to say: a failing module
  gets a full card with its problems in view, everything else collapses to one line — a dot,
  a name, a count — so twelve modules that are fine cost twelve lines instead of twelve cards.
  The line is still a way in: clicking one opens its card, because wanting to look at a module
  that is passing should not require changing view. What you opened is deliberately forgotten
  on the next visit; a summary that filled up with everything ever opened would be the grid
  again with extra steps. A module with no items at all is not called passing — it ran
  nothing, and saying OK about it would be the page's own small lie.
- A filter came with them, matching a module name **or** a check name — half the time you are
  looking for one host, not for the module it happens to live under.
- **All four agree about what a check means.** Whether a result is ok / warning / error, its
  display name, and the value-vs-threshold decoration its module declares in
  `__status_render__` are decided once and drawn from by every view. On a page whose whole job
  is to say what is wrong, two panels contradicting each other about the same check is worse
  than either being wrong alone — and the distinction that costs most to lose is warning vs
  error: a soft threshold breach is amber, not red.
- Switching view, filtering and "only problems" all redraw the data already on screen instead
  of re-fetching. Looking at a result is not asking for a new one, and on a page that
  auto-refreshes a redraw that fetched would also race its own timer.
- "Only problems" now hides the passing **checks**, not just the modules that have none:
  keeping a module with one error and eight OK checks still listed all nine, so on the table
  view — the one where it matters most — the switch looked broken. The counts beside it still
  report the whole set, because hiding the passing checks must not also hide that they exist.
  It is remembered across reloads, and what makes that safe is where it sits: next to totals
  that always state everything, so a filtered page cannot understate how much there is. The
  search term is not remembered — the totals say nothing about a text filter, so a page
  opening with one silently applied could not admit to it.
- **A table header no longer wears light colours in dark mode.** Bootstrap's `.table-light`
  pins a light background AND dark text whatever the theme is, so the check table carried a
  white strip across the top of a dark page. It was in three templates by the time it was
  seen — two written the same week from the same habit, one old enough that nobody looked at
  it any more — so a guard replaced the three fixes. It bans `table-light` and deliberately
  does not ban `bg-light`: a badge inside a primary button is light against the button, not
  the page, and flagging five correct templates is how a test gets switched off. The header
  also needed a rule under it, not just a shade: at that size a background alone reads as
  nothing, and the column titles floated over the data.
- **A row separator that broke at one column.** `d-flex` on a `<td>` takes it out of
  `display: table-cell`, so the cell stops taking part in the row's height and its bottom
  border draws at the height of its own content. Both new tables did it; the flex now goes on
  a wrapper inside the cell, and a guard scans for it — it is invisible in review and obvious
  on screen, which is the worst combination to leave to attention.
- The filter, the view switcher and the "only problems" switch sit on one line with the
  totals rather than in a strip of their own. Not in the Scheduler toolbar, where there is
  visibly room: that toolbar exists only for a user with `checks_run`, and filtering is
  reading, not running.

## [0.0.1+build.10] - 2026-07-27

### Added
- **Modules can be laid out four ways, and you pick.** The section had one — a grid of cards,
  each expanding its configuration inside a 420px cell — and that layout already admitted the
  cell was too small: it carried a "full screen" button that reopened the same body in a modal,
  which is a workaround for the container, not a feature. Three more sit beside it behind a
  switcher in the toolbar, so the choice can be made by using them rather than by arguing:
  **list and detail** (a narrow scrolling list, the selected module gets the rest of the width —
  nothing grows, so nothing reflows), **table** (one row per module: state, items, warnings —
  for "which of these is not how I left it"), and **compact cards** (status tiles that never
  grow, editing opens full width with a back button).
- The chosen view is remembered, and so is the module you were on. A filter box came with them,
  matching the module id AND its display name, because half the time you remember one and half
  the time the other.
- **A view is chrome and navigation, nothing else.** What a module's configuration looks like is
  one renderer used verbatim by all four; none of them counts items, decides whether a module is
  available, or applies the view-only permission on its own. Those were the parts that would
  have become four copies, and the tests hold the line.
- Writing that up found a duplication that predates it: the "add module" picker read the three
  dependency/platform discovery flags itself, one drift away from offering a module the list
  would then refuse to configure. Both ask the same function now.

## [0.0.1+build.9] - 2026-07-27

### Fixed
- **The per-service command menu had no icons.** Start and Stop sit a centimetre away with
  one each, so a text-only dropdown beside them read as unfinished. The glyph is chosen per
  COMMAND rather than per service, because "Reload" means the same thing wherever it appears
  and must not be one icon under Monitor and another under Syslog. Run Now deliberately avoids
  the play glyph Start uses: it runs one cycle now, it does not start the service, and two
  controls that close together must not claim the same action.
- **fail2ban had Start/Stop and nothing else.** Not by design: it was the only controllable
  service with no `_apply_command`. It now offers **Reload** — push the stored config into the
  live jail (thresholds, windows, ban durations and the **whitelist**; an address added to the
  whitelist did nothing until a config save happened to reconfigure the jail) — and **Prune**,
  a retention sweep over stale offence counters, the ban log and the history. The hook lives on
  the embedded twin rather than in a manager mixin because this service has no worker loop: the
  gate runs inline on every request. The manual prune deliberately does not call the jail's own
  `_gc`, which is throttled to once every five minutes and would have reported success while
  sweeping nothing.
- **The destructive commands ask first.** Prune and Clear status delete things that do not come
  back, and they sit in the same dropdown as Reload — one row apart, same colour, no gap. The
  confirmation **names the service**, because the same command destroys different things
  depending on where it is pressed: Prune under Syslog drops stored messages, under fail2ban
  offence counters and the ban log. A dialog that does not say what you are about to lose is a
  speed bump, not a safeguard. Reload and Run now are not gated — asking every time teaches
  people to click through the dialog without reading it.
- A guard now checks that the menu never offers a command the service's own `_apply_command`
  rejects — an entry the backend does not implement is a button that fails every time it is
  pressed. The reverse is left alone on purpose: syslog accepts `clear_status` as an alias of
  `prune` and the panel does not offer it, which is a decision about the UI, not a broken
  control.
- Noted but not fixed, with the reason written into the tests: the route validates an action
  name against ONE GLOBAL set, so `run_now` against fail2ban — which has no work cycle — is
  accepted, queued and only refused by the service itself, leaving `unknown_action` in a table
  row while the HTTP answer already said `ok`. `ok` means "queued", not "ran". Making it honest
  needs each service to DECLARE its commands, which is the same change that would stop the
  panel hardcoding the menu.

## [0.0.1+build.8] - 2026-07-27

### Fixed
- **"Connection lost" stopped firing when the connection was fine.** The overlay covers the
  whole panel, so a false one is not a cosmetic slip: it interrupts whatever the user was
  doing to tell them something untrue, and it stays until the next probe happens to succeed.
  It was raised by a **single** failure. The mechanism read as if it were careful — the
  comment said "debounced (~1.2 s of continuous failure) so a single blip doesn't flash it" —
  but nothing re-checked during that wait: the timer only delayed the announcement, it never
  questioned it. One slow answer was enough (a request that overran the 4 s heartbeat timeout
  because a worker was busy, a blip while a laptop changes network).
- A first failure now asks again instead of announcing: it triggers an immediate re-probe, and
  only a second consecutive failure raises the overlay. A real outage is barely slower to
  show, because the confirmation does not wait for the next heartbeat — and any success
  resets the count and cancels both pending timers, so two unrelated failures minutes apart
  never add up to an outage.
- The confirmation also waits twice as long. The first probe's short timeout is tuned to
  notice a *hanging* backend quickly, but a merely busy one overruns it too, and "slow once"
  is not "gone". A dead socket still fails immediately, so a real outage shows just as fast.
- The authoritative signals still bypass all of it: the browser reporting itself offline shows
  the overlay at once (there is nothing to confirm), a gateway error from a proxy in front of a
  dead backend still counts as unreachable, and a request cancelled by navigation still does not.

## [0.0.1+build.7] - 2026-07-27

### Added
- **The SSO sections can ask whether their app is actually allowed to read the directory.**
  The credentials editor could already check a module's Entra app; the SSO ones could not,
  and they are where the question bites hardest, because **consent is the half that fails
  silently**. Registering the app succeeds, the admin never presses "Grant admin consent",
  and nothing complains until Graph is actually called — the group picker comes back empty,
  or a login maps no groups, with nothing saying a consent is missing. OIDC and SAML2 each
  get a "Check permissions" button next to their register/open buttons.
- The check reads the `roles` claim of an app-only token: a permission that was requested
  but never consented never reaches that claim, which is exactly the distinction being made.
  The required list is declared **server-side**, next to the id the registration grants, so
  the check cannot end up asking for something the register button never provisioned. SAML2
  is checked with **its own** app — it has its own registration and its own Graph secret, and
  borrowing OIDC's would verify an identity nobody pointed at SAML2.
- The checklist modal is now one renderer shared by the credentials editor and the auth
  sections; a caller that does not hold the required list gets its rows built from the answer.

- **A credential's Entra app secret can be rotated (m365, azure).** The SSO OIDC section
  already offered this. For a module credential the only way to replace an expiring secret
  was to register the app again — which mints a **new** app id and starts its permissions and
  consent from zero, breaking whatever else already trusted the old one. Rotation touches the
  secret and nothing else: same app, same grants, same consent.
- The new secret is **stored on the credential**, not merely typed into the open editor: a
  rotation that only filled a form would leave the app holding a secret nobody kept if the
  editor were closed without saving, while the old one keeps ticking towards expiry. It is
  also returned, so the field on screen stops showing the value that is about to go.
- `AADSTS7000215` is returned by Entra both for a wrong secret **and** for a correct one
  created seconds ago that has not replicated yet. The sign-in retries, and if it still fails
  the message says which of the two it might be instead of showing a raw trace id.

- **The site has a favicon.** There was none, so every visit produced a `GET /favicon.ico 404`
  — harmless in itself, and noise in the access log of every deployment forever. The panel's
  own shield-check mark now ships as an SVG (what a modern browser prefers, crisp at any
  density) and as a multi-size `.ico`, both cache-busted like the stylesheet. `/favicon.ico` is
  served as a public route as well as declared in the page, because browsers request that path
  from the site root on their own — on an error page, on a JSON endpoint opened in a tab,
  before any HTML is parsed. Requiring a session for it would answer an icon request with the
  login page.
- The `.ico` is generated by `tools/make_favicon.py` from the shape itself, with no image
  library: a PNG is a few zlib-compressed scanlines and an `.ico` is a directory of PNGs. Each
  size is rendered from the geometry rather than downscaled from one bitmap — at 16px, the size
  a browser tab actually shows, a downscaled check mark turns to mush. A test re-runs the
  generator and compares bytes, so the committed binary cannot drift from its source.

### Fixed
- **The breadcrumb names the whole path to the section, not the last step or two.** It read
  the active sidebar item and its sub-item and stopped there, so Services announced itself as
  plain "Services" — the same shape a first-level section gets — and Servers as
  "Infrastructure / Servers". Both dropped the group they live in, which is the part that says
  where you are: you reach Servers by opening System, then Infrastructure. They now read
  "System / Services" and "System / Infrastructure / Servers", resolved from whichever group
  actually contains the active item. A first-level section (Overview, History, Syslog…) sits
  in no group and stays just its own name — prefixing it would name a place it does not live in.

- **A new Group → Role mapping now survives pressing Save.** Adding a row under
  Configuration › Authentication › SSO (OIDC), pressing Save and reloading left the mapping
  gone — while the toast had said it saved. Changing the Role of a mapping that already
  existed always worked, and that asymmetry was the whole diagnosis: the Role `<select>`
  stages its value synchronously, while the group-id `<input>` went through a handler that
  **awaited a directory name lookup first**. That handler runs on `change`, which fires when
  the Save button takes focus, so the click landed with the lookup in flight: the save sent
  every dirty field except this one, reported success truthfully, and the mapping was staged a
  moment later with nobody left to save it.
- **Two settings could make the panel impossible to log into, and both failed the same way:**
  an endless bounce between `/login` and `/`. The login itself worked — credentials accepted,
  session created — and the browser then arrived at the next page with no session, because
  the cookie carrying it had been dropped on arrival. Nothing said so, and the page where you
  would switch the setting back off was behind that login.
- **Allowing an iframe origin marked the session cookie `Secure` unconditionally**, and a
  browser drops a `Secure` cookie on `http://` — so turning on the Teams embed locked out
  every plain-HTTP deployment. The trade never paid either: a cross-site iframe needs
  `SameSite=None`, browsers refuse `SameSite=None` without `Secure`, and they refuse `Secure`
  over HTTP, so the policy could not enable the embed on such a deployment in the first
  place. It now applies only alongside an explicit HTTPS intent (`secure_cookies` or
  `force_https`) — the same reasoning already applied to `public_url` — and logs a warning
  when an embed origin is allowed without one, instead of silently doing nothing.
- **`force_fqdn` could redirect to itself.** `request.host` carries the port and the public
  URL need not, so `192.168.0.1:8080` read as a different host from `192.168.0.1` and the
  browser was sent to port 80. The setting is about the hostname you arrived on: a public URL
  that names no port now accepts any port, one that names a port still requires it, and the
  comparison is case-insensitive. As a backstop, a target identical to the request being
  answered is never redirected — refusing beats looping, since the worst case is that the
  hardening does not apply, which is where you already were.

- **A successful save no longer leaves the Save button claiming unsaved changes.** With the
  mapping saving correctly, the button went straight back to "pending changes" right after
  announcing success — F5 showed the value stored, and pressing Save a second time was what
  quietened it. Same widget, opposite direction: the button is judged by comparing
  `configData` against `_serverConfigData`, the snapshot of what the server holds, and this
  widget saves one field **on its own** (`group_display_names` — names it resolves itself,
  which the user never typed and should not have to save). That out-of-band save dropped the
  path from the dirty set but never moved the snapshot, so the two disagreed for good and the
  button believed it.
- The version token, the dirty set and the snapshot describe one fact — "the server has this
  now" — and now move together in a single `applySavedField`, which the main save and the
  widget both call. More importantly, a resolved display name is no longer staged as a user
  edit at all: it is written straight into the local config and persisted immediately, so the
  automatic path cannot light the Save button whatever the ordering. The lookup finishes
  *after* the save it races — that is what the user was waiting for when they pressed Save —
  so anything it staged landed in a dirty set that had just been emptied. If that save fails,
  the field is put back to what the server is known to hold, rather than leaving a difference
  the user cannot see, did not cause and could only clear by saving. Nothing on that path
  calls `markDirty` either — it can only ever *light* the button, never leave it alone, so a
  path that stages nothing has nothing to re-judge.
- And "nothing pending" is now **true** rather than displayed: a save in which everything the
  user staged was accepted re-takes the whole saved-state snapshot. Mirroring field by field
  only covers what was sent, so any field that differed without being staged — written by a
  widget outside the dirty set, normalised locally, whatever — made the very next `markDirty`
  light the button for a change nobody made and nobody could clear.

- **The Configuration header stays on screen for the whole section.** The toolbar (title,
  Reload, Save with its unsaved-changes badge) and the search box are the controls you reach
  for *because* you scrolled — and they slid up and out of view after about one screenful,
  exactly where the config list gets long enough to need them. They were pinned with
  `position: sticky`, which could not work there: an active tab-pane is a flex column bounded
  by the viewport, so the sticky element's containing block is one screen tall no matter how
  long the content is, and the header scrolled away with the block that held it. The header
  now keeps its natural height and the config body below it scrolls (`.ss-vscroll`), which is
  the mechanism the rest of the panel already uses — there is no longer any scrolling
  underneath it to carry it off.
- The seam between the two was cleaned up with it. A 1rem strip of page background sat below
  the card, and rows sliding under the header surfaced *in* it — a floating fragment of an
  input that read as a rendering fault. The card's own border is the boundary now, and the
  body fades out over its last few pixels instead of being sliced with a razor edge, so the
  same clip looks deliberate. The bar also sits on the section's top edge rather than
  floating inside its padding: full width, square on top, borders only where there is
  something to separate. Its bottom corners keep their curve, because that curve is the line
  the scrolling body disappears under.
- **The config search box is collapsed by default.** It is for finding one setting among many,
  not something worth a permanent row of the pinned header. Opening it puts the cursor in it —
  you press the magnifier because you are about to type. Hiding it costs one thing, so that is
  handled too: a filter left on while the box is closed would show a fraction of the
  configuration with nothing on screen saying why, so the toggle carries a badge whenever a
  filter is active. And with the box closed the toolbar is the bottom of the card again and
  takes its rounded corners back, instead of ending in a square edge with nothing under it.

- **The domain-layout guard was left failing by build.6.** `lib/web_admin/mixins/freshness.py`
  shipped in that commit and the guard flagged it as a domain mixin sitting outside its
  package. It is not one: the staleness check serves users, roles **and** groups, so putting
  it inside any of the three would make the other two import from a domain they have nothing
  to do with — which is the coupling that guard exists to prevent. It is now listed as
  non-domain glue, with the reason written down.

- Two things keep it fixed: the mapping is staged before the handler can branch at all (not
  merely "before the first await" — the buggy version already did that, inside an `if` that
  returns), and the input stages on every keystroke rather than only on blur, so what is
  pending always matches what is on screen. It affects every section with a group source —
  oidc, saml2 and ldap all declare one.

### Changed
- **The Entra device-code conversation is written once instead of six times.** Six buttons
  register or repair an app — SAML2, SCIM, the OIDC secret, a credential's secret, the generic
  module wizard — and every one of them held its own copy of the same exchange: ask Entra for
  a code, park what the operation will need, poll until the admin has signed in elsewhere.
  With it went six copies of its rules (how long a parked flow lives, that `slow_down` raises
  the interval, that a terminal answer consumes the flow), which is a rule nobody can change.
  It now lives in `lib/providers/entraid/device_flow.py`, and `routes.py` went from 972 lines
  to ~700 of actual routing.
- The copies had already **drifted**: the SAML2 poll checked that *a* flow was parked under
  the token, but not that it was parked *for it*, so a flow of any other kind could be
  advanced through it and then read with the wrong stash. Kinds are now always checked, a
  completed sign-in is dropped **before** the slow part (so a second poll cannot redeem the
  same code twice and run the operation again), and every terminal failure is audited —
  previously two of the polls audited nothing, leaving the failure in a toast the admin had
  already dismissed.
- Every wizard now returns `verification_uri_complete` (the URL with the code already in it,
  so the admin lands on the consent screen with nothing to type); one of the six did not.
- Three more things that were never routing moved out of `routes.py` to where they belong:
  which app an auth section uses and the SP/SCIM URLs this server publishes
  (`entraid/sections.py`), reading and writing the credential that holds an Entra app
  (`entraid/cred_link.py` — including the trap that `update()` replaces a credential
  wholesale, so a rotation must resend every untouched field), and resolving what an app must
  be granted (`entraid/declarations.py`, next to the declaration vocabulary itself). As plain
  functions their rules are testable without going through HTTP, which is how they are pinned.
- The SSO permission-check handler moved out of `entraid/web/_groups_ui.html` into its own
  `_perms_ui.html`: that file is about reading the directory, this is about whether the app is
  allowed to.

## [0.0.1+build.6] - 2026-07-26

### Fixed
- **A second writer is no longer invisible to a running web process.** Roles, users and
  groups were read from the database once, at startup, and every request answered from those
  dicts — a single-writer assumption that was already false twice over: the **CLI** writes
  users and groups against the same database (`ssentry user role bob viewer` was invisible
  until a restart), and a second **web replica** writes all three. The process that did not
  make the change kept serving what it loaded, including permissions that had been revoked.
- Reloading on every request would fix it by re-reading and re-parsing every row to discover
  that nothing changed, which is the normal case. Instead each table is asked something cheap
  and re-read only when the answer moves.
- **The cheap question is a version counter, not a timestamp.** Every writer bumps
  `entity_versions` for its table inside the same transaction as the write, so the version and
  the rows it describes become visible together. A counter says "something changed" with
  nobody's clock involved, which matters precisely because the writers this exists for are
  different machines: with timestamps, a replica whose clock runs a few seconds behind writes
  a row stamped below the current maximum — `MAX(updated_at)` does not move, the row count
  does not move — and its change stays invisible to everybody else until an unrelated write.
  Silent, and in the exact scenario the mechanism is for. The probe still carries the row
  count and newest timestamp in the same round trip, as a backstop for a writer that bypasses
  the counter (a hand-edited row, a migration script, an older build).
- The check runs in `before_request` and **only** there: a reload replaces the dict wholesale,
  so doing it inside a handler — `_get_session_permissions()` is called from several, some
  after they have already mutated the dict — would throw away the edit in progress. Static
  files are skipped: they authorise nothing and would turn one page load into thirty queries.
- An unreadable table answers `None`, which means "keep what you have" — not "nothing
  changed" and not "everything is gone". A database blip must not leave a process authorising
  against zero roles. `_load_users` refuses an empty answer for the same reason: "no users" is
  not a state this product can be in, and applying it would lock everyone out.

- **The second writer to save no longer deletes the first one's work.** Roles, users and
  groups were written back with `DELETE FROM <table>` + re-inserting everything held in
  memory. Two admins on two replicas editing *different* roles did not lose a field each: the
  one who saved second deleted the other's role and restored the table as it looked in ITS
  memory, with nothing failing and nothing logged. A save now writes the **difference**
  against the state that process read (`lib/core/entity_sync.py`). The rule that matters is
  about deletions: a row may only be deleted if this process HAD it and no longer does — a row
  that appeared while we were editing belongs to somebody else. The CLI writes the same way.
- Upserts ask whether the row exists instead of trusting the rowcount: MySQL reports 0 rows
  affected for an UPDATE that sets the values a row already has, so "0 means insert it" would
  end in a duplicate key. `upsert`/`delete`/`apply` share the row-level work because the
  connector's `transaction()` is not re-entrant — an inner commit would end the outer one
  early, leaving half a batch written.

- **The freshness probe used the raw table name for a quoted table.** `groups` is a
  reserved word on MySQL 8, where an unquoted `FROM groups` does not raise: it makes the
  probe return "no answer", which the caller correctly reads as "keep what you have" — so on
  that one backend the reload would never fire, silently. The probe now takes the logical
  name (the counter's key) and the SQL identifier separately, because they are not always
  the same string.

### Changed
- **The part every store does the same way is written once** (`lib/db/store_base.py`). Nine
  identical `close()`, seven identical `count()`, three identical audit-column backfills, and
  a byte-identical pair of encrypt/decrypt helpers now live in a thin `BaseStore` plus an
  `EncryptedPayloadMixin`. Nothing about a domain's own table moved there — columns, joins and
  row mapping stay with their store, and forcing seventeen tables through one hierarchy would
  have cost more than the duplication removed. What each of those really was is a *decision*
  ("closing is a no-op because the connector owns the connection lifecycle"), and a decision
  written nine times is one nobody can change.
- **One timestamp format.** `…Z` in the stores and `…+00:00` from `touch_entity` were two
  spellings of the same instant, and for the same second the second sorts *below* the first —
  so ordering by the stored string stopped being ordering by time exactly when two writers
  met. `utc_now_iso()` is now the single source, used by the stores and by the audit stamp.

### Added
- `web_admin|cache_reload_secs` (default 5, admin-only): how long this process may serve
  roles, users and groups from memory before asking. 0 = every request. It only matters when
  something else writes the same database.
- `tests/test_cache_freshness.py` — the two-process scenario with a second store on the same
  database, a revoked permission that must stop being served, and the constraints that are
  easy to lose in a refactor: the hook runs before the handler and not inside the permission
  check, our own write does not trigger a reload, and each table is tracked apart.
- `tests/test_entity_sync.py` — the diff rule stated exhaustively, and the two-writer scenario
  it exists for.
- `tests/test_store_base.py` — the convention, including the two failures behind it: a probe
  given an unquoted reserved name, and the timestamp format that made lexicographic order stop
  matching chronological order.

### Notes
- **Reading straight from the database on every request was measured and rejected**, not
  assumed: over 25 roles, 500 users and 40 groups on local SQLite, the probe costs **0.28 ms**
  and a full reload **10.8 ms** (9.6 of them the users). Both give the *same* freshness — that
  of the start of the request — so it would be 39× the cost for the same answer. The variant
  that would genuinely win is reading **per entity** (that user, their groups, those roles): a
  handful of rows whatever the table size. Its advantage is not freshness but no longer
  scaling with the number of users, and it costs changing the ~38 places that treat those
  collections as whole dicts. A decision about scale, not correctness — see
  `docs/explica-arquitectura.md`.

---

## [0.0.1+build.5] - 2026-07-26

### Added
- **Permissions is now a section of its own, under Access.** Assigning permissions to roles only
  existed inside the role modal: one role at a time, an accordion over 17 groups and 64
  permissions. The question that matters most when handing out access — "does support have
  everything editor has?" — meant opening two modals and remembering the first. The new section
  puts every role on one page, and ships **two layouts side by side** so they can be compared on
  real data before one is kept: a **matrix** (permissions × roles, sticky header and first column,
  built-ins first in descending privilege) for reading *across* roles, and **two panes** (role list
  | that role's permissions, with room for each permission's description) for working *on* one.
  The switcher remembers the choice; a text filter and an "only differences" toggle (hide the
  permissions every role agrees on) apply to both.
- **Copy one role's permissions onto others.** Pick a source (any role — a built-in is what a
  custom one is usually modelled on), the targets among the roles you may edit, and whether to
  **replace** or **add**; each target shows what the copy would change (+n / -n, or "already
  identical") before you commit to it. The result lands in the **draft**, not on the server: the
  copied cells go amber like any hand-made edit, Save sends them and Discard throws them away.
  Reaching for the API here would have been a second way to change permissions — one that skips
  the screen showing what changed.
- **Which roles are columns is a choice.** Twenty-four of them is not a comparison, it is
  horizontal scrolling: you can no longer see the two roles you are contrasting. A picker in the
  header selects them (with a search, show-all / hide-all, and "hide built-in" as a preset), and
  the selection is remembered. It filters the role LIST rather than the columns, so the counters
  and what "only differences" compares follow it — a screen must not call two roles identical
  because the one that disagreed is hidden. A role with unsaved changes is never hidden: losing
  sight of an edit is how it gets discarded by accident.
- **The per-instance permissions are there too** — `module.<id>.<action>`,
  `server.<uid>.<action>`, `cluster.<uid>.<action>`, the ones that narrow a global flag down to
  one module, host or cluster. The matrix gives each its own row (a row is a permission; the
  columns are already spent on roles); the two-pane view draws the role modal's items × actions
  table, from **that same builder**, hooked to the draft. Where the resources come from is the
  registry both layouts share, so a new scoped resource appears in both at once. A built-in role's
  boxes are derived from its global flag. In the matrix each override block folds — closed by
  default, because N modules × 4 actions unfolded buries the catalog rows the layout exists to
  compare — and a search opens them, since a match hidden behind a collapsed caption makes the
  search look like it found nothing.
- Built-in roles appear as **read-only columns**. Their permission sets are the product's
  definition of admin/editor/viewer and the API refuses to change them — they are shown, not
  hidden, because they are the yardstick a custom role is read against.
- `.ss-gridtable` — generic cross-tabulation grid styling (sticky header + sticky first column),
  `.ss-changed` for a value edited but not yet saved, and the full-bleed rules that stop the grid
  fencing itself in against the window edges. Reusable classes, no per-table or per-id rules. The
  section's own chrome is the card + accent + card-header that every list section already uses, so
  it flattens edge-to-edge in a full-bleed pane exactly like Users or Roles beside it.
- `tests/test_core_domain_layout.py` — the layout rule below is now enforced, not just written
  down: no domain mixin may be left in `lib/web_admin/mixins`, a domain `__init__` may not import
  its own mixin, the catalog must still import **without Flask** (the import cycle discovery
  depends on stays open — with a positive control so the check cannot pass vacuously), the built-in
  UUIDs may appear in exactly one file, and each unified rule must have exactly one definition.
- **A build can no longer be opened without a commit** (`tests/test_changelog_frozen.py`). One
  build per commit means at most ONE section may be unpublished at a time; this very release had
  two, because the version was bumped again before the first was committed. The existing version
  guard cannot see it — the number still matches the newest heading — so it is checked directly
  against `HEAD`.

### Changed
- **Permissions is a core domain package now, like every other domain.** `lib/core/__init__.py`
  says a domain bundles its store, its mixin, its routes and its manifest *"instead of spreading
  those across lib/stores, lib/web_admin/mixins and lib/web_admin/routes"* — and permissions was
  the one domain the reorganisation had stopped short of: its 210-line resolution mixin
  (`_get_effective_permissions`, `_get_session_permissions`, `_role_grantable`, the
  per-module/server/cluster checks) still sat in `lib/web_admin/mixins/permissions.py`. The flat
  `lib/core/permissions.py` is now a package: `__init__.py` keeps the catalog and discovery,
  `mixin.py` holds the resolution. `from lib.core.permissions import …` still resolves, so the move
  is invisible to the modules that import the catalog.
- There is **no** permissions store or routes, and that is deliberate: permissions are not
  persisted (the catalog is static; what a role holds is a field of that role), and the catalog
  reaches the client through the dashboard's template context and `GET /api/v1/me`. Said out loud
  in the package docstring so the absence reads as a decision rather than an omission.
- **The role modal's Permissions tab is gone: there is now ONE place permissions are assigned.**
  Two editors over the same field is how one screen silently undoes what the other saved — and the
  modal PUT every checkbox it held, including the ones it had not refreshed. It keeps what it is
  actually about (the role's identity and who holds it) and its General tab links to the section.
  Editing a role no longer sends `permissions` at all; the one case that still does is **clone**,
  where a POST decides the new role's whole set.
- The registry of scoped resources and the items × actions table moved with the editor, from
  `partials/roles/_permissions.html` to `partials/permissions/_resources.html` — the rest of that
  file was the modal's accordion and went with the tab, along with twelve i18n keys that only it
  used.

### Fixed
- **A per-instance permission now dies with the resource it names.** `server.<uid>.edit`,
  `module.<name>.view` and `cluster.<uid>.delete` scope a global flag to one thing, and nothing
  connected the two: deleting a host left its keys in every role's permission list for good. They
  granted nothing — a UUID is never reused — but they piled up unseen, and the new section counts
  them, so a role reported more scoped grants than it had. Removing a host, a module or a cluster
  item now strips its keys, once, from the roles that held them, and audits it
  (`role_permissions_pruned`) because it edits permissions without anyone asking on that screen.
  Module names are the case worth stating: a name CAN come back, so a stale `module.ping.edit`
  would silently apply to whatever is called `ping` next — that is why they are purged rather than
  kept in case it returns. Pruning happens on delete, where exactly what disappeared is known;
  doing it on load would mean deciding what is "unknown" from a store that may simply have failed
  to read. Keys already accumulated in an existing install stay until their resource is deleted
  again.
- **The built-in `viewer` role could not see credentials.** `credentials_view` was granted to
  editor only, which is what the new section made visible. The listing masks every secret and a
  viewer already reached that endpoint through `servers_view` for the host form's credential
  picker, so withholding the flag only hid the tab. `config_view` stays out: configuration fronts
  secrets in more places and does not mask them the same way.
- **"What counts as a permission" had two definitions, written out identically** — once where a
  role is saved (`roles/service.py`) and once where a role's permissions are resolved. A new kind
  of per-instance key would have had to be remembered in both, and the half that was forgotten
  would silently DROP those keys instead of failing. Now `is_valid_perm` / `filter_valid_permissions`
  live with the catalog and both directions call them.
- **The built-in UUIDs sat in the module that never read them.** `BUILTIN_ROLE_UIDS`,
  `BUILTIN_GROUP_UIDS` and `ROLES` lived in the permissions catalog, which does not use a single
  one of them — users, groups, roles, permission resolution, SCIM and the CLI do. They are
  identity, not catalog, and no domain owns them, so they moved to `lib/core/constants.py`, the
  module that exists precisely so everything imports downwards into `lib.core` (putting them in
  `lib.core.roles` instead would have made the catalog import a domain that already imports the
  catalog). Every importer was updated rather than given a re-export: an alias would be the second
  name the move exists to remove.
- **`ROLES` and the keys of `BUILTIN_ROLE_UIDS` were the same four names, written twice.** `ROLES`
  is derived from the map now, so a new built-in role cannot land in one and miss the other. The
  third enumeration — what each built-in role grants — cannot be derived and is checked by a test
  instead: a role with a UID but no grants would resolve to no permissions at all, silently.
- **Two test files carried pasted copies of the UUIDs**, which is the failure mode that makes them
  worth centralising: a hardcoded copy passes its own assertions while the product uses a different
  value. They import them now, and a guard fails on any new literal.
- **The escalation guard had two spellings too.** "A non-admin may only grant permissions they
  hold" existed as a closure inside the roles routes and again as the last line of
  `_role_grantable` — the same predicate, so either could have been tightened without the other.
  It is now `_perms_grantable` in the permissions mixin, and both callers go through it.
- Documentation said each domain declares its permissions in a `permissions.py`; discovery has
  read `manifest.py` for a while. Corrected across the four docs that repeated it.

### Notes
- Saving from the new section sends **only** `permissions`, so a partial PUT leaves a role's name,
  description and `enabled` exactly as they were, and the draft is seeded from the role's full
  permission list so the granular keys the screen never renders (`module.<name>.view` …) survive a
  save. Both are pinned by tests, from the API end and from the screen's end.
- The 30 s Access poll refreshes untouched roles, but only when the roles actually changed, and
  never over an edit in progress. Redrawing regardless rebuilds the DOM under the reader: it threw
  you back to the top of the grid twice a minute. A redraw also restores the scroll position, which
  matters just as much on each keystroke of the filter.

---

## [0.0.1+build.4] - 2026-07-26

### Added
- **A published CHANGELOG section can no longer be edited** (`tests/test_changelog_frozen.py`).
  Each commit's section is supposed to hold only what that commit changed, and nothing enforced
  the second half of it: after committing `build.2` entries kept being appended to it, so the
  section described work the commit does not contain. The version guard cannot see that — the
  number still matches, the order is right, the section is non-empty; only the content lies. The
  rule is now exact: every section present in HEAD's CHANGELOG must be byte-identical in the
  working copy, so a new commit adds its section above and leaves the rest alone. It also catches
  a published section being renamed or deleted, and **skips** rather than guesses when there is no
  git history to compare against.

---

## [0.0.1+build.3] - 2026-07-26

### Fixed
- **Losing the secret key was silent — and it is how you get the "wrong key" above.** The file
  that signs Flask sessions AND derives the Fernet key for every stored secret was written inside
  an `except OSError: pass`. A failure to persist it leaves the process on an in-memory key: the
  next restart generates a different one, every session dies and everything encrypted in the
  meantime becomes undecryptable. It still does not raise — refusing to start is a worse outcome
  than a short-lived key — but it logs the path at ERROR now, and never the key.
- **The other seventeen swallowed exceptions were all legitimate, and now say why.** Reading an
  optional lang file, closing an already-broken socket, a chmod on a filesystem that has none,
  `int()` on a query string: each catches a specific type in a place where the failure IS the
  expected outcome. They keep the behaviour and gain the one line of reasoning they lacked —
  because an unexplained swallow reads like an oversight, and an audit in this very session
  proposed deleting something for exactly that reason. Across `lib/` there is now no
  `except …: pass` without a stated reason.

---

## [0.0.1+build.2] - 2026-07-26

### Fixed
- **A dangling role reference lost its warning marker.** `role_deleted` was one i18n key
  serving two different messages: the `<option>` that flags a role a config still points at
  ("⚠ Deleted role") and the toast shown after deleting one ("Role deleted"). Defined twice
  in the same table, Python kept the second, so the select silently read like a
  confirmation instead of a warning. They are now two keys — `role_deleted_ref` carries the
  ⚠ — and `test_no_key_is_defined_twice` fails on any duplicate, including the three that
  held the *same* value: harmless today, but the next person to edit one has even odds of
  editing the copy that does not win.

### Changed
- **The severity rule has one home.** `norm_severity` (OK → `''`; non-OK defaults to
  `error` unless marked `warning`) existed as two identical copies, in the result structure
  and in the store that persists it — a rule about severity being exactly the wrong thing
  to keep two of: add a third level and one copy goes on flattening it to `error`. The
  store imports it now, and a test asserts both surfaces answer identically for every
  input.
- **`_resolved_item` moved to `ModuleBase`.** Byte-for-byte the same in `datastore`,
  `proxmox` and `web`, and nothing in it is module-specific.
- **Seven validation limits deleted from `web_admin/app.py`.** `_MAX_USERNAME_LEN` and
  friends restated limits the domain services already own and enforce. Six had no reader at
  all; the seventh passed its copy straight back into a parameter that already defaulted to
  the domain's constant — so the web layer's value would have won silently the day the two
  diverged.
- **A failed ENcryption no longer writes the plaintext in silence.** `decrypt_all` and
  `encrypt_sensitive` had the same `except Exception: pass`, but the trade-off is not the
  same: a failed decryption keeps the ciphertext (harmless), a failed encryption keeps the
  **plaintext** — and the caller persists it, which is the one outcome this module exists
  to prevent. It is logged at ERROR now, naming the field so the exposed secret can be
  rotated, and never the value. Not reachable today (every caller guards on the key being
  present), so this is the fallback being wrong rather than a live exposure.
  Separately, a **wrong** key — secret file regenerated, container rebuilt, a restore
  without it — made every secret fail to decrypt with no signal at all: the operator saw
  LDAP binds, SSH checks and API credentials failing one after another with nothing to
  connect them. That now warns once per process (once, because `decrypt_all` runs on every
  read of every store).
- **A documentation link that names a line must point at that line** (`tests/test_docs_line_links.py`,
  6 tests over 73 links). Line anchors are the most useful links in the reference docs and the most
  fragile thing in them: any edit above the target shifts them silently, and nothing noticed. The
  guard found three rotten ones on its first run — a path left behind when the monitor moved
  packages (the line number was still right), an anchor landing on a blank line, and one broken
  minutes earlier by the `secret_manager` fix in this very build. It checks that the file exists,
  the line is inside it, the line is not blank, and that the number written in the link TEXT agrees
  with the one in the anchor — the two are typed by hand, separately, and had already drifted.
- **Four syslog tests could fail under a full parallel run and pass on their own.** The
  harness asked the OS for a free **TCP** port and then bound it for **UDP**: the two port
  spaces are independent, so the number could already be taken. `_free_port()` takes the
  protocol now and probes with the socket type the caller will actually bind — all
  thirteen call sites checked against the port they configure.
- **Two notification stores became one base plus two table declarations.** The webhook and
  Microsoft Teams stores were 135 and 136 lines whose logic was identical — the differences
  were the table name, the prose, and whether a local was called `webhook` or `channel`;
  even their `TableSpec` matched column for column. Both now subclass
  `lib.core.notify.doc_store.JsonDocStore` (uid + JSON `data` + audit columns: list, get,
  count, upsert, delete, and the at-rest encryption), and each file is 48 lines that
  declare a table and nothing else. What the base deliberately does NOT decide is the shape
  of `data` or which of its fields are secret — that is the part that genuinely differs per
  destination.
- **LDAP: ten unexplained `except Exception: pass` down to two, both documented — and one
  of them was hiding a real failure.** Reading an optional attribute off an ldap3 entry
  *raises* when the entry does not carry it, so every read needs a guard; that guard was
  written out eight times. It is now `lib/providers/ldap/entry.py`, where the reasoning
  lives once. The tenth was different in kind: if the secondary group search (the
  `memberUid`/`member`/`uniqueMember` sweep that covers directories without `memberOf`)
  failed, the exception was swallowed with no log at all — and silently that looks exactly
  like "this user belongs to no extra groups", so a directory error could quietly cost
  someone their role. It still does not block the login, but it is logged now, like every
  other failure path in that function already was.
- **Three more rules stopped being stated twice.** `map_role` (OIDC and SAML had it byte
  for byte) went to `lib/providers/role_map.py`; LDAP keeps its own variant on purpose,
  because Active Directory returns full DNs and it also matches a short pattern against the
  first RDN — folding them together would hand OIDC and SAML that DN parsing for an edge
  case nobody asked for, and the file says so. `_read_config_file` (the monitoring, syslog
  and events workers, identical) became `_StandaloneConfigMixin`: *which configuration a
  process actually obeys* is a bad thing to declare three times, since the day one stops
  overlaying env that worker silently ignores every `SS_*` the deployment sets. And
  `_default_text` (three copies across the health evaluators) is now one function in the
  package that owns them.
- **MySQL and PostgreSQL keep their duplicate `execute`/`execute_ddl` on purpose**, and
  `BaseConnector` now says why: their `executemany` already diverges (PostgreSQL uses
  `psycopg2.extras.execute_batch`), so an intermediate class holding two methods while a
  sibling stays overridden would hide the one thing this layer exists to show — where the
  drivers differ. Fourteen duplicated lines is the cheaper half of that trade.
- **`watchfuls/<mod>/watchful.py` is gone (20 files).** A one-line alias re-exporting
  `Watchful` from the package. Nothing imported it: discovery keys off `__init__.py`,
  `schema.json` and `lang/` across six separate sites, and one module (`snmp`) had shipped
  without it for some time. Its stated purpose — "so every module has the same entry-point
  filename" — dated from when modules were single files; every module is a package now, so
  `__init__.py` already is that name. Removed from the eight documents that listed it,
  including two new-module checklists. Side effect: pyflakes over `watchfuls/` drops from
  dozens of warnings to three, and those three are real (an unused import in `datastore`,
  a dead local in `ram_swap`, an unused `pytest` in an m365 test).

---

## [0.0.1+build.1] - 2026-07-26

### Changed
- **One Microsoft API layer instead of two copies.** `m365` and `azure` had each grown their own
  HTTPS transport, their own client-credentials token, their own error extractor, their own date
  parser and their own "run this item once" — around 150 lines of near-identical code, in some
  cases *verbatim*. They now share `lib/providers/entraid/graph_api.py` (`EntraApi`: request,
  token, paging) and `lib/providers/entraid/client.py` (`EntraApiError` + `api_error`), with
  `lib/providers/azure/arm.py` (`ArmApi`) extending it for Azure Resource Manager — the right
  direction, because an ARM token is issued by Entra. It went into `lib/providers/` rather than
  somewhere new because that package's own docstring already says it is kept low **so
  `lib.modules` can use it**; the layer was there, it just was not being used.
  Three things that were never Microsoft-specific went where they belong: `lang_section()` and
  `run_item_once()` to `lib/modules/page_support.py` (any watchful with a `__page__` needs them),
  and byte formatting to `lib/util/tools.py` as `fmt_bytes`/`to_bytes` — which now scale the full
  binary ladder to YB in both directions instead of stopping at TB/PB, so a large figure reads
  `2.0 EB` rather than degenerating into `2048.0 PB`, and a threshold unit a schema might add
  later cannot be silently misread as GB.
  Paging is now one helper for both surfaces (Graph's `@odata.nextLink`, ARM's `nextLink`), where
  Azure used to hand-roll it twice; `api_error` covers all three answer shapes, so an ARM failure
  that only sends a `code` (`AuthorizationFailed` — the app has no RBAC role) no longer arrives
  empty. **The monitor side stays on `urllib`** while the web side keeps `requests`: swapping the
  transport of two working modules would change timeouts, TLS context and proxy behaviour, which
  is a behaviour change wearing a refactor's clothes.

- **The M365 watchful is seven files instead of one** (886 lines), split the same way as azure:
  `checks_storage` / `checks_health` / `checks_identity`, `page.py`, `actions.py`, `_parse.py` for
  the report CSVs, and `__init__.py` as the composition. Not one m365 test needed changing.

- **Azure RBAC moved out of the Entra provisioning module** into `lib/providers/azure/rbac.py`.
  `list_subscriptions` / `assign_subscription_role` are ARM operations against a different
  audience — the code said so in a comment while sitting in the wrong package. Re-exported from
  `provisioning.py`, so nothing that imports them had to change.

- **The Azure watchful is nine files instead of one.** It had grown to 1260 lines and 39 functions
  in a single `__init__.py`: transport, ARM identifier parsing, eight checks, the section page and
  the web actions, all interleaved. Split along the seams that already existed — `_http.py` (the
  three audiences: ARM, Graph, the public feed — nothing there decides anything), `_names.py`
  (resource ids → readable names, groups, types and stable result keys), one `checks_*.py` per
  concern (health/inventory, compute, cost, identity), `page.py` and `actions.py` — and
  `__init__.py` is now the composition: the item loop, the shared token and the `_SERVICES` table.
  **No behaviour change**: same result keys, same severities, same API versions, all 78 module
  tests green. Adding a check is now one line in `_SERVICES` plus a method in the matching file,
  and the API versions live in one place instead of being repeated at each call site. The live
  refresh and the credential test also stopped duplicating their "run this item once" body — they
  differ only in how they present the answer, so they now share `_run_once`.

- **`docs/ref-tests.md` is now guarded like the route index is** (`tests/test_docs_tests_inventory.py`,
  9 tests). Nothing was watching the test inventory, so it rotted: **25 test files were missing from
  it entirely**, 11 of the 49 declared counts were wrong (m365 claimed 26 against 53 real tests), and
  the header was ~500 tests stale. A new test file now fails the build unless it is documented.
  The pre-existing 25 are listed by name in a `PENDING_DOCUMENTATION` set that is **shrink-only** —
  documenting a file without removing its line fails a test, so the list cannot quietly become a
  permanent exemption, which is a disabled test with extra steps. Counts are checked with a
  tolerance rather than for equality: matching exactly would mean reimplementing pytest's
  collection (parametrize alone makes the static count differ), and a guard that must mirror a
  collector is a liability of its own. The headline total is bounded **asymmetrically**, because
  collected can only exceed `def test_` — a symmetric margin sat at 25% of 30% and would have
  failed the build the first time anyone added a parametrize case. Each of the six checks was
  verified to actually fail when its condition is violated.

- **`docs/ref-tests.md` caught up, and its byte-formatting example was wrong.** It documented
  `bytes2human(1024)` → `"1.0 KiB"`; the real answer is `"1.0K"` — wrong suffix and a space that
  does not exist, written from the IEC convention rather than from the code. Nothing could ever
  contradict it, because that function has no callers. The section now covers `fmt_bytes` and
  `to_bytes` too, plus the new shared-Microsoft-layer file, and the header count went from ~3100
  to 3678. Every example in it was executed against the real code before being written down.

### Fixed
- **An alert could be labelled with the wrong thing, and one module alerted not at all.** A
  watchful publishes a result either by letting the monitor notify (`dict_return.set`) or by
  pairing it by hand (`ModuleBase._emit`); nine modules used BOTH — the second for the main path,
  the first for their error branches. Those branches did not pass `name=`, so the monitor fell
  back to resolving the **bound host**, and the same check appeared under two different names
  depending on how it failed ("A example.com" normally, "ns1" when it raised) — eleven call sites,
  every one an error path, i.e. exactly when the notification matters most. Two of them looked
  right at a glance by putting the name in `other_data`, which `get_name()` never reads.
  Separately, `proxmox` suppressed the monitor's notification in its exception branch **and** sent
  none itself: an unhandled error went red in the panel and told nobody. All fixed, guarded by
  `tests/test_watchful_emit_patterns.py`, and the two patterns are now written down with diagrams
  in `docs/ref-watchful-emit.md` — automatic as the default, manual for the two things it cannot
  express.

- **"Still missing Application.Read.All" now says WHY.** The provisioning wizard reported a
  permission as missing for two completely different reasons and printed them identically: the
  resource does not OFFER that role (a mis-typed or withdrawn name — nobody can grant it), or Azure
  REFUSED the assignment (almost always the signed-in account being unable to give admin consent —
  someone who can just repeats the wizard). Graph's own message for the second case was collected
  and thrown away. `ensure_app_permissions` now returns a `reasons` map alongside `missing`, and
  the wizard prints the reason under each failed permission.

- **Azure gained the permission check m365 already had — and it checks the thing that actually
  breaks.** Until now the only way to learn the app held no Reader role was for a check to 403
  hours later. Adding the m365-style button alone would have been *worse than nothing*: that check
  reads the token's `roles` claim, which lists Entra **application permissions**, while access to
  a subscription comes from an ARM **RBAC role assignment** that appears nowhere in it — so it
  would have reported "all permissions granted" while every ARM call 403s. A profile declaring
  `azure_rbac` now also probes ARM for real (acquire an ARM-audience token, read the subscription),
  and the report names the role assignment as its own line with the reason beside it.
  The Fix button moved off the credential toolbar and into that modal, appearing only when
  something is actually missing — the way m365 already worked. Offering "fix" before anything is
  known to be broken invites blind re-runs of a wizard that needs an admin sign-in. The modal also
  draws the role-assignment row in its checklist from the same declaration — spinning like the
  others, which matters because that probe is the SLOWEST part of the check and leaving it out hid
  the wait exactly where it happens. Rows are matched to the answer by a stable `id`, never by the
  display label, and both sides render that label from one i18n key: matching on text would put the
  same string in Python and in JavaScript and break silently the day someone reworded it.
  Everything Azure-specific about that row — which credential field is the target, which role is
  expected, the row id, the probe itself — lives in `lib/providers/azure/rbac.py`; the Entra route
  folds it in through a generic `merge_row` and never learns what was checked. The first cut put
  twenty lines of that in the route, repeating the layering slip this release had already corrected
  once by moving the RBAC assignment out of the Entra provisioning module.

- **A repaired service no longer erases its own incident.** `service_status` can restart a
  service it finds down; when that worked, the cycle was recorded as a plain OK — so the panel and
  the history showed nothing the moment it was fixed, and a service dying every night looked
  perfectly healthy. The repaired cycle is now stored as a **warning** (it is running again, but
  something happened) and a repair that FAILED stays a hard down. The notifications are unchanged:
  the fall is announced, then the outcome, and a successful repair still routes as a recovery —
  the alert reports the news while the record keeps the incident.

- **A soft threshold breach was paging as if the thing were down.** `_emit` — the record-a-result-
  and-notify-once pairing that four watchfuls carried as a byte-identical copy — passed
  `severity='warning'` to the recorded result but **not** to the notification. Since it also passes
  `send_msg=False`, disabling the monitor's own digest path, that explicit send is the *only*
  notification: the UI painted the row amber while the alert went out as a hard `down`. Affected
  every warning-severity result in `azure` (VM stopped, quota near the limit, budget on course to
  blow, credential expiring, resource state Unknown), `m365` (storage thresholds, licences low,
  app secret expiring), `keepalived` and `proxmox`. Found while hoisting the duplicate into
  `ModuleBase`; covered now by `TestModuleBaseEmitCarriesSeverity`, verified to fail without the fix.

---

## [Before per-build versioning]

> Everything older than `build.1`, exactly as it was: accumulated across many commits without
> being separated per commit. Kept **unrewritten** — splitting it after the fact would be
> reconstruction by eye, with a real risk of attributing a change to the wrong commit.

### Added
- **Azure: cost against budgets, actual and forecast.** In Azure the thing that hurts is rarely an
  outage — it is the invoice, and it is the one number the person paying asks about. Azure already
  knew the budget and the spend against it; nothing was reading them. Past the configured share is
  a warning; **over** budget is an error, because that money is already spent. A budget merely
  **forecast** to be exceeded is reported too, whatever the threshold: one that will be blown on
  the 24th is worth knowing on the 10th, which is the entire point of a forecast — and a budget
  with no forecast is absent, not a comfortable zero. A subscription with **no budget at all** is
  reported rather than painted green: nothing is watching the spend, and that is worth saying out
  loud. Reader already covers reading budgets.
- **A module section can group its rows** — by resource group, type, owner, whatever the module
  says is groupable (`section.group_by`). The core offers the selector but never guesses the keys:
  it does not know what a module's measurements mean. Grouping is a **view**, not a filter — a row
  with no value for the key gets its own bucket instead of disappearing, because an inventory that
  hides things is worse than an unsorted one.
- **The Azure inventory now says which VM owns a disk, a NIC or a public IP.** "What exists" is
  half an inventory; the question asked when a machine misbehaves is "what belongs to what". A VM
  names its disks and NICs in its own properties and each NIC names its public IP, so **two list
  calls** map the whole chain — no per-resource lookups, and nothing inferred from naming
  conventions, which lie. Group by owner and a VM appears with everything it consumes. Resources
  that belong to nothing stay unowned, and a failure of that lookup costs the column, not the
  inventory.
- **Azure: CPU and disk saturation per VM, from Azure Monitor.** The failure mode where every
  health check stays green and the machine is unusable anyway. Averaged over a window on purpose —
  one bad minute is not a problem, and a module that pages for it gets muted — and reported as a
  **warning**, because a saturated VM is still serving, slowly. Only **running** VMs are queried: a
  deallocated machine publishes nothing, and asking would turn "switched off" into a spurious "no
  data". A metric the VM does not publish (a machine on unmanaged disks has no IOPS metric) is
  absent rather than a comfortable 0%. One call per VM, so the number is capped — and what the cap
  left out, like what could not be read, is reported on the row instead of passing for coverage.
  **Disk *space* and guest memory are deliberately not here**: Azure does not report them without
  the Monitor Agent, and ServiceSentry already reads those over SSH with its filesystem/RAM modules
  — what it offers instead is IOPS throttling, which is the thing that silently degrades a VM.
- **The VM check now lists the machines instead of one total**, on by default: the power state *of
  each machine* is the point of that check, and VMs are counted in tens where resources run to
  hundreds. It can still be reduced to a single aggregate row.
- **Azure: expiring app credentials, quota headroom and VM power state.** Three checks for the
  things that break an Azure tenant without anything going "down":
  - **App-registration secrets and certificates about to expire** — the most avoidable Azure
    outage there is: everything works until a secret expires, silently, months after whoever
    created it left. That includes **ServiceSentry's own credential**: the wizard registers an app
    whose secret expires too, and nothing else in the product would notice. Reports each
    credential a configurable number of days ahead (warning), or after it has expired (error, not
    a heads-up — whatever used it is already broken). This one is **Graph**, not ARM: its own
    audience and its own permission, `Application.Read.All`, now requested by the wizard — an app
    created before this check exists needs one pass of the wizard's *fix permissions*. Graph's
    paging is followed, because a tenant with more than one page of apps would otherwise get a
    silent slice of the answer.
  - **Subscription quotas** per region (vCPUs, public IPs, disks). Running out breaks nothing that
    is already running — it breaks the next deployment, which is the worst moment to find out.
    Over the configured share of the limit is a warning; **at** the limit it is an error, because
    the next deployment will fail. ARM wants the region's resource-id form in the path, so the
    field has its own picker (`list_region_ids`) and a display name typed by hand is normalised
    rather than 404-ing.
  - **VM power state**, which Resource Health cannot answer: a deallocated VM reports `Unknown`,
    exactly like a resource Azure has no opinion about. One `statusOnly=true` call covers the
    whole subscription. A stopped VM is always a **warning**, never an outage — shutting one down
    is a deliberate act, and paging someone for saving money at night is how a module teaches
    people to ignore it.
- **The Azure module now watches the resources themselves, not just the platform.** Service Health
  answers "is Azure having a bad day"; it says nothing about whether *your* VM, VPN gateway or
  network is up. A new **resource health** check reads Azure's own per-resource view
  (`availabilityStatuses`) — and because that one API answers for **every** resource type, the
  module needs no per-type code and already covers resource types added after it was written. One
  result per unhealthy resource, so each alerts and is silenced on its own, keyed by resource id so
  that state survives a resource joining or leaving the answer. `Unknown` (Azure cannot tell —
  typically a stopped VM) is a **warning**, not an outage; `Unavailable`/`Degraded` are real. A
  filter narrows it by type (`virtualMachines`), resource group (`/rg-prod/`) or name, and a filter
  matching **nothing warns instead of going green** — a green check watching nothing looks like
  cover it is not. It needs no new permission: the Reader role the wizard assigns already covers it.
  Opting into **list every resource** reports one result per resource, healthy ones included, so
  the section becomes the subscription's inventory with each resource's state rather than only
  what is broken — opt-in because on a large subscription that is hundreds of stored results and
  history rows, which is the admin's call to make, not a default. Rows read as facts about a
  resource, not as ARM paths: the **resource group** and a **readable type** ("VPN gateway", not
  `microsoft.network/virtualnetworkgateways` — ARM lower-cases its ids, so the original casing
  cannot be recovered from them), and no resource-id badge, which was a line of path that pushed
  everything worth reading off the row. Types that Resource Health does not report on — alert
  **rules** and the like, which Azure answers `Unknown` for — are left out instead of appearing as
  amber rows about nothing that drag the whole section amber with them; how many were left out is
  reported rather than swallowed.
- **The public-status filter can now pick a region instead of you knowing its name.** It takes a
  service *or* a region, so it stays free text — but it gained the shared field picker
  (`input_action`, the same mechanism `datastore` uses to choose a database), which reads the
  subscription's own regions from `/locations`. Display names ("West Europe"), because that is how
  Azure writes them in the announcements this filter matches against. The public feed needs no
  credentials at all, so an item without them — or with a rejected one — still gets suggestions
  from a shipped list rather than an empty picker.
- **The provisioning wizard now offers the Azure subscriptions instead of asking for a GUID.**
  The role assignment needs a target subscription, but before signing in nobody knows the ids —
  so asking for one up front meant sending the admin to the portal to go and find it, and leaving
  it blank meant the app was created without the access it exists for. The ARM token is already in
  hand at that point, so the wizard uses it: `provisioning.list_subscriptions()` reads the ones
  **that** admin can see (exactly where they might be able to assign a role), the poll answers
  `azure_rbac_pending` instead of giving up, and the wizard shows a **picker** — by name, not by
  id. `POST /api/v1/auth/entraid/provision/assign-role` closes the assignment reusing that token,
  so choosing costs **no second sign-in**, and the chosen id is written into the credential field
  the module named. That pending flow is single-use and expires in 15 min because it holds an ARM
  token. An account that can see no subscription still gets the manual id — a legitimate answer,
  not an error — and the whole step remains skippable, since the app and secret are already usable.
- **The provisioning wizard can now grant Azure access, not just API permissions.** Registering an
  app was never enough for Azure: reading a subscription needs an **RBAC role assignment on that
  subscription**, an ARM operation against a different audience (`management.azure.com`) that an
  Entra app role does not grant — so the wizard left the one step that actually gives access to be
  done by hand. A module declares `azure_rbac: {role, field}` inside `__entraid_provision__` and
  the wizard chains it after the app exists, **without a second sign-in**: the flow adds
  `offline_access`, the refresh token is redeemed for an ARM token (`auth.token_from_refresh`), and
  the role is assigned to the app's service principal — whose object id `provision_entra_app` now
  returns. `field` names the credential field holding the target, because the subscription is the
  user's value, not the schema's; the role is re-read server-side, so the client cannot pick one.
  The step is reported in `fields.azure_rbac` and audited, and is **never fatal**: the app and its
  secret are already usable if it fails. An assignment that already exists counts as success, so
  re-running the wizard is safe. The `azure` module declares it, and its credential gained a
  *provision app* button plus a link to the subscription's Access control blade — because whoever
  runs the wizard must be **Owner** or **User Access Administrator** there; being an Entra admin is
  not enough, and that is the usual cause of a 403 on this step.
- **A watchful module can claim a top-level section of its own (`schema.json` → `__page__`).**
  Sections were the one extensible surface with no discovery: `HOME_PAGES` was a literal tuple, the
  panes were hand-written in `dashboard.html`, the URL→pane map was a literal, and the render wiring
  named three functions by hand. A module now declares `{id, icon, order, render, perm}` and gets
  its URL, its sidebar entry (permission-gated), its pane and its render wiring — the registry was
  the only piece that was not already data-driven. The label is the module's own translated
  `pretty_name`, so no core string names a module; ids are validated and core ids (`/admin`,
  `/overview`, …) cannot be shadowed; a malformed declaration drops that section instead of
  breaking the panel. Data comes in two halves on purpose: `GET /api/v1/modules/page/<module>`
  serves the module's `page_data()` hook from the monitor's **cached** results (instant, costs the
  upstream nothing), and refreshing **live** is a normal watchful action the module serves itself —
  returning the same shape, so the page has one renderer, not two. Documented in
  `docs/explica-descubrimiento.md` §2c.
- **Microsoft 365 gets its section (`/m365`), the first consumer of that mechanism.** It shows
  service health, licences and storage, security (Secure Score, risky users) and app secret/cert
  expiry — grouped by check kind from what the checks already publish, with a *Refresh from
  Microsoft* button that queries Graph on the spot (`page_refresh`, read-only). The renderer ships
  with the module (`watchfuls/m365/web/_ui.html`) and every string comes from its own lang files;
  `lib/web_admin` contains no M365 string.
- **Clearing the fail2ban ban history, in Config → General → Maintenance.** The append-only ban
  trail had no way to be wiped at all. It joins the other data wipes there, contributed as a
  `CONFIG_ACTION` from `lib/services/ipban/manifest.py`, behind a new **`ipban_history_delete`**
  permission — reading an audit trail must not imply being able to erase it. Backed by a new
  `DELETE /api/v1/ipbans/banlog`, which is itself audited. Active bans live in another table and
  keep blocking after the wipe.
- **Filters on every table that had none.** Access (Users, Groups, Roles, Sessions),
  Infrastructure (Servers, Clusters, Credentials) and fail2ban → Banned IPs all gained the strip
  fail2ban's Ban history already had: a header that folds (collapsed by default) with a badge
  counting active filters, plus *Clear filters*. Users filters by name (username *or* display name
  in one box), role and enabled/disabled; Groups by name/description and role; Roles by
  name/description and built-in vs custom; Sessions by user, IP and user agent; Servers by
  name/address/description, kind and status; Clusters by name/description, module and enabled;
  Credentials by name/description/user and type; Banned IPs by IP, level, minimum offenses and
  reason. Support is generic — `createListTable` gained a `filters: {fields, match}` option, so
  any table on the factory opts in with a schema plus one predicate; the hand-written tables
  (Ban history, Banned IPs) use the same `buildFilterBar` component directly. In both cases the
  bar renders *outside* the re-rendered body, so typing in it never loses focus. Filtering down to
  nothing now says so ("No rows match these filters", with the clear button) instead of falling
  back to a table's own empty state, which would claim there are no users while a filter was
  hiding them. Servers also filters by address, cluster and tag, and Clusters by the extra columns
  each module declares through `__cluster_columns__` (keepalived's VIP today) — derived, so no
  module name is hardcoded in the panel. Select choices are rebuilt from live data on every
  reload, in place, so a new host's tag shows up without stealing focus mid-typing.
  (Modules, Services and Status render cards rather than tables, so they keep their own layout.)
- **Audit's filter bar joined the shared component too, so there are no exceptions left.** It was
  the last one hand-written in the panel's markup — it merely borrowed the CSS classes. Two gaps
  kept it out and are now part of `buildFilterBar`: a `datalist` field type (free text with
  autocomplete over the values the log actually holds — the users and IPs seen) and `leadHtml`,
  for controls that are not filters, which is what Audit's *Sort* and *Group by* are. Its fields
  declare their legacy ids, so the code that populates the datalists and restores saved state
  addresses the same elements and did not change. All 14 filter bars now come from one generator.
- **The one-off search boxes became the same filter strip.** Events (Rules and Log) and
  fail2ban → Whitelist each had a lone search input wedged into the card header that matched a
  fixed bag of columns at once. They now use the shared bar with named fields: rules by name,
  source and tag; the log by rule, source, channel and detail; the whitelist by IP/CIDR,
  description and author. This also retires a hack the whitelist needed — its search box was
  destroyed on every keystroke (the whole card was re-rendered) and had to re-focus itself and
  restore the caret; the bar now sits outside the re-rendered body, so there is nothing to
  restore. Searches that live inside modals and side panels (host logs, dropped senders, the
  config field search, the History series list) are unchanged.
- **Configurable browser→server connectivity heartbeat (`web_admin|conn_check_secs`, default 6 s).**
  The web UI pings `/api/v1/health` on this interval (2–120 s) with a short timeout to detect a lost
  connection and raise the "No connection to the server" overlay. Editable in Config → Interface →
  Connection. It is distinct from `services|health_poll_secs` ("Health check interval"), which is the
  *backend* evaluator of monitored-service liveness — a different layer.
- **The standalone Syslog receiver now enforces the internal fail2ban.** A syslog container running
  on its own (Docker, no WebAdmin) previously never dropped jailed IPs or reported offenses — the
  `is_banned`/`on_offense` callbacks were only wired when syslog ran embedded in the web admin.
  `SyslogService` now builds the shared, DB-backed `IpBanManager` on the **main** connector (the
  same `ip_bans` table every replica converges on), so a ban placed by the web container takes
  effect in the standalone receiver, and offenses it detects feed the shared jail. Bans are audited
  and routed through the notification matrix like the web admin. The framework-free construction was
  extracted to `lib/services/ipban/factory.py` (`make_ipban`/`configure_ipban`/`ipban_notify`),
  reused by both the WebAdmin and the receiver (the old `_IpBanMixin` is Flask-coupled). Config
  (`web_admin|ipban_*`, incl. `SS_IPBAN_ENABLED`/`SS_IPBAN_WHITELIST`) is applied on boot and
  reconciled every 15 s so a web-side toggle converges without a restart. (Events stays out: it has
  no network listener and no ban action.)
- **History and Syslog became their own sections, like Overview.** They are no longer sub-tabs
  inside the admin panel: `/history` and `/syslog` are top-level sections with their own URLs,
  declared once in the `HOME_PAGES` registry with a `standalone` spec (pane, render entry point,
  required permission, sidebar icon/label). One generic route factory serves them all, the sidebar
  builds its section buttons from the same data, and each is selectable as a landing page.
  `/history` accepts a shareable deep link (`?module=&key=`), which is what the "see this check's
  history" jump from Infrastructure uses. (Their URLs serve the single SPA shell — see *the whole
  web admin is a single SPA shell* under Changed — so opening one from the panel is a reload-free
  tab switch, not a page load.)
- **Destructive data wipes gathered in Config → General → Maintenance.** *Clear All History*,
  *Clear a Series* and *Clear Syslog Messages* left the toolbars of the very sections they erase —
  pages that stay open all day, one stray click from deleting everything. The Maintenance card has
  no fields of its own and knows nothing about history or syslog: each domain contributes its
  button as a `CONFIG_ACTION` on section `maintenance` (`lib/core/history/manifest.py`,
  `lib/services/syslog/manifest.py`). Two limitations had to go for that to work — generic cards
  now render contributed actions (previously only the bespoke auth renderers did), and a card may
  now exist on actions alone. `CONFIG_ACTIONS` also gained a `perm` key, so a button whose
  permission the user lacks is never drawn (the API still enforces it). Clearing one series is a
  picker modal now, since there is no "current series" outside the History page.
- **Packages can now contribute config-section buttons and their own web UI — no package-specific
  glue left in `web_admin`.** Two self-describing mechanisms (documented as §7b in
  `explica-descubrimiento.md`): (1) `CONFIG_ACTIONS` — a provider/service/module declares its
  buttons as DATA in `<pkg>/config_actions.py` (`section`, `label_key`, `icon`, solid `variant`,
  `order`, the JS `fn` name and a declarative `show_when: {field, not_empty}` gate);
  `discover_config_actions()` scans `lib.providers`/`lib.services`/`lib.core`, `config_layout()`
  attaches them to the matching card, and the generic `_cfgSectionActions()` renders them.
  (2) the existing package **web-assets** discovery (`web/_ui.html` / `_modals.html` /
  `_styles.html`), until now scanned only under `watchfuls/`, now also covers `lib/providers/`
  (referenced as `providers/<name>/…` so a provider can never collide with a watchful of the same
  name, and a package may ship several `*_ui.html`).
  **Migration:** all Entra ID glue moved out of the panel — the OIDC/SAML2/SCIM wizards became
  `lib/providers/entraid/web/{_oidc,_saml,_scim}_ui.html`, the `_entraAppLink` deep-link helper
  moved with them, and the hardcoded Entra buttons in `partials/cfg/auth/_renderers.html` were
  replaced by the generic renderer driven by the provider's `CONFIG_ACTIONS`.
- **Entra ID OIDC client-secret lifecycle: assisted rotation, expiry warning and unattended
  rotation with a margin.** An Entra app secret expires, so three independent, opt-in pieces were
  added. (1) **Assisted rotation** — a *Rotate secret* button on Config → Authentication → OIDC
  runs a device-code sign-in and mints a fresh secret on the EXISTING app registration via Graph
  `addPassword` (new `POST /api/v1/auth/entraid/oidc/secret/device-code` + `…/device-poll`), with
  no re-registration. (2) **Expiry warning** — a new leader-gated background scanner
  (`lib/core/health/secret_scan.py`) emits the routable `secret_expiring` event once per severity
  (expiring → expired), re-arming when the secret is renewed (`oidc|secret_notify_expiry`,
  `oidc|secret_warn_days`, default 30). (3) **Unattended rotation** — with
  `oidc|secret_auto_rotate` on, the scanner mints the replacement once inside the
  `oidc|secret_rotate_days` margin (default 15) by authenticating the app **as itself**
  (client-credentials) and emits `secret_rotated`; if the app may not modify its own registration
  the rotation fails and it degrades to warning only (never silent). Adding a secret does not
  revoke the previous one, so rotation is non-disruptive. New `provisioning.add_app_secret()`
  returns the **expiry Entra actually granted** (the tenant policy may cap the requested lifetime),
  stored in `oidc|secret_expires_at` — an empty value means unknown and disables both checks.
- **Notification recipients: typeahead over users & groups, resolved on send.** The recipient chips
  (Config → Notifications → Email / Microsoft Teams) autocomplete as you type against panel **users**
  and **groups** (new `GET /api/v1/notify/recipients/suggest`, gated by `config_edit`). Picking one
  stores a token — `user:<uid>` (chip: person icon + name) or `group:<uid>` (people icon + name) —
  that a `RecipientResolver` **expands to email(s) at send time**: a user → their current email, a
  group → its enabled members' emails. Built from the shared DB via `router.store('recipients', …)`,
  so it works in both the web-admin test-send and the monitor process. Resolution is against the live
  directory, so a **disabled or deleted** user/group (and a user with no email) is skipped
  automatically — logged and surfaced in the email test result (its chip shows "unknown"). Emails are
  de-duplicated; plain typed addresses still work. Enabled by flagging the field `suggest: 'recipients'`
  in `build_config_schema()` on top of the `multi` chips widget; still stored as a comma-joined string.
- **m365 Overview widgets** (schema `__overview_widget__` + `Watchful.overview_widget`). A module
  can now contribute **several** widgets — `__overview_widget__` accepts a **list** — each with a
  `view`: **`stat`** (a Servers-like stat card: a big count + a coloured badge per state,
  N OK / N Warning / N Error, from a per-state `counts` backend breakdown; auto height, not
  resizable) or **`table`** (a dense listing with a scope selector: all / aggregate / a specific
  check kind). m365 ships both: a stat card fixed to **Service health** (via `scope: "health"`) that
  **clicks through to Microsoft's service-health page** (via `link`; generic
  `_dwIsNavigable`/`_dwNavigate` support for external module-widget links), plus a **table** widget
  with the selector. In the table, rows are always sorted **worst-first** (error → warning → ok), and
  a second **minimum-level** filter (all / ≥ warning / only errors) narrows them down — both applied
  generically to every module table widget. At the **Aggregate** scope a table widget collapses to a
  stat card, so there it behaves like one: **auto (locked) height, not resizable, and the level
  filter is hidden**. The backend `Watchful.overview_widget` returns one entry
  per check KIND (Service health, Licenses, App credentials, Mailboxes, OneDrive, Secure Score, Risky
  users, SharePoint) aggregated across every m365 item — the same data feeds both widgets. Each widget
  is keyed `mw_<module>` (primary) / `mw_<module>_<id>`.
- **Generic Entra ID "check & fix app permissions"** (the Entra provider owns it; modules only
  declare *what* they need). Two credential-editor actions on any credential that declares
  `__entraid_provision__` (m365 is the first):
  - **Check permissions** → `POST /api/v1/auth/entraid/check-permissions`: resolves the required
    application permissions from the module profile, acquires an app-only token and inspects its
    `roles` claim (read-only, no admin), and returns a ✅/❌ report. Backed by the dependency-light
    `lib/providers/entraid/permissions.py` (`token_roles` + `permission_report`). The modal opens
    **immediately** with the required-permission list (known up-front from the action's provision),
    then ticks each ✅/❌ in sequence as the result arrives — no blank wait. When something is
    missing, a **Fix permissions** button appears in the modal footer that launches the fix flow
    (the fix action itself is `toolbar:false` — invokable from the check modal, not shown as its own
    toolbar button). The credential-editor Actions row groups the app-lifecycle buttons together
    (Create app · Open app in Entra ID · Check permissions).
  - **Fix permissions** → the device-code sign-in wizard in a new **ensure** mode: instead of
    creating a new app it grants the MISSING permissions to the **existing** app (by `client_id`) and
    admin-consents them (`provisioning.ensure_app_permissions` → merge `requiredResourceAccess` +
    `appRoleAssignments`), without a new app or a rotated secret, then shows a
    granted/already-present/still-missing report. Idempotent; audited
    (`entra_app_permissions_ensured`/`_failed`).

  The m365 Watchful no longer implements any of this — it only declares its required permissions in
  `__entraid_provision__` and adds the two credential actions. The shared action/link labels live in
  the **core** i18n (`prov_entraid_action_*`), referenced by each action's `label` key, so modules
  don't duplicate them (both the credential editor and item action resolvers honor `action.label`).
- **m365 module — many more Microsoft 365 checks** (beyond SharePoint storage), each an opt-in
  per-item toggle via the same Graph app-only auth: **service health** (`serviceAnnouncement/healthOverviews`
  — degradation warns, interruption is a hard down; optional service filter), **license capacity**
  (`subscribedSkus` — free units below a threshold / exhausted), **app secret/certificate expiry**
  (`applications` — warns N days before this app's own credential expires, avoiding a dead monitor),
  **mailboxes over quota** (reports `getMailboxUsageQuotaStatusMailboxCounts`), **OneDrive tenant
  usage** (reports `getOneDriveUsageStorage`), **Secure Score** (`security/secureScores` — % below a
  minimum) and **risky users** (`identityProtection/riskyUsers`). Each emits under `<item>/<service>`
  so results stay independent. The Entra "Register in Azure" wizard now requests the extra
  application permissions (`ServiceHealth.Read.All`, `Organization.Read.All`, `Application.Read.All`,
  `SecurityEvents.Read.All`, `IdentityRiskyUser.Read.All`) alongside the existing `Sites.Read.All` /
  `Reports.Read.All`. Full en/es i18n and tests for every new check.
- **Clusters list "check" button**: the Infrastructure → Clusters table now has a per-row test
  button (▶, like the Servers list) that runs that multi-bind check once and shows the per-member
  breakdown in the shared results modal (`_clTestRow` → `/api/v1/hosts/test` with an explicit
  single-check payload + `no_ssh`; members resolve from `host_uids`). Gated on edit, mirroring the
  Servers test.
- **Proxmox "Fix permissions" action**: the *Check permissions* modal often showed a missing
  privilege (e.g. `Datastore.Audit (/)`) with no way to fix it. A new `fix_permissions` action
  (button next to *Check permissions*) grants exactly the privileges the item's enabled checks need
  to the identity the credential uses — the token's own user (parsed from `token_id`) plus the token
  itself for a privilege-separated token, or the password user — over SSH (root/sudo), then
  re-verifies over the API and shows the fresh verdict. It reuses a custom role
  (`ServiceSentryMonitor`) and does NOT rotate the token (unlike *Provision token*). The SSH path is
  now a shared `Watchful._provision_ssh` helper (extracted from `provision_token`, keeping the SSRF
  guard in one place). Write action → requires module edit and is audited.
- **Web admin panel** (Flask + Jinja2 + Bootstrap 5) with card views, an advanced configuration
  panel, navigation reorg and a generic table CSS.
- **Host-centric model**: a host registry with per-protocol profiles (SSH/SNMP/DB/HTTP…),
  host-aware execution (local/SSH) and reusable credentials.
- **Watchful modules**, schema-driven and core-agnostic (ping, web, dns, datastore, raid,
  ram_swap, filesystemusage, process, service_status, temperature, snmp, ssl_cert, keepalived
  VIP, Microsoft 365, proxmox…).
- **Notifications**, multi-channel and grouped per cycle (Telegram / Email / Webhook / Microsoft
  Teams) with a central dispatcher; multiple webhooks.
- **Microsoft Teams** notification channel with two destination kinds under one routing column:
  **channels** (multiple Incoming Webhook URLs, own store + CRUD, delivered as Adaptive/Message
  cards; the URL is encrypted at rest) and **direct-to-user** delivery with a selectable
  mechanism — *activity feed* (Graph `TeamsActivity.Send`, provisioned by the same Entra
  "Register in Azure" wizard) or *bot 1:1 chat* (Bot Framework proactive messaging via a public
  `/api/teams/messages` endpoint — optional, gated on PyJWT for Bot Framework JWT validation, and
  documented as requiring a registered Azure Bot + a public endpoint). Recipients are the configured
  UPN/email list and/or panel users. Wired into the routing matrix, per-cycle monitor grouping, and
  event rules. For the activity-feed path, a **"Download Teams app"** button generates the required
  Teams app package (`manifest.json` + icons, zipped; `webApplicationInfo.id` wired to the app
  registration) — pure-stdlib, no image library — so the admin can upload/sideload and install it
  for recipients (Teams requires an installed app to accept `sendActivityNotification`). The
  Teams "Register in Azure" wizard also configures the app's SSO surface (`expose_api`: Application
  ID URI `api://<clientId>` + an `access_as_user` scope + the Teams web/desktop clients
  preauthorized) so the generated Teams app can be **admin-installed** (a unified-store install
  validates SSO and otherwise fails); the personal tab that makes the app installable is included
  in the package.
- **Notification-event discovery** (`lib/core/notify/events.py`): the core now discovers *what*
  can be notified, symmetric to channel discovery. Each domain that publishes notifications
  declares a `notify_events.py` with a `NOTIFY_EVENTS` list (monitoring → `down`/`recovery`/`warn`,
  syslog → `syslog`, events → `event`); `events()` scans `lib.core.*`/`lib.services.*`/`lib.providers.*`
  (same self-describing pattern as `MODULE_PERMISSIONS`/`OVERVIEW_WIDGETS`) and `register_event()`
  adds one manually. `matrix_events()` are the auto-routing kinds (`matrix=True`); a rule-driven
  kind like `event` is a known source with no matrix columns. The config routing-matrix keys
  (`notifications|{channel}_on_{kind}`) are **fully dynamic — a single source of truth**: they are
  NOT declared in `lib/config/spec.py` (that duplicated the registry). A cell is stored in the DB
  `config` table only when the admin ticks it; dispatch reads `notif.get(key, False)`, so absent =
  off. (Generating them into `spec.py` at import was tried and reverted: `spec.py` is foundational,
  so discovering domains at its import time perturbs the other domain-discovery passes.) The
  **routing-matrix UI** is registry-driven at request time: its rows
  (event kinds) and columns (channels) are injected from the backend (`NOTIFY_MATRIX_EVENTS` /
  `NOTIFY_CHANNELS` in `core/_constants.html`) instead of being hardcoded in the renderer, so a new
  source kind or channel appears in the grid with no frontend edit. An event may set `ui=False` to
  stay hidden from the grid (used for the legacy `syslog` kind, which has no active dispatcher).
- **Services now emit their own notification events** (routable rows, opt-in per channel):
  the internal fail2ban emits `ipban_banned` / `ipban_unbanned` (from the ban lifecycle), and
  auth emits `auth_login` / `auth_login_failed` / `auth_account_locked` (from the login flow,
  covering local + LDAP + SSO). Each domain declares its events (`notify_events.py`, or
  `register_event(...)` for auth which lives outside the discovery roots) and dispatches them
  through the router; the matrix keys are dynamic (runtime), so they need no `spec.py` entry and
  default off. They appear as rows in the routing grid automatically.
- **Certificate-expiry notifications**: a background scanner (`lib/core/health/cert_scan.py`)
  periodically checks the certificate of every configured `ssl_cert` check (resolving a bound
  host's address) and emits `cert_expiring` when one is within `certs|warn_days` of expiry —
  **once per severity** (expiring → expired), re-arming when a cert is renewed; leader-gated.
  Configurable via `certs|notify_expiry` (off by default), `certs|warn_days` (21),
  `certs|scan_every_secs` (86400 = daily). Routable as the *Certificate expiring* row.
- **Service-health notifications**: a background evaluator (`lib/core/health/health.py`)
  watches the heartbeat registry and emits `service_down` / `service_up` **once per transition**
  when a background worker (monitor/syslog/events) stops beating (crash/unreachable) or recovers —
  leader-gated so replicas don't double-alert, seeded silently at boot (no startup noise), and a
  clean operator stop is treated as idle (never alerted). Configurable via `services|notify_down`
  (off by default), `services|down_after_secs` (60), `services|health_poll_secs` (30).
- Both the service-health and cert-expiry evaluators live in a new **`lib/core/health`** domain
  (platform self-monitoring — is my own stack alive, are my certs valid — a core concern
  *below* the monitoring service, which monitors external targets). Their config is a dedicated
  **Platform health** card in the General tab, not mixed into the Monitoring service card.
- **Manual-run notification event** (`manual_run`): an on-demand *Run all* / *Run select* from the
  Status tab now routes as its own single event (one routing row, grouped under a *Manual* source),
  separate from the daemon's per-kind `down`/`recovery`/`warn`. The whole batch is forwarded to the
  channels that have `notifications|{channel}_on_manual_run` ticked — regardless of each check's real
  kind (the digest still shows the real states) — so an admin can send interactive runs to a
  dedicated channel (or silence them) without touching the daemon routing. The transient monitor
  built for the run carries a cycle notifier pinned to this event (`MonitorNotifier(route_kind=…)`),
  so *Run all* notifies exactly like the daemon does, just under its own row.
- **SSO / provisioning**: OIDC and SAML2 (assisted Entra ID registration), SCIM 2.0 with
  before/after auditing, LDAP/Active Directory.
- **Internal fail2ban** (service-level IP bans) + an extracted security layer.
- **Self-describing Overview** (per-domain/service widgets) with its own `/overview` page,
  configurable landing and AJAX refresh; an integrated **syslog server** (RFC 3164/5424,
  UDP/TCP/TLS); a **connection-lost overlay**.
- **Management CLI** (users/groups/status/reload) on the same core logic as the web.
- **`ldap|ssl_verify`** (enabled by default) to validate the LDAPS server certificate.
- **Microsoft Teams personal-tab SSO** (`lib/providers/entraid/sso_routes.py`, alongside the
  OIDC/SAML providers): the Teams tab signs in via the Teams JS SDK (`getAuthToken`) instead of a
  redirect (Microsoft's login can't be iframed). `GET /auth/msteams/tab` loads the SDK and posts
  the token to `POST /auth/msteams/sso`, which validates it (PyJWT — JWKS, audience
  `api://<clientId>`, issuer) and establishes a session, mapping the AAD identity to an existing
  user by UPN/email with the same anti-account-takeover guard as OIDC. Enabling `embed_in_teams`
  also sets the session cookie `SameSite=None; Secure` (required for the cross-site iframe). Added
  **PyJWT** as an optional dependency (also used by the bot endpoint).
- **Route path convention + discovered CSRF-exempt list**: documented the convention (internal
  frontend APIs `/api/v1/<domain>/*` with session+CSRF vs external/host-facing
  `/auth/<provider>/*` + `/scim/v2/*`, CSRF-exempt and protocol/token-authenticated). The
  CSRF-exempt prefixes are no longer hardcoded — each route module self-declares them via
  `wa._register_csrf_exempt(...)` in its `register()`, so the set is discovered. Teams external
  endpoints are `/auth/msteams/{tab,sso,messages}`.
- **Configurable iframe allowlist** (`web_admin|frame_ancestors` + `web_admin|embed_in_teams`):
  the panel blocks framing by default (CSP `frame-ancestors 'none'` + `X-Frame-Options: DENY`),
  but an admin can now allow specific origins to embed it — and one toggle adds the Microsoft
  Teams/Outlook/M365 hosts so the **Teams personal tab renders ServiceSentry**. When an allowlist
  is set, `X-Frame-Options` is dropped (it can't express an allowlist), CSP `frame-ancestors`
  governs, and the session cookie switches to `SameSite=None; Secure` (so it survives in a
  cross-site iframe). The core security layer stays provider-agnostic: integration-specific
  embed origins (the Teams hosts) are declared by the provider via `wa._register_embed_origins()`
  and discovered — not hardcoded in `lib/security/headers.py`.
- **`BaseConnector.last_insert_id()`** (portable) + a per-connector `KIND` tag (sqlite/mysql/postgresql).
- **Email → Microsoft 365 "Register in Azure" wizard**: the M365 (Graph) email-notification
  provider now offers the same assisted Device Code Flow as SSO — it reuses the shared generic
  Entra wizard (`showEntraIdProvisionWizard`) to register an app with the `Mail.Send` application
  permission and auto-fill `ms365_tenant_id`/`ms365_client_id`/`ms365_client_secret` (secret
  stored encrypted). No new backend routes — it passes an inline `app_roles: ['Mail.Send']` spec
  to the existing `/api/v1/auth/entraid/provision/*` endpoints. An **"Open in Entra ID"** button
  (shared `_entraAppLink`) opens the registered app in the Azure portal in a new tab.
- **Syslog listener load/concurrency tests** (`TestLoad` in `tests/test_syslog_server.py`): 1000
  simultaneous TCP connections streaming 5000 messages arrive with zero loss/duplication, a
  single connection with 3000 octet-counted frames is fully received, and a UDP burst is
  asserted best-effort (the receiver survives and delivers the bulk).
- **Scheduler lifecycle notifications** (`scheduler_started` / `scheduler_stopped`): starting or
  stopping the background check scheduler now emits a routable notification event (opt-in per
  channel in the matrix, default off), so operators can be alerted when the daemon is turned on/off
  — distinct from the health domain's crash detection, which deliberately ignores a clean start/stop.
- **Editable notification texts (custom text layer over i18n), for every channel and module.**
  The Notifications → Templates editor now covers **all** notification strings, not just email: an
  admin can override any text per language, and the resolution is *custom → i18n default*. Texts are
  discovered as **packages** (`/api/v1/notify/text-packages`): Core themes (**Events / Messages /
  Statuses**), **Email** strings, and **one package per watchful module** (its `messages` section).
  Each entry shows its i18n default as the template; a blank field reverts to i18n. Overrides live in
  `notif_text_overrides` (`{lang: {'core:<key>'|'mod:<mod>:<key>': text}}`), resolved by
  `formatting.notify_text` / `ModuleBase._msg` / `event_title`; email keeps its own `notif_templates`
  store, unified into the same editor. Backend: `lib/core/notify/text_catalog.py`.
  - **Reorderable, named placeholders.** Templates take `{}` (sequential) **and** `{0}`/`{1}`… (by
    index), so a custom text can *reorder* the inserted values. Each message declares a **schema of
    its placeholders** (name per position) — core via `_CORE_VARS` (i18n `notif_var_*`), modules via
    an optional `messages_vars` section in their lang file — surfaced in the editor as clickable tag
    chips (`{0} user · {1} reason · {2} IP`) that insert the placeholder at the cursor. instead of English-only — both the
  **titles** and the framework-generated **bodies/statuses**. A notification has no user context but
  a *system* one, so the title (reusing the SAME i18n keys the routing grid shows, `notif_event_*`,
  so title and grid row can't drift) and the body are translated with the configured notification
  language. Framework event bodies now come from i18n templates with placeholders (`notif_msg_*` /
  `notif_status_*`, filled via `lib.i18n.translate`): login (*admin inició sesión vía LDAP desde …*),
  failed login, IP ban/unban, scheduler start/stop, service down/up and certificate expiring/expired.
  `formatting.event_title(kind, lang)` replaces the old hardcoded English `EVENT_TITLE` map, and the
  login method label (Local / LDAP / SSO …) is now i18n too (`notif_auth_*`).
- **Watchful check messages are localised via each module's own lang file.** New `ModuleBase._msg(key,
  *args)` reads a `messages` section from the module's `lang/<lang>.json` (in the system notification
  language, `en_EN` filling gaps, `{}` placeholders filled positionally) — so a module's digest text
  (e.g. *CPU (srv) uso excesivo 99.8%*) is translated where its labels/hints already live. **All 19
  watchful modules** are converted (cpu, ram_swap, filesystemusage, temperature, ntp, ssl_cert,
  hddtemp, datastore, process, dns, ups, ping, web, raid, service_status, keepalived, snmp, proxmox,
  m365) — each with a `messages` section in its `en_EN`/`es_ES` lang file.
- **Unified language selector** in the config UI: `lang`, `status_lang` and the new `notif_lang`
  fields all render through one template (`_field_render.html`) — each shows the language's native
  name (English / Español…, never the raw `es_ES` code) and, where a blank is allowed, a translated
  **Default** option (`— Default (system language) —` for the notification language). Replaces three
  near-duplicate per-field blocks.
- **Notification language is now a single global setting** (`notifications|lang`) that applies to
  **every** channel (Telegram / Email / Teams / webhooks), moved out of the *Email* provider into a
  **Notification settings** card at the top of the Notifications → Routing tab. A shared
  `formatting.notify_lang(cfg)` resolves it — preferring `notifications|lang`, then the legacy
  `email|lang` (kept for back-compat), then the panel language — and the email channel and the
  Telegram digest/single-event all use it. Existing `email|lang` values keep working via the
  fallback.
- **Telegram messages are now sent as HTML** with a designed layout instead of flat plain text,
  across both paths:
  - *Single-event* alerts: an event-kind **icon + bold title** (e.g. 🔓 *Sign-in*, ⛔ *IP banned*,
    📜 *Certificate expiring*), the target as inline `code`, the body as a **quote block** and a
    dimmed timestamp.
  - *Grouped monitor digest*: **bold section headers** (⚠️ *Issues (n)* / ✅ *Recovered (n)*), and
    each alert rendered as its own **quote-block card** — a bold header (status icon + item) with the
    message on the line below, blank-line-separated for breathing room instead of one crammed run-on
    line per alert — plus a summary line whose status URL is a real clickable `<a>` link.
  HTML is robust — every dynamic field is HTML-escaped (`& < >`), so module text with `_`/`*`/`<>`
  renders safely (the old plain path existed precisely to dodge Markdown breakage). Icons/titles per
  kind live in `lib/core/notify/formatting.py` (`event_icon`/`event_title`).
- **Login notifications now state the auth method** (Local / LDAP / SSO (OIDC/SAML/Entra ID)…):
  `_establish_session` derives it from the user's `auth_source` and includes it in both the alert
  status and message (e.g. *"admin signed in via SSO (OIDC) from 192.168.0.1"*), so an alert says
  *how* the user authenticated, not just that they did.
- **Notification Routing matrix**: rows are now **grouped by their source domain** — a subheader
  (Monitoring / IP ban / Authentication / Platform health / Certificates …) precedes each group so
  it's clear where every event comes from. The `source` is carried from the discovered descriptor to
  the grid (`NOTIFY_MATRIX_EVENTS`), labelled by `notif_source_<domain>`.
- **monitoring notification kinds** (`down`/`recovery`/`warn`) are now declared once in the
  monitoring domain's discovered `notify_events.py` (as `KIND_*` constants) and referenced by the
  emitter (`Monitor._alert_kind`), so the routing registry and the emitter can't drift apart. Removed
  the dead duplicate `KINDS` tuple from `monitor_notifier.py`.
- **Notification Routing matrix**: each channel column header now has a **select-all / deselect-all**
  checkbox that toggles every event row for that channel (tri-state: indeterminate when partial),
  driving the individual cells.
- **Allowed iframe origins** (`web_admin|frame_ancestors`) is now a **removable-chips input** —
  each origin is added on Enter and removed with its ×, instead of one free-text field (reuses the
  existing `multi` field control, like `syslog|allowed_sources`). Stored space-separated as before.
- Reorganization into **`lib/core` (foundational layer) / `lib/services` / `lib/providers`** with
  self-describing modules; thin HTTP routes + a Flask-free service layer per package; unified
  routing (one `routes.py` per domain) and central registration.
- Editable configuration migrated to the database (single read/write flow); registry-driven
  configuration layout.
- Notifications → Providers sub-tab reordered to a fixed sequence: **Event rules → Telegram →
  Email → Webhooks**.
- **Notification routing moved into a core-owned `NotificationRouter`**
  (`lib/core/notify/router.py`), built from an explicit `NotifyContext`
  (`lib/core/notify/context.py`) — DB connector, config reader, cipher, debug/audit sinks,
  public-URL/panel-user callables — so routing is independent of the web admin and Flask. The
  router *owns* every channel store (webhooks + Teams channels + the Teams bot reference store)
  and does the fan-out; each host (web admin, monitor/events/syslog workers) builds one and
  sends through it. `notification_dispatcher.dispatch()` and `MonitorNotifier` are now thin
  entry points that route through the host's router. Removed the per-service channel-store
  wiring and `_load_webhooks`/`_load_msteams`/`_msteams_bot_refs` duplicated on the syslog/events
  services and the embedded context; the standalone monitor now reaches webhook/Teams channels
  too (it previously had no channel stores).
- **Notification channels are now self-registering and own their stores** (`lib/core/notify/registry.py`):
  each channel is a `Channel` descriptor (`send` + grouped-`flush`) declared in its own
  `lib/core/notify/<channel>/channel.py`, which registers itself with the core registry on import.
  The registry **discovers** those `channel.py` modules (no central channel list). The router's
  dispatch and the monitor's per-cycle notifier iterate the registry instead of hard-coding the
  channel list / per-channel `if` blocks and `_flush_*` methods. The `NotificationRouter` is now
  **channel-agnostic**: it names no concrete store — a channel that needs persistence owns its
  store and builds it via `router.store(key, factory)` from the context; the webhook/Teams store
  code lives in each channel package (`webhook/channel.py`, `msteams/channel.py`), not in the
  router. Adding a channel is a new `channel.py` with no change to the router or the monitor.
  Removed the web admin's channel-store aliases and `_load_webhooks`/`_load_msteams`/`_msteams_bot_refs`
  shims; routes and the config bundle reach a channel's store through its `channel.get_store(wa._notify)`.
- **Row-hover highlight on the notification-routing matrix** (Config → Notifications → Routing): the
  event row under the cursor is tinted so the active line stands out. Implemented with Bootstrap
  `table-hover` + a reusable `.ss-hover-rows` utility class (section sub-headers keep their own
  background).

### Fixed
- **The Azure resource inventory silently omitted whole categories.** It was built from
  `availabilityStatuses`, which only answers for the resource types Resource Health has an
  opinion about — so virtual networks, IPSec connections and NSGs could be missing from the
  listing entirely, and the section looked like it held only VMs and storage. The inventory now
  comes from the **resources** API, which lists what actually exists, with health merged on top
  where Azure reports it. A resource Azure reports no health for is listed as such (an em dash,
  not `Unknown` — that is Azure saying it looked and could not tell) and counts as fine, because
  not being covered by Resource Health is not a fault.
- **A module section that declared a live refresh never got its button.** The declaration was
  read from `schema.json` and normalised into the page catalog, but `refresh` was dropped when
  the spec was handed to the browser — and the core's generic renderer offers the button only
  when the spec says the module can fetch live data. So the same declaration produced two
  behaviours: a module shipping its own renderer drew its own button (m365), while one relying
  on the generic renderer silently had none (azure). It travels now, with a test pinning it.
- **A module section's live refresh failed unless the Modules screen had been opened first.**
  Watchful actions were built for the module-config form, which posts the whole (possibly
  unsaved) item — so the browser sent the item it had. A section has no form: it knew only the
  item key and sent whatever the modules config happened to be cached in the page, which is
  nothing until that screen has been visited. The action then ran against an empty item — no
  `cred_uid`, so no credentials, so an authentication failure on a check that works everywhere
  else. The server now fills in whatever the caller did not send from the stored item, with the
  caller's values still winning (a form action is testing exactly what it posted, including a
  field the user cleared).
- **Azure Service Health could never have worked: its query was wrong twice over.** The time
  window was expressed as an OData `$filter=lastUpdateTime ge …`, which ARM rejects with a 400 —
  this API defines `queryStartTime` for exactly that — and its spaces were never percent-encoded,
  so the HTTP client refused the URL outright (*URL can't contain control characters*) before a
  request was ever made. The query is now built with `urlencode` from `queryStartTime`, and a test
  asserts the path carries no whitespace, no `$filter`, and an ISO-8601 start time.

### Changed
- **The docs caught up with the new UI, and the route index is now enforced.** Auditing it turned
  up 11 endpoints missing from their own module header (plus three documented under a placeholder
  name that had drifted from the real parameter) and `/account` absent from the surface index in
  `routes/__init__.py`. All fixed, and `tests/test_routes_documented.py` now fails the build when a
  route is added without documenting it — in its module header, and under some prefix in the index.
  `explica-web-admin.md` gained a *Layout de la UI* section (single SPA shell, the `.ss-vfill` /
  `.ss-vscroll` fill chain, `.ss-main` as the only scroll container, full-bleed, and the shared
  filter bar with its two usage modes), its navigation and Maintenance rows were rewritten for the
  sidebar model, and the permission count went from 63 to 64 across every doc that pinned it.
- **The web-admin partials follow one naming convention.** The tree had drifted into three
  different names for "the section's list" (`clusters/_table`, `sessions/_render`, everyone
  else's `_list`), while `_table` also meant *column state* in `events`/`syslog` — so the same
  name covered two things and the same thing had three names. Now: `_render` is the section
  shell, `_list` its list, `_columns` the hand-built column state, `_modal` the editor, and
  `_<concern>` an extracted concern. `_table` is retired. `ipban/_render.html` (908 lines,
  three sub-sections in one file) was split into `_bans` / `_history` / `_whitelist` behind a
  thin shell — a pure move, no code changed. `account/_modal.html` became `_render.html` (it
  stopped rendering a modal when Account became a page), `status_body.html` gained the `_`
  prefix every other partial has, and the old top `_navbar.html` — dead since the sidebar
  replaced it — was deleted. Documented in `docs/explica-arquitectura.md` (including the
  markup-vs-script split that makes `modals/_user` and `users/_modal` different animals) and
  enforced by `tests/test_wa_partials_convention.py`: names, one shell per folder, no orphan
  partials, no double includes, and a line cap on shells.
- **The boot splash now waits for the landing section's data.** It used to lift as soon as
  `init()` finished, so the first thing you saw was an empty section with a second spinner: init
  activates the landing tab, but the render that fires from `shown.bs.tab` was never awaited (the
  event system discards its return value, and with fade panes the event lands after the CSS
  transition). The section render entry points now publish their promise, and init awaits it as
  its very last step — everything else is already wired, so a slow section only delays the reveal.
  Capped at 8 s, and a sidebar-level fallback releases the splash for any section whose render is
  not tracked, so a stalled or untracked one can never pin it on screen.
- **The boot overlay became a brand splash.** A bare Bootstrap spinner over "Loading…" was all the
  first paint showed. It is now the app lockup — the sidebar's shield inside a ring with a bright
  arc sweeping around it, the ServiceSentry wordmark, and an indeterminate progress sweep (boot has
  no measurable percentage). It sits straight on the dimmed, blurred backdrop instead of in a card,
  and every animation is dropped under `prefers-reduced-motion`.
- **Clearing the event-notification log moved to Config → General → Maintenance.** It was a red
  button in the Events toolbar, a page that stays open all day. It joins the history, syslog and
  audit wipes, contributed declaratively as a `CONFIG_ACTION` from `lib/services/events/manifest.py`
  and gated on `events_notify_delete`. Renamed from the bare "Clear log" — in a card listing four
  different wipes, that said nothing about *which* log.
- **The filter bars set their type a step smaller, with even top/bottom padding.** Labels, inputs
  and buttons inside a filter strip are chrome, not content, so a bar with many fields stays
  compact. The strip also looked top-heavy: Bootstrap's `.form-label` is `inline-block`, so the
  line box around it was sized by the parent's strut (~1.5 × 1rem) rather than the label's own
  line-height, padding a phantom gap above the text that the bottom did not have — as a block it
  hugs its glyphs and both sides match. Its padding moved off the `.py-2`/`.px-3` utilities too,
  since those are `!important` and left no way to tune the rhythm. One rule, all 14 bars.
- **Audit's toolbar was reorganised like every other section.** Its bespoke controls bar mixed
  three unrelated things in one block above the table. Now: the sort/group/filter controls wear the
  shared collapsible filter-strip design (folded by default, with the active-filter badge);
  **Refresh** and **Export** moved into the table's own header, between the accent strip and the
  pagination band, where every other section keeps its tools; and **Delete All Audit Events** left
  the toolbar for Config → General → Maintenance, joining the other data wipes — contributed
  declaratively as a `CONFIG_ACTION` from `lib/core/audit/manifest.py` and gated on `audit_delete`,
  so the panel needs no audit-specific glue. Its label is now self-describing, since in the
  Maintenance card "Delete all events" said nothing about *which* events.
- **The shared filter bar folds away, and starts folded.** The field row (Syslog, fail2ban → Ban
  history) costs a lot of vertical space the table wants, and filtering is occasional — so it is
  now a thin always-visible header ("Filters" + caret) over a collapsible body, collapsed by
  default. The header carries a badge with the number of active filters, so a folded bar is never
  a silent filter, and the state is remembered per bar across renders and reloads. Its spacing
  moved out of the markup into `.ss-filterbar`: standalone it keeps its gap, but inside a
  full-bleed pane it butts straight against the table below, the two reading as one surface
  instead of two floating cards.
- **Events dropped its dismissible intro banner.** "Notify selected channels when matching audit
  or syslog events occur." explained the section on every visit until dismissed, costing a row of
  vertical space above the rules table; the section is self-evident from the rule editor. The
  `event_hint` string and its `ss_ev_hint_dismissed` sessionStorage flag are gone.
- **Every section runs full-bleed, like History.** Infrastructure (Servers, Clusters,
  Credentials), Access (Users, Groups, Roles, Sessions), both Events sub-sections (Rules and Log),
  all three fail2ban sub-sections (Banned IPs, Ban history, Whitelist), Syslog and Audit lost
  their card chrome — no border,
  rounding or shadow — and now span the full width and height available, so the table gets the
  whole area instead of floating inside the content gutters, with its accent strip flush against
  the breadcrumb line. The edge-to-edge margins became a reusable `.ss-fullbleed` utility
  (+ `.ss-fullbleed-top`, which eats the shell's top padding — valid for these panes because the
  sidebar drives their sub-tabs, so `#infraSubTabs`/`#accessSubTabs` are hidden). History now uses
  the same utility instead of its own bespoke margins. Since all seven tables built on
  `createListTable` are full-bleed, flush became the factory's **default** rather than a per-table
  flag; a caller that wants card chrome back passes `cardClass: 'ss-card'`.
- **The sidebar's admin group is now "System" ("Sistema").** "Administration Panel" was long
  enough to wrap in the sidebar. "Settings" was the obvious short form but the group already
  contains a *Configuration* entry, so the two would have read as duplicates.
- **Navigation moved to a collapsible left sidebar.** The top bar of section buttons + the admin
  panel's horizontal tab strip were replaced by a single left sidebar: the sections
  (Overview / History / Syslog) at the top, the admin panel's tabs grouped under a **Settings**
  accordion (whose open/closed state is remembered), and the user block pinned at the bottom
  (account, dark-mode quick toggle, logout). It collapses to an icons-only *mini* mode on desktop
  (state persisted) and to an off-canvas drawer on mobile. The tabs with sub-tabs (Infrastructure,
  Access, Events, fail2ban) expose their sub-tabs as a **hover flyout** to the right (the in-pane
  sub-tab bars are hidden, so the flyout is the single control); exactly one sub-item is
  highlighted, always the one belonging to the section currently loaded, restored deterministically
  on reload from each pane's own saved sub-tab. Dark mode is now a one-click toggle in the user menu.
- **The whole web admin is a single SPA shell — no full-page reload on any navigation.** Previously
  Overview / History / Syslog were served as *standalone pages* that shipped only their own pane, so
  moving between them (or back to the panel) was a full document load. Now every URL — `/admin` and
  every section URL (`/overview`, `/history`, `/syslog`, `/account`) — renders the **same** full
  shell with all panes; the client opens the pane the URL points at (`_sbPaneIdFromPath`) and every
  section switch is a Bootstrap tab change that syncs the URL with `pushState` (Back/Forward and
  reload/deep-link all land on the right pane). The section routes stay for shareable URLs and keep
  their permission gating. This reverses the earlier "each standalone page ships only its own pane"
  optimisation in favour of reload-free navigation (the `standalone` template flag is now always
  empty; the section render runs on its tab's first `shown.bs.tab`).
- **Account settings is its own page (`/account`), not a modal.** Personal preferences (language,
  landing page) and the change-password form moved out of the `accountSettingsModal` into a pane
  (`partials/account/_page.html`) reached from the user menu, opening in place like any section
  (SPA, URL synced to `/account`, no reload; Cancel just goes Back). The dark-mode selector was
  removed from it (the user-menu quick toggle owns that now), so the page saves only lang + landing
  (+ optional password) and the merging preferences endpoint leaves dark mode untouched.
- **Pinned dependency versions for reproducible builds (`requirements.lock`).** Every dependency
  in `requirements.txt` used an open `>=` range and nothing was locked, so each `docker build` /
  `pip install` pulled whatever satisfied the minimum — two builds on different days could ship
  different trees, and a new major (Flask 4, a breaking Werkzeug…) would enter on its own and could
  break the runtime with no repo change (the same class of surprise as the paramiko `.deb` break).
  `requirements.txt` now stays as the intent (ranges) and a new `requirements.lock` carries the
  exact, **tested** versions from the dev venv (the one the 3402-test suite passes on) — 41 pinned
  packages across the full tree, each with **`--hash` digests** so pip verifies integrity in
  `--require-hashes` mode (supply-chain protection). Everything installs from the lock: Docker, the
  `tests` / `db-backends` workflows, and `setup_env.ps1` (so the dev venv matches what deploys, not
  a floating `requirements.txt`); the workflows' pip cache key tracks the lock. Dev tooling is
  layered on top without the lock as a `-c` constraint (a hashed constraints file would force
  `--require-hashes` onto the unhashed dev requirements) — the lock is already installed, so its
  pins hold. Header in both files documents how to regenerate. (`PyJWT` is optional and absent from
  the dev venv, so its lock entry keeps the resolver's version.)
- **Removed the dead `email|notify_on_*` keys (pre-release cleanup).** Superseded by the
  `notifications` routing matrix (`notifications|email_on_*`) and **read by nothing** — they only
  still rendered three no-op switches on the Email card. Dropped the 3 `Cfg` declarations, their
  6 i18n label/hint entries per language, and the doc rows/compat note.
- **`ai-module-guide.md` → `caso-guia-modulo-ia.md`**, bringing the last doc into the naming
  convention (17 inbound references rewritten, including the `watchfuls/*/watchful.py` pointers).
  It stays **deliberately self-contained** rather than deduplicated: its whole purpose is for an
  agent to build a module from that file alone (its frontmatter records the validation), so the
  README now documents it as a conscious exception to the single-source rule — with the caveat
  that changing schema/discovery/guide material means **revalidating it** as well as editing the
  SSOT.
- **One discovery convention for every self-describing feature: `manifest.py` + a single
  scanner.** Each feature used to grow its own near-identical `pkgutil.iter_modules` loop
  importing a differently-named submodule (`permissions.py`, `overview_widget.py`,
  `notify_events.py`, `config_actions.py`, `__init__.py`), so adding a mechanism meant copying a
  scanner and inventing a file name. Now a package declares everything it contributes in its own
  **`manifest.py`**, and the shared `lib/discovery.py` (`scan`/`scan_values`/`scan_flat`) collects
  it. Migrated all five families — `MODULE_PERMISSIONS` (16 packages), `OVERVIEW_WIDGETS` (14),
  `NOTIFY_EVENTS` (6), `CONFIG_ACTIONS` (1) and `EMBEDDED_SERVICE`/`STANDALONE` (4) — and deleted
  the four bespoke scanners. Heavy implementations (a widget's 150-200-line data provider) stay in
  their own module and are imported into the manifest, so it reads as a list of what the package
  offers. Descriptors stay **Python** (not JSON) because they bind live objects — callables like a
  widget's `stat` provider; watchful modules are the opposite case (drop-in plugins with no core
  code) and keep declaring in `schema.json`. Documented as §0 of `explica-descubrimiento.md`.
- **Dropped the legacy `email|lang` fallback (pre-release cleanup).** Since no version has shipped
  there is nothing to migrate, so `notify_lang()` now resolves `notifications|lang` → `web_admin|lang`
  → `''` (the `email|lang` branch is gone). Removed all references — the fallback code + docstrings
  (`formatting.py`, `app.py`, `spec.py` comment), the `test_falls_back_to_legacy_email_lang` test
  (and the precedence test's `email` layer), and the docs (`explica-i18n.md` flow + diagram,
  `explica-notificaciones.md` precedence, `ref-configuracion.md` migration note).
- **i18n sweep: hardcoded user-facing strings routed through i18n** (excluding the standalone
  `overview2.html` dev page). Backend: the four notification channels (`email`/`msteams`/`webhook`/
  `telegram` `notify.py`) now translate their send/test result messages via `translate(lang, key)`
  (lang threaded from `notify_lang(cfg)`, so both the monitor and the "Send test" toast are
  localized); route error bodies use `wa._t(key)` in `modules`, `entraid` (incl. the lone leftover
  **Spanish** literal), `msteams`, email `template_routes`, `hosts` (SSH test), `scim`, `history`,
  `ldap`, plus generic `not_found`/`unauthorized`. Frontend: `msteams_tab.html` (Teams SSO landing),
  the HTML-template editor toolbar/toasts/shortcuts (`_tpl_html.html`), `_utils.html` copy toast,
  `audit/_detail.html` labels, and the group/role name placeholders (`modals/_access.html`) now use
  `t(...)` / `{{ i18n[...] }}`. New keys follow the codebase's per-domain families — channel result
  messages under `email_*` / `webhook_*` / `telegram_*` / `msteams_*` (matching the existing 56
  `msteams_*` / 33 `webhook_*` / … keys), reusing `msteams_url_required` where it already existed;
  the cross-channel recipient chips stay `notif_recipient_*`. en/es parity throughout.
- **i18n: session keys homogenized under `session_*`.** The scattered session labels/messages/actions
  (`active_sessions`, `no_active_sessions`, `sessions_closed`, `current_session`, `revoke_session[_tt]`,
  `revoke_user_sessions`, `confirm_revoke_user_sessions`, `close_all_sessions[_tt]`,
  `confirm_close_all_sessions`) now use the `session_*` prefix (e.g. `session_active`, `session_none`,
  `session_close_all`, `session_revoke_user_confirm`), matching the already-`session_*` audit events.
  The two odd audit events were renamed too (`user_sessions_revoked`→`session_user_revoked`,
  `all_sessions_revoked`→`session_all_revoked`); audit rows written before this show the raw event slug.
  Cross-cutting families left untouched (`col_sessions`, `subtab_sessions`, `overview_sessions`) and the
  `sessions_view`/`sessions_revoke` **permission flags** are unchanged.
- **Notification recipient fields render as removable chips** (Config → Notifications → Email and
  Microsoft Teams). Type an address and press Enter to add it (or paste a comma-separated batch);
  each entry is a chip with an × to remove. Reuses the existing `multi` field widget — just flags
  `email|recipients` / `msteams|recipients` with `multi: true` in `build_config_schema()`; still
  stored as a comma-joined string, so the channels' recipient parsing is unchanged.
- **Auth flow refactor (thin `/login` route + Flask-free resolver, no behaviour change).** The
  `login` route no longer holds the LDAP orchestration: the local-vs-LDAP decision (and the two
  previously-duplicated LDAP branches — known-SSO user vs unknown user) is now one Flask-free
  `_AuthMixin.resolve_login(username, password) -> LoginResult`; the route only maps the result to
  session/audit/flash. The shared post-auth helpers `_establish_session`, `_landing_url` and
  `_auth_method_label` moved from `web_admin/routes/auth.py` onto `_AuthMixin` — so the OIDC/SAML/Teams
  provider routes call `wa._establish_session(...)` / `wa._landing_url(...)` instead of importing them
  from `web_admin.routes.auth` (removes the provider→route layering coupling flagged in the audit). The
  LDAP protocol stays in `providers/ldap`. Verified behaviour-identical: anti-timing/anti-enumeration,
  lockout, LDAP fallback and all SSO paths — 151 auth/LDAP/OIDC/SAML/Teams-SSO/security-regression tests pass.

### Fixed
- **Visiting History no longer breaks the layout of every other section.** The History pane was
  styled through an unqualified `#tab-history` selector, and an id (specificity 1-0-0) outranks
  Bootstrap's `.tab-content > .tab-pane { display: none }` — so once rendered, the (tall) History
  pane stayed displayed *under* whatever section you switched to. Reloading straight onto Syslog,
  Servers, Clusters or Services looked fine (History was still an empty spinner), but opening
  History once and coming back pushed the section far down a page-tall gap and dragged the sticky
  sidebar out of view. The full-bleed `display:flex` is now scoped to `#tab-history.active`; the
  negative full-bleed margins stay unconditional (harmless while hidden).
- **The content column is now the only scroll container.** With the shell fixed at `100vh`, a
  section taller than the viewport (a plain flowing table such as Servers or Services) grew the
  document itself, page-scrolling the whole shell and detaching the sidebar. `.ss-main` scrolls its
  own overflow instead, so the sidebar stays put; sections that fill exactly never trigger it.
- **The public status page counted backwards while the backend was down, and took a minute to
  say so.** Its auto-refresh reset the countdown only once the request *settled* and raised the
  overlay only from the `catch` — but with a proxy in front, a downed backend leaves the request
  hanging until the browser's own (very long) timeout. The 1 s ticker kept subtracting, so the
  page showed "refreshing in **-30s**", and the overlay waited just as long. The countdown now
  tracks what it claims to: it **holds** while a refresh is in flight and restarts only once that
  refresh has actually delivered data — never when one is merely fired — announcing itself as
  "Refreshing…" meanwhile, since sitting at "Refreshing in 0s" for the length of a request reads
  as a stuck page. It is **frozen**
  outright while the overlay is up, since "refreshing in Ns" is a promise the page cannot keep
  with the server gone. A refresh also **aborts after 5 s**, so an unreachable backend is reported
  promptly instead of when the browser gives up, and refuses to stack while one is running; while
  disconnected a quiet 5 s retry takes the countdown's place so the page notices the server
  returning. No heartbeat runs while healthy: the page is public, so the refresh it already makes
  is the only request it needs — the cost is that a disconnect takes up to one
  `web_admin|status_refresh_secs` to notice.
- **Connection-lost detection now works behind a reverse proxy and blocks the whole page.** Three
  problems: (1) with a proxy in front, a downed backend makes the proxy answer **502/503/504** — a
  *resolved* HTTP response, so the fetch wrapper read it as "reachable" and the overlay never fired
  (it only worked on a direct connection, where the fetch rejects). The wrapper and the heartbeat now
  treat 502/503/504 as unreachable (`_connGatewayDown`). (2) Detection was slow/none between the
  60 s reload poll and the keepalive; a dedicated **connectivity heartbeat** (`/api/v1/health`, short
  abort timeout, interval = `web_admin|conn_check_secs`) now flips the overlay within seconds and
  also catches a *hanging* connection. (3) The `#conn-lost-overlay` was nested inside the sticky
  header's stacking context, so it sat **below the sidebar** (still clickable); it now lives at top
  level and covers/blurs the entire page, blocking interaction until the connection returns.
- **Section tables load on access, not from init cache.** In the single SPA shell the panel no longer
  pre-renders section tables at init; each section fetches its data when its tab is opened (Config /
  Modules re-fetch only when they have no unsaved edits). So a section never shows stale rows, and
  opening one with the backend down triggers a failing fetch → the connection-lost overlay. (API GETs
  already send `Cache-Control: no-store`; the client also sets `cache: 'no-store'` on same-origin GETs.)
- **`ConfigControl.is_changed` could miss a real edit (timestamp race).** It compared two
  `datetime.now()` marks (`_update > _load`), so a read-then-modify inside a single clock tick —
  fast code paths, coarse clocks — reported *unchanged* for data that had in fact changed. It
  surfaced as a flaky CI failure (`test_changed_after_read_then_modify`, which passed on Windows
  where file I/O between the two marks let the clock advance, but failed on the faster Linux
  runner). Replaced the timestamp compare with an explicit `_dirty` flag set by the data setter and
  cleared by `read()`/`save()` — exact and platform-independent. (Verified 10/10 deterministic;
  the flag has no production consumers yet, but the API is now correct for them.)
- **Flaky syslog tests: the embedded listener bound real sockets on port 514 during the whole
  test suite.** `test_syslog_service::test_udp_message_is_stored` failed in CI with `TCP 514:
  Permission denied`, but that was the visible tip: the `admin`/`client` fixtures build a full
  `WebAdmin`, whose syslog service **autostarts a real UDP+TCP listener on the privileged default
  port 514** on every instance. Root cause: the harness tried to suppress it with the env var
  `SS_SYSLOG_AUTOSTART=0`, which the embedded boot path does not read — so every test's listener
  competed on 514 with live sockets, making message counts non-deterministic (e.g. `test_stats`
  seeing 5 rows where it seeded 3; the same test failed 2 of 4 identical runs). Fixed by setting
  `syslog: {autostart: False}` as **config** in the `config_dir` fixture (which the boot path does
  honour); syslog stays enabled, the listener simply does not bind. Separately, the three
  service-level tests that exercise UDP now pin `tcp_port: 0`/`tls_port: 0` so their explicit
  listener never touches 514 either. (`test_stats` now passes 5/5, `test_wa_syslog` 18/18 across
  repeated runs — both were non-deterministic before.)
- **`SS_SYSLOG_AUTOSTART` env override was ignored by the embedded syslog boot (product bug).**
  Surfaced by the flakiness above: `EmbeddedSyslog._syslog_autostart()` read the raw config
  section, which applies neither the registry default nor the section's `env=` override, so the
  var never took effect and the listener always bound port 514 — a Docker/env deployment could not
  turn autostart off. `_syslog_cfg()` now overlays the section's `SS_SYSLOG_*` env vars (via
  `overlay_section_env`, the same path `syslog_db`/`monitoring` already use, so it also works in
  the **standalone** receiver, not just the web-embedded one), and autostart reads through it.
  Verified: `SS_SYSLOG_AUTOSTART=0` now binds no listener; two regression tests pin the contract.
- **`SS_*` env overrides were ignored whenever config was CONSUMED outside the web layer (same
  class of bug, generalised).** `ConfigManager.read()` deliberately returns the saved config
  without env (the config UI needs saved-vs-`env-locked` kept separate), and only ad-hoc per-section
  patches applied env. So **`SS_TELEGRAM_TOKEN`/`CHAT_ID` were never applied when actually sending a
  Telegram alert** (web *and* standalone), and `SS_EVENTS_AUTOSTART` was ignored on the embedded
  events boot. Fixed centrally without touching the UI edit path: a new
  `overlay_all_env(cfg)` (`lib/config/manager.py`) applies every section's `env=` vars (except
  `database|*`, owned by bootstrap), applied on the two **consumption** surfaces —
  `NotificationRouter._read_config_file` (dispatch for every host) and the three standalone service
  `_read_config_file` (their whole-config read). The embedded events autostart now overlays its
  section too. `ConfigManager.read`/`WebAdmin._read_config_file`/`_config_section` are left raw so
  the config editor still distinguishes saved from env-locked. Regression tests cover the overlay,
  telegram-via-router, and events autostart.
- **Install aborted on Debian/Ubuntu fetching a dead paramiko `.deb` (affects real installs,
  not just CI).** `dependencies.txt` pinned `python3-paramiko` to a hardcoded pool URL for
  paramiko 2.4.2 (2018); that file is gone from current mirrors, so `wget` returned 404 (exit 8)
  and aborted the install. The pinned version also contradicted `requirements.txt`
  (`paramiko>=3.0`). Now it installs `python3-paramiko` from the distro repo like every other
  dependency (Debian 13 ships paramiko 3.x).
- **CI: install tests aborted on Debian/Ubuntu with `sudo: command not found`.**
  `check_dependencies.sh` called `sudo apt install` unconditionally, but the install-test
  containers run as root with no `sudo` present. It now uses `sudo` only when not already root,
  falls back to running `apt` directly as root, and skips with a clear message when it is neither
  root nor has `sudo` (instead of crashing under `set -e`).
- **CI: three further install-test breakages, surfaced once the `sudo` abort was fixed.**
  (1) The systemd check asserted a `ServiSesentry.timer` that no longer exists — the timer was
  dropped when the monitor became a long-running service; the stale assertion is removed.
  (2) The "monitoring daemon" step ran bare `main.py`, which now starts the **web panel** (the
  default mode) and would hang forever — it runs `main.py --monitor -t 0` (one pass, then exit).
  (3) The web-startup health check used `curl`, installed only on the systemd images, so it would
  fail the Gentoo job — it now probes with `python3` (present on all three images).
  (4) The first-run step asserted `config.json` was created — but no run mode writes it (verified:
  both `--monitor -t 0` and `--web` create only `data.db`). `config.json` is an optional read-only
  bootstrap file, and after the config→DB migration the database is what first run creates; the
  assertion (a leftover from when startup seeded `config.json`, and unmeetable in CI since
  `data/config.json` is gitignored) now checks `data.db` alone.
  (5) The partial-uninstall check asserted `/var/lib` (runtime data + the SQLite DB) was removed,
  but `uninstall.sh` without `-a` deliberately **preserves** it (and `/etc`) so an uninstall can
  never silently destroy the database — the check now asserts that data is kept, matching the
  script's documented safety guarantee.
- **CI: the test workflow installed `pytest-xdist` but ran serially.** Added `-n auto`, so the
  full suite runs in parallel (~13 min) instead of leaving the dependency unused.
- **CI: the Docker workflow warned that its actions target the deprecated Node.js 20.** Bumped the
  four `docker/*` actions to their Node 24 majors — `setup-buildx-action@v4`, `login-action@v4`,
  `metadata-action@v6`, `build-push-action@v7` (all require Actions Runner ≥ v2.327.1, which the
  GitHub-hosted runners satisfy). The workflow's inputs are unchanged.
- **CI: the Docker workflow logged `test is not a valid semver` twice.** The `type=semver` tag
  patterns tried to parse the `test` build tag as a version. They are now gated with
  `enable=${{ startsWith(github.ref, 'refs/tags/v') }}`, so they apply only to real `v*` release
  tags and stay quiet for the `test` tag.
- **The Overview syslog card was slow and then reported a plausible `0`.** It called
  `SyslogStore.stats()`, which computes four separate `GROUP BY` aggregations over the whole
  message table (host, app, severity, facility) — the card displays only the total and the
  severity split, so three quarters of that work fed nothing, slow enough on a large store to
  look like a hung widget. `stats()` now takes `only=(…)` to compute just the requested
  breakdowns (omitted ones come back as empty lists, never missing keys) and the card asks for
  `severity` alone. Its `except` also swallowed every failure into `0` messages — indistinguishable
  from a genuinely empty store; it still keeps the card alive but now logs a warning.
- **Standalone pages loaded nothing but an endless spinner.** Two top-level
  `document.getElementById('btn-tab-status').addEventListener(...)` calls in
  `partials/init/_wiring.html` lacked the optional chaining every other tab hook uses. Once the
  admin tab bar stopped being rendered on `/overview`, `/history` and `/syslog`, that element no
  longer existed, so the access threw **outside** the init `try/catch` and aborted the entire
  script before any renderer ran — the page arrived intact and simply never initialised. A static
  test now fails on any unguarded access to a panel-only element (`btn-tab-*`, `subtab-*`).
- **Two spinners at once while a standalone page loaded, and a navbar that assembled in two
  steps.** Every tab pane ships a spinner placeholder in the markup, and on a standalone page that
  pane is `show active` from the first paint — so it sat under the `#loading` overlay as a second
  spinner, both visible from the very first frame, before any script ran. The pane placeholder is
  now emitted only for the panel (where panes are inactive at load and it is what a tab switch
  shows first), and the overlay is handed over to the section's own skeleton right as the render
  starts. The overlay itself stays on every page: it dims the page to block interaction while
  booting, not merely to spin. Separately, the *Admin* button rendered visible while the section
  buttons waited for `applyRoleRestrictions()` — it now carries an empty `data-nav-perm` and goes
  through the same single reveal.
- **The browser's "leave site?" dialog fired on every navigation away from a standalone page.**
  `_isDirty()` read `!document.getElementById(id)?.classList.contains('d-none')`, which evaluates
  to `true` when the element is missing — and the dirty badges live in the Modules/Config panes,
  which a standalone page does not render. Every section was therefore permanently "unsaved". It
  now treats an absent badge as clean. Latent since the badges had always existed; moving the
  sections out of the panel exposed it. Leaving the panel with genuinely unsaved changes is now
  intercepted too, reusing the in-app Cancel/Discard/**Save** modal — the browser's own dialog
  cannot offer Save, and both Modules and Config are resolved before the page is left.
- **DB portability — cross-engine schema evolution.** `add_column_if_missing`/`_apply_incremental`
  no longer emit a bare `ADD COLUMN … NOT NULL` with no default (fatal on a non-empty table in every
  engine): a `NOT NULL` constraint is only rendered when the column carries a default, otherwise the
  column is added nullable (and a warning is logged). A `unique=True` column is now enforced with a
  follow-up `CREATE UNIQUE INDEX` (`ux_<table>_<col>`) instead of an inline `UNIQUE` clause, which
  MySQL/SQLite reject on `ALTER TABLE ADD COLUMN`.
- **History bucket downsampling was SQLite-only.** The time-bucket aggregation used integer division
  that silently returned floats (or errored) on MySQL/PostgreSQL; it now truncates with
  `CAST(FLOOR((ts - ?) / ?) AS <int>)` in both the SELECT and GROUP BY, so downsampled history graphs
  render identically across engines.
- **`/history/diag` used a SQLite-only path** (`PRAGMA table_info` + a private `_conn()`); it now goes
  through the portable connector API (`list_columns`, `fetchone`, `KIND`), so the diagnostics endpoint
  works on any backend.
- **Field-value picker / discovery modal could show stale results.** Opening a picker or a discovery
  modal for one field while a slow request for a previous one was still in flight let the late response
  overwrite the current modal. Each open now takes a generation token; a response whose token no longer
  matches the active open is dropped (`_fpGen` in the field picker, `_discoverGen` in discovery).
- **Sessions tab exposed revoke controls to view-only users.** The card/table revoke buttons, the bulk
  bar and the "close all" header button are now gated on `sessions_revoke` client-side (`_canRevokeSessions()`),
  matching the server-side check, so a user with only `sessions_view` no longer sees dead buttons.
- **Group→role mapping listed custom roles by UID.** The role dropdown built custom-role options from
  the role UID instead of its name, so a mapping to a custom role couldn't resolve; it now uses `rd.name`
  (built-ins by key, customs by name), matching `_role_name_to_uid`.
- **Field rename/delete left orphaned entries in the multi-select set.** Renaming or deleting a
  collection item didn't update `_modItemSel`, so a stale `parent|key` selection lingered (and a rename
  lost the selection); both now fix up the set.
- **Config tab could open on a hidden tab / servers "migrate" crashed on a memberless cluster.** The
  active-config-tab fallback now snaps to the first available tab when the remembered one is gone, and
  the migrate modal guards `cluster.members` (`|| []`) at both the `.map` and `.length` sites.
- **`_fmtDateTime` returned "Invalid Date" for unparseable values** instead of echoing the original
  string; it now falls back to the raw input.
- **Built-in Editor role now includes `credentials_view` + `credentials_edit`.** The editor could
  configure modules that use reusable credentials but couldn't see or edit the credentials themselves;
  granted via `roles: ('editor',)` on those two flags in `credentials/permissions.py` (add/delete stay
  admin-only).
- **Overview card hover effects broke at the corners.** Both the `.dw-clickable:hover` outline and the
  "pop" glow box-shadow traced a square-ish box (the outline used the default `--bs-border-radius`; the
  glow used `.dw`'s unset radius), while every card rounds with `.rounded-3` (`--bs-border-radius-lg`),
  so the page background showed through at the rounded corners on hover. `.dw` now carries that radius,
  so both effects hug the card corners. Separately, the stat cards' top **accent bar** now rounds its
  own top corners (`border-radius: …-lg …-lg 0 0`, in both `_dwStatCard` and `_dwMwStatCard`) instead
  of relying on the card's `overflow:hidden` clip: Chromium drops that clip at the corner while an
  ancestor is `transform`-scaled (the hover "pop"), so the square accent corner poked past the card's
  rounded corner. (Verified with a headless-Edge screenshot of the exact markup + CSS.)
- **Overview module stat cards pop by a fixed small amount** (a `dw-module` class). A wide card popped
  with the core's proportional `scale(1.04)` ballooned — overflowing the viewport and overlapping its
  neighbours. `_dwOnGridHover` now sets `--dw-pop = 1 + 8px/width` (capped at 1.04), so a wide card
  grows the same ~8px a narrow one does, and points `transform-origin` at the side with room; the
  neighbours also recede (they did already for core cards), so the popped card has space instead of
  overlapping. Verified with a headless-Edge measurement (cols-8 at the left edge: scale 1.0148,
  8px growth, no overlap, on-screen). Plus glow + a crisp outline; only the stat-card view pops
  (tables don't). Compact core stat cards are unchanged.
- **Stylesheet cache-busting.** `web_admin.css` is now linked with a `?v=<mtime>` query, so an edited
  stylesheet always reaches the browser. The dev watcher doesn't restart on `.css`, and the plain URL
  was cacheable, so earlier CSS-only fixes could silently not take effect until a hard refresh.
- **Overview edit-mode toolbar showed a module widget's raw id** (e.g. `mw_m365:0`) instead of its
  title: the label fell back to the widget id because module widgets have no `lkey`; it now uses
  `_dwLabel(def)` (the module's translated `pretty_name`, e.g. "Microsoft 365").
- **Multicheck modules — live per-check checklist + status reasons.** A module whose item runs
  several sub-checks (m365: SharePoint/tenant/health/licenses/secrets/mailbox/OneDrive/Secure
  Score/risky users) can declare them in the schema (`list.__multicheck__` = `[{toggle, suffix}]`).
  The item's **Check** button then opens a checklist modal **immediately**, lists every enabled
  sub-check with a spinner, and runs each on its own request (`test_connection` honours a `_service`
  suffix → runs just that one), ticking each row ✅/⚠️ with its reason as the result arrives — no
  more waiting for the whole batch before anything shows. The **Status** card now also prints each
  non-OK check's message (the reason) under its name, and the m365 checks' failure paths carry a
  friendly name so a failed sub-check shows e.g. "… · OneDrive (tenant)" instead of the raw
  `<item>/onedrive` key. m365's **service health is now one check per service** (`<item>/health/<svc>`):
  with no filter it auto-surfaces just the **affected** services from Microsoft's API (a single
  aggregate OK row when all are healthy); with a `health_services` filter it shows each chosen
  service (OK or not), and that filter is **discoverable** (`list_services` feeds a multi-select
  picker, so you pick services without knowing their names). Each service's raw Microsoft status
  code (`serviceDegradation`, `serviceInterruption`, `investigating`, …) is now shown as a
  **human-readable label with a ✅/⚠️/🔴 icon** (new `health_states` i18n map, read via a generalised
  `ModuleBase._module_lang_section`) — so a degradation reads warning and an interruption reads
  error, in the Status card *and* in Telegram/email notifications. The live checklist expands a
  sub-check that returns several results (like per-service health) into a row each, and the discover
  picker now **opens immediately with a loading state** instead of freezing the button until data
  arrives. The risky-users check no longer 400s (`$top` capped at the API's 500).
- **Test fix**: `test_wa_hosts::TestApiMigrate::test_preview_and_apply` asserted the migrated SNMP
  `community` by reading `/api/v1/modules`, which now masks it (`community` is `secret: true`) — so
  it read `None`. It now verifies the value survived the migration against the decrypted stored
  config (`_load_modules()`).
- **Monitor now prunes orphan check status**: the monitor only ever *set* status keys, never
  removed them, so a deleted item / disabled sub-check left its last status lingering forever (the
  root cause behind the m365 phantom, and stale rows for removed items generally). Each cycle a
  module's result now prunes the keys it no longer covers: a stale **result** key (carrying a
  `status`) is dropped immediately, while a **bookkeeping-only** key (no `status` — e.g. a bare item
  key holding just `fail_count` while results live under `<item>/site`) is kept as long as any
  sub-key of that item is still reported, so an in-flight failure streak survives. Pruning runs only
  when the module ran and returned a result set, so an errored/timed-out module never wipes its
  last-known state. The Status card also stops counting bookkeeping-only entries as checks.
- **m365 showed a phantom extra check per item**: a single item reported two results (e.g.
  `item_1 · Microsoft 365` Error **and** `item_1 · SharePoint` OK). The check emitted a success under
  a per-service key (`<item>/site`, `<item>/tenant`) but a pre-service failure (no creds / auth)
  under the **bare item key** — and the monitor never prunes keys a module stops emitting, so once
  auth started working the old base-key error lingered forever beside the real result. Failures now
  report under the SAME per-service keys, so a later success overwrites them; and the monitor now
  prunes orphan status (below), so any pre-existing base-key result clears on the next cycle.
- **m365 auth error was unreadable**: a failed token request showed only `Auth: HTTP 400: Bad
  Request`, hiding the cause. `_graph_error` only parsed Graph's `{"error": {"message": …}}` shape,
  but the OAuth token endpoint returns `{"error": "invalid_client", "error_description":
  "AADSTS…"}` (with `error` as a string) — so `('invalid_client').get('message')` threw and the real
  reason was dropped. It now handles both shapes, surfacing the AADSTS code (e.g. *AADSTS7000215:
  Invalid client secret provided* → expired/wrong secret; *AADSTS90002* → wrong tenant) so the test
  says exactly what to fix.
- **Servers "test" results**: two probe fixes. (1) Check messages were shown as their raw i18n key
  (`cpu_ok`, `dns_ok`, `ssl_expiring`…) instead of the translated text, because the probe monitor
  (`lib/core/hosts/probe.py`) left `dir_modules=''`, so `ModuleBase._msg` couldn't load each module's
  `lang/<lang>.json` and fell back to the key. The probe now receives `modules_dir` (to resolve the
  message catalogs) and the global config (`notify_cfg`, so messages use the configured notification
  language + admin text overrides), matching how notifications/Status render them. (2) A per-item
  field that inherits a **module-level** setting (e.g. `ssl_cert` *warning_days*, blank → inherit)
  used the hardcoded default (30) in the test instead of the configured module value, because the
  probe passed only the tested collection's items — not the module-level scalar settings. `_run_checks`
  now merges the saved module-level fields so `get_conf()` resolves them.
- **module config UI**: per-item numeric fields that inherit a module-level setting via
  `placeholder_module` now show the inherited value as the placeholder (they were blank). The
  fallback wrongly used `CONFIG_FIELD_DEFAULTS['modules|<field>']`, but that JS constant only holds a
  few `web_admin|*` keys — never module defaults — so it always resolved to `undefined`. Resolution
  now cascades module-level value → live *Configuration → Modules* value → the module's own
  `__module__` schema default (via a shared `_placeholderModuleValue` helper), and a genuine `0` is
  shown (e.g. datastore *Max connections* → `0` = "no limit"; DNS item *Timeout* → the module default).
  The live placeholder refresh (`_refreshConditionalFields`, on item expand) kept the old broken
  logic — it read only `modulesData[mod][field]` and suppressed `0`, so **expanding an item wiped the
  correct placeholder the render had just set**; it now reuses the same `_placeholderModuleValue`
  cascade so the inherited value survives expand.
- **notifications UI**: the routing matrix no longer repeats a section header. Rows are now grouped
  by source so each subheader (Monitoring / IP ban / Authentication / Service control / …) appears
  once with its events contiguous, even when different sources interleave by `order` (previously the
  header re-emitted on every source change, so *Authentication* and *Service control* showed twice).
- **notifications**: starting/stopping **syslog**, the **event processor** or the internal
  **fail2ban** from the Services tab sent no notification (only an audit entry) — only the monitoring
  scheduler did (`scheduler_started`/`scheduler_stopped`). Added generic operator lifecycle events
  `service_started` / `service_stopped` (source *Service control*), dispatched **synchronously at the
  control point** — in each service's embedded `control()` and in `_control_external` (so a split/
  microservices toggle notifies from the operator's instance immediately, instead of waiting for the
  remote worker's reconcile). Monitoring keeps its own scheduler events (`_LIFECYCLE_NOTIFY = False`
  on `EmbeddedMonitor`, no double-fire). New routing-matrix rows (opt-in, default off) + i18n
  (en_EN/es_ES). The `service_down`/`service_up` (platform health) events are unchanged: those are
  crash detection and still ignore a clean operator start/stop.
- **audit**: two audit events showed their raw key instead of a label in the Audit tab —
  `entra_saml2_graph_secret` (SAML2 provisioning creates the Graph client secret) and
  `notif_text_saved` (unified notification-text editor). Both added to the `audit_events` i18n dict
  (en_EN/es_ES, parity kept). Verified no other emitted audit event is missing a translation.
- **uninstall**: `uninstall.sh` no longer destroys runtime data by default. It now removes only the
  program code (`/opt/ServiSesentry`) and **preserves** both the config (`/etc/ServiSesentry`) and the
  runtime data (`/var/lib/ServiSesentry`, which may hold the SQLite database) — `--all` is required to
  remove those too. Previously a plain uninstall silently deleted `/var/lib` (potential DB loss).
- **install**: `check_dependencies.sh` actually installs missing OS packages now. Every `apt`/`wget`
  command was prefixed with `echo` (and the script ran under `bash -x`), so it only *printed* the
  install commands — the dependency check sourced by `install.sh`/`update.sh` was a no-op. Removed the
  `echo`/`-x`, and guarded it to warn-and-skip (not abort under `set -e`) on non-apt systems. (Note:
  `dependencies.txt` remains an incomplete OS-package subset — several runtime deps are pip-only.)
- **notifications**: the notification-text editor's **messages** Core package is no longer empty /
  frozen. The `notif_msg_vars` meta key (a dict of placeholder names) shares the `notif_msg_` prefix
  and was being swept into the package as a bogus entry with a non-string default, which crashed the
  client render when switching to that package. Discovery now keeps only real string entries.
- **monitoring**: a first-seen passing check no longer announces a spurious **recovery**. A
  `recovery` needs a prior problem state, so an OK item observed for the first time (no recorded
  baseline) is not a recovery — this stops a first daemon cycle / manual "Run all" over 100+
  passing checks from blasting 100+ recovery alerts (and a digest email listing them all).
  First-seen DOWN/WARN checks still announce (real problems), and genuine DOWN → UP transitions
  still notify; the working state is still recorded either way.
- **monitoring**: an on-demand **Run all** (Status tab → `POST /api/v1/modules/checks/run`) now
  sends notifications like the background daemon. Its transient monitor got no cycle notifier, so a
  state change detected during a manual run was never routed to Telegram/Email/etc.; it now gets a
  `MonitorNotifier` routed through the host's core notification router. It behaves exactly like a
  daemon cycle — state-change based (the shared `check_state` is the baseline), routed by the
  notifications matrix — so which channels receive what is controlled per-channel there.
- **monitoring**: resource sensors that breach a **soft threshold** now alert as a **warning**
  instead of a **down**. High CPU, RAM/SWAP, filesystem usage, temperature, HDD temperature, a
  near-expiry TLS certificate, a datastore connection-count breach and an NTP offset over the limit
  are all conditions where the host is reachable — they now carry `severity='warning'` so the
  monitor routes them to the `warn` kind. Genuinely hard failures (unreachable host, parse/connect
  error, an **already-expired** certificate) stay `down`. Also threads `severity` through the
  `send_message` bridge (ModuleBase → Monitor) so ad-hoc module alerts (ssl_cert, hddtemp, datastore,
  ntp) route correctly too, not only the reference `dict_return` path. The **Status tab** and the
  **Overview checks widget** now render this: a soft-threshold check shows an **amber "Warning"**
  badge (not red "Error"), a card whose only problems are warnings reads amber, and the Overview
  badge tallies warnings apart from errors (showing both when a module has each). The Overview
  **CHECKS stat card** likewise counts warnings apart from errors — a warning-only state reads amber
  with a "N warning(s)" badge, a mixed state shows both an error and a warning badge. The Overview
  **modules and servers table widgets gain a "Warning" filter** option, and their filter dropdowns
  are now **generated from the descriptor** (`view.filter.options` in each domain's
  `overview_widget.py`) instead of a hardcoded per-widget `<select>` in `_layout.html` — so adding a
  filter option is a backend-only change, and the two per-widget change handlers collapse into one
  generic `_dwSetTableFilter`. The servers `error`/`warning` filters now **exclude hosts in
  maintenance** (maintenance is its own bucket, as in the servers stat), so a maintenance host —
  whose skipped checks read "warning" (pending) — no longer leaks into the warning filter.
- **Overview severity filter with a =/≥ operator + maintenance union**: the modules and servers
  table widgets' error/warning filter is now a **compound control** — a level (Warning/Error) with
  an operator (**exactly `=`** or **that level or higher `≥`**, since error outranks warning), and
  on servers a **"+ maintenance" checkbox** that unions in hosts in maintenance. So "≥ Warning"
  shows warnings *and* errors, "= Warning" only warnings. The compound state is one opaque value
  (`<op>_<level>[+m]`, parsed by `lib/core/overview/filters.py`), so it rides the existing single-
  value filter plumbing; legacy saved filters (`error`/`warn`/`maint`/`errmaint`) map onto it. The
  control (level select + operator + maintenance check) is built from the descriptor
  (`view.filter.kind:'severity'` + `levels`), so a new level stays a backend-only change.
- **monitoring**: scheduler start/stop was **audited twice** (once as the request user `admin`, once
  as `system`) because both the HTTP route and the scheduler wrote a `daemon_started`/`daemon_stopped`
  row. The route-level audit is removed; the scheduler is the single source and writes **one**
  actor-aware row via a new `_audit_auto` — the request user for a manual action, `system` for an
  autostart/background one.
- **events**: the worker *tick* is now serialized (`_event_tick_lock`) so the periodic loop
  and a `run_now` command can't drain the cursor at the same time → no duplicate notifications.
- **syslog**: the listener prunes finished per-connection threads (TCP/TLS) → no unbounded
  memory growth.
- **heartbeat**: can restart after `stop_heartbeat()` (the thread handle is reset and the
  stop event is captured in the loop).
- **ipban**: `web_admin|ipban_enabled` is applied at boot (a persisted "disabled" survives a
  restart); the housekeeping DELETEs (bans/history/offense_counters/offense_log) run inside a
  transaction → deterministic on PostgreSQL/MySQL.
- **ipban**: `parse_manual_ban` rejects a negative duration (previously → a silent permanent ban).
- **MySQL / PostgreSQL portability** (production runs on both, via Docker; only SQLite was
  exercised by the tests, so these were invisible): the raw runtime SQL now quotes
  reserved-word identifiers (dialect-aware `quote_ident`) — the `key` column (check_state,
  history), the `virtual` column (hosts), the `groups` table (groups store) on MySQL, and the
  `user` column (audit) on PostgreSQL (which otherwise errored on INSERT and returned
  `CURRENT_USER` instead of the column). Without this, whole features were broken on the
  production engines: check state (`/status`, overview, monitor change-detection/alerts),
  history, host CRUD, group/role & SSO-group mapping, and the audit log. Verified end-to-end
  against real **MariaDB 11.8** and **PostgreSQL 18** instances (all fixed operations
  round-trip correctly on both).
  Regression guards: `tests/test_db_portability.py` (offline — asserts the raw SQL quotes
  reserved words) and `tests/test_db_portability_live.py` (opt-in — runs the stores against a
  real MySQL/PostgreSQL when `SS_TEST_MYSQL_HOST` / `SS_TEST_PG_HOST` are set, skipped otherwise).
- **history**: dialect-aware string concatenation for the group key (`CONCAT` on MySQL, `||`
  on SQLite/PostgreSQL); `get_stats` extracts JSON fields per engine (no `json_extract` on
  PostgreSQL); the down-sampling query uses `CAST(… AS SIGNED)` on MySQL and aggregates the
  `data` column (`MAX(data)`) so PostgreSQL's strict `GROUP BY` accepts it — previously the
  bare non-grouped `data` errored on PostgreSQL (swallowed → empty chart). The per-field
  aggregate (`min`/`max`/`avg`) is isolated in its own try/except, so a non-numeric field value
  (which makes PostgreSQL's numeric `CAST` raise; SQLite/MySQL degrade to NULL) only drops those
  three keys instead of losing the whole stats result.
- **events**: the MySQL connection reports MATCHED rows from `UPDATE` (`CLIENT.FOUND_ROWS`),
  so the cursor/cooldown upsert (`UPDATE; if rowcount == 0: INSERT`) no longer hits a UNIQUE
  violation when re-writing an unchanged value on MySQL.
- **schema migrations (MySQL)**: table rebuilds are now atomic — MySQL auto-commits DDL, so the
  base create-copy-drop-rename (transactional on SQLite/PostgreSQL) could lose data if it failed
  mid-way; MySQL now swaps the rebuilt table in with a single atomic `RENAME TABLE old→backup,
  new→old` and drops the backup only after the swap. Verified data-preserving on real MariaDB.
- **schema introspection (PostgreSQL)**: `information_schema`/`pg_class` lookups are scoped to
  `current_schema()`, so a same-named table in another schema no longer causes spurious rebuilds
  or column mix-ups in multi-schema deployments.
- **services (manager)**: `commands.enqueue()` returns its own INSERT's id (`last_insert_id`),
  not a race-prone `SELECT MAX`.
- **config**: a change to the `database` section or to `web_admin|host` (bind address) now flags
  a pending restart (previously only port/proxy/`syslog_db` did).
- **security (secrets)**: `restore_sensitive` now recurses into **lists** too (like
  `mask_sensitive`) → a secret nested inside a list of dicts is no longer erased on save.
- **watchfuls**: `datastore` — the SSH tunnel now serves **multiple** connections (InfluxDB 1.x /
  MongoDB over SSH are no longer reported down); integer coercion of thresholds in `web`/`ping`.
- **audit**: editing a user no longer records a spurious role change (compares uid to uid).
- **UI**: bulk enable/disable reflects the real state; on a failed module save `modulesData` is
  re-synced from the server; role reassignments check each result (no misleading "success").
- **config (email)**: the notification **provider** selector now persists — it registered a
  dirty *section* but not the `email|provider` field path, so `saveConfig()` (which sends only
  dirty field paths) never saved it and it reverted to `smtp` on reload. Now uses `updateField`.
- **MySQL**: `READ COMMITTED` so cross-process config changes are visible.
- The daemon no longer leaks a Telegram sender thread on every start/stop cycle.
- Correct *running* state for active-active external services.

### Security
- **SNMP community string is now a secret** (`watchfuls/snmp/schema.json`): marked `secret: true`, so
  it is encrypted at rest and masked in the API like the SNMPv3 auth/priv keys (previously stored in
  clear). Also gated with `show_when: version ∈ {1, 2c}` (it does not apply to SNMPv3).
- **Outgoing webhooks now pass through the SSRF guard** (`lib.security.net_guard.validate_external_url`
  in `webhook/notify._dispatch`) — the only server-side fetcher that previously skipped it. Rejects
  non-HTTP(S) schemes (`file://`, …) and the link-local / cloud-metadata range (169.254.x); private/
  internal endpoints stay allowed (a legitimate webhook target for a monitoring tool). Regression tests
  added (`test_wa_webhook.py::TestWebhookDispatch::test_ssrf_*`).
- **Non-root deployment, per role.** The Docker image now creates a fixed-uid non-root user
  `ssentry` (uid/gid **1000**) owning `/app`, `/etc/ServiSesentry` and `/var/lib/ServiSesentry`, and
  the deployments run each role as the least privilege it can:
  - **Compose** (microservices / traefik / test / ha-test): `web`, `events` and `syslog` run as
    `user: ssentry`; `syslog` gets `sysctls: net.ipv4.ip_unprivileged_port_start=0` so the non-root
    process can bind :514.
  - **Helm**: the `web` and `events` Deployments get a non-root `securityContext`
    (`runAsNonRoot`/`runAsUser: 1000`/`fsGroup: 1000`, `capabilities: drop [ALL]`, seccomp
    `RuntimeDefault`); the `netRaw` capability block was removed from `web.yaml` (web runs no
    in-process checks, `*_EMBEDDED=0`).
  - **Stay root** (documented in-file): the `worker` role and the **monolithic** web container,
    because the `ping` module uses `pythonping` (raw ICMP) which needs `CAP_NET_RAW` as an *ambient*
    capability — not grantable to a non-root process via `cap_add`/K8s `capabilities.add`.
  - **Upgrade note**: existing (root-owned) named volumes must be chowned once to uid 1000
    (`docker run --rm -v <vol>:/d alpine chown -R 1000:1000 /d`); fresh volumes inherit it from the image.
- **LDAPS validates the server certificate** by default (previously `CERT_NONE` → man-in-the-middle
  risk and theft of the bind credentials).
- **LDAPS validates the server certificate** by default (previously `CERT_NONE` → man-in-the-middle
  risk and theft of the bind credentials).
- **`/api/v1/overview/widget/<id>` requires a session** (`@login_required`) — it was previously
  readable anonymously (a session-less request resolved to `viewer` permissions).
- **Privilege escalation** in role assignment: a unified `_role_grantable` guard (a non-admin can
  never assign the built-in admin role, and a *custom* role only if its permissions are a subset
  of their own) on user/group create and update — **including group membership** (`_groups_grantable`),
  so a non-admin can't escalate by adding a user to a group that carries a higher-privilege role
  (e.g. the built-in Administrators group).
- **SSO account takeover**: OIDC/SAML/LDAP no longer convert a **local** account to SSO on a
  username collision (all three login callers reject cleanly — no 500).
- **LDAP group→role mapping is exact** (was a substring match: `Admins` matched `Admins-ReadOnly`);
  a short-name pattern still matches the CN of a full-DN `memberOf` value so Active Directory keeps
  working.
- **`saml2|graph_secret`** is now encrypted at rest and masked to the client (it was sent in cleartext).
- **`POST /api/v1/credentials/test` hardened**: requires a credentials permission
  (`credentials_view/edit/add`) — `servers_edit` was dropped, which let a server editor test a
  stored credential (decrypted secret) against an arbitrary address and exfiltrate it.
- **CSRF**: the `fetch` wrapper no longer attaches the token to protocol-relative URLs (`//host/…`).
- **watchfuls (Windows)**: `service_status`/`dns` quote the argument for `cmd.exe` (prevents
  injection from configuration values).

### Docs
- **Generalised the Entra doc and split out IdP-agnostic SCIM.** `caso-sso-entra.md` →
  `caso-entra-id.md`, broadened from "SSO" to all Entra-specific material (OIDC, SAML2 and the
  Device-Code app-registration wizards for SSO/SCIM/M365-email/Teams). New `caso-scim.md` is the
  single source for **generic SCIM 2.0 provisioning** (IdP-agnostic per RFC 7643/7644): enable +
  token + base URL, JIT-vs-SCIM, configuring Entra/Okta/other IdPs, user/group de-provisioning and
  group soft-delete, badges — pointing to `ref-api.md` (endpoints), `explica-seguridad.md`
  (security) and `caso-entra-id.md` (the Entra auto-registration shortcut). The Entra doc keeps
  only the Entra-specific SCIM registration. All inbound links (docs index/topic map + the 8
  referring docs) rewritten; 0 broken links/anchors verified.
- **Added Mermaid flow/diagram coverage for the requested areas** (all from ground-truth code
  reads): a module **dependency (layer) graph** in `explica-arquitectura.md` (the component,
  start, check-cycle and delivery diagrams already existed); an **authentication flow** section in
  `explica-seguridad.md` (sequence diagrams for local login and SSO OIDC/SAML2/Teams — all
  converging on `_establish_session()` — plus a per-request `_check_session()` flowchart); and an
  **API call flow** section in `ref-api.md` (request-lifecycle sequence with the CSRF/401/403
  branches + a layered call-flow flowchart route→service→store→connector).
- **Added worked examples** alongside the new diagrams: an illustrative `oidc` config block + a
  local-login `curl` in the auth section, and a `PUT /api/v1/config` request/response (200 +
  403-CSRF shapes) in the API section.
- **Removed macOS from the documentation** (not currently supported or tested): platform tables and
  "multiplataforma" claims now read Linux/Windows, macOS-only command rows (`launchctl`,
  `sysctl`/`vm_stat`) and the `darwin` schema examples were dropped across README, `ref-modulos`,
  `explica-arquitectura`, `ref-configuracion`, `ref-schema-json`, `caso-desarrollo`,
  `caso-guia-watchful` and `caso-ssh-hardening` (FreeBSD/BSD kept). The `test_darwin*` rows in
  `ref-tests.md` and the macOS mentions in `ai-module-guide.md` were left untouched — the former
  are real test names (removing them would misrepresent the suite), the latter is exempt from the
  reorg; note the module code still contains `darwin` paths even though macOS is unsupported.
- **Documentation reorganised with a type-prefixed naming convention and a single-source-of-truth
  policy.** Every doc is now prefixed by its type — `ref-` (reference/look-up), `explica-`
  (explanation/how-it-works), `caso-` (case/how-to) — with Spanish stems (e.g. `architecture.md` →
  `explica-arquitectura.md`, `api-reference.md` → `ref-api.md`, `deployment.md` →
  `caso-despliegue.md`; 25 files renamed). `README.md` and `ai-module-guide.md` are exempt. All
  inbound links were rewritten — cross-doc links, the docs index/topic map, and the code-comment
  pointers in `watchfuls/*/watchful.py` and tests — with 0 broken links/anchors verified.
- **Mixed docs split into ref + explica, one SSOT per topic.** New `ref-permisos.md` (the RBAC
  catalog: 63 permission flags, roles, groups, dynamic perms — extracted from web-admin, now the
  single source) and `ref-i18n.md` (tag schemas + `lang/*.json` structure + `_fill` — extracted
  from i18n). The Debug/logging explanation moved out of the config reference into
  `explica-logging.md`. Duplicated topics across docs (concurrency, DB schema/reconcile, service
  topology, REST control-plane, config/env vars, notification grouping, schema.json reference,
  discovery, host model, reverse-proxy) were trimmed to a summary + pointer to their SSOT.
- **Doc/code contradictions reconciled against ground truth.** Permission count corrected 52 → **63**
  (`ref-permisos.md` canonical; the stale table removed from security). Per-module thread pool cap
  documented as `min(len(módulos), 16)` (architecture previously implied unbounded). Action/button
  `variant` examples changed from `outline-*` to solid variants (the actual convention). `info.json`
  `dependencies` documented as **required** (enforced by `test_info_json_has_required_keys`).
  `input_action.result` corrected to `toast|list|field_picker|modal|fields`. The `_DEFAULTS`
  snippet fixed to exclude `__*__` meta-keys (`ModuleBase._schema_defaults`). The misleading global
  "SSH RejectPolicy default" note corrected (only `Exec` uses it; host-aware path defaults to
  `AutoAddPolicy`). Deprecated `@write_required`/`@admin_required` decorators flagged as unused.
- **New reference docs for previously-undocumented areas, all generated from ground-truth code
  reads.** Added `docs/api-reference.md` (complete, authoritative REST inventory: route
  architecture — no blueprints, thin routes + Flask-free service layer —, CSRF/versioning, and
  every endpoint by domain with method/path/permission/purpose + examples), `docs/db-schema.md`
  (the 32 runtime tables with columns/types/indexes, an ER Mermaid diagram, and the
  reconcile/multi-engine portability mechanism), `docs/performance.md` (concurrency model,
  bottlenecks, caches, table row caps, scaling), and `docs/logging.md` (the custom `Debug`
  system + the residual unconfigured stdlib `logging` path). Extended `docs/README.md` with an
  index entry per new doc plus a topic map (documentation-outline → doc).
- **Corrected stale facts across existing docs** found while cross-checking against the code:
  `web-admin.md` REST tables — hosts use the `servers_*` family (not `modules_*`), history
  `test-write`/`diag` require `history_view` (not `history_delete`), Entra ID provisioning
  requires `credentials_add`/`credentials_edit` (not `config_edit`), the IP-ban endpoints use the
  granular `ipban_*` family (not `config_*`), roles/groups paths are `<uid>` (not `<name>`), and
  `/logout` is POST; a pointer to `api-reference.md` as the maintained source was added.
  `configuration.md` — `--verbose`/`SS_VERBOSE` only enables Flask's interactive debugger and does
  NOT change the log level (use `--log-level`). `security.md` — the encrypted-fields table now
  includes `graph_secret`/`idp_cert`/`webhook_url`/`bot_app_password`, and the runtime-transparency
  note reflects that editable config is written encrypted to the DB via `ConfigManager`
  (`_save_config_file` no longer exists on `WebAdmin`). `development.md` — added the missing
  dependencies `jinja2`, `dnspython`, `pysnmp`, `pysmi`, `PyJWT`, and a note that M365/Entra uses
  `requests`+`PyJWT` (not `msal`) and that non-core deps are lazily imported.
- **Doc filenames standardised to kebab-case** (lowercase, hyphen-separated — the URL/slug-friendly
  convention; `README.md` stays the conventional exception). Renamed `ai_module_guide.md` →
  `ai-module-guide.md`, `watchful_guide.md` → `watchful-guide.md`, `web_admin.md` → `web-admin.md`,
  and updated every inbound reference (cross-doc links, the docs index, the root README, and the
  `watchfuls/*/watchful.py` comment pointers). 0 broken links/anchors.
- **Public-API docstrings filled in** for the three lowest-coverage areas surfaced by the audit
  (Google-style, English, no behaviour change): 62 docstrings across `lib/cli` (the `cmd_*` handlers +
  `context` helpers), `lib/db` (backend-specific `describe_table`/`list_indexes`/`vacuum` overrides),
  and `lib/providers` (LDAP/OIDC/SAML `is_available` + route handlers, the full SCIM `ScimService`
  CRUD, and the Entra device-code/SSO/tab handlers). Already-documented symbols were left untouched.
- **`schema.md` — nueva referencia del esquema de base de datos**: además del
  `schema.json` de configuración de módulos, el documento ahora incluye una sección
  «Esquema de base de datos (tablas relacionales)» que cataloga las **32 tablas fijas**
  (16 del núcleo `lib/core/*`, 14 de servicios `lib/services/*`, 2 de syslog) —PK,
  columnas clave, índices, JSON blobs y store de origen, verificadas contra cada
  `TableSpec`— más las tablas dinámicas por módulo (`mod_<módulo>_<name>`) y un diagrama
  ER Mermaid de las relaciones lógicas por `uid`. Documenta el motor conectable
  (SQLite/MySQL/PostgreSQL), la ausencia de FKs físicas y la capa editable en la tabla
  `config`; enlaza a `configuration.md` y `architecture.md`.
- **New test coverage for audit-identified gaps**: `test_ratelimit.py` (the sliding-window rate
  limiter — under/over limit, window slide, per-key isolation, `peek` vs `hit`, reset, GC, with a
  controllable clock) and `test_ha_failover.py` (end-to-end leader-gating: a single-owner service runs
  on exactly one replica, fails over to a standby on lease expiry / clean release, and an active-active
  service runs on every replica).
- **Corrected stale in-code docstrings** surfaced by the code/doc audit (comment-only, no
  behaviour change): the monitoring scheduler docstrings/comments no longer claim a Telegram
  sender thread / `pool_run` is closed on dispose (`monitoring/manager.py` ×4 — notifications are
  synchronous via `MonitorNotifier`); `telegram/notify.py` no longer references a queued Telegram
  client; `events/manager.py` now describes the cursor-based worker instead of a syslog "per-message
  hook"; `hosts/__init__.py` calls `routes` a module (not a package); `entraid/__init__.py` lists the
  real Graph submodules (client/auth/directory/mail/teams/provisioning) instead of a non-existent
  `graph` module; `users/store.py` schema comment fixed (`uid` PK, `username` UNIQUE).
- **`notifications.md` rewritten** to match the current delivery layer end-to-end: the
  `NotifyContext` → `NotificationRouter` → channel-registry / event-registry architecture (Flask-
  and web_admin-independent); the self-registering `Channel(send, flush)` model and the discovered
  `NOTIFY_EVENTS` kinds with `matrix`/`ui` flags; the dynamic routing matrix; the grouped-per-cycle
  `MonitorNotifier`; the WARNING severity; per-channel specifics (Telegram now **HTML**, not
  plain/Markdown; Email SMTP/M365/Gmail; Webhook HMAC; Microsoft Teams); and a detailed **notification-
  text system** section — the custom→i18n resolution layer (`formatting.py`), how the editable
  listings are generated (`text_catalog.py` packages), the **tag schemas** (`notif_msg_vars` /
  `notif_email_vars` / `messages_vars`), and the editor UI + endpoints. Removed the obsolete
  "central dispatcher / plain-text Telegram / queued-thread" descriptions.
- `discovery.md`: added the two new self-describing systems — the **notification-channel registry**
  (`register_channel`/`Channel`, discovered from `lib/core/notify/<name>/channel.py`) and the
  **notification-event registry** (`NOTIFY_EVENTS` in each domain's `notify_events.py`) — with their
  flow diagrams and two rows in the "how to add each thing" summary.
- `architecture.md` synced with the `lib/core/notify` reorg: rewrote the `core/notify/` directory
  tree (context/router/registry/events/monitor_notifier/formatting/text_catalog + per-channel
  `channel.py`, incl. the whole `msteams/` package; `notification_dispatcher.py` marked a legacy
  shim), added `lib/core/health/` (platform self-monitoring → `service_down/up`, `cert_expiring`),
  corrected the concurrency model (synchronous flush, no Telegram queue/thread), the component and
  check-cycle diagrams (accumulate-then-flush, multichannel), and the `lib/__init__` export note.
- `README.md` (docs index): the notifications/i18n rows and the overview now name the router/registry
  architecture, all four channels (incl. Microsoft Teams), the WARNING severity and the notification-
  text/tags system.
- Fixed stale cross-doc anchors surfaced during the sync (control-plane / high-availability links
  now point to `services.md`; the notifications-matrix and permissions anchors).
- `i18n.md` synced with the notification-text code: reframed the two-layer architecture to add the
  third concern (notification texts, reusing both layers); documented the module file's new
  `messages` / `messages_vars` keys; catalogued the core notification key families
  (`notif_event_*` / `notif_msg_*` / `notif_status_*` / `notif_auth_*` / `notif_source_*` and the
  `notif_tpl_*` editor keys); documented the `email_tpl` overlay flow (`_DEFAULT_STRINGS` base +
  per-language overlay + admin overrides); documented the three tag schemas (`notif_msg_vars`,
  `notif_email_vars`, `messages_vars`); `ModuleBase._msg()` precedence; admin overrides
  (`core:` / `mod:` scoped keys); and indexed `{0}`/`{1}` placeholders for reordering. Editor
  detail links to `notifications.md`.
- `configuration.md` synced with the notifications code: the `notifications` routing matrix is
  now documented as **dynamic** (keys generated from the discovered notify-event registry, not a
  fixed 4×4 table), with the real `matrix=True` kinds and their sources, `syslog` flagged as
  compat-only (`ui=False`, no active dispatcher) and `event` as non-matrix; new global
  `notifications.lang`; removed the obsolete `email.lang` (migration note) and `msteams.app_id`;
  webhooks relocated from `config.json` to their own DB table (`FILE_ONLY_SECTIONS` = `database`
  only); rewrote the Telegram section (synchronous HTML send, `(ok, status_code, info)` — no
  background queue, no `-1/-2/-3` codes); documented the `notif_text_overrides` / `notif_templates`
  / `notif_html_templates` feature-data stores. Deep detail links to `notifications.md`.
- Documentation aligned with the routing refactor (architecture, web_admin, cli, services,
  discovery, security, SSO); a note that the `/scim/v2/*` routes are an IETF standard and can't
  be renamed.
- Documented the multi-engine DB portability: `architecture.md` (connector layer — `quote_ident`,
  `KIND`, atomic MySQL rebuild), `configuration.md` (`ldap.ssl_verify`; exact LDAP group→role
  matching), and `tests.md` (§81 — the security-regression and offline/live DB-portability tests,
  with the `SS_TEST_MYSQL_*` / `SS_TEST_PG_*` env vars — auto-loaded suite-wide from a
  gitignored `src/tests/.env.test` by `src/conftest.py` — to run against real
  MySQL/PostgreSQL; the live harness self-skips under `-n auto` and must run with `-n0`).
- Documented the syslog receiver's measured resource footprint under load (`tests.md` §49) and
  a sizing rule of thumb — thread-per-connection, ≈47 KB RAM per live TCP/TLS connection — with
  deployment guidance in `docker.md` (isolate the `syslog` container / set `mem_limit` for very
  high persistent-connection counts) and a pointer from `deployment.md`.
- `web-admin.md` synced with the notifications UI/endpoints: documented the Notifications config
  tab's four sub-tabs (General / Routing / Providers / Templates) and the General sub-tab's global
  `notif_lang`; added the unified "Notification Texts" editor and the `text-packages`
  GET/PUT endpoints (Core/Email/per-module discovery; legacy `templates/<lang>` PUT no longer
  invoked by the UI); added the Microsoft Teams channel endpoints (channel CRUD + channel/user
  test + app-package); corrected the built-in/preview HTML-template endpoints to `config_view`;
  added the `notif_text_saved` audit event and the `summary` HTML-type "preview-only" caveat.
  Deep detail links to `notifications.md`.
- `modules.md`, `watchful-guide.md` and `services.md` synced with the WARNING severity, the
  `_msg()` + `messages`/`messages_vars` module-i18n helper, and the monitor's grouped-per-cycle
  notification. `modules.md`: `ReturnModuleCheck` now documents `severity`/`name` and multi-channel
  plain-text delivery (the OK/DOWN model is no longer binary), plus a per-module note on the 11
  soft-threshold modules that emit `warning` (`ssl_cert`: near-expiry = `warn`, expired/handshake
  failure = `down`). `watchful-guide.md`: fixed the `send_message(self, message, status=None,
  item='', severity='')` signature (three kinds recovery/down/warn), added a `_msg(key, *args)`
  subsection (admin override → module `messages` → key; positional `{}` + indexed `{0}`/`{1}`),
  replaced the hardcoded inline-Markdown messages in the minimal template and the tcp_check example
  with `self._msg(...)` + `messages`/`messages_vars`, added those two keys to the lang-file table,
  and added checklist steps. `services.md`: the monitoring row/notes now describe `MonitorNotifier`
  grouped-per-cycle multichannel dispatch (one synchronous flush, no background thread), the `warn`
  severity and the `manual_run` kind. Canonical detail links to `notifications.md`.
- **`modules.md` aligned with the host-aware system-module model** (no `psutil` in the check): the
  system modules (`cpu`, `ram_swap`, `temperature`, `filesystemusage`, `process`, `service_status`,
  `raid`) run OS commands via `ModuleBase.host_exec` local/SSH on the bound host — `psutil` is used
  only in local `discover()`. Corrected each module's flow and platform: `cpu` (`_cpu_cmd`:
  `/proc/stat`/`kern.cp_time`/`top`/`wmic`), `ram_swap` (`_MEM_CMDS`; emits `<key>_ram`/`<key>_swap`,
  added the `list`/host example), `temperature` (**Linux-only** `/sys/class/thermal` via `grep`),
  `filesystemusage` (`df -P -k`/`wmic logicaldisk`) and `process` (`ps`/`tasklist`). `service_status`:
  the check **always** uses `systemctl is-active` on Linux (init detection is `discover()`-only),
  documented auto-remediation and the SSH/host-aware mode. `ssl_cert`: parsed with the `cryptography`
  library (`x509.load_der_x509_certificate`), documented the dependency and the OK/warn/down states
  (expired or handshake failure = `down`). `web`: example updated to the host-centric
  `scheme`/`server`/`port`/`path` schema (`url` is compat). Added a cross-cutting note on host-aware
  system modules, and per-module `severity='warning'` (amber) on soft-threshold breaches. Fixed the
  "via psutil" description in `cpu`/`filesystemusage`/`process` `info.json`.
- **`troubleshooting.md` — nuevo registro de bugs resueltos y trampas conocidas**: documenta
  fallos no evidentes con su causa raíz, solución y lección generalizable (formato de fichas:
  Síntoma / Diagnóstico / Causa raíz / Solución / Lección), separado del changelog. Primera
  entrada: el placeholder heredado (`placeholder_module`) que el render fijaba bien pero
  `_refreshConditionalFields` borraba al expandir el item por usar lógica divergente. Añadido al
  índice de `docs/README.md`.

### Notes
- **Deferred by decision**: `fail2ban` (IP bans) and `events` stay as tabs inside the admin panel
  for now. Both are operational surfaces that would fit the standalone-page treatment Overview,
  History and Syslog now get — the `HOME_PAGES` registry takes them without new machinery (a
  `standalone` spec plus their existing render entry point), so this is a decision, not a
  limitation.
- **`/overview2`**: an internal proof-of-concept to evaluate **Alpine.js** against the current
  Overview (same widgets/API/design; edit mode persisted to the account; a route-scoped CSP with
  `'unsafe-eval'`). Not a product feature — parked.
- **Accepted risk**: `POST /api/v1/hosts/test_ssh` lets a `servers_edit` holder test a stored
  credential against an arbitrary address (exfiltration/SSRF); hardening it would break the
  editor's legitimate flow, so it stays audited and documented. Future option: bind the target to
  a registered host.
- Remaining **deferred** items (verified-harmless / latent): the leader-election
  INSERT-conflict fallback is dead code on PostgreSQL, but the SELECT-first design means the
  common path never reaches it and acquire/renew/steal are correct (verified on real
  PostgreSQL) — the loser of a first-acquire race just retries next cycle; incremental
  `ADD COLUMN` requires a default for a `NOT NULL` column (the current convention — a
  default-less `NOT NULL` or `UNIQUE` add would fail, but no schema does that); the
  `/history/diag` endpoint is SQLite-only (returns an error on MySQL/PostgreSQL). Plus frontend
  low-severity items (discovery-modal races, client-side gating of session revocation,
  invalid-date formatting, escaping hardening).
