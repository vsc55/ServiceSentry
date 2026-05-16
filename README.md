# ServiceSentry

> Infrastructure and service monitoring with Telegram alerts and a browser-based admin panel.
> Monitorización de infraestructura y servicios con alertas por Telegram e interfaz web de administración.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-GPL%20v3-green)
![Author](https://img.shields.io/badge/author-VSC55-lightgrey)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/vsc55/ServiceSentry)

---

## Features

- **15 built-in modules:** CPU usage, databases (MySQL/PostgreSQL/MSSQL/MongoDB/Redis/InfluxDB/Elasticsearch), DNS resolution, disk usage, disk temperature, NTP time sync, ping, process monitoring, RAID, RAM/SWAP, services, SSL certificate expiry, temperature sensors, UPS/SAI status, web availability.
- **Telegram notifications** — alerts only when state *changes* (no spam on repeated failures).
- **Web admin panel** — browser UI to manage modules, config and users; granular per-action roles (15 permission flags); custom roles; dark mode; i18n (EN / ES).
- **Plugin architecture** — each module is an independent Python package in `watchfuls/`.
- **Parallel execution** — modules and per-module items run in `ThreadPoolExecutor`.
- **Cross-platform** — 12 of 15 modules run on Linux, Windows and macOS; services module supports systemd, OpenRC, SysV and Windows SCM.
- **Remote execution** — SSH command execution via paramiko for RAID and other remote checks.
- **Encrypted storage** — sensitive fields (passwords, tokens) are encrypted at rest in `modules.json`.
- **Public status page** — optional `/status` endpoint (no login required) showing real-time health of all modules with collapsible cards and configurable auto-refresh.
- **Custom error pages** — branded 400/403/404/405/500 pages that inherit dark/light theme; API routes return JSON errors.

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
| `--web` | Start the web admin interface |
| `--web-port N` | Port to listen on (default: 8080) |

---

## Documentation

| Document | Content |
|----------|---------|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/architecture.md](docs/architecture.md) | Component diagram, class hierarchy, directory structure, execution flow |
| [docs/configuration.md](docs/configuration.md) | config.json, monitor.json, modules.json, CLI options, Telegram, debug |
| [docs/modules.md](docs/modules.md) | All 15 modules: config reference, fields and flow |
| [docs/web_admin.md](docs/web_admin.md) | Web admin features, roles, security, API endpoints |
| [docs/security.md](docs/security.md) | Authentication, RBAC, sessions, XSS, path traversal, audit log and security tests |
| [docs/development.md](docs/development.md) | Setup, tests, VS Code debug, conventions, dependencies |
| [docs/watchful_guide.md](docs/watchful_guide.md) | Step-by-step guide to create a new watchful module |
| [docs/schema.md](docs/schema.md) | Complete `schema.json` reference: all field properties, meta-keys, language files and `discover_schemas` pipeline |
| [docs/i18n.md](docs/i18n.md) | Internationalisation system: two-tier architecture, `discover_schemas` pipeline, adding languages |
| [docs/tests.md](docs/tests.md) | Full test inventory: what each test checks, pass and fail conditions, organized by group |

---

## License

GPL v3 — see [LICENSE](LICENSE).
Author: **Javier Pastor (VSC55)**
