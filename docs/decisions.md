# devkit — Decisions

## stdlib HTTP client, not `requests`

`lib/api.py` uses `urllib` only. `requests` is not in the venv. The homelab API surface
is simple — GET and POST with auth headers or session cookies — and `urllib` covers it
without adding a dependency. The only non-stdlib Python dep is `rich` for terminal output.

## WireGuard via SSH + sudo, not forced commands

The original plan was a dedicated SSH key with a `command=` forced command in
`authorized_keys`, which would physically limit the key to running `wg show all dump`.

This was abandoned because netrunner is enrolled in FreeIPA. FreeIPA-enrolled hosts use
`sss_ssh_authorizedkeys` as `AuthorizedKeysCommand` in `sshd_config` — it serves keys
from the IPA directory and the `command=` restriction in `~/.ssh/authorized_keys` is
bypassed entirely.

The replacement is a NOPASSWD sudoers rule scoped to the single binary and argument:
```
arpatek ALL=(root) NOPASSWD: /usr/bin/wg show all dump
```
This achieves the same scope: one command, no password, no broader access.

## K3s via local kubectl, not SSH

`k3s.py` runs `kubectl` locally on silverhand with a kubeconfig pointing directly to
`https://erebus.home.arpa:6443`. This is cleaner than SSHing into erebus — the k3s API
server is reachable from the LAN and `kubectl` is already the right tool for the job.

`setup.sh` fetches the kubeconfig from erebus (via a PTY SSH session, see gotchas) and
writes it to `~/.kube/config`.

## WireGuard peer names as a hardcoded map

`wireguard.sh` resolves WireGuard peer public keys to friendly names using a hardcoded
`declare -A PEER_NAMES` map keyed by `allowed_ips` CIDR. The alternative would be a
config file, but the VPN peer assignments are static and small. Keeping them inline
avoids another config file to maintain.

## Pi-hole session auth via URL query parameter

Pi-hole v6 FTL accepts the session SID via three mechanisms: `Authorization: Bearer`
(app passwords only, not session SIDs), Cookie header, and `?sid=` URL query parameter.

The Cookie header approach was tried first but failed: `urllib`'s `CookieJar` has
domain and path matching requirements that don't play well with self-signed certs and
custom openers. The `?sid=` approach is reliable and is what Pi-hole's own web UI uses.

`_PiholeSession` subclasses `Session` and overrides `get`/`post` to append `?sid=` to
every URL so the rest of the module doesn't need to think about it.

## No IPA Kerberos on silverhand

`ipa.py` uses username/password auth via `POST /ipa/session/login_password`. This avoids
any Kerberos setup on silverhand (keytab, ccache, `kinit`). The session cookie returned
is valid for ~20 minutes — long enough for any devkit operation.

## setup.sh stages kubeconfig via PTY

Fetching the kubeconfig from erebus requires `sudo cat /etc/rancher/k3s/k3s.yaml`.
Debian's default `use_pty` in sudoers requires a terminal even for `NOPASSWD` commands
when called from a non-interactive SSH session.

`setup.sh` handles this by staging the kubeconfig in a single `-t` SSH session (PTY
allocated), where sudo can run, writing the file to `/tmp`. A second non-interactive
`-n` SSH then fetches the staged file without needing sudo. The temp file is cleaned up
in both the local and remote traps.
