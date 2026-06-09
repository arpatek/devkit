# devkit — Gotchas

## SSSD intercepts SSH keys on FreeIPA-enrolled hosts

On hosts enrolled in FreeIPA, `sshd_config` has:
```
AuthorizedKeysCommand /usr/bin/sss_ssh_authorizedkeys %u
```

This serves SSH public keys from the IPA directory. Keys in `~/.ssh/authorized_keys`
are still accepted, but `command=` forced-command restrictions in that file are ignored
— SSSD serves keys without the restriction metadata.

**Impact:** You cannot use SSH forced commands for privilege scoping on IPA hosts.
Use a NOPASSWD sudoers rule scoped to the exact binary + arguments instead.

**Affected hosts:** netrunner, mikoshi, and any other IPA-enrolled node.

---

## Debian `use_pty` blocks non-interactive sudo

Debian's default `/etc/sudoers` includes `Defaults use_pty`. This allocates a PTY for
the subprocess of any sudo command. When SSH is non-interactive (no `-t` flag,
`BatchMode=yes`), no PTY is available, and sudo fails:

```
sudo: a terminal is required to read the password
```

This happens even with `NOPASSWD` rules. A per-user `!use_pty` override works in
interactive sessions but is unreliable over non-interactive SSH.

**Workaround:** Any SSH call that needs sudo must use `-t` (allocate PTY). If the
output needs to be captured cleanly, stage it to a file first inside the PTY session,
then fetch the file in a separate non-interactive SSH call.

**Affected hosts:** erebus, and any other Debian-based node.

---

## Pi-hole v6 session auth uses `?sid=` query parameter

Pi-hole v6 FTL has three auth mechanisms for the REST API:
- `Authorization: Bearer <token>` — for **app passwords** only, not session SIDs
- Cookie header — unreliable with `urllib` (domain/path matching issues)
- `?sid=<value>` query parameter — what the web UI actually uses; works reliably

`POST /api/auth` with `{"password": "..."}` returns `{"session": {"sid": "..."}}`. That
SID must be appended as `?sid=<value>` to every subsequent request URL.

**Impact:** If you see 401 on all API calls after a successful auth, the SID is probably
being sent via the wrong mechanism.

---

## Gitea admin runners API path changed in 1.22

The admin runners endpoint moved when Gitea restructured its Actions API:

| Version | Path |
|---------|------|
| < 1.22 | `/api/v1/admin/runners` |
| ≥ 1.22 | `/api/v1/admin/actions/runners` |

The old path returns `404 page not found` (plain text, not JSON). If the runner view
stops working after a Gitea upgrade, check the swagger at `/api/swagger` for the current
path — search for `runner`.

---

## systemd-resolved routes `home.arpa` to the wrong DNS server

`systemd-resolved` scopes DNS queries per-link based on routing domains. If a router
advertises IPv6 DNS via Router Advertisement (RA) alongside Pi-hole's DHCP DNS entry,
`systemd-resolved` may add the router's link-local IPv6 address to the interface's DNS
server list and select it as the active server for the `home.arpa` routing domain.

The router doesn't know about `home.arpa`, so all internal hostname lookups fail —
including from Python (`socket.gaierror: [Errno -2]`).

**Diagnosis:**
```sh
resolvectl status          # look at Current DNS Server per interface
resolvectl query foo.home.arpa
```

**Fix:** Pin the DNS in NetworkManager, ignoring auto-DNS from DHCP and RA:
```sh
nmcli con mod "<ssid>" ipv4.dns "10.33.111.141" ipv4.ignore-auto-dns yes
nmcli con mod "<ssid>" ipv6.ignore-auto-dns yes
nmcli con up "<ssid>"
```

---

## venv bootstrap: use `sys.prefix`, not `.resolve()`

Python modules re-exec themselves into the venv if not already running inside it. The
naive check is:

```python
if _P(sys.executable).resolve() != _venv_python.resolve():
    os.execv(...)
```

This breaks because `.venv/bin/python3` is a symlink to the system Python
(`/usr/bin/python3`). Both sides `.resolve()` to the same path, so the condition is
always False and the re-exec never happens — the module runs with the system Python,
which has no `rich`.

**Fix:** `sys.prefix` identifies the active Python environment regardless of symlinks:

```python
_venv = Path(...) / ".venv"
if _venv.exists() and sys.prefix != str(_venv):
    os.execv(str(_venv / "bin/python3"), [str(_venv / "bin/python3")] + sys.argv)
```

---

## Pi-hole `top_blocked` endpoint does not exist in v6

The Pi-hole v6 REST API has no `/api/stats/top_blocked` endpoint. The equivalent is:

```
GET /api/stats/top_domains?blocked=true&count=N
```

Returns `{"domains": [{"domain": "...", "count": N}, ...], ...}` — a list, not a dict.

---

## Gitea packages API returns size 0 for container images

`GET /api/v1/packages/{owner}?type=container` returns packages with `"size": 0`. Gitea
does not populate size in the packages list endpoint. This is a Gitea limitation — size
data is only available by querying individual package versions.

The registry view displays `0B` for all images. This is correct given what the API
returns, not a parsing bug.
