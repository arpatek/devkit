# devkit config

## menu.json

Drives `cc.sh`. Each entry has a `label` and either:

- **`script`** — path to a module (relative to the repo root). Optional `args` (list of strings) are forwarded.
- **`items`** — array of nested entries. Renders as a submenu.

Adding a new module:

1. Drop the script in `modules/` and `chmod +x` it.
2. Add an entry to `menu.json` under the appropriate group (or create a new group).

## hosts.json

Inventory consumed by homelab modules (status dashboard, Proxmox helpers, etc.).

`hosts.json` is gitignored — copy `hosts.json.example` and fill in real values:

```sh
cp hosts.json.example hosts.json
```

Fields per host:

| field      | meaning                                                |
| ---------- | ------------------------------------------------------ |
| `name`     | short identifier used in module output                 |
| `host`     | DNS name                                               |
| `ip`       | static IP (used when DNS isn't reliable)               |
| `ssh_user` | login user for SSH-based checks                        |
| `checks`   | list of probes the status module runs (icmp/ssh/http)  |
| `url`      | endpoint for `http` checks                             |
| `tags`     | optional tags for filtering                            |
