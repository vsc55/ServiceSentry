# ServiceSentry

> Infrastructure and service monitoring with Telegram alerts and a browser-based admin panel.
> Monitorización de infraestructura y servicios con alertas por Telegram e interfaz web de administración.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-GPL%20v3-green)
![Author](https://img.shields.io/badge/author-VSC55-lightgrey)

---

## Features

- **9 built-in modules:** disk usage, disk temperature, MySQL, ping (cross-platform via `pythonping`), RAID, RAM/SWAP, systemd services, temperature sensors, web availability.
- **Telegram notifications** — alerts only when state *changes* (no spam on repeated failures).
- **Web admin panel** — browser UI to manage modules, config and users; role-based (admin / editor / viewer); dark mode; i18n (EN / ES).
- **Plugin architecture** — each module is an independent Python package in `watchfuls/`.
- **Parallel execution** — modules and per-module items run in `ThreadPoolExecutor`.
- **Cross-platform modules** — `filesystemusage` and `ram_swap` work on Linux, Windows and macOS via `psutil`.
- **Remote execution** — SSH command execution via paramiko for RAID and other remote checks.
- **870 tests** with pytest.

---

## Quick Start

```bash
git clone https://github.com/vsc55/ServiceSentry.git
cd ServiceSentry/src

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\Activate.ps1       # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Run a single check
python3 main.py

# Run as daemon (check every 5 minutes)
python3 main.py -d -t 300
```

Edit `data/config.json` to add your Telegram bot token and chat ID before running.

---

## CLI Options

| Option | Description |
|--------|-------------|
| `-d`, `--daemon` | Continuous daemon mode |
| `-t N`, `--timer N` | Seconds between checks (requires `--daemon`) |
| `-v`, `--verbose` | Verbose / debug output |
| `-p PATH`, `--path PATH` | Custom config directory |
| `-c`, `--clear` | Clear saved state before running |
| `--web-admin` | Start the web admin interface |

---

## Documentation

| Document | Content |
|----------|---------|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/architecture.md](docs/architecture.md) | Component diagram, class hierarchy, directory structure, execution flow |
| [docs/configuration.md](docs/configuration.md) | config.json, monitor.json, modules.json, CLI options, Telegram, debug |
| [docs/modules.md](docs/modules.md) | All 9 modules: config reference, fields and flow |
| [docs/web_admin.md](docs/web_admin.md) | Web admin features, roles, security, API endpoints |
| [docs/security.md](docs/security.md) | Authentication, RBAC, sessions, XSS, path traversal, audit log and security tests |
| [docs/development.md](docs/development.md) | Setup, tests, VS Code debug, conventions, dependencies |
| [docs/watchful_guide.md](docs/watchful_guide.md) | Step-by-step guide to create a new watchful module |
| [docs/i18n.md](docs/i18n.md) | Internationalisation system: two-tier architecture, `discover_schemas` pipeline, adding languages |
| [docs/tests.md](docs/tests.md) | Full test inventory (870 tests): what each test checks, pass and fail conditions, organized by group |

---

## License

GPL v3 — see [LICENSE](LICENSE).
Author: **Javier Pastor (VSC55)**
