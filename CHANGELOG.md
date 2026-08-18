# Changelog

All notable changes to **ServiceSentry** are documented in this file.

> **Versioning.** Every commit publishes a build — `0.0.1+build.N` — and its section holds
> **only what that commit changed**. `src/lib/__init__.py::__version__` declares the same
> build, and `tests/test_version_changelog.py` fails when the two drift. The semantic version
> deliberately stays at `0.0.1`: the counter is build metadata, so it does not spend numbers
> we will want for real releases. This changes once releases begin.

## [0.0.1+build.83] - 2026-08-18

### Added
- **The WebAuthn ceremonies** (`lib/core/mfa/webauthn.py`) — registration and authentication
  verified as arithmetic over bytes the browser posted, with no Flask, no store and no clock.
  Six checks, and each is the whole feature when it is missing: the challenge (constant-time,
  or an assertion captured once is replayable forever), the origin (exact equality — a
  substring test is how `https://panel.example.com.attacker.net` becomes a valid login), the
  RP ID hash, user presence, a signature over `authData ‖ SHA-256(clientDataJSON)` and nothing
  else, and a signature counter that moved forward.
- **The RP ID comes from `web_admin|public_url`, never from the request.** Behind a reverse
  proxy the request says whatever the proxy last said, and a credential registered against the
  wrong name is one that silently never works again — the browser scopes it and it cannot be
  moved. Nothing usable answers empty, and the caller declines to offer WebAuthn rather than
  guessing.
- **Attestation is deliberately not verified**, and that is a choice rather than an omission:
  the statement says which model of authenticator was used, and checking it means shipping and
  maintaining vendor roots to answer a question this panel does not ask. A second factor here
  is "something the person has", not "something from a manufacturer we approve".
- 53 tests. The happy path is one class; the other eight each take a ceremony that would
  verify and break exactly one thing.

## [0.0.1+build.82] - 2026-08-18

### Added
- **The two pieces WebAuthn needs before any of it can touch a browser**, both written here
  because there is no CBOR library in this project and adding one to read two structures was
  not a trade worth making — the same reasoning as the QR encoder, and the same discipline:
  checked against what the standard publishes rather than against themselves.
  - `lib/core/mfa/cbor.py` — decoding only, against RFC 8949's own Appendix A table. It
    **refuses the indefinite-length form** WebAuthn's canonical encoding does not use, because
    accepting two encodings of one value is how a signature comes to be computed over one and
    checked against the other; it refuses a repeated map key rather than picking one for
    whoever sent it; and it **says how much it consumed**, since the credential's public key is
    CBOR followed by extensions and a parser that ignores the remainder cannot tell a key from
    a key with something appended.
  - `lib/core/mfa/cose.py` — the authenticator's key map as something `cryptography` can verify
    with: ES256, RS256 and EdDSA, and nothing else guessed at. **The algorithm is the one
    recorded at registration, never the one the key claims when the assertion arrives** — a key
    that picks its own is the JWT `alg` flaw with different words. An RSA modulus below 2048
    bits is refused: the authenticator chose the size, so the floor is checked rather than
    assumed.
  - 82 tests. The CBOR ones sit on a published table; the COSE ones are an honest round trip
    (a real key pair exported into the COSE map an authenticator would send) and the file says
    so, because what they prove is that the labels are read as the standard numbers them —
    the half that silently produces "invalid signature" for every user when it is wrong.

## [0.0.1+build.81] - 2026-08-18

### Added
- **`ldap|mfa_trusted`, `oidc|mfa_trusted`, `saml2|mfa_trusted` — "this directory already
  requires MFA".** Where it does, asking again is friction with no gain: the account proved two
  things before the panel ever saw it. It is a switch per provider and not a rule in the code,
  because whether an IdP enforces MFA is a fact about somebody else's system that only its
  operator can state.
  - **Off by default**, which is the conservative direction: the panel keeps asking for what it
    can verify itself until an operator says the directory is doing it.
  - Trusting one skips **both halves** for sign-ins through it — the code step and the forced
    enrolment — because both exist to establish the same fact.
  - It says nothing about a **local** sign-in. Trusting a provider is a statement about that
    door, not about the account: somebody who also has a password here still meets the panel's
    own policy when they use it, or trusting one directory would quietly disarm every other.
  - A sign-in source with no config section of its own — the Microsoft Teams tab — is never
    trusted. There is nowhere to say it enforces MFA, and the answer to "no setting" is the
    safe one.
  - Eight tests, including the two that would matter if this were got backwards: trusting one
    provider does not trust the others, and turning the trust back off asks again.

## [0.0.1+build.80] - 2026-08-18

### Added
- **`web_admin|mfa_required` — the installation can now make accounts carry a second factor**:
  `off` (the default, unchanged behaviour), `admins`, or `all`. Three values and not a switch,
  because "everybody" and "the accounts that can change everything" are different decisions
  with different costs, and offering only on/off makes the answer to "protect the dangerous
  accounts" be "make forty people enrol".
  - **Switching it on locks nobody out**, which is the only reason a policy like this is safe
    to turn on at all. Somebody it covers who has no factor enrols ON THE WAY IN, at
    `/login/mfa/enrol` — still with no session, exactly like the code step. Refusing the
    sign-in instead would shut out everybody who has not enrolled, which the moment the policy
    is switched on is everybody, the last administrator included.
  - `admins` counts an administrator **however they became one** — their own role or a group
    carrying it. Asking only the account's own role is the bug the August audit found in four
    other guards, and repeating it here would have left the accounts the policy exists to
    protect as the ones it skipped. It reuses `users_svc.user_is_admin`, which that audit
    added.
  - **A policy that cannot be honoured gives way rather than the installation.** `MfaStore`
    refuses to write a seed it cannot encrypt, so on an install with no key a policy demanding
    a factor would demand something nobody can enrol. `_mfa_policy()` reads `off` in that case
    whatever the config says, and logs why — the alternative is a panel nobody can open and a
    setting that looks correct.
  - A value that is not one of the three is refused at save. Stored, it would be read as "not
    one of the values I check for", which fails OPEN — the one direction a policy field must
    never fail in.
  - A factor somebody already set up is still asked for when the policy is `off`: turning the
    policy off must not silently stop honouring what people opted into.
  - The enrolment screen will not mint a secret for an account that already has a factor.
    Without that, a password alone would replace a working one.
- Nine tests for the policy, and the honest note that goes with forced enrolment: the account
  is one password away from that page, so whoever has the password can enrol THEIR
  authenticator. It is the exposure a password-reset flow already carries, it is audited, and
  the alternative — an out-of-band enrolment step — is a feature nobody would switch on.

## [0.0.1+build.79] - 2026-08-16

### Added
- **Two-factor authentication for local accounts (TOTP)** — phase one: anybody can turn it on
  from `/account`, nothing forces it yet, and an account that has not enrolled signs in exactly
  as before. Which is what makes it safe to deploy on an installation that has never heard of
  it.
  - **RFC 6238 from the standard library** — `hmac`, `hashlib`, `struct`, `base64` and nothing
    else. A dependency for thirty lines of arithmetic that has not changed since 2011 is a
    dependency in a panel people install on segregated networks and count what it pulls in. It
    is tested against the table of expected codes the RFC itself publishes (Appendix B), which
    is the difference between a test and a comment: a TOTP that agrees with itself agrees with
    nobody's phone.
  - **A code is good exactly once.** The verifier answers the time STEP rather than a boolean,
    and the step is stored, so a code read over a shoulder — or off a phishing page — stops
    working the moment it is used instead of at the end of its thirty seconds. The counter
    lives in the database because "already used" has to hold between processes: two web
    replicas with a local counter each would accept the same code twice.
  - **A QR code and the base32 key, always both.** There is no QR library in this project and
    adding one to draw a square was not a trade worth making, so `lib/core/mfa/qr.py` is
    ISO/IEC 18004 in two hundred lines (byte mode, level L, versions 1–10, smallest that
    fits). It is checked against the error-correction codewords the standard prints for its
    own worked example and the published table of format strings — but no test can hold a
    phone up to a screen, so the key is printed beside the square and the factor is not
    switched on until a code the app produced verifies. A wrong QR costs one manual entry.
  - **Ten single-use recovery codes**, shown once, hashed with the account hasher — nothing
    ever needs to read one back. Plus `main.py user mfa-reset <user>` on the machine, which is
    the way back for somebody who lost the phone AND the codes; without it the last
    administrator can lock the installation permanently.
- **The half-finished sign-in is not a session.** A password accepted but not yet seconded
  writes no session row and sets no `logged_in`; it is a short note in the signed cookie that
  expires in five minutes. The alternative — create the session and flag it — hands a real,
  API-usable session to whoever has the password and makes every gate responsible for one more
  field. The check sits in `_establish_session`, the one place in the panel where a session is
  born, so the three SSO callbacks inherit it rather than walking around it.
- Its own tables (`mfa_factors`, `mfa_recovery`) and not a column on `users`: that record is
  merged into what the users API serialises, so a TOTP seed there would be one
  `GET /api/v1/users` away from everybody with `users_view`. The seed is encrypted at rest, and
  **enrolment is refused outright when it cannot be** — the one place in this project that
  will not fall back to plaintext, because a seed is a generator and one read out of a database
  produces valid codes for as long as the factor exists.
- `mfa_reset_others`, granted to nobody by default. Taking another account's factor off is the
  supported way back in for a lost phone, and it is also what an attacker with `users_edit`
  would do before going after the password.
- `showHtmlModal` — the fourth dialog shape, for a modal with a CONTROL in it. The other three
  cannot carry a form, and a bespoke modal per case is how a panel ends up with six that look
  almost alike.
- `.ss-qr` caps the square. The SVG ships with a `viewBox` and no width or height on purpose —
  one sized by the server does not fit somebody's phone at arm's length — and the cost of that
  is that it inherits its container. Unconstrained, the container is the dialog: at `modal-lg`
  it drew 800px wide and pushed the key and the confirmation field below the fold, so the one
  thing the screen exists to show was the one thing off it. Capped with `min()` so a narrow
  phone gets the width it has rather than a square wider than the dialog, and guarded on the
  class rather than the markup so the next place that shows one inherits the fix.

### Fixed
- **Secrets saved during the very first run of a fresh install were stored in clear text.**
  `_get_fernet()` caches what it finds, the stores capture that value rather than the method,
  and `_init_entity_store()` runs *before* `_create_app()` writes the key file — so on an
  install with no `SS_SECRET_KEY` and no `.flask_secret` yet, the hosts, credentials and
  (now) MFA stores were all built with no encryption. It corrected itself on the next restart,
  which is exactly what kept it invisible: the only affected install is the one nobody has
  restarted. The key is now minted before the stores are built. Found because MFA fails closed
  rather than storing a seed in the clear, so it was the first store to report it.

## [0.0.1+build.78] - 2026-08-16

### Security
- **A custom role NAMED `admin` was treated as the admin role.** `_is_admin_requester()`
  asked `_uid_to_role_name(role) == 'admin'`, and that method returns the built-in KEY for a
  built-in UID and the **display name** for a custom role — so a role called `admin`, with an
  empty permission list, answered the admin check. That answer is worth everything:
  `_perms_grantable`, `_role_grantable` and `_groups_grantable` all return True for an admin
  without looking further, so it clears every escalation guard at once. The way in is two
  **delegable** grants — `roles_add` to mint the role, `users_edit` to assign it — and neither
  is the admin role.
  - What kept it shut was an accident: while the built-in role is displayed as `Admin`, the
    name `admin` is taken case-insensitively. The panel lets built-in roles be renamed, and
    `Administrador` — the first thing a Spanish install does — frees it.
  - Fixed at the decision: `_is_admin_role(role_ref)` compares the **UID**, and accepts the
    legacy `'admin'` key only while no custom role is keyed by it. `_is_admin_requester` and
    the users routes' own copy both call it.
  - Second lock, because the two fail differently: `role_name_taken()` now reserves the
    built-in keys (`admin`, `editor`, `viewer`, `none`) as names whatever the display names
    say. One is a rule a refactor can break again; the other is a row that never exists.
- **The section-page gate resolved permissions from `session['role']`**, which holds a display
  name, and got both directions wrong: a **custom** role resolved to no permissions at all —
  its holder bounced off a section their role grants — while a role named `admin` matched the
  built-in key and collected the entire admin set. It now asks `_get_session_permissions()`,
  the resolution every other gate uses.
- **An administrator by GROUP was not counted as an administrator.** The panel grants admin
  two ways — the account's own role, or membership of a group carrying the admin role, which
  is what the built-in *Administrators* group is for — and every last-administrator guard
  asked only the first. So on an installation that grants admin through a group, none of
  those accounts was protected: a `users_delete` holder could remove them, and the "there
  must be one admin" counters never saw them, so they could be demoted, disabled and deleted
  one after another until the panel had no administrator at all.
  - `users_svc.user_is_admin(user, groups)` and `count_admins(users, groups)` answer it the
    way the panel defines it (a disabled group grants nothing, here as everywhere), and the
    four guards go through them: `set_role`, `set_enabled`, `update_user` and the delete
    route. The CLI passes its own group map.
  - The users routes' role-hierarchy guard now calls `_is_admin_requester()` instead of
    reading `requester['role']` — the same divergence that method exists to end — and the
    local wrapper that duplicated the admin check is gone.
- **Deleting a group that carries the admin role had no requester guard**, while editing the
  same group had one. Measured with the two requests back to back as the same non-admin
  `groups_delete` holder: `PUT → 403`, `DELETE → 200`, and every member's group list emptied.
  Deleting is the bigger action — it strips that role from all of them at once — and it was
  the unguarded one.
  - The same guard now applies, decided on the role UID; and an integrity rule that binds
    admins too: a deletion that would leave the installation with **no administrator** is
    refused, counted against the group map without that group, which is what the deletion
    does to every member.
  - The group-edit guard stops comparing display names (`'admin' in current_role_names`) and
    asks `_is_admin_role` as well.
- **A host-bound check was authorized by where it LANDS, not by where it comes from.** The
  module save authorizes item by item, and a check bound to a host is authorized with that
  host's permission — read from the new item only. Adding and removing have one binding;
  a **modification** has two, and only the destination was checked. With `server.mine.edit`
  as the sole permission: moving another host's check onto mine → allowed; moving mine onto
  theirs → denied; editing theirs in place → denied. So the one permission whose purpose is
  to confine somebody to their own machines was also the one write that reached outside
  them — and the damage lands on the other host, which quietly stops being monitored.
  - Both bindings are now resolved separately: an add authorizes the destination, a removal
    the origin, and a modification **both** when they differ. A global `servers_edit` holder
    may still move a check between hosts, which is what a permission not confined to one
    host means.
- **A guard for a fail-open default**: `widget_allowed` treats an Overview widget that
  declares no permission gate as open to any logged-in user, and the gate is declared by the
  widget itself — core or module. All 22 shipped widgets declare one, so nothing is wrong
  today; the next one to forget would be readable by everybody with nothing to say so. The
  default is deliberately left alone (changing it would blank a module's card mid-upgrade
  with no explanation) and a test now names any widget that arrives without a gate.
- Thirty regression tests, and the ones that could be pinned to the old behaviour were each
  validated by reintroducing it.

### Added
- **Webhooks and Microsoft Teams are marked BETA on their own configuration card.** Both
  deliver, and both are short of validations the older channels have — so the badge is the
  honest state rather than a note in a document nobody opens while configuring. Declared once
  (`beta: True` on the card in `lib/config/layout.py`) and drawn by `cfgCardOpen`, the single
  function every card opens with, so the two bespoke renderers inherit it without being told
  and leaving beta is one line in one file. What has to be closed before the badge comes off
  is written down in `docs/ref-pendiente.md`, not left as a feeling.
  - Adding it pushed `cfg/_render.html` past its size guard. The answer was not a shorter
    comment: the card's chrome — open, close, badge — moved to `cfg/_card.html`, which is
    what that guard asks for when a section shell grows.

### Fixed
- **A package only another container runs was asked about under one name and answered under
  another.** `elsewhere_rows` compares canonically (PEP 503) so the same package is not asked
  about twice — and it also *reported* the canonical name, while the screen joins that answer
  back onto the instance's own package list by name and version, where the name is spelt as
  that process publishes it. Eight of the packages installed here differ between the two
  forms (`PyYAML`, `typing_extensions`, `CacheControl`…), so those rows were asked about,
  answered, and then drawn with an empty "Latest" and no CVEs — indistinguishable from a
  package with nothing to report, which is the failure the whole list exists to prevent.
  Compared canonically, reported as spelt over there; two tests, the first validated by
  reintroducing the bug.
- **The advisories of one package at two versions were the same advisories.** The dependency
  check asks about three lists, and the third exists precisely to carry what only ANOTHER
  container runs — including a different version of a package this process also has. The
  answer came back keyed by NAME, so the second `urllib3` overwrote the first; and since the
  other containers' list is asked last, what overwrote this process's own row was always
  somebody else's. A clean 2.2.1 was drawn carrying 1.26.0's advisory, and the reverse — the
  vulnerable one reported clean because a newer container answered after it — is the same bug
  with the worse ending. The reasoning for keying by name and version was already written into
  the route (which splits its "behind" counters that way) and into the browser (which keys the
  answer by pin); the one step between them did not.
  - `vulnerabilities()` answers `by_pin` and `check()` reads it by pin. The totals go with it:
    `vuln_total` and `vuln_packages` are now DISTINCT advisories and packages rather than sums
    over the rows, so one flaw affecting two versions of one package is one finding — which is
    the complaint `collapse_aliases` exists for, arriving by the other door.
  - The click was still by name: opening the count on either row showed whichever came first,
    under a heading naming the version that was clicked. It carries the pin now, and an
    advisory names each package once instead of listing "urllib3, urllib3".
  - Five regression tests, all validated by reintroducing the behaviour.
- **A rootless Podman container reported itself as bare metal.** Podman writes
  `/run/.containerenv` and not Docker's marker, and under cgroup v2 the cgroup line inside the
  container is a bare `0::/` that names no runtime — both signals this looked for, missing. It
  is the row the rest of the page is read against: a path that "exists" is inside an image that
  may be recreated tomorrow, and free disk is the layer's and not the host's.
- **PyPI was asked twice for one package** whenever two containers ran two versions of it.
  "What is the newest release" has one answer for both rows.

### Removed
- **Dead code found by an audit sweep**: `notify.registry.get_channel`,
  `core.users.service.set_groups`, `providers.oidc.auth.OidcUnavailableError` (defined,
  never raised) and `watchfuls.m365._parse._csv_count` — each named exactly once in the whole
  tree, at its own definition.
- **A verbatim second copy of `cap_audit_lists`** in `core/modules/service.py`, docstring
  included — the one the routes and the tests use lives in `core/modules/actions.py`, whose
  module docstring already claimed it. A function whose own documentation says "in one place"
  existed in two.

### Changed
- **The dependency check walks `site-packages` once instead of three times.** Working out what
  only the other processes run means subtracting what this one runs — the same full walk of
  every installed distribution the route had just done twice to build the two lists it is
  subtracted from. The route hands them over; the fallback that computes them is kept for
  every other caller.
- `_grade()` answers the same five keys whether or not the advisory record could be read. A
  dict whose shape depends on the request working is one the reader has to test twice, and the
  half that forgets reads a missing `published` as "computed by us" — which is precisely the
  claim that screen must not make on its own.
- **One `fmtBytes` in `core/_utils.html`** instead of `_bkBytes` and `_dgBytes`, which were
  character-for-character identical in the backup and diagnostics screens. A size formatter
  that exists twice is two answers waiting to disagree about the same disk.
- `docs/ref-pendiente.md` records what the audit found and did NOT act on, with the reason:
  the route `register()` functions that have grown into the file (six of them over 290 lines,
  entraid at 646), and the 474 i18n keys that no code names literally — mostly built by
  concatenation, so any pruning before that list is separated is pruning blind.


## [0.0.1+build.77] - 2026-08-15

### Fixed
- **The Helm chart's syslog ports were a label and nothing else.** `syslog.ports.udp`/`.tcp`
  set the container port and the Service, and never told the listener anything — so anything
  other than the default produced a Service routing to a port nothing inside the pod was
  listening on, which reads as a network problem and is not one. The chart now pins
  `SS_SYSLOG_HOST`/`SS_SYSLOG_PORT` from those values, and refuses to render when udp and tcp
  differ: the app takes ONE port for both, and two fields that must be equal will not stay
  equal on their own. The TLS port stays a saved-config matter — it does not exist until a
  certificate does — so that value only publishes it, which is now said in the chart's README.
- **The chart pointed at two documents that no longer exist**, `docs/kubernetes.md` and
  `docs/architecture.md`, in its README, its NOTES and its values — renamed to `caso-` /
  `explica-` some time ago. A link that resolves to nothing is worse than no link: it reads
  as documentation that was written.
- `Chart.yaml` carried `https://github.com/` as both `home` and `sources`, which is the
  placeholder, not the repository.


## [0.0.1+build.76] - 2026-08-15

### Added
- **`docker/env.example` documents every variable this app reads — sixteen were missing.**
  Counted rather than eyeballed, against the three surfaces that actually read the
  environment: the config registry, the container entrypoint and `os.environ` in the source.
  Absent were every backup setting (`SS_BACKUP_DIR`, `_EVERY_HOURS`, `_KEEP`,
  `_AUTO_SECRETS`), the fail2ban jail (`SS_IPBAN_ENABLED`, `SS_IPBAN_WHITELIST`), the three
  autostart gates (`SS_MONITORING_AUTOSTART`, `SS_SYSLOG_AUTOSTART`, `SS_EVENTS_AUTOSTART`),
  `SS_MONITORING_ENABLED`, the SQLite paths, `SS_AUDIT_DETAIL_MAX_ITEMS`,
  `SS_UPDATE_CHECK_URL`, `SS_CONTROL_BIND` and `SS_PORT`. For anybody deploying, a setting
  that appears nowhere in that file is a setting that does not exist.
  - Two stale comments are corrected with them: monitoring's on/off and autostart, and the
    event processor's autostart, were described as "web UI only, not env vars" — they are
    env-overridable, and setting them LOCKS the value read-only in the panel, which is the
    reason to do it.
  - `SS_WEB_PORT` and `SS_PORT` are told apart, which the names do not do: the first is the
    port this process binds, the second locks the port stored in the config.
- **A guard so it cannot rot again** (`tests/meta/test_docker_env_example.py`). Both
  directions, asymmetric on purpose: a supported variable must be NAMED there (the
  per-topology ones are explained in prose that sends the reader to the compose file, which
  is the right shape for them), while only lines that ASSIGN are checked for existing —
  prose writes families like `SS_DB_*`, and no regex tells a wildcard from a name once the
  star is gone. Validated by removing a variable and by inventing one; both go red.

### Changed
- **Which published image the HA test stack runs is one variable.** The tag was written into
  the `x-app-build` anchor, which is already the single place the four services take it from
  — but changing it meant editing a tracked file to run a stack, and that edit is the kind
  that gets committed by accident. `SS_IMAGE_TAG` (default `test`) now names it:
  `SS_IMAGE_TAG=build docker compose -f docker/docker-compose.ha-test.yml up -d`, or the same
  in front of `make_test.sh ha`, or once in `docker/.env` — Compose reads that file from the
  compose file's own directory, called from there or from the repo root with `-f`. The shell
  WINS over the file, which is the part worth knowing when a stack comes up on an image
  nobody expected.

### Fixed
- **`make_test.sh` no longer overrides a `docker/.env`.** It defaulted `SS_IMAGE_TAG` to
  `test` and exported it, and the shell wins over that file — so writing `SS_IMAGE_TAG=build`
  in `docker/.env` and running the script would have quietly come up on the other image,
  which is the exact confusion the variable was added to prevent. It now exports the variable
  only when it is already set, and asks Compose which image it actually brought up instead of
  rebuilding the answer from it.


## [0.0.1+build.75] - 2026-08-15

### Added
- **A `build` tag that does what `test` does without running the suite.** Same image, same
  `.deb`/`.rpm`/Gentoo overlay, same install of those packages in Debian, Ubuntu and Fedora —
  the one difference is that the tests are not started at all. `test` runs them beside the
  build, which is what puts a red tick against a commit whose answer was already known: the
  suite was just run locally, or the change is in the Dockerfile and no Python test can see
  it. Skipped rather than made non-blocking, because a job that runs and is ignored still
  costs ~13 minutes of runner and still marks the commit.
  - The image publishes as `:build`, its own name, so a `pull` says which of the two claims
    it carries.
  - `packages` keeps `needs: tests` and admits `skipped` beside `success`: a plain `needs`
    would take the packages down with the skipped suite, turning "do not run the tests" into
    "do not build anything either", while dropping the dependency would let a red suite ship
    packages on `v*` and `test`. `!cancelled()` rather than `always()` — a cancelled run is
    somebody pressing stop, and it should stop.


## [0.0.1+build.74] - 2026-08-15

### Added
- **`showTableModal`** beside the panel's other two dialog helpers. `showInfoModal` is
  key/value and `showLinksModal` is label/note, so anything with a third thing to say had to
  write it into a cell with separators. Cells are escaped like everywhere else; `{html: …}` is
  the explicit opt-in a caller uses for markup it composed itself, which is the same escape
  hatch `showLinksModal` exists for, now said once and reusable.

### Changed
- **A container's package list is a table, not a sentence per package.** It read
  `3.5.0 → 3.5.1 · 2 advisories · outside the lock`, which is a table written with separators:
  nothing lines up, and "which of these 43 has the advisory" is answered by reading every line
  to its end. Five columns now — package, version, newest published, advisories, and whether
  the lock pins it — with the lead adding how many are behind and how many carry an advisory.
- **The advisories of a container say which of its packages carries them.** The column gives
  an instance a number and the next question is always *in what*; the list behind it named one
  package per advisory in a note, and only the first one it was seen on. It is a table now —
  identifier, severity, and every package of that container it lands on — sorted worst first,
  with the severity opening the same CVSS breakdown it opens in the dependency card.
- **The comparison against this process puts a column per side.** `1.0 → 2.0` in one cell
  leaves which of the two versions is this process to be inferred from the order it was
  written in. It also carries the advisories of the version THAT container is on, which is
  where "and is it stuck on a vulnerable one" stops being an academic question.
- Inside a dialog the advisories are the **identifiers themselves**, linked to their write-up,
  rather than a count: there is room here that a table row does not have, and a number in a
  modal would be a second thing asking to be clicked on top of the one already open.


## [0.0.1+build.73] - 2026-08-15

### Changed
- **The per-container package list carries the remote answer too.** It showed name and version
  and nothing else, so the newest published version and the advisories — which the check
  already covers for these containers — were only reachable from the card behind it. Each line
  now reads `3.4.9 → 3.5.0 · 2 advisories · outside the lock`, matched by name AND version
  because that container's copy is not this process's. The lead says whether the remote half
  is in there at all: a column of bare versions and "nothing found" are the same picture, and
  telling them apart is what this card exists for.
- **`collect.environment()` is computed once per process and kept.** It is the one thing on
  this page that is cached, and the exception has a reason: everything else is recomputed per
  call on purpose — a diagnostics screen served from a cache describes the problem you had
  before — while this cannot change while the process lives, and it is a full walk of every
  installed distribution that now runs on every render of the page as well as at start-up.


## [0.0.1+build.72] - 2026-08-15

### Changed
- **The instances card answers the two remote questions for the other containers as well.**
  Neither needed a new call: the dependency check already asks about the union of every
  process's packages in one round, and the release check returns one answer for the whole
  installation. What was missing was saying which container a finding belongs to.
  - A **CVE column** per instance, a pure join against the answer already on the page —
    matched by name AND version, because the same package at two versions is two different
    answers and reading one off the other is how a container gets reported clean because a
    different one is. It opens the list, each advisory naming the package and its severity.
  - The **version cell** now separates two claims that look alike: *different from this
    process* (they are meant to come from one image) and *behind the newest published release*
    (the whole installation can be perfectly consistent and perfectly out of date). The second
    only exists once the release check has run, and the comparison is done on the server for
    every version seen — a copy of it in the browser would be a second answer waiting to
    disagree.
  - Both checks refresh **the rows and nothing else**, the rule the dependency card already
    learned.
- **Fixed: a drifted container's answer could be drawn on this process's own row.** The
  browser keyed the remote answer as `byName[r.name] = r`, so the last one won — and since the
  check now covers what only another container runs, the same package can arrive twice at two
  versions. Keyed by name and version now, with the local lists owning the name.
- **"Same as here (42)" now opens too.** It was the one cell on the instances card with
  nothing behind it, and it does not say WHICH 42 — a sentence that asks the reader to take
  the interesting half on trust is what this page exists not to do. Both answers open a modal
  now: the differing one its comparison, the matching one the list of what that process runs,
  marking which of them its lock pins. One shape serves the screen and the remote check, so a
  second flatter copy cannot drift from it.
- **Dependencies refreshed**, off what the panel's own check reported.
  - `requirements.lock` regenerated with the documented `pip-compile --generate-hashes
    --strip-extras` pass. One pin moved of the forty-one: `charset-normalizer` 3.4.9 → 3.5.0.
    Everything else the resolver held, which is the answer a lock is supposed to give.
  - `requirements-dev.txt`: `pytest` 9.0.2 → **9.1.1**, which is a security bump —
    PYSEC-2026-1845, tmpdir handling — and the reason the diagnostics page reported it at all:
    it runs on the machine like anything else installed here, pinned or not. `pytest-env`
    1.6.0 → 1.7.0 and `watchfiles` 1.1.1 → 1.2.0 alongside.
  - The **image now upgrades `pip` and `setuptools`** before installing the lock. They are not
    in it — pip-compile does not pin its own installer — so the container shipped whatever the
    base image carried, and both were reported with advisories. The `.deb`/`.rpm` postinstall
    and the Gentoo ebuild already did this; only Docker did not.


## [0.0.1+build.71] - 2026-08-15

### Added
- **The diagnostics page can answer for the containers it is not running in.** Everything on
  it described the process that served the request: on a single container that is the whole
  installation, split into web / worker / syslog / events it is the web admin and nothing
  else — and the other three were invisible from every screen, while "is that pod on the same
  build?" is what a support thread opens with.
  - Each service publishes its **interpreter, OS, packages and optional libraries** into a new
    `env` column on `service_instances`, and the panel reads them from there. Not over HTTP:
    the standalone services answer none unless `SS_CONTROL_TOKEN` is set, which is not the
    default, and a diagnostics screen that works only on the installs that opted into a token
    is a screen for somebody else. The shared database is what this control plane already
    declares as its source of truth.
  - Published **once, at start-up**, and deliberately not part of the beat: that row is
    rewritten every few seconds by every instance, and none of this can change while the
    process lives. A restart is a new instance row anyway.
  - The card shows the **difference**, never four copies of one list. Four containers built
    from one image carry identical packages, and "same as here" is the whole answer when it is
    true; a count opens the list package by package when it is not, because "they differ" is
    not actionable and "which one, and from what to what" is.
  - A container on **another code version** is marked in amber. That is the real failure: they
    are meant to come from one image, and a tag left behind shows up here before it shows up
    as a bug nobody can reproduce.
  - "Has not published yet" is said, never guessed at — an older build, or one whose first
    beat has not landed, is a different sentence from "differs" and only one of them means
    somebody has work.
  - The remote check covers **what only the other processes run**, in the same round. Each
    container asking PyPI and OSV about its own list would put four processes on the internet
    for nearly the same question, in exactly the deployment where that is least welcome — and
    it contributes nothing when they all came from one image, which is the norm.
  - Packages are matched by **name and version**, not name alone: the web on 3.4.9 and a
    worker on 3.5.0 are two questions for the advisory service, and answering one of them for
    both is how a container gets reported clean because a different one is.
  - The block travels in the **document** too (text and XML), which is the one place the
    screen cannot go.

### Fixed
- **SNMP discovery gave up in silence on a thread that already had an event loop.** It ran
  `asyncio.run` inside a per-server `try/except: continue`, and `asyncio.run` refuses to start
  a loop where one is already going — so every server raised, every server was skipped, and the
  empty list read as *this device has no OIDs*. Which is the exact symptom the walk had already
  been rewritten once to fix, from an entirely different cause. The same call sat in
  `snmp_get`, the path the checks take.
  - `run_coroutine()` runs the coroutine on a thread of its own when the caller's already has a
    loop, and plainly otherwise. Both call sites go through it.
  - Found because CI failed five discovery tests that passed on their own, and passed beside
    `unit`, beside `meta` and beside the whole watchful tree. The pointer was not the assertion
    but a `RuntimeWarning` in the log — *coroutine was never awaited*, on the `continue` line.
    Playwright's sync API keeps a loop alive in the main thread, so the pair that reproduces it
    is `tests/e2e watchfuls/snmp`. The panel serves from whatever thread it is given, which is
    the reason to fix it regardless of the tests.

### Changed
- `behind` and `behind_unpinned` are now **derived from the rows the answer carries**, matched
  by name and version, instead of passed through from the check. Three lists feed one round
  now, and a count the browser cannot reach by counting what it draws is a count that drifts
  from the table under it.


## [0.0.1+build.70] - 2026-08-14

### Added
- **Diagnostics answers "are we on HTTPS?" — and whether that answer can be believed.** The
  panel never terminates TLS itself (there is no `ssl_context` anywhere in it, deliberately:
  something in front does that), so behind a reverse proxy the question could not be answered
  from any screen. The new **Network and TLS** card reports the three answers separately,
  because the failure everybody hits is the one where they disagree:
  - **what the panel concluded** — the scheme, host and client address, already through
    ProxyFix when it is mounted;
  - **what the proxy actually sent** — `X-Forwarded-Proto` / `-For` / `-Host`, shown raw,
    whether or not this panel is reading them;
  - **whether it is reading them** — `proxy_count`, which is what mounts ProxyFix at all.
  - A verdict of **`ignored`** when a proxy declared HTTPS and the count is 0. That is not a
    worse `http`: the install IS on https and the panel does not know, which has a different
    fix and is identical in every other field. Every URL the panel builds, and the address
    fail2ban bans, are wrong until `proxy_count` is set.
  - The **cookie trap** named before it happens: `secure_cookies` on while the panel believes
    the connection is plain means the browser drops the session cookie and the login appears to
    loop. `_hook_csrf` already knew how to say this, but only in the log and only at the moment
    it broke.
  - `TLS terminated by the panel` is reported as a constant `no` rather than probed — phrasing
    it as a question sends somebody hunting for a certificate setting that does not exist.
- The block travels in the **document** too (text, JSON and XML), which is the one place the
  screen cannot go: a support thread.
- **The dependency table can ask the world about itself.** Two columns behind a button:
  the newest version PyPI publishes, and how many known advisories affect the version
  installed (OSV.dev). Both leave the machine, so both follow the rule the update check
  already set — never on load, never a poll, one button, audited with what it found.
  - **The columns do not exist until it is asked.** An empty "Latest" on every install is a
    column that looks broken, and this page's whole contract is that opening it contacts
    nobody.
  - **PyPI has no batch endpoint and OSV does**, so the first is one small request per package
    in a bounded pool and the second is a single request for all of them — which is also why
    the advisory half keeps working where pypi.org is blocked and the other half does not.
  - The two halves **report separately**: "PyPI answered and OSV did not" is a real state, and
    a CVE column of zeros would be stating something nobody checked. It says a dash.
  - The count carries its **identifiers** in the tooltip — something an operator can look up,
    rather than a severity this panel decided on its own.
  - Comparing versions is deliberately not PEP 440: `behind` / `current` / **`unknown`**, and
    a version it cannot read is never painted as up to date.
  - The package list is built **on the server** from the lock and what is installed. A client
    that could name them could make the panel query an outside service for anything it liked.
  - **The click updates three nodes** — the summary line, the tables and the header badge —
    and nothing else. Reported twice as "it reloads the whole section"; it never reloaded the
    document (a JS variable survives the click and no navigation happens), but the first
    version replaced the card element and the second replaced its contents, and both threw away
    everything the reader was looking at. The 700px jump that came with it turned out to be
    neither: it is the browser scrolling the focused BUTTON into view, which a programmatic
    `focus()` and an automated click both trigger and a person clicking a visible button does
    not — measured before believing either explanation.
  - **An open fold stays open.** The "the ones that are fine" list is part of the tables, so
    every redraw built a new `<details>` — and a new one is closed: somebody reading the forty
    matching packages watched them shut when they pressed the button. The state belongs to the
    view and is kept by the view, so any redraw restores it rather than only the one call site
    that happened to be reported.
  - **A newer version is marked, not just tinted**: a badge with an arrow and the jump
    (`3.4.9 → 3.5.0`) in its title, plus a count in the card header. Colour alone is what
    nobody notices on a table of forty rows and what somebody with a colour-vision deficiency
    cannot see at all.
  - **That badge is the link**, to the package's own page on PyPI for that version: "there is
    a newer one" and "let me go read about it" are one click. The URL is built on the server
    from two strings it already had. PyPI also carries a `project_urls` map with whatever each
    project chose to put in it, and rendering one of those as a link somebody clicks inside the
    panel would let the package pick where the operator lands.
  - **The summary says how many packages were asked about.** "No advisories at all" is exactly
    the answer somebody should be able to disbelieve, and zero found and nobody asked read
    identically without it.
  - **PyPI's project document is bigger than it looks** — `cryptography` alone is 3.1 MB,
    because it carries every release and every file. The first read cap was one megabyte, which
    truncated eight of the forty packages in this lock; a truncated body is not JSON, so those
    eight came back as `not_json` and the table showed a dash for exactly the biggest and most
    interesting packages while looking like a clean answer. The cap is 16 MB, and hitting it is
    now its own answer (`too_large`) rather than a parse error that sends somebody to look at
    PyPI's output instead of at our own limit.
  - **It asks about the whole environment, not only the lock.** Reported: every dependency
    showed 0 CVE. That was true — of the forty-one packages `requirements.lock` pins. `pip`,
    `setuptools` and `pytest` had five advisories between them and were never asked about,
    because the table only ever knew about the lock. An advisory does not care whether a
    package was pinned: the code runs on the machine either way.
    - They get **their own fold**, below the pinned ones and separate from them, because it is
      a different claim: they are not drift and there is nothing to reconcile — a container
      built from the lock still carries `pip`. Listing them beside the lock would report a
      correct install as fifty problems, which is why this is not a fourth status.
    - No "Pinned" column in it: there is no lock entry to compare against, and an empty cell
      under a heading that says *Pinned* reads as a package that lost its pin.
    - The **"outdated" count stays about the lock**, which is the one with an action behind it
      — regenerate the lock. A newer `pytest` in a developer's checkout is not that action, so
      it is stated separately rather than added in; otherwise the fold shows arrows the header
      never counted. Advisories are deliberately **not** split that way.
    - The server says by name which packages the lock does not pin. A browser inferring it
      from a missing local row would call every package unpinned the day the lock failed to
      load.
    - Names are compared **PEP 503-normalised** (`charset-normalizer` in the lock,
      `charset_normalizer` on disk), and each distribution is counted once — two
      `site-packages` on the path would otherwise mean one wasted request and a duplicated row.
  - **The CVE count opens the advisories.** A tooltip listing four identifiers is unreadable,
    uncopyable and gone the moment the pointer moves — and the identifier was never the answer
    anybody wanted; the write-up is. The badge opens an in-panel modal where each entry links
    to its page on the same service that reported it. The column is centred under its heading,
    which it was not.
  - **A section listing every advisory once**, above the tables: how bad it is, how many
    packages carry it and which. The tables answer "what is wrong with this package", a row at
    a time; this answers what comes after — *what are we exposed to* — and the same advisory
    routinely lands on several packages, where counted per row it reads as several findings
    with the identifiers scattered down a column of eighty rows that mostly say 0.
  - **A severity, and never this panel's own.** Either the database published a rating — that
    is the word shown — or it published a CVSS vector, and the base score is the arithmetic the
    specification defines for it. Which of the two it is looking at is stated, because they
    disagree: an advisory GitHub calls *moderate* can carry a vector that scores 8.0. Clicking
    it opens the vector read out metric by metric, in the reader's language: `AV:N` versus
    `AV:L` is the difference between patching tonight and patching next release, and that does
    not fit in a tooltip.
  - **One flaw reported twice is counted once.** Found on real data: `pip` came back with
    `GHSA-wf93-…` and `PYSEC-2026-196`, which are the same path traversal under two names, and
    the panel said six advisories where there were three — on the one screen built so that a
    number can be believed. Identifiers are collapsed through the aliases their own records
    publish, keeping the entry that published a severity, and the other names travel with it so
    a search for the one a scanner printed still finds it.
  - **A finding inside a fold opens it.** Both folds hold what was uninteresting *before* the
    check; the check is what can make them interesting, and leaving the answer shut behind a
    summary line asks somebody to go looking for the thing they pressed the button to be told
    about. It only ever opens: a fold closed on purpose stays closed unless there is now
    something in it.

### Fixed
- **The permissions reference stated something this release made false.** `diagnostics_view`
  was documented as opening a page where "the update check is the only thing that leaves the
  machine". There are two now, and the entry says so — which of them go out, that both are
  audited, and that they ride on the page's own permission rather than a separate one.

### Changed
- **`ref-api.md` calls itself a complete inventory of the HTTP surface and was not one.** Two
  whole domains were missing — Backup (18 endpoints, including the table listing that feeds
  selective restore) and Diagnostics (4). Both are now written up, with the `tables` absent /
  `tables: []` asymmetry spelled out beside the restore endpoint. Verified by comparing every
  `@app.route('/api/…')` in the tree against the document: **138 of 138**.
- **The diagnostics page had no functional documentation at all.** `explica-web-admin.md` gains
  its feature row and an endpoint section covering what the screen answers locally, the
  Network/TLS block and why it separates three answers, and the dependency check — its scope,
  the advisories listed once, and where a severity comes from.
- The dependency partial was split at the point it stopped being one concept:
  `diagnostics/_advisories.html` (every advisory once, and how bad it is) and
  `diagnostics/_cvss.html` (a vector read out metric by metric) now live beside
  `diagnostics/_deps.html`, which is back to the card, its tables and the fetch.


## [0.0.1+build.69] - 2026-08-08

### Changed
- **A MIB compile nobody asked for is now bounded.** Importing a vendor folder leaves hundreds
  of raw MIBs on disk, and the next *discovery* — or the next module **startup** — compiled all
  of them. Measured on 1695 real MIBs: **~2.7 s each**, of which **89 % is parsing ASN.1**, so
  the file count is the second count. That is a discovery that answers in an hour, and a panel
  that does not come up, with nothing on screen to say why.
  - The automatic path survives for the case it existed for — a `.mib` dropped into `raw/`
    still just works — but only while the pending set is **small** (5). Past that the files
    stay raw until the MIB manager is told to compile them, which it already knows how to do
    per file, per selection or all at once, with a progress bar and a **cancel** button. That
    is what an hour of work needs and what an implicit compile can never have.
  - Pending is now decided **per file** instead of per directory. `raw_dir_has_new_mibs`
    compares the whole folder against the newest compiled module of them all, so one new file
    made the directory "new" and the compile that followed walked every name in it.
  - **A re-import no longer invalidates what was already built.** The importer rewrote every
    file it fetched, identical bytes included, and staleness is decided by mtime — so
    re-importing a folder for a handful of new MIBs marked all of them for a re-parse. That is
    how a second import came to cost as much as the first. Unchanged content is left alone.
  - What was measured and **rejected**: pysmi's `JsonCodeGen` (skips generating Python
    entirely) is only **1.13×** faster, because the cost is the parse and not the code
    generation. Six processes give **2.9×**, worth doing but not before not doing the work at
    all. Downloading pre-compiled `.py` from a mirror would skip the parse and is not on the
    table: it is importing third-party Python into the panel's own process.

### Fixed
- **A discovery scoped to one item ran without its address or its identity.** An action posted
  as a flat form carries `host_uid` and `cred_uid` at the top level and the route resolved them
  there; a discovery scoped to a parent item posts
  `{module scalars…, "<collection>": {"<key>": {…the item…}}}`, and the item is where those two
  keys live. The action was handed an item with an empty address and no credentials.
  - Reported as *"you launch OID discovery against a server and get nothing back"*: the SNMP
    server took its address from a bound host and its community from a credential, so
    `discover` saw `host: ''` and skipped it **before sending a packet**. The checks on that
    same server worked, because the check path resolves per item — which is exactly what made
    it look like the device. Nothing said otherwise: an empty result reads as *this device has
    no OIDs*.
  - Fixed in the core, not in the module: every module whose discovery scopes to a parent item
    has this shape, and the alternative is each of them reaching into the credential store on
    its own. Precedence matches the top-level pass on purpose — the bound host only fills what
    the item left blank, the credential is applied last and wins. Two passes that disagreed
    would be the harder bug of the two to find.
- **A discovered OID shows what it currently reads.** The value was there all along, behind
  the server's collection KEY: items are rekeyed by uid when stored, so a 36-character UUID
  was prefixed to it and filled the 160 px column on its own, truncating away the one thing
  that column is for.
  - The prefix is gone when there is nothing to disambiguate. The discovery hangs off
    `checks`, *inside* one server, so the modal always asks one — the name repeated down every
    row and bought nothing. With several answering it comes back, as the server's **name**.
  - The column carries the full value as its tooltip either way: `sysDescr` does not fit in
    160 px whatever prefix it is given.
- **OID discovery against an SNMPv3 server returned nothing.** The walk built its own
  credentials — `CommunityData(community, mpModel=1)` whatever the version — so against a v3
  device it sent a v2c request carrying a community string, which that device answers neither.
  The walk timed out, `discover` swallowed it, and the empty result read as *this device has no
  OIDs* rather than *nobody asked it properly*. The checks on the same server worked all along,
  which is exactly what made it look like the device and not the code.
  - There is now **one** builder for "how this server proves who it is", used by the check and
    by the walk. It was written twice and only one copy ever learned v3.
  - The protocols fall back to the schema's own defaults, so a v3 server saved before those
    fields existed is walked with what its own form would show rather than with whatever a
    lookup miss happens to return.
- **An audit entry a module wrote is now readable.** A MIB import logged
  `GitHub import: 988 ok, 12 failed` and the row printed the whole thing as prose — six lines
  of file names and TLS errors in a table cell — with **no way to open it**, while the fields
  that answered "which ones, and why" sat unread inside the entry. Three faults in a row:
  - The modal fell back to the generic renderer only when it had recognised **nothing**
    (`html || renderReadable(detail)`), so an entry with one known key and ten unknown ones
    showed the one and dropped the ten. It now renders what it does not know by name, which is
    everything a module's audit hook records — the hook exists so a module can record what it
    likes, and until now none of it reached the screen that exists to read entries.
  - The row was clickable only when the detail held `changes` or a before/after snapshot — the
    core's own vocabulary. Now anything beyond what the row already states makes it clickable,
    and the label is clipped: a cell is an index, not the record.
  - The import's summary line named the first ten failures. That reads well for three and
    turns into six lines for twelve behind a TLS timeout each. It is a count now; the names
    and the reasons are structured fields, and the entry opens onto them.
- **The MIB import records which files worked, and why the others did not.** It kept the failed
  names and threw the error away, so *rejected* (the file did not look like a MIB) and a
  handshake timeout — different problems with different answers — arrived as the same fact. The
  imported names were not recorded at all. Both questions get asked exactly when the import
  cannot be cheaply repeated: a re-run to find out costs another few hundred requests against
  GitHub's 60/h anonymous limit.
  - How much of that one entry may hold is now decided in **one** place, on the route that
    writes it, honouring `web_admin|audit_detail_max_items` — the setting that already existed
    for this. Left to each module they would each pick a different number. What is dropped is
    said out loud: a list silently cut at N reads as a complete list of N.

### Added
- **The SNMP module declares a credential type (`snmp_auth`).** The identity was written into
  every server entry — community, v3 user, both keys, both protocols — so a device family
  sharing one v3 user meant typing that user, and rotating it, once per entry. It is now a
  reusable credential the manager creates and edits, like `ssh` and `web_auth` before it.
  - **What applies follows the version, and on v3 the security level too.** v1/v2c ask for the
    community and nothing else — a form offering a user name for a v2c device is asking for
    something with nowhere to go. On v3, *no auth/no privacy* asks for neither key,
    *auth/no privacy* for one, *auth and privacy* for both. Gating the keys on the version
    alone would show boxes the device will ignore, and a filled box that does nothing is worse
    than an absent one, because it looks configured.
  - The protocol lists **drop `none`**. The collection's copies carry it because they have no
    level field: `none` is how they say *authNoPriv*. Here the level says it, and two ways to
    say one thing are two ways to disagree.
  - Adds *context* and *engine ID* for v3 — the context because many devices expose a VLAN or
    an instance per context, the engine ID for the devices that do not advertise it.
  - Reuses the module's existing field names, so seven of the ten labels and hints were already
    written; the three new ones went into both `lang/` files.
  - The credential is **declared, not yet consumed**: the server entries still carry their own
    auth fields. Pointing them at a `cred_uid` is the next step and is deliberately separate —
    it changes what the checks read at run time, which is a different kind of change from
    describing a shape.

## [0.0.1+build.68] - 2026-08-14

### Fixed
- **A module's own test still imported a symbol build.67 moved.**
  `watchfuls/proxmox/tests/test_proxmox.py` asked `lib.core.modules.service` for
  `_apply_cred_to_config`, which now lives in `lib.core.modules.actions` as
  `apply_cred_to_config`. Every consumer under `lib/` and `tests/` had been updated; this one
  was in the OTHER tree the suite collects — `pytest.ini` gathers `src/watchfuls/<m>/tests/`
  as well, because a module's tests travel with the module. Four green runs of
  `tests/{unit,integration,e2e,meta}` said nothing about it, and CI failed on the one file
  none of them covers. Moving a symbol means searching both trees.

## [0.0.1+build.67] - 2026-08-13

### Changed
- **`lib/core/modules/service.py` is one file per concept.** At 787 lines it was the largest
  module left in `lib/core` and 46% of its own domain, holding five jobs with nothing to do
  with each other — its own section banners had been saying so for a while.
  - `authz.py` — may this save touch this item. The module save is the one write that crosses
    domains: a check belongs to a module but is bound to a HOST or a CLUSTER, and the person
    editing it may hold the permission for one and not the other. Answering that wrong is an
    authorisation bug, not a bad screen, and it was buried in the middle of a file that also
    knew about uids and page templates. A rule about who may write what should be findable by
    the name of the file it is in.
  - `items.py` — an item's identity: its uid, its name, its schema, and keeping them in step.
    The rekey, the duplicate check and the clone mark all lean on the same question, so they
    stop being three neighbours and become one module.
  - `provisioning.py` — credentials kept out of the payload on the way out, and the hosts a
    module declares created on the way in. The one thing in the package that writes into
    another domain, with its store still injected explicitly.
  - `actions.py` — the config a watchful action runs with, resolved the way a scheduled check
    would: bound host, restored secrets, referenced credential.
  - `service.py` — what is left is the config DOCUMENT: what may be seen of it, whether it is
    well formed, the spellings it is normalised to, and what the UI is built from. 123 lines.
  - `lib/core/modules/__init__.py` carries the map, like the backup domain's does.
- The helpers that cross a module boundary lost their leading underscore
  (`is_item_collection`, `item_host_uid`, `resolve_host_ctx`, `fill_from_stored_item`,
  `restore_action_secrets`, `apply_cred_to_config`, `merge_host_conn`) — the routes were
  already reaching for most of them through the module, which is not what a leading underscore
  claims.
- `routes.py` imports `AdminOpError` from `lib.core.users.service`, where it is defined,
  instead of through the module-config service that only passed it along.
- **`partials/cfg/_render.html` no longer needs its exemption.** It was the only file in the
  repo with one written into a test — `pytest.skip('config renderer, tracked separately')`,
  on the guard that keeps a section shell under 450 lines — and the reason given ("not a
  section shell with sub-sections to split out") was wrong on both counts. It held four:
  `_seed.html` (every option visible before it was ever saved, and the baseline that has to
  know that seeding is not an edit), `_search.html` (the one pass that decides which rows and
  sections are on screen), `_actions.html` (the buttons a section declares as data) and
  `_advanced.html` (this browser's own localStorage). 814 → 437 lines, and the skip is gone.
- **`partials/core/_field_render.html` is six partials.** At 1523 lines it was the largest
  thing in the repo that is not a language dictionary, and it was called "render a field"
  while also holding a whole object's fields, the host binding, the shared control skeleton,
  the multi-value chips and the conditional fields: `_field_scalars.html`, `_field_hosts.html`,
  `_field_ctl.html`, `_field_chips.html`, `_field_conditional.html`. What is left (833) is the
  one job the name claims.
- Both splits made the text guards read the SURFACE rather than a file — `_cfg_js()` and
  `_field_js()`, the same helper the backup section's guards already had, with the same reason
  written on it: naming the file a function happens to live in today is a guard that fails the
  next time one moves.

### Fixed
- **The Config section came up empty after that split**, and the browser guards were what
  said so: `renderConfig` used a `const wa = configData.web_admin` shorthand declared inside
  the seeding block, so moving the seeding into `_cfgSeedDefaults()` left every card below
  reading a variable from a function that had already returned. It is declared in the
  renderer now, after the call that guarantees the section exists.

## [0.0.1+build.66] - 2026-08-13

### Added
- **A restore can go table by table.** The form offered the parts a copy is made of — a curated
  grouping that answers the ordinary question and cannot answer this one: a bad import touched
  one table, and everything else on the install has moved on since the copy was taken. Putting
  the whole part back would roll the rest of it with it.
  - **An "advanced" fold** under the parts, with a group per part and a checkbox per table,
    each carrying its row count. Everything starts ticked, so opening it and changing nothing
    restores exactly what the parts above describe.
  - **Finer, not safer, and it says so.** What you leave out keeps whatever it holds today, and
    rows that point at it can end up pointing at nothing — restoring `hosts` without
    `credentials` is a decision, not an accident. The warning is inside the fold, where the
    choice is made.
  - **`tables` absent means all of them; `tables: []` means none.** Reading the empty list as
    "everything" would rewrite the whole install for a caller who asked for nothing, and the
    form never sends a list at all unless something was actually left out — an ordinary restore
    is byte for byte the request it always was.
  - **A table left out is never emptied.** A restore empties a table before refilling it;
    one that was not chosen is not touched, because emptied-and-not-refilled is the worst
    outcome available here.
  - **The parts still bound it.** Naming a table of a part that is not ticked does not smuggle
    it back in: the two narrow the same selection rather than competing for it.
- **`GET /api/v1/backups/<name>/tables`** — what one copy holds, grouped by part, behind
  `backup_view`. The grouping is the server's because `core` means "every table nobody else
  claimed", the rule that already decides what a copy holds and what a restore applies; a
  second implementation in the browser would be right until the day a part is added.
- **The restore dialog scrolls its body** (`modal-dialog-scrollable`, a third size for
  `_openBackupModal`). Reported from a screenshot: with the fold open the last group of tables
  sat under the footer and the end of the list could not be reached. Two scrollers for one
  form and the outer one missing — the dialog is a flex column with `overflow: hidden`, so a
  body that overflows is not a scrollbar but content clipped behind the buttons, while the fold
  had a capped box of its own that hid where the list ended. Exactly one scroller now, and the
  picker's `#backupModal` rule — which turns the scrolling body off so a two-pane browser can
  fill it — is scoped `:not(.modal-dialog-scrollable)`, because it is the same modal in its
  other shape.

### Changed
- **A hand-picked restore is logged as one.** The first line rises to warning and names the
  tables, the audit entry carries `only_tables` (`all` when nothing was narrowed), and the
  report afterwards says the rest was left as it is — "148 rows in 9 tables" reads as a full
  restore unless something says otherwise, and "why is half this install older than the other
  half" is asked months later.

### Changed
- **`lib/core/backup/` is one file per concept.** `service.py` had reached 1182 lines and was
  the largest module in `lib/core` — a domain describing itself inside one file. It is now the
  domain it always described, and the seams were already written into its section banners:
  - `archive.py` — where a copy lives and how it is laid out, plus how a value goes in and
    comes back. The bottom of the package; it imports no sibling, deliberately.
  - `parts.py` — what a copy can hold and which tables each part means. The vocabulary both
    directions read, so `core` ("every table nobody else claimed") is decided once.
  - `create.py` / `restore.py` — the two directions. `verify.py` — a copy against its own
    checksums, which is also its own permission. `locks.py` — the `.lock` sidecar protocol.
  - `service.py` — what is left is the shelf: which copies exist, how big, from which build,
    and removing one. 152 lines.
  - `folders.py` — the directory picker behind the backup-dir SETTING. It opens no archive,
    reads no manifest, touches no connector and its routes are gated on `config_edit`: it was
    never backup code, and it was 113 lines of a file about backups.
  - `jobs.py` — the copies and restores somebody is standing there waiting for, out of
    `runner.py`, whose docstring is entirely about a thread, a tick and a lease. Half of it
    was neither.
  - `routes_schedule.py` — tasks and retention profiles, which are their own decision with
    their own permission (`backup_schedule`). `routes.py` is about archives.
  - `lib/core/backup/__init__.py` now carries the map, so the next reader does not grep.
- **Three dead helpers removed** — `_lock_path`, `_tables_in_archive` and `_module_part` had
  no caller at all.
- The helpers that cross a module boundary lost their leading underscore (`archive_path`,
  `read_lock`, `file_sha256`, `clean_cell`/`restore_cell`, `tables_by_part`, `part_ids`,
  `DB_DIR`/`FILES_DIR`/`PARTS_PREFIX`/`INTERNAL_TABLES`): a name imported by four modules is
  not private, and pretending otherwise is how a "private" helper ends up with four callers.
- `member_tables` moved the `db/hosts.json` → `hosts` translation into `archive.py`, so the
  part grouping never has to know the archive's own layout.

### Tests
- **The fold is driven in a browser**, not only read as text: it is built from an endpoint and
  wired after the dialog is in the DOM, so whether it populates at all is not something reading
  the template can settle. A copy is taken through the panel's own API, the dialog is opened,
  and the four things only a browser knows are asked — the boxes are the tables the archive
  holds, an untouched fold asks for no list, leaving one out produces the list with everything
  else in it, and unticking a part dims its group instead of hiding it.
- **A geometry guard for the dialog itself**, measured in a deliberately short window (1280×520
  — the form is only too tall *relative to the screen*, and a desktop viewport hides the whole
  bug): something has to overflow, the body has to be what scrolls, nothing inside it may
  scroll as well, and the buttons have to stay on screen. Validated by putting the CSS back the
  way it was and watching it go red.

### Docs
- `explica-backup.md` gains *Restaurar solo unas tablas*: the three meanings of the `tables`
  field, why finer is not safer, and where the choice shows up afterwards. The restore
  flowchart and the audit table follow.

## [0.0.1+build.65] - 2026-08-13

### Added
- **Guards that measure the layout, in a browser.** The suite had 19 browser tests and all of
  them asked one question — did the page load without the browser complaining. This month's two
  sidebar bugs answered "yes" to that and were wrong on screen anyway: a column overflowing the
  page by 52px, and a collapse that blinked where the expand animated. Sizes and positions are
  arithmetic the browser does from the whole cascade, so a guard that reads the stylesheet
  cannot see the outcome.
  - **No railed section overflows its column** — measured in all three (Configuration, Modules,
    Backup), 1px tolerance for rounding. Plus the symptom as reported: the column is scrolled to
    the end and the toolbar must still sit *below* the breadcrumb that stays pinned over it, and
    the index must reach the foot of the window.
  - **Collapsing is the reverse of expanding** — nothing in the navigation hidden by `display`
    (which cannot be animated), the label fading with a declared transition, the icon beside it
    not moving while it does, and the artwork going away and coming back.
  - Measured at rest and never mid-animation: a test that samples a transition fails on a loaded
    CI machine for reasons that have nothing to do with the code. All of it validated by
    **putting both bugs back** and watching three of the six go red — a geometry guard that
    passes with and without the defect is worth nothing.

### Docs
- **`ref-pendiente.md` checked entry by entry against the code, and four of them were already
  done.** Being listed as pending is not free: it is work somebody proposes, estimates and
  starts a second time.
  - **Layouts per section** — the three "pending" ones (Servers, Syslog, History) shipped on
    2026-07-29 in `a5c724f` ("the last table sections"): four views for Servers, three for
    Syslog, two for History, in the JS bundle, documented in `ref-tests.md` §126–§128 and held
    by 64 guards.
  - **`SS_*` in the standalone services and the dedicated syslog's ipban** — shipped too:
    `overlay_all_env` exists, `services/base.py::_read_config_file` applies it for all three
    services, the notification router applies it as well, `SS_EVENTS_AUTOSTART` is honoured by
    the embedded boot, and `SyslogService` builds its jail through `ipban/factory.py`.
  - Scheduled backups as a list of tasks, and the scheduler's lease (fixed in `build.64`).
- **"No test executes JavaScript" was wrong as well**, and is now the narrower thing that is
  true: `tests/e2e/test_ui_playwright.py` loads all six served pages and fails on any console
  error, and CI installs Chromium so it runs there. What nothing measures is **geometry** —
  which is exactly where this week's two sidebar bugs lived, both on pages that loaded without
  a single console error.
- The MIB-catalogue entry now names the contradiction it depends on: the module's own docstring
  argues that its standalone SQLite file is deliberate — a local derived cache, and the
  application database may be remote. Either that reasoning still holds and the entry should
  go, or it does not and the docstring is wrong; deciding that is the work.
- The review line at the top says what to do about all of it: check what is listed against the
  code before believing it, and delete the entry in the same commit that finishes the work.

## [0.0.1+build.64] - 2026-08-13

### Fixed
- **The scheduled backup's lease had never held.** `_claim()` asked the web admin for
  `_instance_id`, an attribute no `WebAdmin` has, so the identity was always empty and the guard
  returned "take it" before reaching the store — and had it got there, `acquire()` is not a
  method of `ServiceLeaderStore` either (it is `try_acquire`), so the `AttributeError` would
  have been swallowed by the catch-all and answered "take it" too. Two ways of saying yes to
  every process, on the one code path whose whole job is to say no to all but one: four web
  replicas over one database meant four archives of the same install every tick, each pruning
  against a folder the other three were writing into.
  - The identity is now the shape its neighbours use — `backup-<host>-<pid>`, like the health
    and certificate scanners — computed once, because a lease renewed under a new id every tick
    is not a renewal but a process taking the lease off itself.

### Changed
- **The product's name lives in one place.** `lib.APP_NAME`, read by everything that signs
  something with it: the page titles, the sidebar head, the boot screen, the emails, the Teams
  cards and manifest, the webhooks, the `User-Agent` of every outbound request, the diagnostics
  report and the config warnings. It was spelt out in fifty-odd string literals across
  twenty-eight files, which is not a rename but a hand search where every hit has to be judged.
  The value is unchanged: this moves where it is written, not what it says.
  - Templates read `{{ app_name }}` from the context processor, scripts read an `APP_NAME`
    constant, and a guard (`tests/unit/test_app_name.py`) fails on any new literal.
  - **Two kinds deliberately keep theirs**, with the reason written down: identifiers registered
    in somebody else's system — the Entra app display names and the Proxmox role and user, which
    are looked up BY name in a tenant we do not own, so deriving them would mean a rename
    silently registering a second app beside the one it registered last year — and the GitHub
    repository URL. Translated prose keeps the name inline too: it sits in sentences that have
    to be re-read in every language when it changes anyway.

### Docs
- `ref-pendiente.md` reviewed end to end: dropped the two entries that were already delivered
  (scheduled backups as a list of tasks, and the lease above), and added the three that were
  missing — the `SS_*` environment in the standalone services with the syslog container's
  missing ipban, the frontend having no test that executes JavaScript (with Playwright already
  installed and two bugs this month that only a browser could have caught), and the artwork
  reading "SENTINEL NEXUS" while the panel is called ServiceSentry.

## [0.0.1+build.63] - 2026-08-12

### Added
- **The lockup fills the foot of the sidebar.** It is the one column with room going spare and
  nothing in it. Full width, and **inside** the scrolling navigation rather than between it and
  the user block: there it would be a fixed slice of the column the list never gets back. With
  slack it drops to the bottom; once the entries fill the column it scrolls below the last one.
  The head of that column keeps its glyph — the mark was tried there and taken back out, because
  with the lockup at full width below it, it is the brand twice in one column and the small copy
  is the one that cannot be read at that size.
  - It **fades** in mini mode rather than disappearing. `display: none` cannot be transitioned,
    so collapsing dropped it in a single frame while expanding let the column's .15s width grow
    it back — the same motion looking like two different ones depending on which way the button
    was pressed. Sharing that .15s, the two directions are each other's reverse. On mobile the
    drawer is full width, so it stays visible there.

### Fixed
- **Four tests that only failed in CI.** The full run reported `4 failed, 5364 passed` in
  `test_backup_service.py::TestItSaysWhatItIsDoingOnTheLog`, with an **empty** captured stdout;
  `pytest tests/unit` passed every time locally. `ObjectBase.debug` is a class attribute — one
  object for the whole process — and two ordinary things turn it off without putting it back:
  building a `WebAdmin` applies `global|log_level`, whose default is `off`, and one test sets
  `off` on purpose to prove the accessor works. With `-n auto`, whichever of those lands first
  in a worker leaves the four asserting on nothing. A `conftest.py` fixture now restores the
  shared debug state after every test, and the class states the level it needs instead of
  inheriting it. Neither the product nor either of those tests was wrong: what was wrong is
  that the next test in the process inherited the state.
- **Collapsing the sidebar is the reverse of expanding it, for the entries too.** Same cause as
  the artwork above, reported right after it: the section labels and their carets were hidden
  with `display: none`, so pressing collapse blanked the text in one frame while pressing expand
  let the widening column reveal it. They fade over the column's own .15s now, kept in flow and
  clipped by the sidebar rather than removed.
  - The icon **stops moving** while that happens. Mini re-centred it in the 56px rail, which
    rearranged the row underneath the fade; the left padding the entry already has puts it
    within a pixel of that centre (measured: 19px from the edge in both states), so holding it
    there costs nothing and removes the jump.
  - The brand row keeps `display: none` on its name, and that is deliberate: it centres what is
    left of it, so a name that merely faded would still take its width and push the hamburger —
    the one control that expands the column again — off the edge.

## [0.0.1+build.62] - 2026-08-12

### Fixed
- **A railed section scrolled the page and took its own toolbar off the top.** Reported from
  Backups — a scrollbar that dragged the rail, the first entry cut in half, and the *Reload* and
  *New* buttons nowhere on screen — but it was every section with a rail: Configuration and
  Modules alike.
  - The rail fitted its column with room to spare, so what was scrolling was not the rail: it
    was the page. `ssRailShell` named the detail column `.ss-main`, which is the name of the
    app's content column — `height: 100vh`, and the only scroll container the page has. Two
    blocks, one class, equal specificity: the later one won the properties it happened to name
    and the `100vh` stayed. A shell that begins under the breadcrumb holding a full-viewport
    child overflows the page by exactly the height of the bars above it, and scrolling that
    overflow away is what took the toolbar and the head of the rail with it. Measured in a
    browser against the real CSS: 52px of overflow, 52px of bars.
  - The detail column has a name of its own now, `.ss-shell-main`, and the three rules that were
    already meant for it (`> .ss-bleed-top` twice, `> .ss-scroll-pad`) say so instead of also
    matching the app's column. Nothing was misspelt and no rule was missing, which is why no
    guard caught it — so the guard is the name, plus the block having neither `height` nor
    `overflow`.

## [0.0.1+build.61] - 2026-08-12

### Added
- **A Diagnostics section under System.** The questions it answers are the ones a support
  thread asks, in that order: what version is this, what is it running on, where does it write,
  and what is missing. All of them were answerable before — by reading a log, opening a shell in
  the container, or knowing which library turns which feature on. That is an afternoon per
  question.
  - **Version**, the instance id, the log level, and **which services this process runs
    itself**. On a multi-container install that last one is usually "none", and it reframes
    every question about a check that did not run: it did not run *here*.
  - **System**: distribution, kernel, architecture, host, whether this is a container, CPUs,
    interpreter and its path, PID, and the time zone **with its offset** — which is what a
    timestamp that looks an hour out gets read against.
  - **Database** read from the connector the panel is actually using, not from the config: the
    interesting case is exactly when those two differ. Says whether syslog has a database of
    its own.
  - **Storage**: the three directories that matter, each with whether it exists, whether it is
    writable and how much room is left. Writability is asked of the OS, never tested by writing
    — a diagnostics page must not create anything in the directory somebody is looking at
    because it is behaving strangely.
  - **Optional features** — the card that answers most of what this page exists for. A panel
    where the SSO button never appears, or every SNMP check is skipped, is almost never
    misconfigured: the library is not installed, the feature switched itself off, and nothing
    on screen said which.
  - **Dependencies**, read from `requirements.lock` and not from `pip freeze`: the lock is what
    the install was built from, so "installed 3.1 where the lock says 3.4" is a fact about this
    deployment. Three verdicts and no fourth — "newer" is deliberately not one, because a
    deployment that drifted upward drifted.
  - **A report to send**, in `txt`, `json` or `xml` (`/report?format=`), from the same
    collectors — a second gathering pass per format is how two reports of the same install come
    to disagree. Text is the default because the destination is usually a comment box and it
    can be read before it is sent; the other two are for the destination that ingests them,
    where the alternative is somebody writing a parser for prose. An unknown format falls back
    to text rather than refusing: it is a link somebody clicks. The XML is built with
    `ElementTree`, so Windows paths and version strings are escaped by something that is not
    hand-rolled, and a list field becomes repeated children rather than a stringified Python
    list.
  - The dependency fold **on screen** holds the ones that match, never the whole list: the
    differences are already open above it, and repeating them underneath showed the same
    package twice with the same badge — which reads as two findings and makes the open table
    look like a summary of something longer rather than the whole of what is wrong. The
    **report** lists them all, differences first: a section that shows nothing because nothing
    is wrong reads as a section that failed to collect.
  - **The update check never runs on its own.** No poll, nothing at boot, nothing while the
    page paints — a monitoring panel gets installed on segregated networks by people who would
    rather it did not talk to anybody. It happens on a click, over HTTPS only, with a short
    timeout, and is audited whether or not it succeeded: a check that failed still made the
    attempt. Its address is a config field, so a fork or an internal mirror needs no code
    change and the one host this panel will contact is visible in the config screen.
  - **Nothing published yet is not a broken endpoint.** `/releases/latest` answers with the
    newest *published* release and excludes drafts and prereleases, so a repository whose only
    release is either — which is this one's state today: a single draft tagged `test` — has
    nothing to return. Reported as its own answer instead of "HTTP 404", which sends somebody
    to check the URL, the one thing that is not wrong. A 403 stays an HTTP status, because rate
    limiting is acted on differently.
  - It reports **"cannot tell"** when both sides carry the same semantic version. That is this
    project's normal state — the counter after `+build.` does not participate in precedence —
    and answering "up to date" there would be a guess dressed as a fact on the one screen whose
    whole job is not to do that.
  - One new permission, `diagnostics_view`, granted to nobody by default: the page holds no
    secret but does describe the shape of the install.
  - The domain is split by **what an answer depends on**, not by file size: `collect` needs
    only the process and the disk, `service` needs the running panel, `report` needs only what
    those two returned, and `routes` is left with three declarations, a permission and an audit
    line. Only the middle one can be wrong in a way that depends on how the install is
    deployed — and the serialisers, being pure, are tested without an app at all.
  - Three things found by looking at the first render: the lock parser carried
    `pip-compile --generate-hashes`' trailing `\` into the version, so **all forty-one** pinned
    packages reported "a different version installed" — a screen that is wrong about everything
    is one people doubt last; the pane stacked two different full-bleed mechanisms, so its
    toolbar sat at other margins and other corners than every other section's; and two columns
    of label-left / value-right put a value flat against the next pair's label — "Windows 10
    Kernel" reading as one field with a strange name — which is a missing gutter and not a
    missing rule, in both the system block and the optional-features one.
- **The brand artwork, on the login card and in the boot ring.** Both were a Bootstrap icon
  standing in for a logo that did not exist yet.
  - **Two derived files, not one.** The lockup is landscape and the boot ring is a 96px circle,
    so the ring gets the mark alone — a wordmark shrunk into that is a name nobody can read.
  - The 2 MB master lives in `assets/brand/`, outside `src/` so it is not packaged, with the
    two `magick` commands that produce what ships. A committed binary with no source is a dead
    end: nobody can re-export it at another size or retouch it without starting over — the same
    reason the favicon has `tools/make_favicon.py`.
  - Served at **76 KiB and 38 KiB**, quantised to 256 colours. The login page is the first
    thing anybody sees, and full colour costs 305 KiB for no visible difference on neon
    artwork.
  - **The transparency is kept**, which is what lets one file work on the light theme's card
    and on the dark backdrop without a black plate behind it. Flattening it is what an
    optimiser does when nobody is watching, and the result passes every other check — so a test
    states it.
  - `width`/`height` are the files' own pixels, so the browser reserves the box before the
    image arrives. The login card must not jump under the cursor while it loads.
  - The heading under the lockup is gone: the artwork carries a wordmark, and printing the name
    again underneath is the same word twice in two typefaces. So is the subtitle beneath it —
    it was `admin_panel`, the sidebar's label for a **section** ("System"), which read as
    "ServiceSentry / System" under the old heading and as a stray word under a logo.

## [0.0.1+build.59] - 2026-08-12

### Changed
- **Retention answers "how far back", not "how many".** A single counter was the whole
  vocabulary, and seven copies can be one week at daily resolution or two years at monthly —
  only the second survives finding out in March that something broke in January.
  - A task now carries **buckets**: keep the newest of the last N days, N weeks, N months, N
    years, plus the newest N whatever the calendar says. A copy survives if **any** rule claims
    it, which is what makes "7 daily + 4 weekly + 6 monthly" cost 17 copies instead of 180.
  - **The old single counter still means what it meant.** A task written before this holds only
    `keep`, and it is read as "the newest N" rather than migrated: a task that was working must
    not need rewriting to go on working, and a migration is a thing that can go wrong once per
    install. The API still accepts it too.
  - All of them zero still means **keep everything**. An operator who prunes elsewhere must be
    able to say so, and reading "no rules" as "delete them all" is the reading that loses data.
- **Two floors no bucket can express.** The **newest** copy is never deleted — a policy that
  leaves a task with nothing has misconfigured the one thing it exists to provide — and neither
  is the newest **good** one: a run of `partial` copies would otherwise push the last `ok` one
  out, leaving seven copies of which none is usable. The verdict already travels inside the
  archive, so this costs a lookup and no guesswork.
- **Retention runs on every tick, not only after a copy.** A monthly task went a month without
  its rules being applied and a disabled one went for ever, its copies outside every counter.
  Switching a task off says "stop making new ones", not "freeze the old ones and let them
  grow".

### Added
- **A size budget per task** (`max_size`). The buckets say what is worth keeping; this says what
  there is room for, and it runs last so it can only ever take away what the rules already
  chose — with the floors applied again afterwards, because running out of room is not a reason
  to be left with nothing. When the ceiling and not the calendar is deciding what survives, it
  is audited (`backup_budget_exceeded`) and notifiable: it means the policy asks for more
  history than there is room for, which somebody should get to revisit rather than discover
  later as a gap.
- **A preview in the task form**: what this policy would keep and delete, against the copies
  that exist right now, with the total size of what survives. A bucket policy is not something
  anybody evaluates in their head, and one nobody can predict is one nobody dares touch. It is
  answered by the server with the **same pure function the scheduler uses** — a preview worked
  out a second way would be a preview that lies on the day it matters.
- **Copies whose task no longer exists get their own rail entry.** Deleting a task never
  deleted its copies — they are backups, and the task was only the reason they exist — but
  retention stopped applying and they grew counted by nobody. Shown rather than pruned:
  inventing a policy for what has no owner is how the copy from before the migration
  disappears.
- **Retention profiles**: a named policy several tasks share, with its own rail entry. Five
  numbers and a ceiling retyped from memory in every task were three chances to type 6 where the
  others say 4, with nothing on screen ever saying they disagreed.
  - A task **follows** a profile rather than copying it, so editing "standard GFS" changes the
    retention of every task pointing at it at once. That is the whole reason to have profiles
    instead of a button that fills the boxes in.
  - The resolution happens in **one place** (`schedule.with_profile`); everything below it —
    `survivors`, `prune`, the preview — is written against a task that already knows which
    numbers are its own. A second place deciding that is a second place for the scheduler and
    the screen to disagree about what is about to be deleted.
  - A profile **replaces** the policy, it does not merge with it: one that says nothing about
    monthlies means none. The task's own numbers stay stored underneath — hidden, not cleared —
    so unlinking gives it back the policy it had, and a profile that disappears some other way
    leaves them standing rather than reading as "no rules", which means keep everything.
  - Deleting a profile a task still follows is **refused, naming the tasks**. Letting it go
    would move them onto whatever numbers they last held: a change of policy nobody asked for
    and nothing announces.
  - The task list now travels with the rules that **actually apply** to each task, resolved by
    the server. A linked task carries two sets of numbers, and a screen picking between them
    itself would be a retention screen guessing.
  - The editor offers **starting points** (`suggested`) that come from the API, not from the
    template: they are the panel's opinion about how much history is worth keeping, and an
    opinion written into a page is one the API cannot state.
  - All of it rides on `backup_schedule` — editing a profile *is* editing several tasks'
    retention, which is exactly the decision that flag already covered. No new permission.

- **A copy can be locked.** Retention answers "how much history" and its two floors answer
  "never leave the task with nothing"; neither can say *this particular archive* — which is what
  somebody means about the copy taken before a migration, or the last one known to be good. A
  locked copy is skipped by retention **and** refused by the delete button, with the row
  offering the padlock instead.
  - The flag is a **file beside the archive** (`<copy>.zip.lock`, carrying who and when), not a
    column. The listing reads the directory precisely so there is no second source of truth
    about files somebody can move with the panel stopped — and a lock in a table would be one,
    with the failure mode of a row claiming an archive that is no longer there is protected.
  - **A damaged marker still counts as locked.** Its existence is the flag and its contents are
    a courtesy; reading a broken courtesy as "not protected" fails in the one direction a lock
    must not.
  - The refusal lives in the **service** as well as the route, so a caller that works out the
    doomed list some other way still cannot delete it — and the route answers 409 saying why,
    because "not found" would be a lie about a file that is right there.
  - A locked copy **still claims its bucket** (filtered at the end, not hidden from the rules,
    so protecting one does not silently buy an extra) and **spends its size** against a budget
    that can never drop it.
  - Sidecars now go with the archive when it is deleted. A leftover `.lock` would make a later
    copy of the same name born protected, never pruned, with nothing on screen explaining why.
  - `backup_delete` in both directions: the lock only affects whether an archive can be
    destroyed, and unlocking is asking to be able to destroy it. It is a guard rail against
    retention and against the wrong row, not protection from an administrator.
  - The lock button carries the state in its **colour** — cyan while locked, grey while not —
    because the same icon in two greys is a button you have to read to know which way it goes.
    It is the padlock's own colour in the name column, so one colour means one thing on the row.
  - The delete button is **disabled, not removed**, on a locked row. Taking it away shortened
    the row and shifted the whole group, so a locked copy read as a different kind of row rather
    than as the same row with one action unavailable — and a disabled control can say why in its
    tooltip, which a missing one cannot.

### Fixed
- **The scheduled-task form no longer scrolls.** It said three independent things — when it
  runs, how long its copies are kept, what they hold — stacked in one column, and had grown to
  nine hundred pixels of dialog with a scrollbar down the middle of a form. They are now three
  tabs, read at the moment each is needed; the name stays above them, because it identifies the
  record all three describe and is what the retention preview counts against. A long pane
  scrolls **inside** the box (`.ss-tabbox`, generic, not per-id) instead of stretching the
  dialog past the viewport.

## [0.0.1+build.58] - 2026-08-09

### Changed
- **Scheduled backups are a LIST of tasks, not one interval.** Each task says what to copy, how
  often and how many to keep. The case it exists for: configuration and inventory are worth a
  daily copy, the syslog and the MIBs perhaps weekly — and with a single schedule that cannot be
  said without copying everything at the pace of the most demanding part, which is how a disk
  fills.
  - **The section navigates by the same rail Configuration and Modules use**, and it earns its
    width because each TASK is an entry: selecting one shows the copies *it* took. That is what
    makes per-task retention visible instead of something to deduce from file names — the
    schedule says "keep 4" and the entry says how many there are. A rail holding only "schedule"
    and "copies" would have been two clicks for two lists.
  - Which copies belong to a task is decided in **one** place, so the count on the entry and the
    rows in the pane cannot disagree. The browser's slug and the server's `task_slug` are the
    same rule for the same reason: two implementations is how a task's copies stop being found
    by the screen that lists them.
  - Tasks live in their **own table** (`backup_tasks`). A task is a record an operator creates,
    renames, disables and deletes one at a time, like a webhook or a host; `spec.py` holds
    scalars somebody tunes, and a list of things somebody keeps belongs where the other lists
    are.
  - **Retention is per task**, and this was the reason for the whole redesign: with one shared
    counter the daily task prunes the monthly one's copies — deleting exactly the ones that took
    a month to become worth having. The copy's NAME now carries the task that took it
    (`auto-<task>-<date>`), and the counter is scoped to it.
  - Copies taken before tasks existed (`auto-<date>`) are still recognised, by the unnamed task
    rather than by any named one. Without that the upgrade would have left every copy already on
    disk outside every counter — never pruned, and never counted as "the last one" either.
  - A task's name is reduced to what may appear in a file name before it is used as one: a task
    called `../etc` would otherwise steer where its own copies are written.
  - **One lease for the whole round, and tasks run one after another.** Two due at once on two
    processes would each copy the same install; two at once in one process would read every
    table twice and write two archives at the same disk.
  - **A task says when its own way: every N hours, or days of the week at a time of day.** The
    interval was the whole vocabulary and it could not say "Mondays at 03:00" — but it is the
    shape that survives the panel being down, so the calendar had to keep that rather than
    replace it. It does: the question asked is *"has the last window passed with no copy since"*,
    which is true from the moment the window passes until a copy is taken. A panel that comes
    back at 09:00 still takes the 03:00 copy, and a tick every ten minutes catches it as well as
    a tick every minute would. Asked the naive way — *"is it 03:00 now?"* — it would be false
    1439 minutes out of 1440 and miss the window entirely whenever the process was not up for it.
  - No day ticked means **every** day, never "no days": a task somebody created that silently
    never runs is the failure this whole feature exists against. A day the calendar cannot
    match is dropped at the door for the same reason.
  - A task with no `mode` at all is an interval one — that is what every task was before the
    calendar existed, and an upgrade that stopped running them would be a schedule switched off
    without anybody saying so.
  - The three settings this replaces (`backup_every_hours`, `backup_keep`,
    `backup_auto_secrets`) **migrate into a task** the first time the scheduler finds none —
    once, audited, and only when something was actually scheduled. Retiring them outright would
    have turned a configured schedule into no schedule at all, and a copy that quietly stops
    being taken is discovered when it is needed.

### Added
- **The schedule and the verify are grants of their own.** Both rode on permissions about
  ARCHIVES and are not about archives at all: `backup_schedule` covers creating, editing and
  deleting tasks — a task edited to run monthly instead of daily destroys no file and quietly
  halves the protection, and deleting one stops the copies without deleting a single one — and
  `backup_verify` covers checking a copy, which writes nothing but walks every member of a
  multi-gigabyte archive and hashes it. *Run now* deliberately stays on `backup_create`: it
  produces a copy exactly like the Create button, and one grant should not be two ways to the
  same result. The buttons follow the same flags, because a button that 403s says the panel is
  broken rather than that the grant is missing.
- **A copy says what it holds and whether it worked, and can prove it later.**
  - **A checklist per part, with its outcome and its row count**, written into the manifest as
    the copy is made — and an overall verdict derived from it: `ok`, `partial` when some part
    failed, `error` when they all did. A percentage says how far along; it cannot say what
    actually made it, which is the only question afterwards. The verdict goes in the audit line
    too: "it ran" is not the same as "it worked".
  - **sha256 per member, plus a `.sha256` sidecar** in the format `sha256sum -c` reads, so a
    copy can be checked away from the panel that made it. The digest of the archive cannot live
    inside the archive, hence the sidecar — written after the file is closed. `Verify` compares
    the file against its own manifest and reports which member drifted, not just that one did.
  - **A Details dialog on every copy**: when it was taken and by whom, the version and engine
    that wrote it, whether it carries secrets, the per-part checklist, the tables it holds
    biggest-first, and the digests. Everything is read from the manifest the archive carries —
    a verdict worked out at display time is a verdict that did not travel with the file.
- **Copies in progress are visible while they happen.** Both kinds — the scheduled run and the
  hand-made one — start a job and report against it: a row appears in the list it belongs to
  the moment the button is pressed, with the table being copied and a bar, and a dialog for
  whoever wants to watch it. Held-open requests were the alternative, and a copy of a large
  install takes minutes: long enough for a browser or a reverse proxy to give up, leaving the
  operator unable to tell whether it worked.
- **The copies table sorts by its columns**, through the same header renderer every other list
  in the panel uses — a table that sorts differently from its neighbours is one somebody has to
  learn twice.
- **The *Contents* column gives way to a *Status* one.** Contents repeated the same four part
  labels on every line — a column that says nothing about the copy in front of it, now that the
  Details dialog lists them properly. *"Is this copy any good"* is the question you actually ask
  of a list of backups, and it was answerable one copy at a time by opening a dialog.
  - It sorts by **how bad the answer is**, not by its name: alphabetically the order would be
    error, ok, partial, which puts the two answers that need attention either side of the one
    that does not.
  - A copy taken before verdicts existed reads **"not recorded"** rather than green. A badge
    calling a copy nobody ever checked good is the one lie this column could tell — and the
    Details dialog gives the same four answers, so the two can never disagree about one file.
  - **No secrets** stays as a mark beside the name instead of joining the column: a copy taken
    without credentials was taken *correctly*, so calling it anything but good would be wrong —
    and it will still restore credentials that authenticate against nothing, which is found out
    at restore time and that is too late.

### Fixed
- **The copy ignored the second database, so restoring brought no syslog back.** With
  `syslog_db|enabled` that feed lives in a database of its own, and the backup only ever read
  the system one: the `syslog` part found no such table, copied nothing, reported nothing wrong,
  and the emptiness surfaced at restore time — the one moment nobody can afford to find out.
  It only ever failed with that option on, which is why the default install never showed it.
  - A part now declares which database it belongs to, and both directions take a map of
    connectors the web admin fills in — only when the syslog connector really is a different
    one, because with the option off it hands back the main one.
  - `core` stays "every table nobody else claimed" **in the system database**, so nothing from
    the second one is swept into it and restored to the wrong place.
  - Restoring groups by database and gives each **its own transaction**: two databases cannot
    share one, and the guarantee that matters — the system tables land together or not at all —
    is kept where it means something. Bulk log data landing separately locks nobody out.
  - A second database that cannot be reached costs its own part and nothing else. The copy of
    everything else is still worth having.
- **A restore left the other containers running on settings that no longer existed.** It
  replaces the whole `config` table, and on a multi-container install the workers only find out
  on their next poll of the shared database — fifteen seconds of a scheduler running the old
  check list. They are poked now, the same way a config save pokes them, and for every service
  rather than the ones whose section "changed": a restore replaced all of them.
- **The progress dialog sometimes never opened, so the click looked like it did nothing.**
  Bootstrap ignores `show()` during a hide transition, and the check for "is the form still
  up?" was the `show` class — which comes off at the *start* of the hide while
  `hidden.bs.modal` only fires at its *end*. In between there is no class to test and no event
  left to wait for, and the reply to the request that starts the job lands in exactly that
  window. It now waits for the event **and** a floor, whichever answers first, once.
- **A copy and a restore left no trace on the log.** They take minutes, run on a thread and
  rewrite the install — and they went past in total silence, so a screen that failed to open
  its dialog left nothing anywhere to say whether anything had happened at all. Both are traced
  now through the panel's own `Debug`, so `global|log_level` governs them and there is no second
  logging path: what was asked for and how it ended at **info**, one line per table at
  **debug**, and at **warning/error** the refusals, the parts that failed, and *what could not
  be applied on restore* — the line somebody greps for when a copy from another build left
  something out. Background jobs carry their id from start to finish.
- **Restoring showed nothing until it was over.** It was awaited, so on an install whose tables
  run to six figures of rows the dialog sat there saying nothing while every one of them was
  replaced — the moment where silence is most alarming, because what it is silent about is the
  install being overwritten.
  - It goes through the **same job the copies use**: a bar, the table being written, and the
    outcome when it lands. One shape, because the two are the same wait to whoever is watching.
  - **The same checklist the copy shows**, one entry per part with its rows and its outcome,
    ticked off as it goes and kept when it ends. The part is the unit somebody chose in the
    form, so it is the unit they want reported back; "148 rows" left them to work out which of
    the six things they asked for had actually arrived. A part is *not* ok when a table it
    holds is gone or a field was dropped — which is exactly the case where rows went in and
    something was still lost — and it keeps the FIRST reason, because the first thing that went
    wrong explains the rest.
  - No row appears in the list of copies. A restore adds nothing to it — it replaces what the
    install already holds, and a row would be the screen inventing a copy that is not being
    made.
  - **The reload waits for the dialog to be closed.** Everything on screen was read before the
    tables changed under it, so the page has to be re-read; doing it while the outcome is still
    being read would sweep away the one thing somebody has to see. Nobody watching means it
    happens straight away.
  - A copy that is not there is **refused before any of it starts**, and still audited. A
    progress bar for something that was never going to happen is worse than an error.
- **Restoring a copy from another build said nothing about it.** The archive's *format* was
  checked and the app version was not, so a copy from any build restored in silence — and
  restoring one from a LATER build drops the columns this schema does not have yet. Silent is
  what turns a version jump into data loss instead of a decision.
  - The restore dialog now **names both sides of the jump** before the button: a plain line for
    an older copy, a warning for a newer one saying what it will drop.
  - The result **says what did not survive the trip**: per table, the columns the live schema
    could not take, or that the table itself is gone and how many rows went with it. It comes
    up as a dialog, not a toast — a toast says a number and disappears, and this is the one
    thing somebody has to read. The page reload that follows a restore waits for it to be
    closed.
  - The same goes into the **audit line**, with the build that made the copy. A restore is the
    moment nobody is looking ten minutes later, and *"which columns went"* is the question that
    gets asked months afterwards, when the answer on screen is long gone.
  - Still **nothing is refused over a version**. The schema moves on almost every build, and a
    panel that turned down "old" copies would be useless on the one day it is needed. Nor are
    there migrations on restore: rewriting rows according to what one build assumes about
    another is the kind of code that breaks the copy while applying it, and the single
    transaction already gives the guarantee that matters — all of it, or none.
- **The backup knew about one module's files because its path was written into the core.**
  `var_dir/snmp_mibs/raw` sat in `lib/core/backup/service.py`, which is the core naming a
  module — the one thing this codebase does not do. It held the SNMP module's files and would
  have missed the next module's, silently, the way a backup that skips what it did not
  recognise always does.
  - A module declares it now, in its own `schema.json`: `__backup_part__` gives an id, a
    directory **relative to `var_dir`**, the key to its label in the module's own lang files,
    and whether the form pre-ticks it. A list contributes several.
  - The declaration **stays inside `var_dir`**: an absolute path, a rooted one or anything that
    climbs out with `..` is dropped. That directory is read when a copy is made and **written**
    when one is restored, so a declaration that escaped would let a module choose where the
    panel writes.
  - It also cannot take a core part's id. A module shadowing `core` would replace the copy's
    tables with a directory.
  - Inside the archive a module's files live at `files/parts/<id>/`, derived from the id on
    both sides so a copy and a restore cannot disagree about where they are. On restore they go
    where the module says they live **today**; a module that is no longer installed has its
    part skipped rather than unpacked into a directory nothing reads.
  - The label travels already translated, because the wording lives in the module's lang files
    and the browser's catalogue does not hold them — the key alone would have put
    `backup_part_mibs` on screen.
  - **Tables needed no such hook**: `core` is every table no other part claimed, so the ones a
    module creates at runtime were already in the copy. This was only ever about files.
- **The progress dialog closed itself the moment the copy ended.** That is the instant its
  outcome is worth reading, and the window somebody deliberately opened to watch the copy was
  taken away at exactly the wrong moment — leaving a toast as the only trace of a run that may
  have lost a part. It now replaces the bar with the verdict, the checklist that produced it and
  a way into the copy's full detail, and waits to be dismissed.
- **The hand-made copy showed nothing at all until it finished.** It awaited the request while
  the scheduled runs had had a progress row for a version — so the one started by a person
  standing there watching was the one with nothing to watch. Both go through the same start
  now: one path, because a second one is a second place to forget the bar.
- **A copy suggested by hand could collide with the one before it.** The proposed name stopped
  at the minute, `create_backup` refuses to overwrite, and the moment you take two by hand is
  the moment you are trying something and repeating it — so the second failed on a collision
  the operator did not cause and could not see. It carries seconds now, like the scheduler's
  names always have.
- **`prune` deleted newest-first while its docstring said oldest-first.** It does not change
  what is deleted, but a run interrupted half way should free the least useful copies rather
  than the ones nearest to being the last good one. Found by a test written against the
  documented behaviour.

## [0.0.1+build.57] - 2026-08-08

### Added
- **A Backups section, and copies that take themselves.** Full or partial, made by hand or on a
  schedule, with restore.
  - A copy is a **zip of JSON, not a dump of the database file**. The panel runs on four
    engines and the copy has to survive the move: an install that grew on SQLite and is being
    lifted onto MySQL is exactly when a backup is asked for, and a `.db` answers that with
    nothing. Rows out and rows in, through the connector both ways.
  - What a copy holds is one declaration (`PARTS`), read by the API, the form and the restore
    alike. `core` is **everything no other part claimed** — inverted on purpose, so a table
    added tomorrow, including the ones modules create at runtime, is in the backup instead of
    being silently missed. A backup that quietly skips what it did not recognise is the failure
    you find out about once.
  - **Secrets are a choice per copy**, and the manifest records which it was: one that holds
    none but looks complete is discovered at restore time. Leaving them out blanks every value
    stored encrypted **at any depth** — the secret is a value inside a JSON column, so a pass
    over column values alone would ship it while reporting a copy that holds none.
  - **Restore replaces, never merges** — merging would produce a third state that never existed
    — and runs in one transaction: users back with roles not back is an install nobody can log
    into. A column the live schema has since dropped does not sink it, because the backup
    somebody reaches for is an old one.
  - **Five permissions, not one.** Downloading is not "viewing": the archive is the whole
    install in one file, so whoever may fetch it holds the install. Restoring is not "creating":
    it overwrites users and roles. Every action is audited, download included.
  - **Automatic copies on an interval**, with retention. An interval and not a time of day
    because a panel that was off at 03:00 must still take its copy when it comes back at 09:00.
    Retention only ever prunes automatic copies — one somebody took before an upgrade is not
    something a counter gets to throw away — and prunes **after** the new copy is on disk, so a
    full disk cannot leave fewer copies than the run started with.
  - **Where they land is configurable** (`web_admin|backup_dir`, `SS_BACKUP_DIR`), with a folder
    picker beside the field. The default — beside the data it copies — survives a human mistake
    and nothing else.
  - The picker hangs off a generic registry keyed by config path: the field renderer draws two
    hundred fields and must not know that one of them is a folder.

### Fixed
- **`apiPost` / `apiDelete` hand back `{status, data}`, not the body.** The new section read
  `res.ok` off them — a key that is never there — so every request that worked announced
  itself as an error, and a delete said "save failed" with the file already gone.
- **`create_backup` reported an unusable folder instead of raising.** `os.makedirs` sat outside
  the try, so a configured path that cannot be created escaped a function whose contract is to
  report failure as a value — and would have taken the scheduler thread down with it.

## [0.0.1+build.56] - 2026-08-06

### Changed
- **A stopped module is visible at a glance in the table view.** Switching one off changed a
  badge from green to grey and nothing else — one cell out of five, read only by whoever
  happened to be looking at that column. The card views have always dimmed the whole card for
  this; the table said it in a corner.
  - The row now carries the state: **the whole row is tinted**, a bar runs down its leading
    edge, and the module's name and id step back to the muted ink. Unavailable gets the same
    treatment in warning, so the two states that are not "running" are told apart at the same
    glance rather than by reading two badges.
  - Off **darkens** in both themes rather than following one recipe: on the dark surface a
    lighter row reads as selected, which is the opposite of what this says.
  - The *Stopped* badge is inverted — foreground ink as the fill, the page colour as the text.
    It was `text-bg-secondary`, a grey pill, and with the row now tinted grey the one cell that
    states the answer had become the least visible thing in it. The contrast comes from the
    inversion and not from a hue: red is this panel's word for something that broke, and a
    module switched off deliberately did not break, while amber is already the answer beside it.
  - The tint goes through `--bs-table-bg-type`, the variable `.table-striped` uses, which
    Bootstrap resolves *after* `--bs-table-bg-state`. Painting the cells directly would have
    won over the hover and left these rows dead under the cursor. The bar is a pseudo-element
    for the same kind of reason: a border would shift that cell's text out of line with the
    rows above and below, and the inset-shadow slot is where the tint is painted.
  - The row is **not** dimmed wholesale. A table cannot do what the card grid does here: the
    switch and the delete button are exactly as usable on a stopped module as on a running one,
    and greying them says they are not. The badges and counts keep full strength too — they are
    the row's answers, and a stepped-back answer is harder to read for no gain.
  - `.ss-row-off` / `.ss-row-warn` are generic, not scoped to Modules: any table listing things
    that can be off or unusable wants the same two marks.

## [0.0.1+build.55] - 2026-08-06

### Fixed
- **Saving the modules form redraws it.** Switch a module off, press Save, and in the
  list-and-detail view it stayed under *On* until the next reload — the save had worked, the
  screen had not caught up, which is the worst of the two failures because it looks like the
  save did not.
  - `toggleModule` writes `enabled` and marks the form dirty, and stops there **on purpose**: a
    row that jumps to another group under the cursor while you are still deciding is worse than
    one that waits. Nothing else moved it, so the save was the moment it should have — and
    that was the one thing the save did not do.
  - Latent since long before the grouping: every view was drawing state that could be stale
    after a save. Nothing showed it until a view started arranging modules *by* the thing being
    saved. The fix is one call, because every view re-reads from `modulesData`.

## [0.0.1+build.54] - 2026-08-06

### Changed
- **Modules' list-and-detail view now navigates by the same rail Configuration does.** Two
  sections had the same shape — an index down the side, one thing open beside it — drawn two
  different ways: Configuration had a grouped rail with counts, Modules a flat `list-group`
  with a state dot. Now there is one rail.
  - **The module tile shows in the list.** Every other view drew it — the table, the compact
    cards, and this view's own detail header — so the one whose entire job is picking a module
    from a list was the only place you could not recognise one by its icon.
  - **Items are grouped by state** (on / off / unavailable), which answers "which of these is
    off?" before anything is clicked. That retires the state dot: three colours of a 4px
    circle said what three headings now say in words, and the row got its width back. An empty
    state leaves no heading behind, and a filter that matches nothing says so in the rail
    rather than emptying it silently.
  - The count keeps its meaning and its colour — warning when a module has items switched off,
    plain otherwise — but is drawn without `_modCountBadge`: that badge carries the per-module
    id `_refreshModuleCount()` writes into, and the detail header beside the rail already
    draws it. Two nodes with one id and the refresh updates whichever comes first.
  - The rail's CSS moved from `.cfg-rail*` to **`.ss-rail*`**. Configuration is no longer its
    only user, and a second copy under a second name is how two lists that should look
    identical stop looking identical.
  - A selected item paints itself a solid accent colour, where the tile's `.14`-alpha hue tint
    all but disappears and its mid-tone glyph goes muddy. On that row the tile borrows the
    row's own foreground instead: same shape, same place, no longer coloured against a
    background it cannot be seen on.
- **…and by the same shell, so the two screens are one panel.** Side by side the difference was
  not the rail: Modules floated inside the content padding with a strip of page background all
  round it, and its toolbar spanned the full width — over the index as well as over the module
  being edited, when reload, save and *add module* are about the latter.
  - The toolbar is now `.ss-bleed-top`, so it belongs to the top edge of the section instead of
    floating inside its padding, and in the list-and-detail view it **moves into the detail
    column**: the index runs the full height of the pane beside it rather than starting below
    the bar.
  - The shell builder is now **`ssRailShell()`** in `core/_utils.html`, and Configuration was
    moved onto it. It had been written once for Configuration; a second copy for Modules is how
    two screens that must look identical stop looking identical. It gained one thing
    Configuration never needed — it can be taken back **down**, because Modules has four views
    and only one is this shape.
  - Which view wants it is declared in the view registry (`shell: true`), not tested for by
    name in the renderer: the registry stays the one place a view is described.
  - The open module's header is the same **`.ss-sheet-head`** a configuration section wears. It
    was `.ss-thead` — a table-header grey against Configuration's card-header blue — and it ran
    edge to edge where Configuration's sits inset with a rounded bottom. Both sit in the same
    column, under the same toolbar, as the first thing below it, so a colour a shade off and a
    width a gutter out was the whole difference between one panel and two screens that merely
    resemble each other.
  - **The pinned bar goes up and down with the shell.** Pinning it to the top edge is what the
    shell wants — it is the head of the detail column, with the open module's header attached
    under it, and a `.ss-toolbar`'s 1rem bottom margin there becomes a strip of page background
    between the two: two bars with a crack down the middle rather than one head. Over a grid or
    a table the same bar wants to be what it was, rounded and with air under it. Baking the
    bleed into the markup gave the seam to one view and took the air from the other three, so
    it follows the layout instead. Configuration always has the shell, so nothing there moves.
  - `.cfg-shell` / `.cfg-main` / `.cfg-rail*` / `.cfg-sheet-head` were renamed **`.ss-*`** for
    the same reason, and the guards that named them moved to where the behaviour now lives.

## [0.0.1+build.53] - 2026-08-06

### Changed
- **The artifact actions move to v5, off deprecated Node 20.** Every run raised four warnings:
  `upload-artifact@v4` and `download-artifact@v4` still declare Node 20, so the runner was
  already forcing them onto Node 24. The warning is the notice period — when it ends, those
  steps fail rather than degrade, and they are what carries the `.deb`/`.rpm` from `packages`
  to `packages-install` and `release`. Every other action was already current.
  - The three call sites name a single artifact with an explicit `path`, the one usage shape
    v5 leaves untouched, so the bump is version-only.
  - Node 24 needs glibc ≥ 2.28 to run inside a job `container:`, which the install matrix
    (Debian 13, Ubuntu 24.04, Fedora) satisfies with room to spare.

## [0.0.1+build.52] - 2026-08-05

### Security
- **Every dependency moved to its latest stable, and the lock now audits clean.** `pip-audit`
  over `requirements.lock` found **4 advisories in 2 packages**; there are now **none**.
  Thirteen packages moved, four of them across a major, with **no transitive additions or
  removals** — the resolution did not drag anything in behind the upgrade.
  - **`cryptography` 48.0.1 → 50.0.0** clears three. Two of them were reachable here rather
    than theoretical: a constrained intermediate CA could be escaped with a wildcard SAN
    (CVE-2026-69248), and a chain carrying duplicated self-signed certificates blew up
    exponentially (CVE-2026-69249) — both through certificate-chain verification, which is
    exactly what the `ssl_cert` module does against servers nobody here controls. The third
    (a Bleichenbacher oracle in `pkcs7_decrypt_*`) does not apply: no third-party
    `EnvelopedData` is decrypted.
  - **`paramiko` 4.0.0 → 5.0.0** clears CVE-2026-44405 (SHA-1 allowed in `rsakey.py`). That
    one was documented in build.39 as *having no fixed release*; 5.0.0 is that release.
  - The floors in `requirements.txt` went up with them (`cryptography>=50.0.0`,
    `paramiko>=5.0.0`) **and carry the reason inline**. A floor with no explanation is one that
    gets lowered to "fix" a resolver conflict, which is how a CVE comes back.
  - `docs/explica-seguridad.md` gained a *CVE de dependencias* section: how the audit is run
    (against the **lock**, because that is what ships — image, packages, `install.sh`), what
    each advisory was, and which ones actually reached the panel.

## [0.0.1+build.51] - 2026-08-05

### Fixed
- **The `.deb` failed to configure on Debian 12, and the error blamed the network.** The
  postinstall's `pip install` died with *"In --require-hashes mode, all requirements must have
  their versions pinned"* — nothing to do with connectivity. The lock is generated on Python
  3.14 and its hashes put pip in `--require-hashes` mode; Debian 12 ships 3.11.2, where
  `redis` turns on `async-timeout` through the marker `python_full_version<"3.11.3"` — a
  dependency the lock has no entry for, and in that mode an unpinned requirement is fatal.
  - The postinstall now checks the interpreter **before** creating the venv and refuses with
    the actual reason and the affected distros, instead of failing 200 lines into pip output.
  - Its generic failure message stopped asserting the cause. It said "fix the network/proxy",
    which is what sent this one looking in the wrong place; it now points at the pip output
    and lists the usual reasons without picking one.
  - Documented in `caso-despliegue.md`: the packages need Python ≥ 3.11.3, Debian 12 and older
    are out, and Docker or `install.sh` is the route on those.

### Changed
- **The package install matrix tracks current distros**: Debian 13 instead of 12 (which is
  below the interpreter floor above), and `fedora:latest` instead of a pinned release —
  pinning one means testing an EOL distro within a year, which is worse than a moving target
  for a check that only asks "does this install".

## [0.0.1+build.50] - 2026-08-05

### Fixed
- **The packaging scripts were committed without their executable bit**, so the runner
  answered `Permission denied` and the `packages` job died at build. `chmod +x` on a Windows
  checkout changes nothing git records (`core.filemode` is off there), and nothing warns
  until CI refuses to run the file. All five `.sh` are now mode 0755 in the index.
  - The same bug was waiting in `.github/scripts/changelog-section.sh`, called from two
    places but only on a `v*` tag — so it had never run, and would have taken out the first
    release at the step that publishes its notes.
  - The workflow also calls them as `bash <script>` now. Belt and braces on purpose, because
    the two failures are different: the mode is what the packaged maintainer scripts need
    (a package manager runs those itself, so `bash` cannot help there), and the explicit
    interpreter is what survives the next file committed from a Windows checkout.

## [0.0.1+build.49] - 2026-08-04

### Added
- **A version tag now ships `.deb`, `.rpm` and a Gentoo overlay, attached to its release.**
  Only for `vX.Y.Z`: `test` is a build tag that moves, and a package claiming to be a version
  it will not be tomorrow is worse than no package. One `nfpm` definition produces both the
  deb and the rpm — two hand-written trees (`debian/` and a `.spec`) are two descriptions of
  one layout that drift apart. Gentoo installs from an ebuild rather than a built package, so
  what ships there is the ebuild, generated from a template into an overlay tarball.
  - **The package carries the application; the dependencies are resolved on the machine.**
    The postinstall builds a venv in `/opt/ServiSesentry/venv` and installs the 41 pinned
    packages from the `requirements.lock` it ships. A venv is bound to the exact python that
    made it, so one built on the CI runner would break on any distro carrying a different
    3.x; and declaring the pins as distro packages would mean mapping 41 names per distro,
    several of which do not exist and most of which are a different version. The cost is
    stated rather than hidden: it needs network and takes a few minutes, and a failure names
    the command to re-run.
  - **No compiler is pulled in.** The pinned wheels have manylinux binaries for the targets;
    dragging `gcc` and dev headers onto every machine that installs a monitoring panel, to
    cover the case where one does not, is the wrong default.
  - **CI installs what it built.** Each package goes into its own distro container (Debian 12,
    Ubuntu 24.04, Fedora 41) and the resulting venv has to actually import `flask`,
    `cryptography` and `paramiko` — building a package proves it was produced, not that it
    works, and the postinstall is exactly the step that fails on a distro nobody tried. The
    release does not happen if that fails.
  - The systemd units are rewritten at **build** time to run the venv's interpreter, from the
    single copy in `init/` — not duplicated into `packaging/`, and not `sed`-ed in the
    postinstall, which would leave a packaged file that no longer matches what the package
    says it installed (`rpm --verify` flags exactly that).
  - Uninstalling removes the venv, because the postinstall created it; `/etc/ServiSesentry`
    and `/var/lib/ServiSesentry` are left alone, which is what makes reinstalling safe.

### Changed
- **`:latest` now means the newest release, not the newest commit.** It followed `main`, so
  `docker pull` with no tag — what most people run — handed out whatever merged last: no
  release notes, no packages, nothing claiming it was fit to install. It is now published by
  a `vX.Y.Z` tag, and the tip of `main` moved to **`:edge`**, a name that says what it is.
  (`:main`, which `type=ref,event=branch` produced, is gone: this workflow only builds branch
  pushes for `main`, so it was a second name for the same image.) Until the first version tag
  exists there is no `:latest` in the registry — `docs/caso-docker.md` says so rather than
  leaving someone to discover it from a failing pull.
- **The `test` tag also builds and installs the packages, without publishing them.** Finding
  out that packaging is broken while tagging a release is too late; `test` is the rehearsal.
  The `.deb`, `.rpm` and ebuild are built and put through the same install matrix, and stay
  as run artefacts instead of being attached anywhere. They are versioned after what the
  application reports (`__version__`), not after the tag: a `servicesentry-test.rpm` would
  mean something different every week.
- **The `test` tag no longer queues behind the suite.** It exists to get an image in front of
  someone quickly and claims nothing about the tests, so its build now starts *beside* them
  instead of waiting ~13 minutes for a claim it is not making. Everything else — `:latest`, a
  version tag — does make that claim and still waits. The build moved into a reusable workflow
  called twice (`build-fast`, `build-gated`) rather than being duplicated: `needs` cannot be
  made conditional, and `if: always() && …` would still *wait* for the tests before starting,
  which is the waiting this removes.

## [0.0.1+build.48] - 2026-08-04

### Changed
- **Nothing is published until the suite and the install check pass.** The image build stood
  on its own, and — worse — `tests.yml` and `install-tests.yml` fired on the same single
  literal tag, so a merge to `main` ran **no tests at all** unless someone remembered to move
  it by hand. Both are now reusable (`workflow_call`) and the Docker workflow is the pipeline
  that calls them: the suite gates everything, then the image build and the install matrix run
  side by side. They are siblings rather than a chain because both only need the suite green,
  and serialising them would add the matrix to every publish for nothing.
- **A `vX.Y.Z` tag now publishes a GitHub Release, with that version's CHANGELOG as its body.**
  `test` deliberately stops one job earlier: it is the manual build tag, it moves, and a
  release per push of it would point at a tag that no longer means that commit.
  - The notes are read straight out of `CHANGELOG.md` by
    `.github/scripts/changelog-section.sh` (five lines of awk). It matches the heading
    literally rather than as a regex, because the dots in a version are wildcards and
    `1.2.3` would otherwise also match a heading for `1x2x3`.
  - A tag whose version has no CHANGELOG section **fails beside the tests**, seconds in, while
    the fix is still "add the heading and re-tag" — rather than after an image has been
    published under a version whose release cannot be completed. That guard is the point:
    an empty release body cannot be un-published, only edited.
  - The release job holds the only `contents: write` in the workflow and uses the preinstalled
    `gh`, so no third-party action runs where the write permission lives.

## [0.0.1+build.47] - 2026-08-04

### Fixed
- **The secret key can be pinned with `SS_SECRET_KEY`, which multi-pod deployments needed to
  work at all.** That key signs session cookies *and* derives the Fernet key every stored
  secret is encrypted with, so every process sharing a database must hold the same one — and
  it was the single setting with no `SS_*` to supply it. It lived only in `.flask_secret`
  inside the config directory.
  - On one host the compose files get away with it: all four services mount the same `config`
    volume. Lose that volume (`down -v`, a recreated volume) and every stored secret in the
    database becomes unreadable, with nothing reporting an error.
  - The Helm chart was never affected: it already ships the key as a Secret mounted into
    every pod as `.flask_secret`, kept stable across upgrades. The **hand-written manifests**
    in `caso-kubernetes.md` were the gap — they wire `envFrom` and mount nothing, so anyone
    following that page by hand got a pod-local key: a credential saved by `web` could not be
    decrypted by `worker`, and restarting a pod made everything encrypted before it
    unrecoverable. Confirmed before changing anything — with `SS_SECRET_KEY` exported it was
    ignored outright, and two instances with their own config dir raised `InvalidToken`
    reading each other's data.
  - The environment wins over the file, the file stays the fallback so existing installs are
    untouched, and the value is **not** written to disk — it is supplied per process, and
    persisting a copy would leave a second source of truth to drift from it.
  - A malformed value **stops the process** instead of falling back. The fallback would
    encrypt with a key the operator never chose and say nothing; the discovery comes months
    later, when a replica cannot read a secret or a restart makes the data unreadable.
  - `docs/caso-kubernetes.md` now carries it in the Secret (required for the hand-written
    manifests, not for the chart), and `env.example` plus `ref-configuracion.md` explain when
    it is needed and that losing it loses every stored secret.

### Changed
- **`env.example` stops shipping a password that works.** It set `SS_PASSWORD=admin`, which is
  the kind of value that survives into production precisely because nothing ever complains
  about it; it now reads `change-me`. Each secret also carries the command that generates a
  good one (`openssl rand -base64 24`, `-hex 32`, `token_hex(32)`) instead of only being
  labelled REQUIRED, and a header states which values must be set before anyone can reach the
  panel. The database passwords stay **empty** on purpose — an empty one stops the stack, and
  a deployment that refuses to boot is safer than one running on a password anybody can guess;
  `change-me` is used only where the alternative is not starting at all, which is the admin
  login.
## [0.0.1+build.46] - 2026-08-04

### Changed
- **The container is published on its own now.** The workflow already built and pushed to
  GHCR correctly; what was missing was ever being asked to. It fired on one literal tag named
  `test`, so every image came from moving that tag by hand and the tagging rules it already
  carried — `latest`, semver, per-branch — described releases that could not happen. The
  triggers now say the policy out loud: `main` publishes `:latest`, a `v1.2.3` tag publishes
  `:1.2.3` and `:1.2`, the `test` tag still works as the manual escape hatch, and every build
  also gets `:sha-<commit>` — the only tag that never moves, and so the one to pin a
  deployment to.
  - Pull requests **build without publishing**. That keeps a broken `Dockerfile` from reaching
    `main` unnoticed, and is the one case where a fork could otherwise write to the registry.
  - `linux/amd64` only, deliberately: arm64 has to be emulated through QEMU on a GitHub
    runner, and the pip layer turns a ~30 s build into minutes. Adding the platform is a
    one-line change if that trade stops paying.
  - Concurrent pushes cancel the older run, so `:latest` is whatever the newest commit built
    rather than whichever job happened to finish last.
- **The HA test stack runs the published image.** `docker-compose.ha-test.yml` pulled its
  image from a local build, which proves the `Dockerfile` compiles and says nothing about the
  artefact people actually pull; it now runs `ghcr.io/vsc55/servicesentry:test` with
  `pull_policy: always` (that tag moves, and a stale local copy would quietly test the
  previous build). Building from the working copy — what you want while changing code — moved
  to `docker-compose.ha-test-build.yml`, an **override** rather than a second copy: the two
  differ in five lines out of 180, and two files that must stay identical except for those
  five is how they stop being identical. `make_test.sh ha` and `make_test.sh ha-build` pick
  between them.

## [0.0.1+build.45] - 2026-08-04

### Fixed
- **The sidebar no longer offers modules that are not there.** *Azure* and *Microsoft 365* sat
  in the navigation of a panel whose Modules tab listed only `ping`, because the nav was built
  from the pages **discovered on disk**: every module shipping a `__page__` appeared, added or
  not. Clicking one reached a section that could only ever be empty — its data is the monitor's
  last results for a module that never ran — and an empty section does not read as "not
  installed", it reads as a feature that exists and is broken. The nav now asks the
  configuration, using the rule the Modules tab already draws: configured, and not switched
  off, means it exists.
  - The asymmetry is worth stating because it inverts easily: a **configured** module with no
    `enabled` key is ON (the registry declares `default: True`), but an **absent** one is not
    on by default — it simply has not been added.
  - **The decision belongs to the client, and that is the whole design.** Filtering it in the
    render worked on load and then failed the moment it mattered: adding or enabling a module
    left its section missing **until F5**, because an entry that was never painted cannot be
    revealed without a reload — the reload the panel exists to avoid, and which reads as the
    save not having worked. So the shell ships every pane and every entry, each module entry
    tagged `data-nav-module`, and `syncModuleSections()` decides; it runs on load, after saving
    modules and after reverting them.
  - Pinned on both sides: the integration test fixes the tag (without it the client has nothing
    to key off), and the browser tests fix the behaviour — hidden when the module was never
    added, visible immediately once it is, gone again when switched off, with the core sections
    proven untouched by any of it.

## [0.0.1+build.44] - 2026-08-04

### Fixed
- **Adding one check to a server no longer switches on six modules nobody touched.** Enable
  `ping`, create a server, bind `ping` to it in the monitoring section, save — and the Modules
  tab came back with `cpu`, `hddtemp`, `ntp`, `raid`, `ram_swap` and `snmp` enabled, every one
  of them without a single item. Exactly the single-check host modules, which is what pointed
  at the cause: that section renders an empty placeholder slot for each of them even when the
  user never touches it, and `_applyHostChecks` reserved `modulesData[module][collection]`
  *before* discarding that slot. A module left behind as `{}` does not read as "off" — the
  registry declares `'enabled': {'default': True}`, so an absent key means **on** — and since
  saving the one real check PUTs the whole object, the empty entries were persisted with it.
  The entry is now created lazily, on the first write that actually happens.
  - Pinned by a browser test rather than a template scan, because the defect lived where no
    text guard could see it: the real function is fed the state a real modal produces and its
    effect on `modulesData` is read back. With a positive control — a module the user *did*
    enable must still be written — so the guard cannot be satisfied by writing nothing.
  - Written up in `docs/caso-diagnostico.md`: when the absence of a value means "enabled",
    creating an empty container *is* a decision, and "save one part, PUT the whole object"
    turns any in-memory leftover into a persisted change.

## [0.0.1+build.43] - 2026-08-04

### Added
- **Fullscreen Overview keeps the screen awake.** Kiosk mode exists to be left on a monitor,
  and the operating system was quietly undoing that: ten minutes idle and the display dims,
  the screensaver starts, the session locks — so whatever went down at 3 a.m. was on screen
  for nobody. Entering fullscreen now takes a screen wake lock and leaving releases it, by
  either exit (the button or Esc out of fullscreen), so a panel nobody is watching stops
  holding the machine awake.
  - **Re-taken when the page becomes visible again.** The browser drops the lock on its own
    whenever the page is hidden and never takes it back, so without this the display stays
    awake exactly until the first tab switch and then stops — while the mode still looks
    enabled. The re-acquire is silent and only fires if kiosk mode is still on.
  - **It still works over plain `http://`.** The Wake Lock API needs a secure context, and a
    self-hosted panel is usually reached by IP on a LAN, where `navigator.wakeLock` does not
    even exist — which would have made the feature useless exactly where it is wanted. The
    fallback is media playback: a muted 2×2 clip looping in a corner, since browsers hold the
    display on while media plays (the reason a video call never dims the screen). Its frames
    come from a canvas rather than a base64 blob pasted into the template — the NoSleep.js
    trick, but readable. It is best-effort by construction, so it stays the second choice and
    announces itself rather than claiming a guarantee it cannot give.
  - **Nothing fails silently.** If neither route works the panel says so and names the fix
    (HTTPS, or localhost); a lock refused by power saving warns too. The alternative was
    letting someone believe their wall screen was pinned awake while it slept every night.

## [0.0.1+build.42] - 2026-08-03

### Fixed
- **The whole suite now passes with no Flask installed: 3326 pass, 1654 skip, nothing fails.**
  build.41 closed the collection abort and left nine real failures documented as a known gap;
  this closes them, so the Flask-less run is a guarantee that can be re-checked rather than a
  caveat in a document. Two fixes cover all nine:
  - **`conftest.py`'s `admin` fixture skips instead of exploding.** Six of the nine died on
    `NameError: name 'WebAdmin' is not defined` — the import sits in a `try/except`, so
    without Flask the name never existed and every test requesting `admin`/`client` blew up
    with a message naming the symptom, not the cause. One explicit skip in the fixture fixes
    all of them at the source, and means no file has to repeat the guard just to use it.
  - **`pytest.importorskip` for the three lazy imports.** `test_config_spec` (both halves) and
    `test_core_domain_layout` import the panel *inside* the test — the case no import scan can
    see. They now skip cleanly instead of failing.

  Nothing regressed with Flask present, which is what the `conftest.py` change had to be
  checked against since every integration test goes through that fixture: integration 1482,
  unit+meta 2655, module tests 763 — the same numbers as before.

## [0.0.1+build.41] - 2026-08-03

### Fixed
- **`tests/unit` is runnable without Flask again: 231 tests stop skipping there.** Flask is a
  hard dependency (`flask>=3.0`), so in a normal install these tests always ran — this is
  about the slimmed case the code deliberately supports: the three standalone services import
  cleanly with no Flask, `conftest.py` guards its `WebAdmin` import, and every web test
  carries `skipif(not _HAS_FLASK)`. The by-class split copied that module-level gate into
  halves that no longer touch the app, so in that environment they skipped for nothing:
  `test_entity_sync` gated 6 tests of `diff_entities`/`snapshot`, `test_providers_ldap` 5 of
  pure `map_role` logic. Of the 27 candidates the gate is gone from the 26 that proved they do
  not need it, and stays on the one that does — `test_wa_sessions` imports Flask inside its
  cases, which no amount of reading the imports would have shown. Proved, not assumed: re-run
  under a harness that blocks `import flask` outright — 231 passed, and the static analysis
  alone had been wrong about four of them.
- **A Flask-less run no longer dies at collection, so the suite runs at all there.** Six files
  — both halves of `test_wa_request_hooks`, `test_scheduler_lifecycle` and `test_wa_server` —
  imported the web stack at module level with no guard (`test_scheduler_lifecycle` pulls it
  transitively through `lib.core.audit.mixin`, which imports `flask` for `request`/`session`).
  Without Flask, `pytest tests/` aborted with *Interrupted: 3 errors during collection* and
  ran **nothing**; it now collects all 4217 and runs 2558 of unit+meta. Pre-existing: it
  predates the reorganisation. `test_wa_server` keeps its two pure tests alive there — only
  the third needs `WebAdmin`, and only for a class constant, so that import moved inside it.
  Nine tests across six files still fail there (individual cases that import Flask lazily and
  never had a guard); they were invisible while collection aborted, and are left as a measured
  known gap rather than papered over.
- **The dead scaffolding the splitter copied into both halves is gone.** Splitting by class
  duplicated every module preamble, so each half carried the other's machinery: 60 helper and
  fixture definitions that nothing in that file called (`_ldap_cfg`, `_make_wa`,
  `saml2_admin_client`…) and 286 unused imports, across 72 files. Beyond the noise it was
  actively misleading — `grep -l test_client tests/unit/` matched 13 files that never touch
  the app, so the folders read as impure to anyone (or any tool) scanning them.
- **The last cross-file test import is gone.** `test_wa_account_page` reached `_login` through
  `test_wa_standalone_pages`, which only re-exported it from `conftest`; it now imports the
  source directly. A test module is no longer part of another's public surface.

### Changed
- **One copy of the structural-guard helpers, in `tests/helpers.py`.** `_read` existed 27
  times in the suite (21 byte-identical), `_fn` 21 times (18 identical), `_strip_comments` 16
  times: fixing one fixed one of twenty, silently. The identical copies — 45 definitions
  across 24 files — now import a single canonical version; the variants that genuinely differ
  (a `_read` that joins a module-specific directory, a `_strip_comments` that also strips HTML
  comments) were left alone rather than flattened into a wrong shared default. Note this
  duplication mostly predates the reorganisation: the split inherited it and added a few
  copies. It is a plain module, not `conftest.py` — these are functions to import, not
  fixtures — and it is not named `test_*.py`, so pytest does not collect it.
- **Each half of a split file says which half it is.** Both halves inherited the original's
  module docstring verbatim, so both claimed to cover the whole subject. All 110 now end with
  the category they hold and where the rest of the original lives.
- **`docs/ref-tests.md` states the `_HAS_FLASK` rule in both directions**, because getting it
  wrong hurts either way and the convention was only ever half-written down: no guard when the
  file does not import Flask (otherwise tests skip for nothing), a guard when it does at module
  level (otherwise collection aborts and nothing runs), a local import when a single test needs
  it. It also warns about the transitive case (`_AuditMixin`), documents `tests/helpers.py`, and
  records the ten-test gap rather than leaving it folklore.

## [0.0.1+build.40] - 2026-08-03

### Changed
- **The test suite is now sorted into `unit/`, `integration/`, `e2e/` and `meta/`.** The ~160
  files used to sit in one flat `tests/` directory with no way to run just the fast ones or
  just the ones that touch the app. Every file is now under the folder that names what it
  needs: `unit/` runs in isolation (no app, no DB, no HTTP), `integration/` drives the Flask
  app through `test_client`, `e2e/` is the live-engine and Playwright work, and `meta/` holds
  the structural guards that read the repo's own source, docs and git. `pytest tests/unit` is
  now a real, fast feedback loop.
- **The 54 files that mixed categories were split, one file per category.** A file that held
  both isolated unit tests and app-driven ones became `tests/unit/<name>.py` and
  `tests/integration/<name>.py`; the classification is by test class (a class stays whole,
  goes to the home its methods mostly need) so shared setup is never torn apart. Placement was
  computed, not guessed: an AST pass resolves each test's fixtures and helpers — through
  `conftest.py` — to decide what it actually touches.
- **`docs/ref-tests.md` follows the files, and opens by explaining the layout.** A new
  "Organización de directorios" section documents what each folder requires and where a new
  test belongs; every `**Archivo:**` entry and inline path names the new location, split
  entries carry one line per category with its own count, and the inventory guard
  (`test_docs_tests_inventory.py`) confirms every file on disk is still documented and every
  documented path still exists.
- **The prose docs point at the new paths too.** The `caso-*` and `explica-*` guides plus
  `ref-esquema-bd.md` and `ref-watchful-emit.md` referenced ~20 test files by their old flat path; each now names the
  real location (a moved file's folder, or the split half that holds the class the prose
  cites — e.g. `test_wa_ui.py::TestPaneDisplayRules` → `tests/unit/`). The `tests/` directory
  trees in `explica-arquitectura.md` and `caso-desarrollo.md` now show the four folders instead
  of a flat list; the co-located module-test trees under `watchfuls/` were left as they were.

### Fixed
- **Test path anchors no longer break when a file moves a directory deeper.** ~60 files located
  the source tree with `dirname(dirname(__file__))`, which silently pointed one level short
  once the file lived in a sub-folder. They now anchor on the `tests/` segment itself
  (`abspath(__file__).split(os.sep + 'tests' + os.sep)[0]`), so a file reads the same repo
  paths from any depth — including the aliased-`os` and repo-root variants the first pass missed.

## [0.0.1+build.39] - 2026-08-02

### Added
- **The first tests that execute the panel's JavaScript.** Every other frontend test reads
  the template as text: that fixes the structure of the markup and says nothing about whether
  the code in it runs, so a `TypeError` on line one of the bundle leaves ~600 guards green
  while the page is dead in the browser. The same blind spot as the page that 500'd because
  nothing opened it, one layer out. Six Playwright tests now load every server-rendered page
  in Chromium and **fail on any `console.error` or uncaught exception**, naming the page —
  navigation is only how the JavaScript is made to run.
- **A save driven the way a person drives it.** Open the user modal, fill it, press save, and
  insist the row a person sees and the store agree afterwards. That path is where most of the
  frontend lives, and it is the only place the CSRF token, the session cookie and the fetch
  wrapper are exercised together: a token the wrapper stopped attaching would 403 every write
  in the panel and no other test would notice.
- Waiting is on the panel's **own** boot signal (the `#loading` overlay it removes in a
  `finally`), never on `networkidle` — this is a monitoring panel, it polls health and
  services forever, so the network is never idle and that wait can only ever time out. When
  the boot never finishes, the collected browser errors are raised instead of the timeout:
  reporting "timed out waiting for #loading" would send the reader hunting for a slow page
  when the browser had already said `ReferenceError` and named the symbol.
- Opt-in by construction: Playwright and its browser are optional, and the file skips itself
  when either is missing, so a checkout without them still gets a green suite. Verified by
  breaking a shared partial on purpose and confirming the failure names the cause.
- **Stored payloads are proven not to execute, in the one place that can prove it.** The
  browser tests store `onerror`/`onload` canaries — not `<script>`, which does not fire when
  assigned through innerHTML and would pass on markup that is in fact vulnerable — as a display
  name, a syslog line (the least trusted input in the product: whatever a device on the network
  sent), an audit detail and a credential name, then open each list and assert nothing ran.
  Each also asserts the payload is still *shown*: an escape that silently drops it would pass
  the first check and be its own bug. Plus two properties only a browser settles — the session
  cookie is unreadable from JavaScript (HttpOnly honoured, not just sent), and the panel refuses
  to render inside an iframe (clickjacking, asked of the browser, not of the header).
- **A security audit that runs against the real engines.** `tests/test_security_live.py` boots
  the whole panel on MySQL, MariaDB and PostgreSQL and runs the attacks an auditor would:
  injection payloads on every string field (a 500 would betray a concatenated query; a canary
  table's survival proves no `DROP` was smuggled in — sharper on MySQL, which rejects quoting
  SQLite forgives), and the access-control matrix (anonymous reads nothing, a viewer mutates
  nothing, a `users_add` holder can neither mint an admin nor promote itself). Every attack
  asserts the exact rejection code and the resulting state, and every role carries a positive
  control so a silently-broken login cannot pass the audit vacuously. Confirmed to catch a real
  regression by disabling the escalation guard and watching it fail. Opt-in, serial, live only.
- **…and IDOR across the per-host scope.** Hosts are scoped per resource
  (`server.{uid}.view/edit/delete`), so holding a permission on host A must not reach host B by
  naming B's UID — the exact spot a scoped model breaks quietly, because the list endpoint
  filters but every per-host endpoint has to run its own check, and secrets make a leaked host
  carry its stored SSH credential. A user scoped to A only is refused read/edit/delete on B
  (403, B untouched) with a positive control that it can still reach A. Confirmed to catch the
  regression by making the per-host check pass unconditionally and watching it name the leak.
- **SSO provisioning grew the two security tests it was missing.** A SAML2 assertion whose
  username collides with a LOCAL account cannot hijack it (sync returns None, the account stays
  local) — the guard was in place but untested, and LDAP/OIDC already pinned their equivalents;
  a forged assertion for `admin` is the case that matters most. And a SCIM `default_role`
  pointing at the admin role is downgraded to `none`, so a directory that provisions hundreds of
  users cannot mint hundreds of admins. Both confirmed to catch their regression by disabling
  the guard and watching the test name the escalation.

### Changed
- **CI installs the Playwright browser, so the browser tests actually run there.** `pip install
  -r requirements-dev.txt` installs the Playwright *package*, not the *browser*: Chromium is a
  ~100 MB binary Playwright keeps in its own cache and fetches only with `playwright install`.
  Without it `test_ui_playwright.py` skips itself — which on CI meant the 13 JavaScript-executing
  tests silently covered nothing (build.39's CI run showed them SKIPPED). The `tests.yml`
  workflow now runs `playwright install --with-deps chromium` before the suite (`--with-deps`
  pulls the OS libraries Chromium needs on ubuntu-latest), so those tests become part of the CI
  gate rather than a local-only check.

### Fixed
- **Documentation caught up with the last two builds.** A doc that describes what does not
  exist is worse than none — it sends the reader looking for the wrong thing. Fixed: the
  live-engine env-var table in `ref-tests.md` §81 still showed **two** slots (MySQL/MariaDB as
  one) after the code split MariaDB into its own `SS_TEST_MARIADB_*`; §142 named the browser
  tests but never said `pip` cannot fetch the browser (`playwright install chromium` is a
  separate ~100 MB download); the dev guide claimed **"más de 2700 tests"** (now ~5000) and
  "~62 ficheros" (now ~160), and did not mention the three opt-in families a fresh checkout
  skips silently; and `explica-seguridad.md` tied mechanisms to their tests but did not know
  about `test_security_live.py` (injection / access-control / IDOR on real engines) or the
  browser XSS/HttpOnly/clickjacking checks. No new claims — only aligning the prose with the
  code and tests that already shipped.
- **A flask-import probe stopped failing under full parallel load.** `test_the_probe_detects_flask`
  spawns a subprocess that imports `lib.web_admin.app` (a positive control for "does this drag in
  Flask"). The import takes ~3 s in isolation, but under a full `-n auto` run every core is taken
  by xdist workers and the extra process can be starved so badly the import barely runs — a
  bumped 600 s cap still expired on a loaded Windows box (green on CI and `-n0`). Raising the
  timeout does not fix starvation, so a timeout is now read by context: under xdist it means "the
  machine was too busy to run the probe" and **skips** (the property is parallelism-independent
  and still checked on every `-n0` run and on CI); under `-n0` there is nothing to contend with,
  so a timeout is a genuine hang and stays a failure.
- **The modal-save browser test stopped gating on a Bootstrap animation.** Once CI actually
  ran the browser tests (with Chromium installed), `test_creating_a_user_through_the_modal_persists_it`
  flaked: `saveUserModal()` fires right after the modal opens, and under CI's parallel load
  Bootstrap can still be mid opening-transition, so its `.hide()` on save is dropped and the
  modal lingers — a `state='hidden'` wait then times out on a save that in fact succeeded (POST
  → 201, user in the store). The wait is removed; persistence is proven by the rendered row and
  the store, exactly as the sibling CSRF test already does it reliably.

### Security
- **Dependency CVE audit (`pip-audit` over `requirements.lock`): 17 advisories across 7
  packages, and the lock is bumped to clear them.** `pip-audit` over `requirements.lock` found
  the 17; `pip-compile -P` then bumped exactly six, no transitive surprises, hashes regenerated:
  **cryptography 46.0.6 → 48.0.1** (a two-major jump — a statically-linked OpenSSL advisory and
  a non-contiguous-buffer overread; this is the library that derives the Fernet key for every
  stored secret, so it led the list and was smoke-tested first: 104 tests across secret_manager,
  boot, SSO and SSH pass on it), **joserfc 1.6.5 → 1.6.8** (forged HMAC tokens accepted when the
  verification key is empty/None; reached through Authlib on the OIDC path), **urllib3 2.6.3 →
  2.7.0** (sensitive headers kept across cross-origin redirects), **pyasn1 0.6.3 → 0.6.4**
  (quadratic-time decode DoS on crafted ASN.1, on the SNMP/LDAP path), **idna → 3.15**, **click →
  8.3.3**. A re-audit confirms **17 → 1**. The one that remains, **paramiko 4.0.0**
  (PYSEC-2026-2858 — allows SHA-1 in `rsakey.py`, the SSH client), has no fixed release yet —
  track upstream. `requirements.txt`'s `cryptography` floor is raised from `>=41.0` to `>=48.0.1`
  too, so an install that bypasses the lock cannot pull a version with these CVEs; the five
  transitive packages are not in `requirements.txt` (the lock is their only pin).
- **The dev dependencies are pinned, like production already was.** `requirements.txt` uses
  ranges on purpose — it declares intent, and `requirements.lock` (exact versions + hashes) is
  what Docker, CI and `setup_env.ps1` actually install. `requirements-dev.txt` had no such
  backstop: CI installs it as a second command on top of the lock, so pytest, xdist, flake8 and
  the rest floated. A new major could break CI overnight with no repo change, and an unreviewed
  release of any of them executes on a developer's machine and in CI the moment it lands. They
  are now pinned to the versions the full suite passes on. Deliberately **without** hashes: CI
  installs this file separately and a hashed one would force `--require-hashes` onto that whole
  install — pinning stops silent drift, which is most of the exposure, and a hashed dev lock is
  the next step if the transitive tree (execnet, greenlet, pyee…) needs covering too.
- **Two VS Code launchers that run the full suite without xdist.** The existing `pytest`
  launcher inherits `-n auto` from `pytest.ini`, and on some Windows boxes execnet aborts at
  bootstrap with `OSError: [Errno 22]` before a single test runs. Added a serial one
  (`-p no:xdist`, reliable but ~45 min, no progress until the end) and an `-n 2` one (far less
  bootstrap-prone than `-n auto`, with visible progress). The original is left untouched.

## [0.0.1+build.38] - 2026-08-02

### Added
- **The panel can now reclaim its own disk space.** Deleting a year of history freed nothing
  an operator could see: the rows went, the file did not shrink, and the disk graph kept
  climbing — the only way to fix it was a shell on the host. Maintenance now offers two
  actions, kept apart because they cost wildly different things. **Optimize** refreshes the
  statistics the query planner reads (`ANALYZE` + `PRAGMA optimize`, `ANALYZE TABLE`,
  `ANALYZE`): cheap, safe, changes no row, no confirmation. **Compact** rewrites storage to
  hand space back to the filesystem (`VACUUM`, `OPTIMIZE TABLE`, `VACUUM FULL`) and holds the
  database while it does, so it asks first and says so. Offering only the combined operation
  would have meant the safe one could never be run on its own.
- **`db_maintenance`, a permission of its own, granted to no role by default.** Editing a
  setting and freezing the database for the length of a rewrite are not the same authority,
  and riding on `config_edit` would have handed the second to everyone who needed the first.
- **The run shows its progress, unit by unit.** A single call that returns only when
  everything is done says nothing while it works, and on a large database that silence is
  indistinguishable from a hang. The dialog lists what it will walk *before* starting and
  marks each unit as it comes back — so a tick means THAT unit finished rather than that time
  passed, and a run that stalls shows exactly where. What the list is made of is the
  **engine's** answer (`maintenance_targets(op)`), never inferred from the engine's name: a
  row per table where the statement works per table, and a single row standing for the whole
  database where it does not. Splitting SQLite's `VACUUM` into thirty-three ticks would invent
  a granularity the engine does not have and make every tick a claim about work that had not
  finished. Cancel means "stop after this unit", and the dialog cannot be dismissed mid-run:
  closing the window would not stop the work, only stop you seeing it.
- **A table name from the client is checked against the catalog before it reaches SQL.** An
  identifier cannot be a bound parameter, so it is interpolated — accepting whatever arrived
  would have been an injection point, and quoting is not a reason to skip the check but the
  reason the check has to be what decides. Validating against `maintenance_targets(op)` rather
  than the plain table list also refuses a per-table `compact` on an engine that cannot divide
  it, where it would have rewritten the WHOLE database once per table.
- **Per-unit steps write no audit entry each.** The run is one operator action; a row per
  table would bury the entry it belongs to under thirty lines saying nothing. The closing
  call — the one with no table — is what records it, and what measures what was reclaimed.
- **The audit entry says what happened, not just that it did.** It was an event name and
  `ok: true`: true, and useless — it recorded that something occurred rather than what, which
  is the one question the person opening it has. A maintenance run now records how many
  tables it walked, how many succeeded, and names the ones that failed with their error. The
  summary comes from the browser (the server answers one table per request and keeps nothing
  between them, so the client is the only witness to the run as a whole) and is therefore
  treated as a claim: table names this operation could not have walked are dropped, errors
  are truncated, and a long failure list is cut at twenty — an entry reproducing four hundred
  error strings is not a record, it is a denial of service against whoever reads the log.
- **Clearing the check state says how many rows it erased**, counted before the delete. The
  gap between clearing four rows and four thousand is the whole question somebody has when
  they find that entry a week later.
- **The entry names the tables on BOTH sides, not just the failures.** With a clean run the
  counts alone left the detail saying "33 of 33" — a question nobody asked. What the reader
  wants is which tables the run covered.
- **How long that list may get is a setting**, `web_admin|audit_detail_max_items` (default
  100, `0` turns the names off, `SS_AUDIT_DETAIL_MAX_ITEMS`). It started as a hardcoded
  constant, which is a guess about somebody else's install: the number of tables is not
  bounded — modules create their own at runtime — so what counts as "too long to read" is the
  operator's call. The ceiling exists at all because the detail is stored as JSON in one row
  and painted whole when opened, and a run on a broken database would otherwise write hundreds
  of error strings into a single entry, exactly when reading the log matters most. At `0` the
  COUNTS are still recorded: they are what says the run happened and how it went, and an entry
  without them would be indistinguishable from one that covered nothing.
- **What an audit event MEANS is now declared by the package that writes it**, not guessed
  from its name. `AUDIT_EVENTS` in each `manifest.py`, discovered exactly like `NOTIFY_EVENTS`
  and `MODULE_PERMISSIONS` — 132 events across 20 packages, each with a severity.
  The badge is the only thing a glance down two hundred log rows gives you, and it was decided
  by a rule matching `deleted`/`revoked` plus five names written out by hand. Two things were
  wrong and only the first was visible: **seven** destructive events and **fifteen** failures
  rendered neutral grey — deleting ONE audit entry was red while emptying the WHOLE audit log
  was grey, and among the neutral failures were three security signals (`csrf_failed`,
  `scim_auth_failed`, `msteams_sso_failed`) plus `internal_error`, the entry written when the
  panel itself crashed. And even with the word lists widened, the colour still depended on the
  noun somebody chose: `purge_done` would have slipped through, `rule_failed` would have gone
  red for a rule that merely reported "no match". The renderer now holds one mapping —
  severity to CSS tone — and not a single condition on the event name.
- **Guards make the next event impossible to forget**: every emitted event must declare a
  severity, no declaration may outlive its event, and an unknown severity is dropped at the
  door — it would reach the browser as a CSS class that does not exist and render the row with
  NO badge, which reads as an event that carries no weight at all. The literal scan cannot see
  an event emitted through a variable (`wa._audit(event, …)` — how `db_optimized` and
  `db_compacted` slipped past), so it is crossed with the i18n catalog, which is complete
  because every event needs a label to render.
- **An audit entry always names who caused it.** A SCIM auth failure showed an empty USER
  column — the only `username=''` in the codebase. Not `system` either: that means the panel
  acted on its own (a service starting, a scheduled prune), and an intrusion attempt filed
  under it reads as the panel doing this to itself, in the one filter these entries are most
  often looked up by. A blank cell is no better — it reads as a missing value rather than as
  "there was no identity to record". `ANONYMOUS_USER` now names the caller who never
  identified themselves, and **both** audit identities are reserved usernames: an account able
  to take either name would have its actions read as the panel's own or as an unauthenticated
  caller's, and "who did this" would stop being answerable.
- **The reserved names are now refused at all five doors, not one.** Only `create_user`
  checked. Accounts also arrive from LDAP, OIDC and SAML2 — which provision on the fly at
  first sign-in — and from SCIM, where the IdP creates them outright, and none of those looked
  at the name. A directory with a user called `system` created a local `system` whose every
  action then read as the panel's own: the log stays complete and stops being trustworthy,
  which is the one failure an audit log cannot have. One shared check
  (`is_reserved_username`) rather than five copies, protected the way the built-in roles and
  groups are — declared once in `lib.core.constants`. SSO **rejects the sign-in** instead of
  renaming (there is no safe account to let them into); SCIM answers `400 invalidValue` rather
  than `409`, because the name is not taken — it is not available.
- **`system` and `anonymous` are built-in USERS now, not bare strings.** Each has a stable UID
  (`BUILTIN_USER_UIDS`) and a row in the users list marked with the `Built-in` padlock, exactly
  like the `Administrators` group: the audit column that answers "who did this" was naming
  something the rest of the system knew nothing about, so there was nothing to look up.
  `RESERVED_USERNAMES` is **derived** from that map, so a third internal identity is one line
  rather than two that can drift. They are **synthesized, never stored**: a database row is a
  login surface — a password hash to set, a session to open, one CLI edit away from being a
  real account — and these two must not be reachable that way. No password, no session, no
  permissions (they carry the built-in `none` role because the shape demands one; `system` acts
  with the panel's authority precisely because it never passes a permission check). Editing or
  deleting one answers `403 user_builtin`, and they are kept out of the group-member and
  role-assignment pickers and out of bulk selections. One exception, deliberate: an
  installation that provisioned a `system` account *before* the name was reserved still sees
  that real account and can delete it — hiding it behind a row marked "built-in, not editable"
  would leave the admin unable to remove the very account that made the log ambiguous.
- **Service accounts: an identity that is active but never signs in.** A new per-user
  `login_enabled`, deliberately **not** the same switch as `enabled`: disabling an account to
  stop it logging in also stops it being a valid owner and a valid notification recipient,
  which is not what "this identity belongs to a script" means. Off means the password form,
  LDAP, OIDC and SAML2 all refuse it — "never signs in" that only covered the password form
  would be a setting that does not mean what it says. Turning it off **revokes the live
  sessions** (a session would otherwise outlive the setting meant to end it), you cannot take
  away your own sign-in (it locks you out exactly as surely as disabling yourself, which was
  already refused), and the login page still shows the same generic failure as a wrong
  password — saying "this account cannot sign in" would confirm the account exists, so the
  real reason stays in the audit log. Stored only when switched OFF, so every account written
  before this existed is untouched and keeps signing in. Available on the users API, in the
  Edit-user modal, and as `ssentry user add --no-login`.
- **The reserved names can no longer log in, whatever a row says.** The SSO doors refuse them
  on *every* sign-in (the check sits in `sync_user`, not in the create path), but local
  authentication went straight to the users table — so the legacy `system` account described
  above would still have signed in with its old password. `system` in the audit log has to
  mean the panel acted on its own; the moment a person can sign in under that name it means
  nothing at all. The attempt is refused before any credential work, audited with
  `reason: username_reserved`, and answered with the same generic message as any other failure
  (naming the rule would confirm which accounts exist). The way out is to delete the account,
  which Users still allows.
- **Maintenance actions are audited as maintenance.** Deleting a history series from that
  section logged "Histórico: Entrada Eliminada" — accurate about the domain and useless about
  the act: the reader wants to know somebody went to Maintenance and wiped a table, not which
  subsystem owns the rows. All nine now carry the `Mantenimiento:` / `Maintenance:` prefix.
  It is a fact rather than a convention: each is reachable ONLY from that section now, and a
  guard keeps events that are still triggered from their own tab (`audit_entry_deleted`,
  `syslog_drops_cleared`) out of it — the prefix says where the operator was, so it may only
  go on events that could only have happened there.
- **Every audited event now has a label, and one that names its area.** Adding a prefix to
  the maintenance events turned up **six** shipping as bare `snake_case` identifiers on the
  audit screen (`ipban_history_cleared` among them) and **four** more with no area prefix at
  all. A guard scans the `_audit*()` CALLS across `lib/` rather than a list — the list is the
  thing that goes stale, since ~30 modules write events and the next one added will not think
  to register itself anywhere. Without a prefix, filtering two hundred entries by eye means
  reading every row.
- **The result says what it actually reclaimed.** Both operations report the database size
  before and after, and the toast names the difference. "Compacted" on its own is a claim
  nobody can check, and whether there *was* anything to reclaim is most of the reason to run
  it. A size the engine will not disclose (a managed PostgreSQL can refuse
  `pg_database_size`) is reported as unknown, never as zero. The size is formatted
  server-side by `fmt_bytes`, the formatter the rest of the panel already uses: a
  browser-side one was written first and caught in review, and it would not merely have
  duplicated the logic — `fmt_bytes` scales in 1024s and it counted in 1000s, so the same
  number of bytes would have printed as two different sizes depending on which side of the
  wire formatted it. A guard now fails the build if a second one reappears.
- `BaseConnector` gained `compact()`, `optimize()` and `list_tables()`. `vacuum()` stays
  exactly as it was and still means the routine post-delete reclaim History calls
  automatically — on PostgreSQL that distinction is the whole point, since pointing it at
  `VACUUM FULL` would let a background step take an ACCESS EXCLUSIVE lock on every table.

### Removed
- **The experimental `/overview2` page.** An Alpine.js proof-of-concept that had stopped
  rendering at all: its template linked to `url_for('overview')`, an endpoint renamed to
  `page_overview`, and a renamed endpoint does not degrade to a dead link — Jinja raises
  `BuildError` and the whole page 500s. It had been that way on every engine, unnoticed,
  because nothing opened it. Deleted rather than repaired: it duplicated a page the panel
  already has.

### Fixed
- **Every page the panel serves is now opened by a test.** The blind spot the dead page
  revealed was the real bug: the route index listed it, so it *looked* covered. The sweep now
  comes from Flask's own `url_map` — every GET that takes no path parameters must not 5xx and
  must not raise, logged in and logged out — so a page added later is covered without anyone
  remembering the guard exists.
- **Optimize and compact raised on PostgreSQL, always.** `VACUUM`/`ANALYZE` cannot run inside
  a transaction block, which the connector knew — it turns autocommit on for them. What it did
  not account for is that psycopg2 refuses the flip *while a transaction is open* ("set_session
  cannot be used inside a transaction"), and one always is: the driver opens it on the first
  read. So every maintenance call on PostgreSQL failed before running a single statement. The
  transaction is now ended first — committed rather than rolled back, since what is open is the
  read that preceded the request and discarding a caller's pending work to run maintenance
  would be the worse surprise. Invisible to the existing suite, which verifies the MySQL and
  PostgreSQL implementations by **reading the connector source**: the SQL was right, the driver
  call around it was not.
- **One failed freshness probe took down the whole PostgreSQL connection.** `table_stamp`
  swallows its error on purpose — "a blip must not cost the caller its cache" — but on
  PostgreSQL a failed statement aborts the entire transaction, so it also cost every *other*
  store the shared connector: each later query answered "current transaction is aborted", far
  away from the probe that caused it. It rolls back before giving up now. The tables that
  trigger it are the ones with no `updated_at` (audit, sessions, check_state), where the probe
  legitimately has no answer. Harmless on SQLite and MySQL, which is why it survived: it took
  booting the real panel against a live PostgreSQL and walking every store to see it.
- **MySQL could not create most of its own tables.** `TEXT NOT NULL DEFAULT ''` is a MySQL
  syntax error, not a lost default — "BLOB, TEXT, GEOMETRY or JSON column can't have a default
  value" — and **27 tables declare exactly that**, `users` among them. The SQLite suite cannot
  see it and the live suite only built a handful of stores, so it sat there: of the ten live
  MySQL tests, **nine failed**, every one on the same line. Defaults are now emitted as an
  expression (`DEFAULT ('')`) where the engine requires it — MySQL 8.0.13+ and MariaDB 10.2+
  both take that form, and nothing changes for SQLite or PostgreSQL.
- **Every history graph came back empty on MySQL.** The bucketed query grouped by the bucket
  index and selected it multiplied back into a timestamp; MySQL runs with `ONLY_FULL_GROUP_BY`
  by default and refuses a select expression it cannot prove depends on the grouping one. The
  query raised, the caller's `except` returned `[]`, and a chart with no points looks exactly
  like a series with no data. It groups by the output column now — an exact 1:1 transform of
  the bucket index, accepted by all three engines. With both fixes the live suite goes from
  1/10 to 20/20 across MySQL **and** PostgreSQL.

### Changed
- **The built-in UIDs are one declaration, not three.** Roles, groups and users each had their
  own map of the same idea, so "which UIDs are built in" had no single answer and nothing could
  check that two of them did not collide. `BUILTIN_UIDS` now holds all three by kind and the
  per-kind names (`BUILTIN_ROLE_UIDS`, `BUILTIN_GROUP_UIDS`, `BUILTIN_USER_UIDS`, `ROLES`) are
  **derived views** — every caller keeps the name it already imports and **no value moved**.
  What the single map buys beyond tidiness is the reverse lookup: `builtin_kind(uid)` answers
  what a UID names, which is also what makes the no-collision rule testable instead of merely
  intended. The convention the three maps had grown into is now written down and enforced: the
  last block is a decade per kind — `…0000-…000f` roles, `…0010-…001f` groups, `…0020-…002f`
  users — so a UID says its kind without a lookup and a new kind takes the next decade.
- **`00000000-0000-4000-*` is reserved for them alone.** The prefix is declared once
  (`BUILTIN_UID_PREFIX`) and every built-in UID is **composed** from it — that direction, and
  not deriving the prefix back out of the values, is what makes it impossible to declare a
  built-in outside the range rather than merely detectable; one edit moves all of them
  together. The other end is `lib.core.uids.new_uid`, which re-draws if a `uuid4` lands in
  that range — so "is this UID one of ours?" is answerable from the value, with no lookup and
  no false positive possible.
  Twelve leading zeros is not a realistic draw and this loop will not run twice in the
  product's lifetime; it exists so the boundary is a guarantee rather than a probability,
  which is the only kind of statement worth making about identity. The rule holds only while
  every identity goes through it, and accounts are minted in **seven** places — the three
  services plus LDAP, OIDC, SAML2 and SCIM — so a guard fails the build on a bare `uuid4()` in
  any of them. Existing UIDs are untouched: this is a promise about new values, not a
  validation rule.
- **…and they moved: the kind now lives in the UUID's variant block** — `…-8001-…` users,
  `…-8002-…` groups, `…-8003-…` roles. **This is a breaking change for any database written
  before it, and it ships with no migration** (pre-release; the development databases were
  rewritten by hand). Those values are identity: they sit in every user's role, in every
  group→role link, in the group row itself, and — as plain text inside JSON — in the six
  `*|default_role` config keys and in any `group:<uid>` notification recipient. An older
  database does not fail loudly on the new code; it resolves to "unknown role" and everyone
  lands on the fallback. Recreate it, or rewrite those five UUIDs before starting.
- **Byte sizes now say which base they are in: `GiB`, not `GB`.** The ladder was always
  binary — it divided by 1024 while printing "GB", the Windows convention — and the
  ambiguity surfaced the moment somebody asked whether the two formatters counted the same
  thing: a `1.0 GB` here is 1073741824 bytes, while the same three characters on a disk's
  box mean 1000000000. **No value moved**; only the suffix names it. `to_bytes` still reads
  the old spellings (`GB` → `GiB`) because a threshold an admin saved has to go on meaning
  the same number of bytes, and it shares the ladder with `fmt_bytes` — if one scaled by
  1024 and the other by 1000, a limit typed as "100 GiB" would read back as "107.4 GiB" and
  drift every time it was looked at.
- **Stored unit names are migrated on the way out of `/api/v1/modules`.** Not cosmetic: the
  m365 threshold dropdowns now offer `MiB/GiB/TiB`, and a `<select>` whose value is absent
  from its options displays the FIRST one — so opening an item and saving it without
  touching anything would have rewritten a 100 GB limit as 100 MiB, a thousandfold change
  made by looking at a page. Driven by the `_unit` field-name suffix, so a module that adds
  a threshold later is covered without this having to know about it.
- **Maintenance stopped presenting eight identical red buttons as one row.** Reclaiming space
  and deleting data have opposite consequences and the section said they were the same kind of
  act. It is now a card per action — icon, name, one line of what it does — under a heading
  per group. Actions declare which group they belong to (`group_label_key`) and their
  description (`desc_key`): declared data, not inferred from a handler name or a button
  colour, which is what the next action added would have had to guess at. A section whose
  actions declare no group keeps the single row it had.
- **"Reset state" moved from the Status toolbar to Maintenance.** It empties a table exactly
  like the wipes beside it, and a destructive action parked among a screen's view controls —
  refresh, filter, run-now — is the one pressed by accident. `resetStatus()` still lives with
  the Status code it refreshes; only the button moved, and it now checks that screen is
  rendered before re-rendering it.
- **Clearing the check state needs `checks_delete`, a new permission held by no built-in
  role.** It used to ride on `checks_run`, which `editor` holds and which means "may operate
  monitoring" — a fair pairing while the button sat next to "run now", and the wrong one once
  it moved in beside the data wipes, where it left one destructive action an editor could fire
  among eight that nobody can by default. Running a check and erasing what every check reported
  are different acts. Changed on the endpoint, not just on the button.
- **Every permission is now labelled and explained, and a guard keeps it that way.**
  `db_maintenance` shipped with neither: a flag with no label renders in the roles matrix as
  its raw name, and one with no hint is a checkbox granting something the admin has to guess
  at. The guard walks all 66 flags in both languages, and in the other direction too — a label
  for a permission that no longer exists is dead text that outlives every reader who could
  have noticed it.
- **The six wipes all say the same verb now, in both languages.** They read as three
  different operations when one said "Borrar", another "Eliminar" and a third "Vaciar" —
  a difference that implies a distinction which is not there, and costs the reader attention
  working out that there is none, in the section where attention is worth most. English had
  the same split between "Clear" and "Delete". A guard now fails the build if the verbs
  diverge again, per language.
- **A button inside a card only says the verb.** With the name and the description two lines
  above it, "Eliminar todos los eventos de auditoría" was a caption repeating what had just
  been said — the button is now "Borrar", "Vaciar". Declared as `button_key`, falling back to
  the full `label_key`, because an action rendered as a bare row has no card around it and
  there the button IS the only label. The database pair keeps its own names: "Optimizar" and
  "Compactar" are already one verb, and shortening them would say less.

## [0.0.1+build.37] - 2026-08-01

### Fixed
- **The Configuration index counted options that do not apply.** Database showed "6 modified"
  while offering two settings: on SQLite the host / port / name / user / password left behind
  by a MySQL deployment are still in the config, no longer apply to anything, and were still
  being counted. The number then sent the reader hunting for four settings that are not on the
  screen and would do nothing if they were — the opposite of what a "modified" count is for.
  Conditional options already declare themselves (`.sw-field[data-sw-when]`); nothing was
  asking. The check goes into `_cfgFieldIsChanged`, the single definition the count, the
  filter and the index all read, so all three agree by construction. It reads the marker and
  never computed visibility: every card but the section on screen is hidden at any moment, so
  `offsetParent` would have zeroed the count of every other section.
- **Switching the database engine left the count one change behind.** The select fires
  `updateField(...);_refreshConditionalFields(...)` in that order, so the refresh the first
  call triggers ran against the old visibility. `_refreshConditionalFields` — the only thing
  that changes which options apply — now recomputes the marks itself, scoped to the config
  sheet so module items do not pay for it.

## [0.0.1+build.36] - 2026-08-01

### Fixed
- **Cloning an item stored it and reported failure.** Reported against m365, true of every
  module: clone an item, rename it, save — the record IS written while the screen says "Error
  al guardar", the Save button stays lit, and the audit shows neither the save nor the error.
  Two defects lined up. The clone kept the original's `uid` (a deep copy of an item copies its
  identity too), so it arrived claiming to be the original and tripped the duplicate-uid alarm
  built to catch real corruption. And recording that duplicate crashed the request:
  `_diff_dicts` returns `[{field, old, new}]` and the note was appended with `+` as if it were
  a string — `TypeError`, raised AFTER the write had committed and BEFORE the audit line ran.
  The clone now drops uids (recursively, and by exact name so `cred_uid`/`host_uid` references
  survive), and the note is a row in the change list. The endpoint still tolerates a duplicate
  uid, because an imported config or a hand-edited file can still carry one.
- **"Modules saved" was audited even when nothing changed.** A PUT that stores what was
  already there is a no-op, and an entry with nothing under it is worse than no entry at all:
  the audit is read to answer "what changed and when", so a row that answers "nothing" costs a
  click to find that out and invites the reading that a change was made and lost. Now the
  entry is written only when there is something in it. (The duplicate-uid note counts as
  content in its own right — it reports something that happened even when no field moved.)
- **The pinned header's shadow broke off square at its rounded corner.** A `box-shadow`
  traces the `border-radius` of the element that DECLARES it — and the shadow is declared on
  the `.ss-bleed-top` wrapper while the rounded bottom belongs to the toolbar inside it, so
  the shadow went on drawing the wrapper's square corner beside the child's curve. The
  wrapper now carries the same radius; it draws nothing itself, so the value exists purely to
  shape the shadow. One token covers both states, since `.ss-toolbar` and the search box's
  `.rounded-bottom-3` both resolve to `--bs-border-radius-lg`.
- **The Configuration toolbar looked square-bottomed in light mode.** Reported as a missing
  border radius; it was never missing. `.ss-bleed-top` removes the pinned header's side and
  top borders, so its bottom border is the only thing left to draw that curve — and the dark
  theme redefines `--bs-border-color` to a value *lighter* than the bar it sits on, while the
  light theme inherits Bootstrap's `#dee2e6` against a `#e9ecef` bar. Two greys a dozen points
  apart render a corner nobody can see. The light theme now gives that one border enough
  contrast to show the shape it already had.
- **Cloning asks for the name before it copies anything.** It used to clone on the click,
  which left two rows under the same label with no way to tell which was which — and no way
  back, since the copy already existed and leaving meant Undo or Discard. A modal now proposes
  `<name>_Copia1`, counting up to the first free one and restarting from the base name so
  cloning `web_Copia1` offers `web_Copia2` rather than `web_Copia1_Copia1`. Blank and
  already-taken names are refused in the modal, where they can be corrected. Cancel means
  nothing happened. The typed name is written where the list READS it — through the same
  helper, so the two cannot drift: most collections declare the field (`label`, `ups_name`,
  `process`), and the ones keyed by the thing itself become field-named the moment the
  server's re-key turns their key into a uid and stamps the old key into `label`.
- **The audit now says whether an item was created or cloned, and from what.** `_diff_dicts`
  reports a new item's fields the same way either way, which is exactly the distinction
  somebody comparing two near-identical rows needs. The UI stamps `__cloned_from__` on a copy;
  the save TAKES it — never stores it, since it is a fact about the moment the item was
  created, not a property of the item — and turns it into a row naming both items by the field
  their module declares as the name.
- **The clone toast quoted the item's key instead of its name.** Once an item has been saved
  its key IS its uid, so cloning announced "Cloned as:
  `d19b5737-da04-4fa2-b2ab-6c6e11c3e913_copy`" — a string identifying nothing visible on
  screen, about a copy the user is about to rename anyway. It now uses the collection's
  declared title field, the same one the pencil button edits.
- **An unhandled exception left no trace anywhere.** Asked directly: why is there nothing in
  the audit or the console, just "Error al guardar"? Because nothing recorded it at any of the
  four points that could have — no `errorhandler` was registered, `after_request` does not run
  when a handler raises (so the per-endpoint trace line that logs every 4xx/5xx never fired),
  the traceback went to Flask's logger which this panel wires into neither its debug output nor
  its log file, and no code wrote an audit entry. The client then discarded what survived: an
  HTML error body threw inside `r.json()` and landed in the same `catch` as a dropped
  connection, returning the same `null` the toast had no error to read from. Now one short
  reference appears in three places at once — the log line, an `internal_error` audit entry
  naming the endpoint and the exception, and the message on screen — while the traceback stays
  out of the response. `HTTPException` passes through untouched (a 404 is an answer, not a
  fault), and under pytest/debug the exception is still raised, so a crash in the suite still
  fails like one.
- **A syslog hostname from the network could take a write batch with it.** `hostname` and
  `app` are indexed columns, so on MySQL they are `VARCHAR(255)` — an index needs a bounded
  type — and nothing between the socket and the INSERT bounded their content. A sender
  emitting a 1000-character hostname hits "Data too long for column" on a strict-mode MySQL,
  and the writer batches 500 rows at a time, so one malformed datagram could fail the batch.
  SQLite stored it happily, which is why it never showed up in development. Clamped to the
  RFC's own limits (5424 §6.2: HOSTNAME ≤ 255, APP-NAME ≤ 48), in the public parse function
  rather than inside the parser, which has four exits.

### Added
- **A guard that keeps `ref-esquema-bd.md` describing the tables that exist, and all of them.**
  It is the only place the physical schema is explained in prose, which makes it what somebody
  reads before touching a store — and nothing kept it honest: the tables matched by hand on the
  day it was written, and the next `TableSpec` would not have failed anything by going
  undocumented. Both directions, because a documented table that no longer exists is the rot
  that lasts longest: nobody greps for a name that is gone. Columns and their order too — order
  is load-bearing for the reconcile, since a column missing from the end is added in place
  while one missing from the middle rebuilds the table. It found the first drift immediately:
  `msteams_channels` was described in prose ("same shape as `webhooks`") instead of with its
  columns — accurate, but not checkable, and the kind of claim that expires by itself the day
  `webhooks` gains a column.

### Changed
- **`app.py` is the class again, not the panel.** It had reached 1119 lines with a single
  372-line method inside it; four things that had no business there moved out to
  `lib/web_admin/mixins/`, each as a whole block rather than rewritten. What stayed is what the
  file is for: `__init__` composing the object in an order its own comments explain, and
  `_create_app` assembling the Flask app from the pieces. 1119 → 626 lines.
- **The order of the request lifecycle is declared, not implied.** Flask runs `before_request`
  handlers in registration order, so the panel's security order was the order of five
  decorators in the middle of that 372-line method — true, load-bearing, and written down
  nowhere. Moving a block while tidying would have changed who guards what, and every test
  would still have passed with the fail2ban gate running third. `_HooksMixin._BEFORE_REQUEST`
  is the order now, with the reason for each position beside it, and a guard that checks the
  registration actually reads it rather than the tuple being documentation.
  Writing it down surfaced two dependencies nobody had stated: CSRF is judged **before** the
  FQDN redirect, or a state-changing request that arrived on the wrong hostname is bounced to a
  URL that drops its body and its token is never looked at; and the shared caches refresh
  **before** anything authorises, since a CSRF rejection is audited against the user store.
- **The four route guards share one refusal.** They all began with the same "is there a
  session?" check, written out four times — and the load-bearing part is not the check but the
  ANSWER: an API caller gets 401 JSON, a browser gets the login page. Reply the wrong way and a
  `fetch()` renders a login page into a table. Written once now, so four copies cannot drift
  into three answers.
- **The template context is one file.** Adding a constant for a template used to mean opening
  the file that owns the request lifecycle. It also gained a seam worth having: "available" and
  "enabled" are different questions about an auth provider, and the login page asks both.

## [0.0.1+build.35] - 2026-08-01

### Fixed
- **Two thirds of the configuration had no default.** No "restore default" button, and an
  emptied box that showed nothing instead of the value the system would actually use —
  Platform health, LDAP, the database, the syslog receiver, most of Notifications. The
  frontend asked `CONFIG_FIELD_DEFAULTS`, which is five deliberate exceptions back-filled at
  boot from `/api/v1/config/schema`; that schema carries `default` for instance-backed
  bool/int fields and for nothing else, so ~65 options had one and the other ~136 silently did
  not. It read as correct because the code around every lookup said "the registry default"
  while asking a map that only knew a slice. One helper answers now, exceptions first — `lang`
  still restores to the system's language rather than the factory one, because restoring a
  Spanish install to English is not "restore default" — and nothing reads either map directly.
- **A config number sitting at its default is drawn empty**, with that default greyed inside
  the box. Printing 60 as a value claims an admin chose 60, and leaves nothing on screen to
  tell a deliberate 60 from the one that shipped. Clearing the box returns to exactly that
  state, so it stays empty rather than springing back with the number in it. What gets stored
  is the default itself, never null: a config option has nothing to inherit from, and
  `cfg.get('x', 60)` returns None for a stored null — it falls back only for an absent key —
  so the quiet consumers would be the first to break. This is the plain-number branch, where
  most config options land, since the schema only describes the instance-backed ones. Text
  options show their default too when it is not empty, but clearing one still means empty —
  for a string that is usually a real answer.

### Changed
- **A configuration section is a sheet, not a card.** The frame, the chevron and the colour
  accent were right when seven tabs showed several cards at once. With one section on screen
  the box was a frame inside a frame, the chevron collapsed the only thing there, and the
  accent distinguished it from nothing — the index already says which section you are in, and
  says it better. What is left is a title, a line saying what the section is for, and its
  options as hairline-separated rows.
- **Every section says what it is for**, in one line under its name — thirty-four of them, in
  both languages. Registered by convention (`cfg_desc_<id>`): writing the string is what
  registers it, so thirty-four sections cannot become thirty-four chances to add one and
  forget the line.
- **An unset option is no longer reported as an edited one.** Blank is how "not set" is
  stored, and not set IS the default — which is exactly what the greyed placeholder in the
  empty box says. Comparing the two as text made every unset option look like a change away
  from a value it had never been given: the bind address sat empty, showing `0.0.0.0` behind
  it, and was counted and marked as edited. `0` and `false` are real answers and go on being
  compared.
- **A locked option is marked wherever it is drawn.** The env/file lock was bolted onto the
  row by `renderScalarFields`, which only the bespoke cards go through — so the same option
  was marked inside one kind of card and unmarked inside another, and everything reading the
  mark disagreed with itself depending on where the option happened to live. `renderField`
  marks it now, and every renderer goes through there.
- **Every row says whether it is stock, edited, or edited and not yet saved.** The header
  counts them and the index counts them per section, but neither answers it for the row in
  front of you — and "is this 60 mine or theirs?" gets asked one option at a time, in the
  middle of changing something else. Two signals, because a colour alone is not one: an accent
  down the left edge to scan a column by, and the row's own "restore" button going dim and
  inert when there is nothing to restore. That button always sat there offering a no-op on
  stock rows.
  Pending is its own state and its own colour: "edited" and "edited a moment ago and not
  written yet" answer different worries, and collapsed into one, a row you just typed into
  looks exactly like one somebody configured last year.
- **Four of the five hand-written selects are declared instead of drawn.** The audit sort and
  its direction, the e-mail provider and the Teams delivery mechanism are described in the
  registry now — options, per-option labels, default, and `on_change` for the sibling to
  refresh — and the shared renderer draws them. A hand-written control quietly misses whatever
  the shared one learns next, and these four missed the env/file lock: an option pinned in
  `config.json` looked editable, and the save was discarded server-side without a word.
  `on_change` is the one thing a select could need that the registry could not say, and the
  reason all four were written by hand; the function name belongs to whoever needs it, not to
  the core.
- **The fifth one too: a list of numbers is now vocabulary** (`int_list`). The renderer knew a
  list of strings and an array it stored as strings, so an option holding numbers had nowhere
  to land — which is exactly why the table row-count list was written by hand, missing the
  env/file lock and repeating its own default as a literal placeholder. Nothing in the
  Configuration screen draws its own control any more.
- **The row counts a table's chooser offers are declared once, in the registry**
  (`web_admin|table_rows_options`), and reach the panel through `CONFIG_REGISTRY_DEFAULTS` like
  every other default. `[25, 50, 100, 200, 0]` was a literal in three files, so changing it
  meant finding all three — and one copy per side is still two copies. The list gains **15** as
  its first choice.
- **`web_admin|lang` and `web_admin|dark_mode` are `default_lang` and `default_dark_mode`** —
  which is what they are: the language and theme a user gets *before* choosing their own, since
  every account keeps its own preference. Under the naming rule above, `lang` produced `_LANG`,
  and `session['lang'] or wa._LANG or DEFAULT_LANG` then read as "the session's language, else
  the language, else the system's" with no way to tell which term was the default. The option
  was the thing named badly, not the rule. `SS_LANG` and `SS_DARK_MODE` are unchanged: an
  environment variable is a published surface.
- **The start-up fallbacks stopped restating a default.** `DEFAULT_PORT = 8080` and
  `DEFAULT_HOST = '0.0.0.0'` sat on `WebAdmin` beside the registry entries that already said
  exactly that. They come from the registry now: a second copy of a default is a copy that gets
  to disagree, and the failure it produces is the panel offering one number as the default
  while the server binds to another, with nothing on either side saying which is real.
- **Four class constants named files the product no longer writes.** `_ROLES_FILE`,
  `_GROUPS_FILE`, `_SESSIONS_FILE` and `_STATUS_FILE` were declared on `WebAdmin` and read by
  nothing: roles, groups and sessions have their own DB stores, and `status.json` became the
  `check_state` table. Worse than dead weight — they send a reader looking for where the data
  lives to a file that will never exist.
- **`.flask_secret` has one name.** It signs Flask's session cookies AND derives the Fernet key
  every stored secret is encrypted with, so losing it is not "sign in again" — it is every
  secret in the database becoming unreadable. Its filename was spelled out in six places: the
  panel, the CLI and the four standalone services, one typo away from a process deriving a
  different key, decrypting nothing, and reporting the configuration as empty rather than as
  broken. `lib.config` owns it now, beside `CONFIG_FILENAME`, with a helper for the path.
- **A mirrored config attribute follows from its option**: `_` plus the option name, upper-cased.
  It was written out by hand beside each one — thirty-seven `_UPPER_SNAKE`, eleven
  `_lower_snake`, and ten that matched nothing (`_WEB_PORT` for `port`, `_LOGIN_RL_MAX` for
  `login_ratelimit_max`). With no rule to check, `_DEFAULT_PAGE_SIZE` outlived the rename of the
  option it mirrors and nobody noticed; a guard fails now if the two drift again.
- **Four options were mirrored on two attributes at once.** `_PUBLIC_STATUS`, `_PUBLIC_URL`,
  `_FORCE_HTTPS` and `_FORCE_FQDN` sat as class defaults beside the lower-case attributes the
  config actually wrote to. Only one of each pair was ever updated; the other looked
  authoritative and answered with the value the product shipped with. The rename collapsed
  each pair into one.
- **`syslog|max_rows` is `syslog|max_messages`** — the same mistake as `page_size`: table
  vocabulary for what an admin is actually setting, which is a number of messages. The store
  keeps `prune(max_rows=…)`, because at that layer they really are rows and renaming it there
  would have been the opposite error.
- **Four providers shared "Default role (new items)"**, which names neither who gets the role
  nor when. LDAP, OIDC and SAML2 assign it when no group maps; SCIM when a user is
  provisioned — and each says so now.
- **Two options were labelled with another section's words**, and three more did not say what
  they were. A label is looked up by path and then by bare name, so `scim|token` inherited
  Telegram's "Bot token" and a Teams channel's `name` inherited the database's "Database name".
  The section renderers happen to pass their own text, so the screen was right — but anything
  resolving a label generically, such as the "config changed elsewhere" dialog, printed the
  wrong one. Keyed by path now, where nothing else can claim them. And `monitoring|timer_check`
  ("Interval"), `modules|threads` ("Threads") and `modules|timeout` ("Timeout") now say what
  they time and what they count.
- **Clearing a list option means its default.** Making the row-count list editable through the
  shared renderer made emptying it a natural gesture, and emptying it produced an empty list —
  the only thing it could produce — which the server rejects outright, contradicting both the
  rule the rest of the screen teaches and the greyed default in the box's own placeholder. At
  its default the box is drawn empty now, which is what makes "clear it to get the default
  back" true rather than a claim. The server keeps refusing an empty list: nothing can produce
  one any more, so it is the last line of defence instead of the first thing a reader meets.
- **No table carries a second default.** `let _syslogPageSize = _tableRowsDefault || 50` was
  two faults in one line: it ran at parse time, before the config had loaded, so the admin's
  choice never reached it — the number was decided by the declaration and nothing could change
  it — and `|| 50` turned 0 into fifty, when 0 means "show all". Every table reads the
  configured value on first use, and no number is supplied beside it. The panel's own copy of
  that default is gone too; it comes from the registry like the list.
- **`page_size` renamed to say what it counts**: `web_admin|table_rows_default` (what a table
  opens with) and `web_admin|table_rows_options` (the counts its chooser offers). "Page size"
  reads as something about the size of the page and names neither tables nor records; and the
  two are a pair — the second is the vocabulary the first is expressed in — so they are named
  as one. Labels and hints follow. "Audit entries" became "audit events", the word the rest of
  the panel already uses for the same thing.
- **`web_admin|audit_max_entries` was rendered nowhere.** The registry said "rendered by the
  'audit' card"; the card drew two selects and nothing else, and the option has no `card=` for
  a generic card to place it by. It was invisible in the panel, env-lockable and all.
- **The five hand-written option rows behave like every other row.** Audited on request:
  Audit's two sort selects, Tables' page sizes, the e-mail provider and the Teams delivery
  mechanism write their own control instead of going through `renderField`, and every one of
  them omitted `data-cfg-path`. That attribute is how a row tells the sheet which option it
  is, and four things hang off it — the stock/edited accent, the section count, the "only what
  changed" filter, and whether the restore button has anything to do. Without it the row looks
  identical and is invisible to all four. The Teams row also had no restore button at all, and
  the two Audit selects wrote `configData` from their own handler, skipping the bookkeeping
  that refreshes the marks.
- **A UI preference has a default too.** Sort order and page sizes are deliberately not in
  `spec.py`, so a check that consulted only the registry found no default for them and
  reported them as edited for ever; `audit_sort_dir` had none in either map, which left its
  restore button calling a function that bailed on the spot — a control that looks live, does
  nothing, and says nothing about it.
- **fail2ban's exposed services behave like the rest of the screen.** They had no restore
  button and never reported an edit: each row is a record in its own store, written through
  its own endpoint, so the registry has nothing to compare it against. That is a reason to
  behave differently on the wire, not on screen — a reader has no way to know which rows are
  backed by which store, and should not need one. A row can now answer for itself
  (`data-cfg-changed`), through the same predicate as every other row, so the card stops being
  a hole in every total; and it gets the same "back to the default" button, inert when it is
  already there.
- **Putting a value back where it was undoes the pending state.** Changing an option and then
  restoring it left the row marked as unsaved with the Save button still lit. Two causes: the
  pending set only ever grew, so a path stayed staged after being undone — which also meant the
  save wrote a value the server already held — and the "as loaded" baseline that decides the
  Save button was snapshotted BEFORE the renderer seeds the options the server never sent. From
  the first render the two differed by dozens of keys nobody had touched; the button stayed off
  only because nothing compared them until the first edit, and after that putting the value back
  could never turn it off, because the difference was never the value. The baseline is given the
  seeded keys now — only the ones it lacks, never a value it holds, so a real edit cannot be
  swallowed. An option the server never sent at all — many are only ever read as
  `cfg.x || <default>` and never stored — has somewhere to return to as well: what the server
  would use for it is its default, and comparing against `undefined` can never match anything
  a reader can type. Once such an option has been typed into, its key exists on one side and
  not the other, so it is written into the baseline too, but only where the two values already
  agree.
  Records with their own routes — webhooks, Teams channels, the scheduler interval — are saved
  state as well: the panel wrote them to the server and synced only the in-memory copy, so
  creating a webhook lit "unsaved changes" for something already written, and Save then sent
  nothing (it sends the staged paths, which these never enter) and could not put the light out.
- **The marks and the counts follow an edit and a save**, instead of waiting for a full
  re-render. They were frozen at whatever the last one decided, so a row you had just changed
  went on claiming to be stock and stayed wrong through the save — until you left the section
  and came back. A number that is only right at certain moments is worse than no number,
  because nobody can tell which moment they are in. Neither a re-render nor a re-filter: the
  fields keep their DOM, so focus, caret and half-typed values survive, and the rows on screen
  do not shift under the hands of someone in the middle of typing.
- **"Only what changed" is a switch in the toolbar**, beside search, reload and save — and the
  "N modified" count in any section header is the same switch. The screen could count that
  answer and never show it: reading "3 modified" was followed by hunting for the three, which
  is the work the number was supposed to save. On, sections holding no changes drop out of the
  index and options still at their shipped value drop out of the section; on a stock install
  it matches nothing, and says so rather than leaving an empty screen. Env-locked counts as
  changed — the deployment moved those, and they are the ones an admin cannot move back here.
  It is a MODE, not a search: everything is still navigated one section at a time from the
  index. Searching is what replaces the navigation, because being shown one section at a time
  is not an answer to "where is X"; a mode that also changed how you move around would have
  stopped being a mode and become a different screen.
- It runs THROUGH the search filter rather than beside it, so the two compose: **one pass**
  decides which rows and which sections are on screen, and the index reads the result. Two
  passes setting the same `display` end with whichever ran last winning by accident — which is
  also why the redraw is one function in a fixed order (restore, filter, index): restoring
  after the filter handed visibility straight back to everything the filter had just hidden,
  and the index saw all thirty-four sections survive. The filter and the index also walk the
  same unit now; matching `.cfg-card` left the notification-templates wrapper — two cards, and
  the thing the index actually lists — undecided, so it outlived every filter with nothing in
  it. Two passes with two ideas of what a section is will always disagree about one. And
  "changed" is now defined once instead of three times — they agreed only by luck, and the day
  one of them learned about env-locked and the others did not, the count and the list it was
  counting would have stopped matching.
- The search matches sections by `.cfg-card`, the class one is BUILT with, instead of the four
  Bootstrap utilities its frame happened to carry. That selector stopped being true the day
  the frame went, and it would have taken the search with it without a word.
- **Closing the search box clears the term.** Putting the box away is how you say you are done
  searching, and a filter left running from a control that is no longer on screen leaves the
  panel showing a fraction of itself with nothing visible to explain why. That state used to
  be survivable because a warning dot sat on the toggle; the dot is gone with the state it
  warned about, because a badge for something that cannot happen is one more thing to keep true.
- **While a search is running, the index is the result list.** It used to answer "here it is"
  in the sheet and go on listing all thirty-four sections beside it, as if nothing had been
  asked — and the one question it could have answered there, *where did this turn up*, it was
  refusing to. Now only the sections that matched appear, each with how many of its options
  did, empty groups drop out entirely, and a search that matched nothing says so where the
  results would have been. The badge changes colour with its meaning: "matched here" and
  "departs from stock" are different questions, and one badge meaning either depending on a
  box elsewhere on screen means neither.

### Added
- **The section header is pinned.** Which section you are editing, and how much of it this
  install has moved, stay readable however far down the options you are — the two things a
  long list makes you scroll back up to check. Three sheets were built and compared on real
  data (a plain list, one with every hint in view instead of behind an (i), and this one); the
  two that lost took their CSS, their strings and their switcher with them the day it was
  decided, because three ways to draw the same rows is what this screen was rebuilt to stop
  doing.
  A pinned header, it turns out, has to be opaque, has to start flush against the bar above
  it, and must not reach past the rows it covers — and it started as none of the three. The
  scroll box fades its own top 10px and opens with padding there, both exactly where the
  header pins; and stretching it to cover Bootstrap's row gutter only painted over the pane's
  own edge. The FIRST section on screen keeps a square top and a rounded bottom for the same
  reason the toolbar does: that is the line the scrolling body disappears under, and rounding
  it is what says so. Every other header — a search puts several on screen — rounds all four,
  because a block that touches nothing with one square edge looks attached to something that
  is not there.

## [0.0.1+build.34] - 2026-07-31

### Added
- **Configuration is an index down the side and one section beside it.** Seven sub-tabs held
  twenty-seven cards and answered exactly one question well: "show me the settings about X".
  Finding a setting meant opening seven of them, and they said nothing about the six you were
  not looking at. The index shows the whole shape at once — and **marks where this install
  departs from stock**, per section and per group, before anything is opened. That count is
  why it earns its width: it is the first question of any diagnosis, and a tab strip can
  never answer it. Env-locked options count too: the deployment decided them, so they are not
  stock either.
- **Notifications is eight sections instead of one card with four sub-tabs inside it.**
  General, routing, events, Telegram, e-mail, Teams, webhooks and templates each stand on
  their own in the layout. They were nested because the screen was a strip of tabs and there
  was nowhere else to put them; with an index there is, and a section reachable only by two
  clicks and a nav the index has to hide is a section pretending to be a card.
- **A card that fetches declares its own loader** (`data-cfg-load`), and the index calls it
  when the section is shown. Notification templates used to start that fetch from the click
  on its sub-tab, and the day the sub-tab stopped existing it sat on "Loading…" for ever with
  nothing on screen to say why. The next card built that way needs no change to the index.

### Changed
- The index is a **pass over the DOM `renderConfig()` already produced**, exactly as the
  search filter has always been. Cards are shown and hidden, never rebuilt, so switching
  section keeps every field's handlers, tooltips and half-typed values; the detail column
  **moves** the rendered content rather than copying it, because a copy would be a second set
  of the same inputs and only one of them would be the one that saves.
- **The index sits beside the section, not inside its body.** It reads as one change and it
  is the one that finally made it work: inside the body it began where the body began and
  ended where it ended, which is why it kept stopping short of the page however its height
  was computed. It runs the full height of the pane now, and the toolbar sits over the DETAIL
  — reload, save and search are about what is being edited, not about the index of what could
  be. Sizing it with a max-height guessed from the viewport was the wrong tool throughout:
  the number never matched where the pane actually ends. It reaches the frame on all four
  sides too: the content container's gutters, its top padding and its bottom padding were
  showing through as strips of page background around it, and an index is a piece of the
  frame rather than content sitting inside it. The column is what bleeds now — the toolbar
  inside it gave up its own, because cancelling the same padding twice put it above the
  header and a gutter past both sides.
- **The search and the index share one screen, and agree about who is deciding.** Searching
  still reaches every section — all thirty-four cards stay in the DOM precisely so it can —
  and emptying the box hands the screen back to the index rather than dumping every card on
  it at once. Picking a section ends the search, because opening one with most of its fields
  still hidden by a collapsed filter box is how a screen lies about what it contains.

### Fixed
- **A module section is a landing page you can actually be sent to.** The post-login redirect
  resolved landing ids against the CORE page tuple, which module sections were never in — so
  choosing "m365" saved the setting, logged you into the admin panel anyway, and said nothing.
  It resolves against every destination now.
- **The landing menu names its destinations and lists all of them.** A module section names
  itself in the module's own lang file, which the core catalog has never heard of, so the menu
  printed the raw id ("m365", "azure") among proper names. And a section with several views is
  several destinations: "m365" is not a place, it is whichever view happens to be first, so
  each view is now its own entry ("Microsoft 365 · Almacenamiento") and the bare section drops
  out of the list — while staying valid, because it is what every landing saved before views
  existed says. Labels resolve server-side, once, for the three selects that offer them
  (config, user, group).
- **Forty-four configuration options had no label in either language.** `fieldLabel()`
  humanises a missing key instead of failing, so "Landing Page", "Allowed Sources",
  "Retention Days" and "Max Rows" sat in the middle of a Spanish panel looking enough like
  labels to survive review. Named now, and a guard fails when the next option ships without
  one.

### Removed
- **The sub-tabs, and the switcher that offered them alongside the index.** Both shipped for
  a while and the second navigator earned nothing: the same cards, reachable a second way,
  with its own state to keep in step and its own bugs — a card whose sub-panes the index had
  to reach through, a panel that loaded from a click the index never made. Deleting it
  deleted them. Three further views went the same way — a flat list, an only-what-changed
  filter, an all-on-one-page scroll — along with their strings: a view nobody can reach is
  code that rots unread until someone believes it works.

## [0.0.1+build.33] - 2026-07-31

### Added
- **The tenant is ASKED about its own storage settings** rather than having them deduced
  (`/admin/sharepoint/settings`, read-only, `SharePointTenantSettings.Read.All`). Two things
  this check used to guess at now come from the tenant itself:
  `isSitesStorageLimitAutomatic`, which decides whether the per-site quotas mean anything at
  all — a site at 25 TB is a ceiling under automatic management and a real quota under manual,
  and nothing else can tell those apart — and `siteCreationDefaultStorageLimitInMB`, which IS
  the ceiling, so the hardcoded 25 TB drops to the fallback it should always have been.
  Unanswerable — no permission, any failure — keeps the old inference, which errs towards
  "no capacity".

- **A diagnostic action, `sharepoint_settings`**, that returns the tenant's SharePoint
  settings verbatim. The pooled quota is the one number the storage check cannot obtain, and
  how much of `/admin/sharepoint/settings` actually carries is a question about a live tenant
  rather than about documentation — this answers it with the tenant's own reply instead of
  anybody's recollection. Read-only, unfiltered on purpose, with the storage-looking
  properties called out because the reader is hunting one number among twenty-odd.

- **Warn when the free space drops below X** (`tenant_free_min` + `tenant_free_unit`), beside
  the % and the absolute-used thresholds. It is the third way of asking the same question and
  the one capacity is actually planned with: a percentage means different amounts as the
  tenant grows, and "250 GB used" says nothing without knowing the capacity — "under 50 GB
  free" survives both. Offered only where there IS a capacity: without a total there is no
  "left", and a threshold that silently never fires is worse than one never offered.

- **Every threshold has a module default now.** Ten of them existed only per item, so with
  several tenants the same policy had to be typed into each one — and three hid a fallback in
  the code (30/60/14 days) that the schema never declared. One helper resolves the chain the
  way `site_usage_pct` always did, item → module → schema, and the module pane finally offers all
  of them.
- `global_admins_max` ships **5** as its module default, deliberately: a tenant with more than a
  handful of Global Administrators is worth saying out loud whether or not anyone configured
  it, and five is Microsoft's own guidance. The cost is stated rather than discovered — an
  item left at 0 inherits it, so a tenant that had this alert off gets it back.
- The other optional ones start at 0 in the module pane on purpose. A 0 in an item used to mean OFF
  and now means "inherit": with an inherited 90 that would switch on an alert somebody
  deliberately switched off. A fleet-wide policy is something an admin writes, never something
  an upgrade decides for them.

- **A module default can be cleared again.** `sites_top`, `accounts_top` and
  `breakdown_page` had no `inherit_blank`, so emptying one restored the stored value on blur
  and no placeholder said what a blank would fall back to. They store null now and show the
  built-in default as the placeholder — which is what a blank at module level means: "use what
  the system ships with". `alert` stays as it is: it is the consecutive-failure count with a
  floor of 1, and "no threshold" is not a state that field has.
- **The guard found twelve more across eight modules, and they are fixed too** — cpu, ntp,
  ping, process, datastore, ram_swap, ssl_cert, ups and web. Not by setting the flag in bulk:
  `inherit_blank` stores null, and a read like `int(self.get_conf(x))` meets that null as a
  TypeError in the middle of a check, which is a monitor that stops monitoring because a box
  was emptied. Each read moved to `module_default`, which keeps the distinction that matters:
  blank falls through to what the system ships with, an explicit 0 stays 0.
- `module_default` now returns the TYPE of its fallback. cpu's `interval` and ntp's
  `max_offset` are floats, and coercing them to int turns 0.5 s of sampling into 0 — a
  different measurement, not a rounder one.
- **An item field now shows what it inherits.** "Sites to store" and "Accounts to store"
  rendered an empty box with no placeholder: an item field that inherits from its MODULE has
  `default: null` of its own, and the placeholder cascade only knew about the GLOBAL
  Configuration>Modules value — so it ended at null and showed nothing, which is exactly what
  "blank means inherit" must not look like. The cascade gained the module step: global →
  registry → the module's own value → the field's schema default. A guard fails on any field
  that inherits without saying what from.
- **`alert` too**, in all eleven modules that declare it. It had been left out on the theory
  that "no threshold" is not a state it has; that was the wrong reading. At module level a
  blank never meant "off", it meant "use what the system ships with", and the placeholder is
  what says so.
- **An amount and its unit are one row now.** "Warn under 50 GB" is one thing to decide and
  it was drawn as two — the number, then the unit on the next row — leaving the reader to
  assemble it. A field names the sibling that holds its unit (`unit_field`) and the core
  attaches that sibling to the box; the unit loses its own row, and writes through the same
  field it always did. Declared rather than guessed from a `*_unit` name, which would work
  until a module ships one the convention does not fit. A guard fails on any unit nobody
  claims, so a new amount+unit cannot land as two rows again. The selector states its
  width in a class of its own: Bootstrap gives a `.form-select` inside an `.input-group`
  `flex:1 1 auto; width:1%`, so clearing only the growth leaves the 1% behind and the
  control collapses to its chevron — three options present and nowhere to draw them.

### Fixed
- **An item can no longer be lost to a repeated uid.** Re-keying items by uid builds a dict
  keyed by that uid, so two items sharing one meant the second write silently replaced the
  first — no error, nothing in the audit, a check that stopped existing. A taken uid now gets
  a fresh one instead of a casualty, and the duplicate is recorded in the audit entry of the
  save that carried it, because that is the record someone reads when they ask where an item
  went. (This was NOT the cause of the reported disappearance — those two items were
  long-lived and distinct — but it is a way to lose one, and it was open.)
- Two tests walk the reported flow through the real endpoint: two items, one disabled with the
  item checkbox, saved and reloaded. Both survive, and a disabled item comes back from the
  GET. The store deletes every uid absent from the payload, so an item dropped anywhere
  upstream becomes a real DELETE — which is why proving the server side clean matters before
  looking further.
- **Every threshold now lives under "Alerts", where its own label says it belongs.** Fourteen
  fields labelled "Warn when…" sat in "Checks" while an Alerts group existed holding exactly
  one field. `__field_order__` was reordered with them: the pane emits a group header every
  time the group CHANGES as it walks that list, so moving fields without reordering would have
  drawn "Checks / Alerts / Checks / Alerts…" down the form. A guard now fails on any module
  whose field order jumps back to a group it already left.
- `sites_top` and `accounts_top` left "Checks" for a group of their own, "Stored data": they
  are neither a check nor a threshold but how many rows get written each cycle.
- hddtemp's "Alerts" group header rendered with no text — it used the group and translated it
  in neither language, and the core only supplies labels for its own two sections. Found by
  the same new guard, which now covers every module.
- **`zero_as_blank` was schema vocabulary that did nothing.** The attribute the on-change
  validator looks for was emitted only as a side effect of a field having a placeholder, so a
  clearable field that inherits nothing never got it: emptying the box and leaving it snapped
  back to the stored value, which reads as an input refusing to be cleared. Reported on
  `tenant_capacity` — "optional", yet it filled itself back in. Five shipped modules declare the
  key; the core now reads it directly, and a guard fails if it ever stops.

### Changed
- **And twelve labels renamed for the same reason.** "Alert if % drops below" — of what?
  Moving the thresholds into their own Alerts group took away the check they used to sit
  beside, so every label that had been borrowing its subject from that adjacency was suddenly
  reading alone and saying nothing. Each one names its subject now: the Secure Score, MFA
  coverage, SharePoint, OneDrive, the site, a licence. The ones that already did were left
  untouched.
- **Thirteen fields renamed to say what they measure.** `global_admins_max` counts accounts
  holding Global Administrator — `privileged_max` did not say *max of what*: users, groups,
  roles? The rest followed the same test: read the name alone, out of the context of its
  check, and see whether it still means anything.

  | before | after |
  |---|---|
  | `privileged_max` | `global_admins_max` |
  | `risky_max` | `risky_users_max` |
  | `secure_min` | `secure_score_min` |
  | `mfa_min` | `mfa_coverage_min` |
  | `license_min` | `licenses_free_min` |
  | `secret_days` | `secret_expiry_days` |
  | `unused_days` | `unused_after_days` |
  | `announce_days` | `announce_before_days` |
  | `tenant_max` + `tenant_unit` | `tenant_capacity` + `tenant_capacity_unit` |
  | `usage_pct` / `free_min` / `free_unit` | `site_usage_pct` / `site_free_min` / `site_free_unit` |

  `tenant_capacity` is the one worth pausing on: it is a capacity, not a maximum of anything,
  and calling it a maximum is part of how it ended up holding a typed 1 TB that nobody
  revisited. **No migration** — the project has not begun releasing, so a value stored under
  an old name is simply not found and the field falls back to its default.

- **The SharePoint capacity is never guessed.** A licence formula was added and removed within
  the same build: 1 TB + 10 GB per licence, Microsoft's own published numbers. A real tenant
  killed it — its admin centre reads **300 GB**, under the formula's 1 TB FLOOR. An estimate
  that can be three times the truth is not a capacity, and it errs in the direction that hides
  a tenant filling up; the comment claiming it "errs low" was wrong. Two sources remain, both
  facts: what the admin typed (`tenant_capacity`) and the sum of real per-site quotas. Neither
  available → the check reports the amount and says there is no total, which is worse to look
  at and better to trust.
- **Verified, not remembered:** a live tenant answers 28 SharePoint settings, three of them
  about storage — automatic-management on, a 25 TB site ceiling, a 5 TB personal-site default
  — and none of them the pooled tenant quota. The `sharepoint_settings` diagnostic is what
  established that, and it stays for the next time somebody wonders.
- The exact pooled figure exists in exactly one place — the SharePoint admin centre, Active
  sites, top right — and the only API that serves it is the SharePoint admin one:
  `Get-SPOTenant`/CSOM, an app-only token SharePoint accepts only when minted with a
  CERTIFICATE (this module authenticates with a secret), and `Sites.FullControl.All`, full
  control of every site in the tenant to read one number. Until that trade is worth making,
  `tenant_capacity` is where that number goes.

## [0.0.1+build.32] - 2026-07-30

### Fixed
- **A sum of ceilings was passing itself off as a capacity, and the check could never fire.**
  Every SharePoint row read "of 25.0 TB": that is the per-site CEILING, which automatic site
  storage management — the default — assigns to every site because it reserves nothing, the
  real limit being the pooled tenant quota. Summing it turned 65 sites into 1.6 PB, against
  which any real usage is a comfortable 0 %. With a typed `tenant_max` nothing changes; with
  the field blank the check now reports the amount and says there is no total, which is the
  honest answer, instead of a percentage that can never reach a threshold.
- The Storage table's share is of each row's OWN service, and the header says so ("% of its
  service"). Dividing by SharePoint plus OneDrive made the column internally comparable and
  operationally meaningless — a 3.4 TB site read 26.8 % of a tenant instead of half of the
  SharePoint it actually fills, and you cannot move a site into OneDrive. The `kind` column
  and its filter are what keep the two halves apart.
- A site at that ceiling has no quota to show, so the list says "—" rather than printing a
  limit nobody set.

### Added
- **A module section can have more than one VIEW of itself.** The row layout answers "is
  everything all right"; a table of who holds what answers "where is it all going". Those are
  two questions about one subsystem, and answering them with two SECTIONS would mean two
  sidebar entries, two permissions to keep in step, two panes and two routes for a thing the
  reader thinks of as one place. So `__page__` grew a `views` list, the sidebar entry becomes
  a parent with a flyout — the pattern Infrastructure and Access already use — and a view is a
  **sub-path**: `/m365` and `/m365/storage` share the pane, the permission and the descriptor,
  and cost ONE extra route between them however many views a module declares.
- **Module sections moved under `/module/<id>`.** A module page used to claim a top-level
  path, which made every future core section a potential collision and left the core policing
  a blocklist of names it had to remember to grow — and a module that shipped `/reports` first
  would have won by accident of ordering. Now the collision is impossible by construction and
  the URL says where the page comes from: `/module/m365/storage`, `/module/azure`. The URL is
  decided in one place, so the sidebar links, the pane resolver and the route loop all
  followed. The landing-page setting stores the page ID, not its path, so every saved landing
  page still points where it did. `_RESERVED` stays, for the smaller and truer job it always
  had: the id is also the pane (`tab-<id>`) and that namespace IS shared with the core.
- Caught right after: the view flyout still pushed the old path, because it composed the
  URL from the page id instead of reading it from the registry. Where a section lives is
  the server's decision, and a URL built in the client goes stale the moment it changes —
  silently, because `pushState` never 404s. A guard now fails on any section URL built
  from an id.
- **A generic inventory table, declared not coded.** A view of `"kind": "table"` names an
  action; the module answers with `{columns, rows}` and the core lays it out on the shared
  list-table machinery — sortable, searchable, resizable, with the column chooser. A value may
  be `{v, s}`: `v` sorts and `s` is read, which is how "3.0 TB" sorts as its bytes without the
  core ever learning what a byte is. The module formats; the core lays out.
- **M365 → Storage.** One row per place the storage is going: every SharePoint site and every
  OneDrive account, side by side, with tenant, kind, name, used, quota and TWO percentages:
  its share of the whole and how full it is against its own limit. Two columns because one
  meant a different thing on each half of the table — a share of the tenant for a site, how
  close to full for an account — and "—" where there is no limit to be close to.
  Live and unstored — it runs the two storage checks now, with the caps lifted, and keeps
  nothing: a table of who holds what is a photograph, and the monitor's own checks are what
  carry the alerting and the trend. It runs ONLY the storage checks, because answering a
  storage question with the licence and identity ones would spend a dozen Graph calls nobody
  asked for.
- **The inventory table reads three ways, and filters by what the module declares.** A table
  answers "which one"; it is a poor answer to "how is it distributed", because comparing forty
  numbers down a column is work the reader should not be doing. So a table view also offers
  **bars** (magnitude at a glance, each one a share of the largest row — of the total, forty
  rows would each be a sliver) and **groups** (subtotals first, then who is inside), drawn from
  every filtered row with no pagination bands: they are read as a shape, and a shape cut at
  row 25 is a different shape. Same `createViewState` + `_viewSwitcher` every other section
  switches views with.
- A column may ask for its own dropdown (`filter`), and the core fills it with the values
  actually present — so it offers no choice that matches nothing and learns no vocabulary of
  its own. M365's Storage marks **tenant** and **kind**, the two axes it is read along. The
  free-text box still reaches every column.
- Fixed before it shipped: only the search box appeared. The filter bar is built ONCE, from
  the fields it sees at that moment, and the table was being created before the module's
  columns had arrived — so its dropdowns were decided while there were no columns to declare
  them. The table now waits for its data, and a later answer with a different field set drops
  the bar so it is rebuilt (only then: typing in the search box is not interrupted for
  nothing).
- The extra layouts appear only when the module says which column is the label, which is the
  magnitude and which one groups (`layout` in the action's answer). Which of six columns is
  worth drawing is module knowledge, and a bar of the wrong column is worse than no bar. A
  group reports its SHARE, never a reconstructed total: the core cannot add "3.0 TB" to
  "512 MB" without learning what either is.
- The breakdown rows now carry their raw `bytes`/`quota_bytes` beside the formatted text. The
  core still reads only `pct` and prints `text`; the table needs numbers to sort by, and
  parsing "3.0 TB" back into bytes would be inventing a measurement that is right there.

## [0.0.1+build.31] - 2026-07-30

### Added
- **OneDrive says who is using the space.** The check read `getOneDriveUsageStorage`, which
  publishes a tenant total and nothing about who makes it up — so "OneDrive holds 2 TB" could
  not be followed by the question it always provokes. It now reads the **account detail**
  report, one row per person, and gets the same breakdown SharePoint has: biggest first, with
  the account count and how many of them are deleted beside the total.
- **Each account's bar is against ITS OWN quota.** OneDrive quotas are per person — 1 TB,
  5 TB — and the accounts share no pool, so a share of the tenant total would say nothing
  about whether anyone is about to run out. The pooled share stays for SharePoint, whose sites
  really do draw from one tenant quota. Ordering is by bytes used in both: the list is opened
  to find who occupies the space, which is a question about size, not about fullness.
- **A list is ordered by what it draws.** With the bar now showing each account's own
  fullness, ordering by bytes made the order invisible: 50 GB of 1 TB (5 %) sorted below
  200 GB of 5 TB (4 %), so the column read as unsorted — several rows at 0 % and then, out of
  nowhere, one at 5 %. The per-quota list orders by fullness and the pooled one still orders
  by bytes, each by what its own bar shows. Bytes break the ties, so a tenant whose quotas are
  all equal — the ordinary one — gets exactly the same list as before.
- Concealed reports are handled here too, with one difference: an account has no identifier
  that survives concealment AND appears in the directory — the principal name IS the
  identifier and it is what gets hashed — so there is no join to try and the accounts are
  measured directly (`/users/{id}/drive`, batched). Failing that, the rows are numbered.
- `accounts_top` is its own setting rather than sharing the site one, because it is not the
  same decision: these rows name PEOPLE and how much each one keeps, which is a different
  thing to write to a database every cycle than a list of site URLs. Same three states —
  blank inherits, a number caps, 0 stores none.

### Changed
- `sites_page` is now `breakdown_page`: it governs both lists, and a name that says "sites"
  while paging accounts is the kind of small lie that costs an hour later.
- The breakdown builder takes its nouns as a parameter (`_SP_KEYS` / `_OD_KEYS`). Same list,
  same maths, different words — a message that calls a person "site 4" is not a translation
  away from right.
- `_measure_drives` replaces `_measure_sites`: `/sites/{id}/drive` and `/users/{id}/drive` are
  the same question asked of two collections, and only the path and the label differ.

## [0.0.1+build.30] - 2026-07-30

### Added
- **M365: SharePoint total, with a percentage that means something.** The check now sums what
  EVERY site occupies and divides it by the capacity, so "how full is SharePoint" is one number
  instead of an amount you had to judge by eye. It reads the per-SITE usage report, which
  carries both what each site uses and the quota it was given — the tenant-wide storage report
  it used before publishes bytes and no denominator, which is why there was never a percentage.
- **Warn at a percentage, at an amount, or both.** `tenant_pct` warns at % occupied and
  `tenant_warn_at` + unit warns at an absolute figure, whichever arrives first. They answer
  different questions: on a large tenant "500 GB" arrives long before "80%", and on a small one
  the reverse.
- **100% is an error, not a warning.** Full is the point where writes start being refused, so
  it must not arrive in the same colour as the warning that preceded it.
- The capacity can be typed (`tenant_max` + unit). Graph does not publish the pooled tenant
  quota — it is 1 TB + 10 GB per licensed user and no endpoint exposes it — so an admin who
  knows it can say so; blank falls back to the sum of the quotas assigned to the sites, which
  is what they are actually allowed to use. The result says which of the two is in play.
- Sites in the recycle bin count, because they keep occupying the tenant's storage until they
  are purged; how many there are is reported separately, since "12 TB used" and "12 TB used,
  four of those sites deleted" lead to different actions.
- **The row unfolds into the sites behind it.** The total answers "how much"; the question
  that always follows is which sites, and until now the only way to ask was to add one
  per-site check per site. The list is biggest-first, each with a bar showing its share of the
  total — the same denominator as the ring above it, so a site at 15 % under a tenant at 20 %
  reads as what it is. Capped at the top 25, with the number left out stated: a list that
  silently stopped would read as "these are all of them".
- **Concealed reports get their names back from the other API.** A tenant can hide
  identifiers in its reports ("Display concealed user, group and site names") and then Graph
  answers with the bytes and a blank URL — which drew a column of dashes, and then a column of
  hashes, several of them identical because the surviving identifier was the OWNER's, shared by
  every site that person owns. The setting belongs to REPORTS: `/sites` — the same enumeration
  the site field's discover button uses — still publishes names. The site-collection GUID joins
  the two, so ONE extra call turns the hashes into real URLs. It is only made when something is
  actually concealed, a tenant that publishes its URLs never pays for it, and a failure there
  costs the labels and never the measurement.
- **And when there is nothing to join on, the sites are asked directly.** A tenant can conceal
  the site id too, and it arrives as the zero GUID — identical on all eighteen rows. So the
  fallback stops trying to name the report's rows and reads the sites themselves instead
  (`/sites/{id}/drive`), 20 per `$batch` request: real names, real figures, one round-trip per
  twenty sites, bounded at 200 so a huge tenant gets the anonymous list rather than a check that
  spends its cycle naming things. The list says where those rows came from, because they exclude
  deleted sites — which do count towards the total, and the total is still the report's.
- **How many sites are stored is now a setting, and 0 means "none".** The cost of the list
  is bytes written every cycle, for ever — the same nature as `threads` or `timeout`, so it is
  configured the same way: `sites_top` in the module defaults, overridable per tenant. Three
  states, three intentions: blank inherits, a number caps, and **0 stores nothing at all** —
  the breakdown is diagnostic context, not a measurement, so a tenant nobody drills into need
  not write its site list to the database on every cycle. It stays one click away, because a
  live refresh queries Graph and builds the list in full.
- A live refresh now says so (`_live`) and ignores the caps, which exist to keep STORED
  results small: a list the admin asked for by hand goes nowhere near the database, so it
  comes back whole — including for the item that stores none.
- The page size is the module's to state (`breakdown.page`, `sites_page` in the module
  defaults): a list of 6 partitions and one of 500 tables do not read the same. Declaring
  nothing still means 25, the same arrangement as the ring's `chart`.
- **Fixed: the tenant threshold fields were invisible in the item editor.** `__field_order__`
  does not merely sort — a field missing from it is filtered OUT — so `tenant_pct`,
  `tenant_warn_at` and `tenant_warn_unit` shipped unreachable.
- **"40 more" is a button now, and the rest of the list opens in place.** The cap was doing
  two jobs at once. How many rows are worth STORING in a check result, on every cycle, for
  ever is the module's call; how many are worth DRAWING at once is the page's. So the module
  now keeps 100 sites instead of 25 and the core pages through them 25 at a time — those rows
  are already in the payload, so growing the list is a repaint of one list, with no request,
  no re-render of the row (which would fold shut the breakdown the click just opened) and no
  loss of the expansion when a live refresh repaints the page. Only what was never sent stays
  as text, because the core has nowhere to fetch it from.
- **The per-site bars stay proportional when the tenant is over capacity.** A share of
  capacity goes past 100 % for the big sites when more is occupied than was declared (a typed
  `tenant_max` that is out of date, or a real overage), the bar clamps, and a 3.4 TB site is
  drawn exactly like a 1.0 TB one. The share is now of the total OR of what is actually
  occupied, whichever is larger: the bars stay proportional to each other and still sum to the
  whole, and "667 % of capacity" stays where it belongs, on the ring above. It also fixes the
  list for a tenant with no denominator at all, where every bar used to be drawn at zero.
- The per-site list drops the tenant host and the `/sites/` managed path from every label.
  Both are the same on all eighteen rows, so they pushed the part that DIFFERS off to the
  right; `/teams/` and `/personal/` stay, because those do say something, and the root site —
  which has no path — is the one row where the host is the name.
- A hash is no longer shown as a name at all. The owner's is shared by every site that person
  owns and a concealed site id is all zeros; neither identifies anything, so identifiers are now
  join keys only and an unnamed row is numbered.
- **`breakdown` is a core page contract, not an M365 feature.** A row may declare
  `{label, items:[{name, text, pct}], more}` and the generic module-page renderer folds it
  away behind a toggle — so a datastore's tables or a cluster's nodes get the same treatment
  without a line of front-end. The core reads exactly one field, `pct`; `text` arrives
  formatted by the module, because bytes-versus-rows-versus-seconds is knowledge the core does
  not have.

### Fixed
- **A blank `site` never meant "everything".** It resolves the tenant ROOT site — one site
  among many — and the field's help implied the total. Both the hint and the module reference
  now say so, and point at the check that does answer it.
- The tenant ring on the /m365 page drew "used against the number you asked to be warned at",
  which is not a fraction of anything: the check published `limit_bytes` (a threshold) where
  the page expected a capacity. It publishes `total_bytes` now, the same pair the per-site
  check uses.

## [0.0.1+build.29] - 2026-07-29

### Added
- **The host registry can be read four ways.** Beside the table: **cards** (a host as one
  object instead of eight columns you turn on and read left to right), **by status** and
  **coverage**.
- **By status** is the answer you actually want from a fleet list. There was a status column
  you could sort by, which answers "which host is worst" and never "how many are broken";
  grouped, the counts are the first thing on screen and an empty error group is itself the
  good news. Hosts with no checks get their own group rather than a fifth colour — "we do not
  know how this machine is" is not a shade of "fine", and painting it green would say it was.
- **Coverage** is the one that finds the gap: a host with no checks at all is registered and
  watched by nothing, and a host whose checks are all disabled is worse, because the row looks
  configured and somebody turned them off. The table drew "0/0" and "0/3" in the same grey
  pill, which is how a panel stays green while a machine is down. Both lead; the working
  majority is at the bottom.
- The modules pill always shows both numbers — "3" alone cannot say whether the other two were
  never added or were switched off.
- **Syslog can be read three ways.** A **stream** — the shape a log is actually read in:
  reading one in a grid means re-reading five column headers per line to follow one machine's
  story, and spends a third of the width on chrome. And **patterns**, which collapses "the
  same message with different numbers in it": five hundred lines are usually a dozen distinct
  messages, and the one that matters is often the one that appears twice.
- Patterns says what it counted over, on screen. This is the section whose rows arrive already
  paged by the SERVER: the store can hold millions of lines and the browser has a few dozen, so
  a bare count would be read as "the log". The page-size control is how you widen it. The
  grouping replaces numbers, addresses, UUIDs, hex blobs and quoted strings and never touches
  words — two different messages collapsing into one is a worse failure than two similar ones
  staying apart. The pager stays in every view, because here it is what loads the next rows.
- **History gained a series inventory** beside the chart: one row per series with its sample
  count, uptime, last sample and last value, sortable, opening worst-first. The sidebar is
  navigation — names and a three-colour dot — and it hides two things the index already
  carries: which series **stopped recording** (a removed or renamed check leaves its history
  behind and looks identical to a healthy one) and which checks have the worst uptime, because
  you cannot sort dots. Clicking a row goes back to the chart with that series selected.
- A series counts as stopped after 24 h without a single sample, and the rule is written next
  to the count: a threshold nobody can see is a badge nobody can trust.
- **Access gained the view it never had: what an account can actually do.** Users, Roles and
  Groups are three tables over one graph — a user holds a role directly, belongs to groups, and
  a group grants roles — and each table showed its own row and the edge leaving it. The
  composition was written down nowhere: an account whose role column says "viewer" and which
  sits in a group mapped to admin IS an admin, and the table said viewer. Finding that out
  meant opening Groups, reading member lists and holding it in your head, which is the work an
  access review is supposed to be.
- **Users → effective access**: the direct role, what the groups add, and a flag on every
  account that reaches admin through a group. **Roles → who holds it**: reach counted as a
  union of direct holders and group members (a user in both is not counted twice), with the
  roles nobody holds marked. **Groups → what it grants**: the three ways a group does nothing
  — disabled, no roles, no members — which the table's separate columns could only be read as a
  pair of numbers. **Sessions → by user**: twelve rows can be one person with twelve tabs or
  twelve people, and a list sorted by time reads the same either way.
- A **disabled group grants nothing**, here as on the server. Over-reporting access is the one
  direction an access review must not be wrong in: it sends you chasing something that is not
  there and buries what is. The group is still shown — it is how the account is configured —
  and marked as granting nothing today.
- The four sections share one view state (`createViewState`): read, validate against the
  registry, fall back to the first view. It was about to be the same twenty lines four times,
  which is four places for the fallback to differ. Their card views keep the id the old
  card/table toggle stored, so nobody's saved layout resets.
- **Clusters gained cards and a by-host view.** A cluster exists for redundancy, and the table
  hides the two ways it can be a lie: a cluster with ONE member is a failover pair with nothing
  to fail over to (a "1" where another row has a "3"), and several clusters pinned to the same
  host all go down together while each row looks redundant on its own. The second is a fact
  about the intersection of the rows, so no per-cluster view can show it — hence the pivot onto
  the host, with the most-loaded machine first.
- **fail2ban's two lists gained the grouping an address list needs.** Banned IPs **by network**:
  forty bans are usually three networks, because whoever is knocking rotates the last octet, and
  that shape is what changes the decision from banning addresses to banning a range. Ban history
  **by address**: the question asked of a history is who keeps coming back, and sorted by time an
  address banned six times is six scattered rows. A ban and its unban count as one incident.
- The network rule is deliberately blunt and stated in the code: /24 and /64, the two sizes that
  correlate with "the same person". Deriving a prefix from the addresses present would make the
  grouping change every time a ban expires.
- **The never-ban whitelist can be read by reach**, which is the one list in the panel where an
  entry is a hole made on purpose. `10.0.0.7` and `10.0.0.0/8` are one line each and the second
  exempts sixteen million addresses — typing an 8 where you meant a 24 is a one-character
  mistake no column shows. It sorts widest first, states how many addresses each entry covers,
  and marks the ones already inside another (a whitelist grows by accretion, so the narrow entry
  that looks like the rule protecting a host often does nothing). Containment is computed for
  IPv4 only and says so: getting 128-bit arithmetic subtly wrong would mean calling an entry
  redundant when it is the only thing exempting a host.
- Left alone on purpose: Syslog's dropped-senders panel — a short table already sorted by the
  only thing you ask it, where a switcher would be chrome rather than an answer.

### Fixed
- **The auto-refresh button was invisible while it was off.** It wore Bootstrap's `btn-dark`,
  and the dark theme's surfaces are #181818 / #212121 / #2a2a2a — so "dark" landed within a
  shade of the card it sits on and only the caret gave the control away. A refresh button
  nobody can see while it is off is a button nobody finds to turn on. It now wears
  `.ss-btn-graphite`, one step up that same neutral greyscale: still quiet, which is right for
  an off state, without being the surface. Grey rather than a tinted dark on purpose — a
  blue-ish slate was tried first and read as a colour from another palette. Guarded three ways,
  including that its hex stays on the neutral ramp.
- **The control lives in `core/` now.** It was defined inside `overview/_render.html` — its own
  comment said "shared across Status / Overview / History" and it stayed there anyway — while
  six sections draw it: Overview, Status, History, Syslog, the Servers monitoring panel and the
  cluster modal. A section's file is for what only that section does; this is the same mistake
  as a generic module runner living in the hosts domain.
- **Two answers to "what is this module called".** `servers/_checks.html` defined a second
  `_modPrettyName` beside core's `modulePrettyName`, and they disagreed: the local one returned
  the raw module id where core title-cases it, and it took no config override. One caller was
  already passing a config to it — `_modPrettyName(c.module, modulesData[c.module])` — which the
  one-argument local version silently dropped. Deleted; every call site now reaches the core
  helper, and that caller finally gets the override it asked for.
- **Five more shared things moved out of the section that happened to write them first**, all
  found by the same audit rather than by eye: `_moduleHue` (a module's colour, which now sits
  beside `moduleIcon` and `modulePrettyName` instead of inside the Modules list), `_genUuid`,
  the `datetime-local` ⇄ unix pair, the role vocabulary (`ROLE_LABELS`, `roleBadgeClass` and
  friends, which lived in the "my own account" page and forced a load-order warning in the
  bundle), and the Live poll interval — Syslog owned it while the cluster modal and the Servers
  panel reached across with `typeof _SL_LIVE_SECS !== 'undefined' ? … : 2`, and a fallback is
  what code writes when it knows a value might not be there.
- **The series inventory's columns did not fit their content and could not be resized.** Its
  table was hand-written markup instead of the panel's column machinery, so it got none of it:
  the browser shared the width evenly and the two name columns ended up as narrow as the number
  beside them. It now declares its columns like every other table — drag to reorder, drag the
  edge to resize, double-click to fit, and content-fit sizing for the number, the percentage
  and the age. The order and the widths are remembered.
- The inventory's search moved up beside the view switcher. It is the only control that view
  has, and its own row above the table spent a whole band on one input; the chart view keeps
  its copy in the series sidebar, where the list it filters is.

### Removed
- **The duplication this round introduced, before it set.** Building eleven sections' worth of
  views produced seven copies of the summary-header strip, six identical chip helpers and nine
  hand-written "cut this list to N with a +n tail" blocks. They are now `_summaryHeader`,
  `_summaryChip` and `_chipList` in one place: seven copies of one line of markup is seven
  places for the padding to end up different, and the cut is worth sharing because naming the
  members of a set is nearly always more useful than counting them — while one row with forty
  of them stops being a row.

### Changed
- **createListTable learned what a summary body is.** `bodyMode: 'summary'` is handed every
  filtered row instead of the page and draws no pagination bands, because a summary counts
  things: "4 hosts have no checks" is a fact about the fleet, and counted over one page that
  number changes as you page through it. `cardsBody` now receives the full row list as a third
  argument, so an existing card view can ignore it and nothing else had to change.
- Credentials' two grouped views (by type, who uses them) became summaries on the same
  mechanism, which removes the caveat they carried: their groups now partition the catalogue
  rather than the page.
- The per-host permissions become buttons in one place, composed by every view and guarded.
  Servers is the section where `server.<uid>.edit` grants exactly one row, so a view
  assembling its own buttons would be a view that forgot the granular case exists.

## [0.0.1+build.28] - 2026-07-28

### Added
- **Event rules can be read four ways.** Beside the table: **cards** (a rule drawn the way the
  panel draws any entity), **by channel** and **delivery**.
- **By channel** answers the question the icon column can only be scanned for: if Telegram
  breaks, what stops arriving? It is also where a rule with **no channel at all** finally
  shows up — one that can match perfectly and notify nobody, which nothing else on the page
  made obvious. A rule with two channels appears under both, on purpose: the view answers
  "what does THIS channel carry", and the header states the rule count so the difference
  cannot read as a miscount.
- **Delivery** is the triage `last_fired` could only be sorted by: failing now, never fired,
  delivering. "Never fired" is its own state rather than a shade of success — a rule that has
  never fired is either a gap in the alerting or dead configuration, and a two-state view
  would have to call it fine.
- **The notification log gets the same treatment**: **timeline** (the day stated once, the
  clock down the left), **by rule** (which one is noisy, which one is failing) and **by
  channel** (whether a transport is broken). Forty lines from one rule and one line each from
  forty rules look identical in a flat list until they are counted. The last send carries its
  own outcome beside the totals: 12 failures out of 300 ending green is a transport that
  recovered, and the same numbers ending red is one that is down right now.
- Both sub-sections remember their view separately — choosing cards for the rules does not
  decide how the log is drawn — and the summaries describe everything the filters left
  standing, with no pagination, like the Audit ones.

### Changed
- **One view switcher for the whole panel.** Six sections (Status, Modules, module pages,
  Services, Credentials, Audit) had each grown their own copy of the same button group, which
  is six places for the same control to end up a different size. `_viewSwitcher(registry,
  current, setter)` now draws it and each section passes the part that actually differs.
- **One channel vocabulary in Events.** The icon map existed twice — the rules table and the
  modal — and the copy in the table had already lost `msteams`, so a Teams rule drew a generic
  bell. Same for the send-status badge, now composed by all four log views.
- The `events_*` permissions become buttons in one place, composed by every rule view, and
  guarded. The log views offer no rule actions at all: a log line is history, and a row that
  carried Edit and Delete would invite acting on a rule from a record of what it once did.
- "Which day is this" is decided once for the whole panel (`_dayKeyLocal`), in the reader's
  timezone. Audit and Events both group by day, and where midnight falls is not something two
  sections may answer differently.

## [0.0.1+build.27] - 2026-07-28

### Added
- **The audit log can be read four ways, and two of them are not lists.** The table reads it
  one line at a time, which is right for "what happened at 14:32" and wrong for every question
  about the log as a whole. **Timeline** reads it as a log — the day stated once, the clock
  down the left, each entry one sentence — instead of making you re-read five column headers
  per line to follow a sequence.
- **By actor** sums the log up by WHO: entries, failed logins, how many kinds of thing, from
  which addresses, first and last seen. The table shows every line by every actor and never a
  per-actor total, so "an account nobody uses did forty things last night" was invisible unless
  you already suspected it and filtered by that user — you had to know the answer to ask the
  question. Failed logins get their own column rather than being folded into the total: a
  hundred entries from an admin who was working is not news, six failed logins from an account
  that did nothing else is, and averaged into one number they look the same.
- **Activity by hour** is a day × hour grid. A 03:00 login and an 11:00 login read identically
  in a list sorted by time — the timestamp is a value in a column and nothing about it says
  "this is an odd hour". Side by side on a grid they are in different places, and "does
  anything happen here outside working hours" becomes a shape you see rather than a query you
  have to think of. One hue getting darker, never a red-to-green ramp: the colour carries a
  count, and this view has no opinion about whether activity is good.
- Those last two are **summaries**, and they behave like it: computed over everything the
  filters left standing rather than over the page, not paginated (page 2 of a heat map is not
  a thing), and their header always states the whole set. The grid caps at the 62 most recent
  days and says so on screen when it does — a silent truncation would read as "this is all
  there is", which is the one thing an audit view must not imply.

### Changed
- `audit_delete` becomes a button in exactly one place, composed by the table and the
  timeline alike, and guarded.
- Sort and Group by are hidden while a summary view is on screen. They decide the order of a
  LIST; a summary picks its own axis, and a control that does nothing when you use it is worse
  than one that is not there. The column chooser follows the same rule — it configures columns
  the other three views do not have.
- The chosen view travels with the rest of the section's UI state (sort, grouping, filters)
  rather than growing a storage key of its own, and switching returns to the first page:
  page 3 of the table is not page 3 of anything else.

### Fixed
- The day an entry belongs to is computed in the reader's timezone. Built from `toISOString()`
  it would have been the UTC day, so entries either side of local midnight would have sat
  under a heading whose date was not their own — in the timeline and in the activity grid,
  which counts hours locally.

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
