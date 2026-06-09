# devkit

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

**A personalized homelab cockpit — one entry point for all daily ops.**

DevKit isn't a rebuild of `kubectl`, `qm`, or `wg` — those tools are fine. The value
is a single launcher already wired to your infra: Proxmox, k3s, Pi-hole, WireGuard,
FreeIPA, Prometheus, and Gitea reachable from one menu with zero typing.

`cc.sh` reads `config/menu.json` and dispatches to modules under `modules/`. Modules
are standalone scripts — run them directly or via the TUI.

---

## Modules

| Module | What it does |
| --- | --- |
| `status.py` | Homelab health dashboard — ICMP / TCP / HTTP probes against all hosts in parallel |
| `proxmox.py` | VM list, node resources, start / stop / restart / snapshot via Proxmox REST API |
| `k3s.py` | Node status, pod views by namespace, log tailing via local `kubectl` |
| `pihole.py` | DNS stats, top blocked domains, blocking toggle, DHCP leases via Pi-hole v6 API |
| `wireguard.sh` | WireGuard peer status — last handshake, RX/TX, active/idle/offline state |
| `ipa.py` | FreeIPA user / group / host / HBAC views and user operations via XML-RPC API |
| `monitoring.py` | Prometheus scrape target health, active alert viewer, Grafana launcher |
| `gitea.py` | Act runner status, recent pipeline runs, container registry listing |
| `sys_info.sh` | Local system info (CPU, GPU, memory, disks, ports) |
| `log_entry.sh` | Quick DEV journal entry → appends timestamped note to `devkit.log` |

---

## Setup

### Requirements

- `bash` 4+, `python3` 3.9+
- `dialog`, `jq` — for the TUI launcher
- `kubectl` — for the k3s module
- `ping` — for ICMP probes in the status module

### First time

```sh
# 1. Copy and populate config files
cp config/hosts.json.example config/hosts.json
cp config/secrets.env.example config/secrets.env
$EDITOR config/hosts.json    # homelab inventory
$EDITOR config/secrets.env   # service credentials

# 2. Make modules executable
chmod +x modules/*.py modules/*.sh

# 3. Run setup — creates venv, installs deps, configures SSH access
./setup.sh

# 4. Launch
./cc.sh
```

`config/hosts.json` and `config/secrets.env` are gitignored — they stay local.

### What setup.sh does

- Creates a Python venv under `.venv/` and installs `rich`
- Pushes a scoped `NOPASSWD` sudoers rule to netrunner for `wg show all dump`
- Fetches the k3s kubeconfig from erebus and writes it to `~/.kube/config`
- Validates all required secrets are present in `secrets.env`

### One-time prerequisites

**Proxmox API token** — Proxmox UI: `Datacenter → Permissions → API Tokens`  
Recommended: Privilege Separation OFF (token inherits user permissions), or assign
`PVEVMAdmin` + `PVEAuditor` manually. Put token ID + secret in `secrets.env`.

**Pi-hole password** — Admin password for Pi-hole v6 session auth. Put in `secrets.env`.

**Gitea token** — `Gitea → Settings → Applications`  
Required scopes: `read:admin`, `read:repository`, `read:package`  
Put in `secrets.env`.

**IPA credentials** — Admin username + password for XML-RPC auth. Put in `secrets.env`.
No Kerberos setup required.

**WireGuard access** — `setup.sh` handles this. It pushes the following sudoers rule to
netrunner via SSH:

```
arpatek ALL=(root) NOPASSWD: /usr/bin/wg show all dump
```

File: `/etc/sudoers.d/devkit-wg` (mode 440). The rule is scoped to the single binary
and argument — no broader sudo access is granted.

---

## Structure

```
devkit/
├── cc.sh                         # data-driven TUI launcher (dialog + jq)
├── setup.sh                      # first-time setup: venv, sudoers, kubeconfig
├── config/
│   ├── menu.json                 # menu structure → drives cc.sh
│   ├── hosts.json.example        # homelab inventory template
│   ├── secrets.env.example       # service credentials template
│   └── README.md                 # config schema reference
├── lib/
│   ├── probes.py                 # network health probes (icmp/tcp/http)
│   ├── api.py                    # HTTP client (auth, sessions, IPA XML-RPC)
│   └── secrets.py                # secrets.env loader
│   └── lib.sh                    # Bash decorators (BANNER/PLUS/COMPLETE/FAILED/LAMBDA)
├── modules/
│   ├── status.py                 # homelab health dashboard
│   ├── proxmox.py                # Proxmox VE — VMs + node resources
│   ├── k3s.py                    # k3s — nodes + pods + logs
│   ├── pihole.py                 # Pi-hole — stats + blocking + leases
│   ├── wireguard.sh              # WireGuard — peer status via sudo
│   ├── ipa.py                    # FreeIPA — users + groups + hosts + HBAC
│   ├── monitoring.py             # Prometheus + Grafana
│   ├── gitea.py                  # Gitea — runners + pipelines + registry
│   ├── sys_info.sh               # local system info
│   └── log_entry.sh              # DEV journal
├── .gitignore
├── LICENSE
└── README.md
```

---

## Adding a module

1. Drop a script into `modules/` and `chmod +x` it.
2. Add a menu entry to `config/menu.json`:

```json
{ "label": "My Module", "description": "What it does", "script": "modules/my_module.sh" }
```

Optional fields: `args` (list forwarded to the script), `items` (nested submenu).
See `config/README.md` for the full schema.
