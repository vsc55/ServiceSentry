# Deployment Guide

This document covers all supported ways to deploy ServiceSentry in production.

| Method | Best for |
| ------ | -------- |
| [Docker](docker.md) | Any server — easiest setup, isolated environment |
| [install.sh](#automated-install-installsh) | Quick automated install on Debian / Ubuntu / Gentoo |
| [systemd](#systemd-debian-ubuntu-rhel-arch) | Manual install on systemd-based distributions |
| [OpenRC](#openrc-gentoo-alpine) | Manual install on OpenRC-based distributions |

---

## Prerequisites

- **Python 3.10+** — required for all deployment methods except Docker
- **Application installed to `/opt/ServiSesentry/`** and config in `/etc/ServiSesentry/`
- A Telegram bot token and chat ID if you want alert notifications

---

## Docker

See [docs/docker.md](docker.md) for the full Docker reference including all environment variables, volumes, and reverse proxy configuration.

```bash
docker compose -f docker/docker-compose.yml up -d
```

---

## Automated install (`install.sh`)

`install.sh` detects whether the system uses systemd or OpenRC and installs
the appropriate init scripts automatically.

```bash
sudo bash install.sh
```

**What it does:**

1. Creates `/opt/ServiSesentry/`, `/etc/ServiSesentry/`, `/var/lib/ServiSesentry/`
2. Copies application files to `/opt/ServiSesentry/`
3. Copies default config files to `/etc/ServiSesentry/` (skips files that already exist)
4. Detects the init system and installs the corresponding scripts
5. Enables and starts the monitoring service

The web admin panel is **not** started automatically — see the output of
`install.sh` for the command to enable it.

### Update

```bash
sudo bash update.sh
```

Stops services, replaces application files, reinstalls init scripts, and restarts.
Config files that already exist are not overwritten; new config files introduced
in the update are installed.

### Uninstall

```bash
sudo bash uninstall.sh       # remove app, keep /etc/ServiSesentry config
sudo bash uninstall.sh -a    # remove everything including config
```

---

## systemd (Debian, Ubuntu, RHEL, Arch…)

### Architecture

| Unit | Type | Purpose |
| ---- | ---- | ------- |
| `ServiSesentry.service` | oneshot | Runs a single monitoring check pass |
| `ServiSesentry.timer` | timer | Triggers `ServiSesentry.service` every 5 minutes |
| `ServiSesentry-web.service` | simple | Runs the web admin panel continuously |

### Install

```bash
sudo cp init/systemd/ServiSesentry.service     /lib/systemd/system/
sudo cp init/systemd/ServiSesentry.timer       /lib/systemd/system/
sudo cp init/systemd/ServiSesentry-web.service /lib/systemd/system/
sudo systemctl daemon-reload
```

### Enable monitoring

```bash
sudo systemctl enable --now ServiSesentry.timer
```

The timer fires every 5 minutes (`OnCalendar=*:0/5`). To change the interval,
edit `/lib/systemd/system/ServiSesentry.timer` and run `systemctl daemon-reload`.

### Enable web admin panel

```bash
sudo systemctl enable --now ServiSesentry-web
```

The panel starts on port `8080` bound to all interfaces. To change the port,
edit the `ExecStart` line in `ServiSesentry-web.service`:

```ini
ExecStart=/usr/bin/python3 /opt/ServiSesentry/main.py --web --web-host 0.0.0.0 --web-port 9090
```

### Service management

```bash
# Status
systemctl status ServiSesentry.timer
systemctl status ServiSesentry-web

# Logs
journalctl -u ServiSesentry.service -f
journalctl -u ServiSesentry-web.service -f

# Force a check right now
systemctl start ServiSesentry.service

# Stop / disable
systemctl disable --now ServiSesentry.timer
systemctl disable --now ServiSesentry-web
```

---

## OpenRC (Gentoo, Alpine…)

### Architecture

| File | Installed to | Purpose |
| ---- | ------------ | ------- |
| `init/openrc/init.d/ServiSesentry` | `/etc/init.d/ServiSesentry` | Init script for the monitoring daemon |
| `init/openrc/conf.d/ServiSesentry` | `/etc/conf.d/ServiSesentry` | Configuration for the monitoring daemon |
| `init/openrc/init.d/ServiSesentry-web` | `/etc/init.d/ServiSesentry-web` | Init script for the web admin panel |
| `init/openrc/conf.d/ServiSesentry-web` | `/etc/conf.d/ServiSesentry-web` | Configuration for the web admin panel |

### Install

```bash
sudo cp init/openrc/init.d/ServiSesentry     /etc/init.d/
sudo cp init/openrc/init.d/ServiSesentry-web /etc/init.d/
sudo cp init/openrc/conf.d/ServiSesentry     /etc/conf.d/
sudo cp init/openrc/conf.d/ServiSesentry-web /etc/conf.d/
sudo chmod +x /etc/init.d/ServiSesentry /etc/init.d/ServiSesentry-web
```

### Enable monitoring daemon

```bash
sudo rc-update add ServiSesentry default
sudo rc-service ServiSesentry start
```

### Enable web admin panel

```bash
sudo rc-update add ServiSesentry-web default
sudo rc-service ServiSesentry-web start
```

### Configuration via conf.d

Edit `/etc/conf.d/ServiSesentry` to change monitoring options:

```sh
# Override check interval (seconds)
SS_ARGS="-d -c -t 120"
```

Edit `/etc/conf.d/ServiSesentry-web` to change web panel options:

```sh
SS_WEB_HOST="127.0.0.1"   # bind to localhost only (behind a reverse proxy)
SS_WEB_PORT="9090"
```

Restart the service after editing:

```bash
sudo rc-service ServiSesentry restart
sudo rc-service ServiSesentry-web restart
```

### Service management

```bash
# Status
rc-service ServiSesentry status
rc-service ServiSesentry-web status

# Logs (OpenRC writes to syslog)
tail -f /var/log/messages | grep ServiSesentry

# Stop / remove from runlevel
rc-service ServiSesentry stop
rc-update del ServiSesentry default
```
