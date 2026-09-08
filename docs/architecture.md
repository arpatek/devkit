# devkit — Architecture

## Overview

A data-driven TUI launcher for homelab operations. `cc.sh` is the entry point — it reads
`config/menu.json` and renders a `dialog` menu. Each menu item dispatches to a standalone
script under `modules/`. Modules can be run directly without the TUI.

---

## Layers

```
cc.sh (TUI shell)
  └── config/menu.json (menu structure)
        └── modules/* (standalone scripts)
              └── lib/* (shared libraries)
                    └── config/secrets.env (credentials)
```

### `cc.sh`

Pure Bash. Reads `menu.json` via `jq`, renders dialog menus recursively, and execs module
scripts. Handles nested submenus (groups with `items`), per-item `args`, theming via
`DEVKIT_THEME` (generates `.dialogrc` at startup), and a HELP button.

Does not know anything about services — it only reads the menu config and dispatches.

### `config/menu.json`

Drives the entire menu. Each entry has:
- `label` — displayed in the menu
- `description` — shown in the item-help bar
- `script` — path to the module script
- `args` — optional list of arguments passed to the script
- `items` — optional list of sub-entries (makes this a submenu group)

### `modules/`

Each module is a standalone executable. Python modules use `lib/api.py` and
`lib/secrets.py`. Bash modules source `lib/lib.sh`.

| Module | Transport | Auth |
|--------|-----------|------|
| `status.py` | ICMP / TCP / HTTP | none |
| `proxmox.py` | HTTPS REST (port 8006) | API token header |
| `k3s.py` | HTTPS (port 6443) | kubeconfig |
| `pihole.py` | HTTPS REST | session SID via `?sid=` query param |
| `wireguard.sh` | SSH | NOPASSWD sudoers rule scoped to `wg show all dump` |
| `ipa.py` | HTTPS XML-RPC | session cookie via `login_password` |
| `monitoring.py` | HTTP REST | none (open LAN) |
| `gitea.py` | HTTP REST | bearer token header |
| `sys_info.sh` | local | none |
| `log_entry.sh` | local | none |

### `lib/`

| File | Purpose |
|------|---------|
| `api.py` | urllib-based HTTP client. `Session` class with headers, cookie jar, optional SSL bypass. `IPAClient` subclass for IPA XML-RPC. |
| `secrets.py` | Loads `config/secrets.env` into `os.environ`. `require(key)` raises with a clear message on missing keys. |
| `probes.py` | ICMP, TCP, and HTTP health probes used by `status.py`. |
| `lib.sh` | Bash output decorators: BANNER, PLUS, COMPLETE, FAILED, LAMBDA. Color map `C[]`. |

### `config/secrets.env`

Loaded by `lib/secrets.py`. Gitignored — never committed. Values already set in the
environment take precedence (real env vars win).

---

## Access model

No broad privilege grants. Each access path is scoped to the minimum capability needed.

**Proxmox** — API token with `PVEVMAdmin` + `PVEAuditor`. SSL verify disabled (self-signed
cert). Token-based auth via `Authorization: PVEAPIToken=` header.

**Pi-hole** — Password auth via `POST /api/auth` returns a session SID. All subsequent
requests pass `?sid=<value>` as a URL query parameter. Sessions are deleted on exit.

**Gitea** — Personal access token with `read:admin`, `read:repository`, `read:package`.
Passed as `Authorization: token <value>` header.

**FreeIPA** — Admin credentials via `POST /ipa/session/login_password`. Returns a session
cookie captured by the `CookieJar`. All XML-RPC calls reuse that session. A `Referer`
header matching the IPA web UI origin is required.

**WireGuard** — Regular SSH to netrunner as `arpatek`. A NOPASSWD sudoers rule scoped
to `/usr/bin/wg show all dump` grants the one command needed. No interactive session
required.

**k3s** — `kubectl` on darwin with kubeconfig at `~/.kube/config` pointing directly
to `https://erebus.home.arpa:6443`. No SSH involved.

**Prometheus / Grafana** — Unauthenticated HTTP on the internal LAN.
