# devkit — Upgrading

## General process

```sh
git pull
./setup.sh    # re-runs venv install and validates secrets
./cc.sh
```

`setup.sh` is idempotent — safe to re-run. It skips steps that are already in place.

---

## Pi-hole

Pi-hole v6 rewrote the REST API from scratch. If you upgrade Pi-hole and modules start
returning 401 or 404:

- **Auth** — session SID still passed as `?sid=` query parameter. If this breaks,
  check `/api/auth` response structure — the SID field path may have changed.
- **Endpoints** — check Pi-hole's API docs at `https://<host>/api/docs`. The endpoint
  map changed significantly between v5 and v6.
- **`top_blocked`** — currently uses `/api/stats/top_domains?blocked=true`. If this
  stops working, check the docs for the current top domains endpoint.

---

## Gitea

Gitea renames and reorganises API routes between major versions. If a Gitea module
starts returning 404:

1. Fetch the live API spec: `curl http://<host>:3000/swagger.v1.json`
2. Search for the resource name (e.g. `runner`, `package`, `actions`)
3. Update the endpoint path in the module

The runner path changed from `/api/v1/admin/runners` to `/api/v1/admin/actions/runners`
in 1.22 — this pattern may repeat in future versions.

Token scopes may also need expanding as new API features are added. Current required
scopes: `read:admin`, `read:repository`, `read:package`.

---

## Proxmox

Proxmox REST API is stable across versions. No known breaking changes expected.

SSL is disabled (`verify_ssl=False`) due to the self-signed cert. If you add a real
cert to Proxmox, remove the `verify_ssl=False` flag from `proxmox.py`.

---

## k3s

The kubeconfig path and format are stable. After a k3s upgrade the kubeconfig at
`~/.kube/config` remains valid unless the cluster CA was rotated.

If cluster auth fails after an upgrade, re-fetch the kubeconfig:

```sh
ssh -t arpatek@erebus.home.arpa \
  "sudo cat /etc/rancher/k3s/k3s.yaml" \
  | sed 's/127.0.0.1/erebus.home.arpa/' > ~/.kube/config
chmod 600 ~/.kube/config
```

---

## FreeIPA

IPA XML-RPC API is stable. No breaking changes expected from minor version upgrades.

If the IPA host cert changes (e.g. after a Let's Encrypt renewal or IPA CA rotation),
Python will reject the new cert if it can't verify the chain. `ipa.py` uses
`verify_ssl=False` so this should not be an issue in practice.

---

## Python dependencies

devkit has one external Python dependency: `rich`. It is pinned to whatever version
`setup.sh` installs at setup time.

To upgrade it:

```sh
.venv/bin/pip install --upgrade rich
```

No other runtime deps. `lib/api.py` is pure `urllib`.

---

## Adding a new service

1. Add credentials to `config/secrets.env.example` with a comment explaining the scope
2. Write the module under `modules/` following the existing pattern
3. Add menu entries to `config/menu.json`
4. Update `setup.sh` if any remote access setup is needed (sudoers, kubeconfig, etc.)
5. Document access quirks in `docs/gotchas.md`
