# devkit

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

**A personalized homelab cockpit — TUI launcher over thin modules that know your hosts and call the right tool.**

DevKit isn't a rebuild of `ping`, `kubectl`, or `qm` — those tools are fine. The value is one entry point already configured for *your* infra. The launcher (`cc.sh`) reads `config/menu.json` and dispatches to modules under `modules/`, with shared probe primitives in `lib/`.

---

## Modules

| Module | What it does |
| --- | --- |
| `status.py` | Homelab health dashboard — runs ICMP / SSH / HTTP probes against every host in `config/hosts.json` in parallel, renders a colorized grid via `rich` |
| `sys_info.sh` | Local system info (CPU, GPU, memory, disks, IP, gateway, listening ports). Robust against missing tools — shows `n/a` instead of failing |
| `log_entry.sh` | Quick DEV journal entry via dialog → appends to `devkit.log` |

Invoke from the menu or directly:

```sh
./cc.sh                          # launcher
./modules/status.py              # one-shot status grid
./modules/sys_info.sh --full     # full local system info
```

---

## Setup

Requirements:

- `bash`, `python3` (3.9+)
- `dialog` and `jq` for the launcher
- `rich` for the status dashboard: `pip install --user rich`
- `ping` for ICMP probes

First time:

```sh
cp config/hosts.json.example config/hosts.json
$EDITOR config/hosts.json
./cc.sh
```

`config/hosts.json` is gitignored — your real inventory stays local. The `.example` is the committed template.

---

## Structure

```
devkit/
├── cc.sh                       # data-driven TUI launcher (dialog + jq)
├── config/
│   ├── menu.json               # menu structure → drives cc.sh
│   ├── hosts.json.example      # homelab inventory template
│   └── README.md               # config schema reference
├── lib/
│   └── probes.py               # reusable health probes (icmp/tcp/http)
├── modules/
│   ├── log_entry.sh            # DEV journal entry
│   ├── status.py               # homelab dashboard
│   └── sys_info.sh             # local system info
├── .gitignore
├── LICENSE
└── README.md
```

---

## Adding a module

1. Drop a script into `modules/` and `chmod +x` it.
2. Add a menu entry to `config/menu.json`:

```json
{ "label": "My Module", "script": "modules/my_module.sh" }
```

Optional fields:

- `args` — list of strings forwarded to the script
- `items` — nested array for submenus (any depth)

See `config/README.md` for the full schema.

---

## Roadmap

Direction: thin wrappers that glue your inventory to standard tools. Planned modules:

- **Proxmox** — VM start / stop / snapshot via SSH + `qm`
- **K3s** — node and pod queries via SSH to the master
- **Pi-hole** — admin API queries (block / unblock, stats)
- **WireGuard** — peer status, last handshake
- **Monitoring** — Loki log tailing, Grafana dashboard launchers
- **FreeIPA** — user add / lock / password reset
