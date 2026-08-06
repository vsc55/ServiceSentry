# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**ServiceSentry** — a self-hosted monitoring panel in Python/Flask: a web admin, a scheduler
that runs checks against hosts and services, an integrated syslog receiver, and a notification
pipeline. It runs either as one process with everything embedded, or as dedicated processes per
role (web / worker / syslog / events) coordinating through a shared database.

Monitoring logic lives in **watchfuls** — 21 self-contained plugin modules discovered at
runtime, each carrying its own schema, translations, tests and (optionally) UI.

## Commands

Everything runs **from `src/`**, with the project venv at `src/.venv` — the system Python lacks
the dependencies. The interpreter is `.venv/Scripts/python.exe` on Windows and
`.venv/bin/python` elsewhere; the commands below are written relative to `src/`, so they work
from any clone path.

```bash
cd src
.venv/Scripts/python.exe -m pytest tests/unit -n auto   # Windows
.venv/bin/python        -m pytest tests/unit -n auto    # Linux / macOS
```

| What | Command (from `src/`, with the venv interpreter) |
|---|---|
| Fast feedback | `-m pytest tests/unit -n auto` — no app, no DB, no HTTP |
| Structural guards | `-m pytest tests/meta -n0` — docs, changelog, version |
| Whole suite | `-m pytest -n auto` — **ask first** (see below) |
| Dev server | `dev_watch.py --verbose` — restarts on `.py`/`.html`/`.json` change |
| Panel, no watcher | `main.py --web` |

- **Targeted pytest runs: just run them.** A **full-suite** run (no path, everything under
  `-n auto`) is ~5000 tests and ~13 minutes — **always ask first**, background runs included.
- VS Code: task *"🔄 Watch & Restart Web"*; launch configs *"🖥 Main.py Web"*, *"🩺 pytest"*.
- `WebAdmin.run()` forces `use_reloader=False` on purpose: Werkzeug's reloader re-runs
  `__init__`, which binds the syslog ports and starts the scheduler twice. `dev_watch.py` is
  the reload mechanism instead.

## Layout

```text
src/lib/core/<domain>/     each domain owns store + mixin + routes + permissions
src/lib/services/<svc>/    monitoring, syslog, events, ipban, control plane
src/lib/config/spec.py     THE registry of config defaults (see below)
src/lib/web_admin/         Flask app, templates (Jinja partials), static
src/watchfuls/<module>/    a plugin: __init__.py, schema.json, lang/, tests/
src/tests/{unit,integration,e2e,meta}/
docs/                      caso-* (guides) · explica-* (concepts) · ref-* (reference)
packaging/ docker/ helm/ init/   distribution
```

## Conventions that are enforced by tests

Break one of these and the suite tells you — they are guards, not style advice.

### Version and CHANGELOG

- `src/lib/__init__.py::__version__` is `0.0.1+build.N`, **one build per commit**, and it MUST
  equal the newest `## [0.0.1+build.N]` heading in `CHANGELOG.md`
  (`tests/meta/test_version_changelog.py`).
- **Already-committed CHANGELOG sections are frozen** — `test_changelog_frozen.py` compares the
  working copy against `git show HEAD:CHANGELOG.md`. Add a new section; never edit an old one.
- The CHANGELOG is written in **English**, even though the rest of the docs are in Spanish.
  Update it as part of any change, without being asked.

### Documentation

- Every test file must be named in `docs/ref-tests.md` as
  ``**Archivo:** `tests/<folder>/<file>.py` — N tests``, and every path named there must exist
  (`test_docs_tests_inventory.py`). The declared count is a floor: it may not be **below** the
  `def test_` count.
- A non-obvious bug that took real work to isolate gets an entry in `docs/caso-diagnostico.md`
  (Síntoma / Diagnóstico / Causa raíz / Solución / Lección), newest first.
- Docs are in Spanish; code, comments, commit messages and the CHANGELOG are in English.

### Tests

Files live in the folder that matches **what they touch**, not their subject:

| Folder | Needs |
|---|---|
| `tests/unit/` | nothing external — no app, no DB, no HTTP |
| `tests/integration/` | the Flask app through `test_client`/`_login`, or DB-backed stores |
| `tests/e2e/` | live DB engines (`SS_TEST_*`) or a Playwright browser |
| `tests/meta/` | the repo itself: source, docs, templates, git |

- Module tests stay **co-located** with their watchful (`src/watchfuls/<m>/tests/`) — the module
  is self-contained and travels with them. `pytest.ini` collects both trees.
- To locate the source root from a test, use
  `os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]`. **Not**
  `dirname(dirname(__file__))`, which silently points one level short from a subfolder.
- Shared helpers for the structural guards (`_read`, `_fn`, `_strip_comments`) live in
  `tests/helpers.py` — import them, do not copy. Shared *fixtures* stay in `tests/conftest.py`.
- Cross-test imports are absolute (`from tests.<folder>.<mod> import …`), and better still,
  avoided: if two files need a helper, it belongs in `conftest.py` or `helpers.py`.

### The `_HAS_FLASK` guard — both directions

The suite must survive a Flask-less install (a slimmed service container). The rule is
symmetric and getting it backwards hurts either way:

- the file does **not** import Flask → **no guard**, or the tests skip for nothing;
- it imports Flask **at module level** → `try/except ImportError` + `pytestmark = skipif(...)`,
  or an `ImportError` **aborts collection** and the whole suite runs nothing;
- only **one** test needs it → `pytest.importorskip` inside that test.

Watch the transitive case: `lib.core.audit.mixin` imports `flask`, so inheriting `_AuditMixin`
needs the guard even where the word "flask" never appears. Verify by running, not by reading —
a pytest plugin that blocks `import flask` in `sys.meta_path` is how these were found.

## UI conventions (web_admin)

- **No browser dialogs.** `confirm()`/`alert()`/`prompt()` are never used — the panel has
  `showConfirmModal` / `showToast` / `showInfoModal`.
- **No outline/transparent buttons.** Solid variants only (`btn-secondary`, `btn-warning`, …).
- **No per-id CSS for layout behaviour.** Add a reusable generic class (`.ss-vfill`,
  `.ss-vscroll`, `.ss-nosleep`) instead.
- **Everything is SPA.** All navigation — Overview, History, Syslog, /account, module pages —
  switches panes without a full reload. If a change only takes effect after F5, it is not done.

## Architecture notes worth knowing before editing

- **Config defaults have one home**: `lib/config/spec.py` (`cfg_default` + derived rule dicts).
  Change a default in one place. The Config UI is registry-driven too: `spec.py` is the data,
  `layout.py` the presentation.
- **Editable config lives in the DB** (table `config`), read through `_read_config_file` and
  written through `_write_config`. `config.json` is read-only bootstrap. Feature data
  (webhooks, overview layouts) is not config.
- **A module absent from the config is not "off"** — `enabled` defaults to **True**
  (`lib/modules/discovery/schemas.py`). Absent means *not added*; that asymmetry has caused
  real bugs (creating an empty module entry silently enabled six modules).
- **Modules extend the core by declaring, not by the core naming them**: `__page__` (a section),
  `__overview_widget__` (a dashboard widget), `__host_profile__` (host binding),
  `__provision_host__`. The core ships no string that names a module.
- **`SS_SECRET_KEY`** pins the key that signs sessions *and* derives the Fernet key for every
  stored secret. Every process sharing a database must hold the same one. Without it, the key
  is a file in `config_dir` — fine while that directory is shared and persistent.

## CI / release pipeline

`.github/workflows/docker.yml` is the pipeline; `tests.yml`, `install-tests.yml` and
`build-image.yml` are reusable workflows it calls.

| Trigger | Result |
|---|---|
| PR | tests + install check + image built, **never pushed** |
| push to `main` | tests → image `:edge` |
| tag `test` | image `:test` **beside** the tests (it claims nothing), plus packages built and installed but not published |
| tag `vX.Y.Z` | `:1.2.3`, `:1.2`, `:latest`, the `.deb`/`.rpm`/Gentoo overlay, and a GitHub Release whose body is that version's CHANGELOG section |

- `:latest` is the newest **release**, not the newest commit. `:edge` is the tip of `main`.
- A `vX.Y.Z` tag needs a matching `## [X.Y.Z] - date` CHANGELOG heading; the `changelog` job
  fails in seconds without it, before anything is published.
- Packages carry the app; the postinstall builds a venv from `requirements.lock` on the target.
  That requires **Python ≥ 3.11.3** — the lock is generated on 3.14, and older interpreters turn
  on conditional dependencies it does not carry.
- Scripts committed from Windows lose their executable bit (`core.filemode` is off), so the
  workflow calls them as `bash <script>` **and** their mode is set in the index.

## What is still open

`docs/pendiente.md` records what was left half-done or deferred **on purpose**, with the
reason: unfinished section layouts, the MIB catalogue still outside the module-table
mechanism, one CVE with no fixed release, the deferred low-severity findings (and one
explicitly accepted risk), and the Debian 12 packaging floor. Read it before proposing work —
several entries are decisions already taken, not oversights.

## Working agreements

- **Reply in Spanish** (Castilian). Code, comments and commits stay in English.
- **Commit message shape** — keep it exactly as the history has it:

  ```text
  type(scope): short description

  - flat bullets, no intro paragraph
  - what changed and why it was wrong before

  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```
- **Do not commit, amend, tag or push unless asked.** The user drives git; when they ask for a
  commit, they mean that commit.
- Prefer plain `mv`/`rm` over `git mv`/`git rm`.
