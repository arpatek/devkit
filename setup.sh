#!/usr/bin/env bash
# =============================================================================
# Script Name: setup.sh
# Description: devkit first-time setup — verifies dependencies, copies config
#              templates, makes modules executable, installs Python deps,
#              ensures the WireGuard sudo rule is in place on netrunner,
#              fetches the k3s kubeconfig from erebus, and validates
#              secrets.env. Safe to re-run — all steps are idempotent.
# Author: Juan Garcia (arpatek)
# Created: 2026-06-08
# Version: 1.0
# =============================================================================

if ((BASH_VERSINFO[0] < 4)); then
  printf "setup.sh requires bash 4 or higher (detected: %s)\n" "$BASH_VERSION" >&2
  exit 1
fi

# No -e: setup continues past non-fatal failures and reports them at the end
set -uo pipefail

DEVKIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/lib.sh
source "${DEVKIT_ROOT}/lib/lib.sh"

# ──[ State ]───────────────────────────────────────────────────────────────────
WARNINGS=()   # non-fatal issues collected throughout; printed in summary
_STEP=0

# ──[ Helpers ]─────────────────────────────────────────────────────────────────
step() {
  (( _STEP++ )) || true
  printf "\n%s Step %d: %s\n" "$(BANNER)" "$_STEP" "$*"
}
ok()    { printf "  %s %s\n" "$(COMPLETE)" "$*"; }
info()  { printf "  %s %s\n" "$(PLUS)"     "$*"; }
warn()  { printf "  %s %s\n" "$(FAILED)"   "$*"; WARNINGS+=("$*"); }
fail()  { printf "  %s %s\n" "$(FAILED)"   "$*"; }  # print only, no WARNINGS entry
blank() { printf "\n"; }

ask() {
  local prompt="$1" default="${2:-y}"
  local reply
  printf "  %s %s [%s] " "$(PLUS)" "$prompt" "$default"
  read -r reply
  reply="${reply:-$default}"
  [[ "${reply,,}" == "y" ]]
}

# ──[ Package Install ]─────────────────────────────────────────────────────────
_SUDO_CACHED=false

_cache_sudo() {
  if [[ "$_SUDO_CACHED" != true ]]; then
    printf "  %s sudo password required for package install:\n" "$(PLUS)"
    if sudo -v; then
      _SUDO_CACHED=true
    else
      warn "sudo unavailable — cannot install packages"
      return 1
    fi
  fi
}

install_pkg() {
  local pkg="$1"
  if command -v brew >/dev/null 2>&1; then
    brew install "$pkg"
  elif command -v apt-get >/dev/null 2>&1; then
    _cache_sudo || return 1
    sudo apt-get install -y "$pkg"
  elif command -v dnf >/dev/null 2>&1; then
    _cache_sudo || return 1
    sudo dnf install -y "$pkg"
  else
    return 1
  fi
}

# ──[ Step: Preflight ]─────────────────────────────────────────────────────────
step_deps() {
  step "System dependencies"

  local deps=(bash python3 ssh ssh-keygen dialog jq ping)
  local optional=(kubectl)
  local any_failed=false

  for cmd in "${deps[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ok "${cmd}: $(command -v "$cmd")"
    else
      info "${cmd}: not found — installing..."
      if install_pkg "$cmd"; then
        ok "${cmd}: installed"
      else
        printf "  %s %s\n" "$(FAILED)" "${cmd}: install failed — install manually and re-run"
        WARNINGS+=("${cmd}: not found — install manually")
        any_failed=true
      fi
    fi
  done

  for cmd in "${optional[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ok "${cmd}: $(command -v "$cmd")"
    else
      warn "${cmd}: not found — k3s module will not work until installed"
    fi
  done

  if [[ "$any_failed" == true ]]; then
    blank
    printf "  Some required tools could not be installed automatically.\n"
    if ! ask "Continue anyway?"; then
      exit 1
    fi
  fi
}

# ──[ Step: Config files ]──────────────────────────────────────────────────────
step_configs() {
  step "Config files"

  local hosts_src="${DEVKIT_ROOT}/config/hosts.json.example"
  local hosts_dst="${DEVKIT_ROOT}/config/hosts.json"
  local secrets_src="${DEVKIT_ROOT}/config/secrets.env.example"
  local secrets_dst="${DEVKIT_ROOT}/config/secrets.env"

  if [[ -f "$hosts_dst" ]]; then
    ok "hosts.json already exists — skipping"
  else
    cp "$hosts_src" "$hosts_dst"
    ok "hosts.json created from template"
    warn "Edit config/hosts.json with your real homelab inventory"
  fi

  if [[ -f "$secrets_dst" ]]; then
    ok "secrets.env already exists — skipping"
  else
    cp "$secrets_src" "$secrets_dst"
    ok "secrets.env created from template"
    warn "Fill in config/secrets.env with your service credentials"
  fi
}

# ──[ Step: Module permissions ]────────────────────────────────────────────────
step_perms() {
  step "Module permissions"
  chmod +x "${DEVKIT_ROOT}"/modules/*.py "${DEVKIT_ROOT}"/modules/*.sh
  ok "All modules are executable"
}

# ──[ Step: Python virtual environment ]───────────────────────────────────────
step_python() {
  step "Python virtual environment"

  local venv_dir="${DEVKIT_ROOT}/.venv"
  local venv_pip="${venv_dir}/bin/pip"
  local venv_python="${venv_dir}/bin/python3"

  # Create venv if it doesn't exist
  if [[ -d "$venv_dir" ]]; then
    ok "venv already exists: ${venv_dir}"
  else
    info "Creating venv: ${venv_dir}"
    if python3 -m venv "$venv_dir"; then
      ok "venv created"
    else
      warn "venv creation failed — run: python3 -m venv ${venv_dir}"
      return 0
    fi
  fi

  # Install rich if not already present
  if "${venv_python}" -c "import rich" 2>/dev/null; then
    ok "rich: already installed in venv"
  else
    info "Installing rich into venv..."
    if "${venv_pip}" install rich --quiet; then
      ok "rich: installed"
    else
      warn "rich: install failed — run: ${venv_pip} install rich"
    fi
  fi
}

# ──[ Step: WireGuard access ]──────────────────────────────────────────────────
step_wg_sudoers() {
  step "WireGuard access"

  local wg_host="netrunner.home.arpa"
  local wg_user="arpatek"
  local sudoers_rule="${wg_user} ALL=(root) NOPASSWD: /usr/bin/wg show all dump"
  local sudoers_dst="/etc/sudoers.d/devkit-wg"

  # Remove the old forced-command key entry if devkit-wg.key.pub exists locally.
  # netrunner is FreeIPA-enrolled — SSSD intercepts key lookups and serves keys
  # without the command= restriction, so the forced command never applied and the
  # key granted unintended shell access instead.
  local pub_path="${HOME}/.ssh/devkit-wg.key.pub"
  if [[ -f "$pub_path" ]]; then
    local key_material
    key_material="$(awk '{print $2}' "$pub_path")"
    info "Cleaning up stale forced-command key entry from ${wg_host}..."
    if ssh -n -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
         "${wg_user}@${wg_host}" \
         "if grep -qF '${key_material}' ~/.ssh/authorized_keys 2>/dev/null; then
            grep -vF '${key_material}' ~/.ssh/authorized_keys > ~/.ssh/authorized_keys.tmp
            mv ~/.ssh/authorized_keys.tmp ~/.ssh/authorized_keys
            chmod 600 ~/.ssh/authorized_keys
          fi" 2>/dev/null; then
      ok "Stale key entry cleaned up on ${wg_host}"
    else
      warn "Could not clean up stale key entry on ${wg_host} — remove manually from ~/.ssh/authorized_keys"
    fi
  fi

  # Ensure sudoers entry is present. On a fresh install sudo requires a TTY (use_pty
  # Defaults); -t allocates one. On re-runs the check passes via the existing NOPASSWD
  # rule and skips the push entirely.
  info "Checking sudoers entry on ${wg_host}..."
  if ssh -n -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
       "${wg_user}@${wg_host}" \
       "sudo grep -qF 'wg show all dump' '${sudoers_dst}' 2>/dev/null" 2>/dev/null; then
    ok "sudoers entry already present: ${sudoers_dst}"
  else
    info "Pushing sudoers entry (sudo password on ${wg_host} may be required)..."
    if ssh -t -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
         "${wg_user}@${wg_host}" \
         "{ echo '${sudoers_rule}'; echo 'Defaults:${wg_user} !use_pty'; } | sudo tee ${sudoers_dst} > /dev/null && sudo chmod 440 ${sudoers_dst}" 2>/dev/null; then
      ok "sudoers entry written: ${sudoers_dst}"
    else
      warn "Could not write sudoers entry on ${wg_host} — add manually:"
      blank
      printf "    On netrunner, run:\n"
      printf "    echo '%s' | sudo tee %s\n" "$sudoers_rule" "$sudoers_dst"
      printf "    echo 'Defaults:%s !use_pty' | sudo tee -a %s\n" "$wg_user" "$sudoers_dst"
      printf "    sudo chmod 440 %s\n" "$sudoers_dst"
      blank
      return 0
    fi
  fi

  # Smoke test via regular SSH with scoped sudo — no special key needed
  info "Testing WireGuard access..."
  local test_out ssh_rc=0
  test_out="$(ssh -n -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
    "${wg_user}@${wg_host}" "sudo /usr/bin/wg show all dump" 2>/dev/null)" || ssh_rc=$?

  if [[ "$test_out" == *"wg0"* ]]; then
    ok "WireGuard access and peer data: OK"
  elif (( ssh_rc != 0 )); then
    warn "WireGuard: SSH to ${wg_host} failed (rc=${ssh_rc}) — check connectivity"
  else
    warn "WireGuard: connects but no wg0 data — verify WireGuard is running on netrunner"
  fi
}

# ──[ Step: k3s kubeconfig ]────────────────────────────────────────────────────
_verify_kubectl() {
  local kubeconfig="$1"
  local k3s_host="$2"

  if ! command -v kubectl >/dev/null 2>&1; then
    warn "kubectl not installed — install it and re-run setup to verify cluster access"
    return 0
  fi

  ok "kubectl: $(command -v kubectl)"

  # Verify kubeconfig permissions
  local perms
  perms="$(stat -c '%a' "$kubeconfig" 2>/dev/null || stat -f '%Lp' "$kubeconfig" 2>/dev/null)"
  if [[ "$perms" == "600" ]]; then
    ok "kubeconfig permissions: 600"
  else
    info "Fixing kubeconfig permissions (was ${perms})..."
    chmod 600 "$kubeconfig"
    ok "kubeconfig permissions: fixed to 600"
  fi

  # Print server URL — informational only; reachability check below is the real gate
  local server
  server="$(KUBECONFIG="$kubeconfig" kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null)" || true
  ok "kubeconfig server: ${server}"

  # Verify cluster API is reachable
  info "Testing cluster API reachability..."
  if KUBECONFIG="$kubeconfig" kubectl cluster-info --request-timeout=10s 2>/dev/null | grep -q "Kubernetes control plane"; then
    ok "Kubernetes control plane is reachable"
  else
    warn "Cannot reach cluster API — ensure you are on the LAN or VPN, then run: kubectl cluster-info"
    return 0
  fi

  # Node check
  info "Checking node status..."
  local node_out
  node_out="$(KUBECONFIG="$kubeconfig" kubectl get nodes --no-headers 2>/dev/null)" || true
  if [[ -n "$node_out" ]]; then
    local total ready
    total="$(printf '%s\n' "$node_out" | wc -l | tr -d ' ')"
    ready="$(printf '%s\n' "$node_out" | awk '$2=="Ready"' | wc -l | tr -d ' ')"
    ok "Nodes: ${ready}/${total} Ready"
    if (( ready < total )); then
      warn "$((total - ready)) node(s) not Ready — run: kubectl get nodes"
    fi
  else
    warn "kubectl get nodes returned no output — cluster may be empty or unreachable"
  fi
}

step_kubeconfig() {
  step "k3s kubeconfig"

  local kubeconfig="${HOME}/.kube/config"
  local k3s_host="erebus.home.arpa"
  local k3s_ip="10.33.111.103"
  local k3s_user="arpatek"

  if [[ -f "$kubeconfig" ]] && grep -qE "erebus\.home\.arpa|10\.33\.111\.103" "$kubeconfig" 2>/dev/null; then
    ok "kubeconfig already points to erebus: ${kubeconfig}"
    _verify_kubectl "$kubeconfig" "$k3s_host"
    return 0
  fi

  if [[ -f "$kubeconfig" ]]; then
    info "kubeconfig exists but does not reference erebus"
    if ! ask "Overwrite with k3s config from ${k3s_host}?"; then
      warn "Skipping kubeconfig setup — k3s module will not work"
      return 0
    fi
  fi

  local k3s_sudoers_rule="${k3s_user} ALL=(root) NOPASSWD: /usr/bin/cat /etc/rancher/k3s/k3s.yaml"
  local k3s_sudoers_dst="/etc/sudoers.d/devkit-k3s"

  # Stage the kubeconfig in /tmp in the same -t session as the sudoers push.
  # Debian's use_pty Defaults can block non-interactive sudo even with NOPASSWD;
  # running both sudo operations while a PTY is available avoids this entirely.
  local tmp_remote="/tmp/.devkit-k3s-$$.yaml"

  info "Pushing sudoers entry and staging kubeconfig on ${k3s_host} (sudo password may be required)..."
  if ssh -t -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
       "${k3s_user}@${k3s_host}" \
       "{ echo '${k3s_sudoers_rule}'; echo 'Defaults:${k3s_user} !use_pty'; } | sudo tee ${k3s_sudoers_dst} > /dev/null && \
        sudo chmod 440 ${k3s_sudoers_dst} && \
        sudo cat /etc/rancher/k3s/k3s.yaml > '${tmp_remote}' && \
        chmod 600 '${tmp_remote}'" 2>/dev/null; then
    ok "sudoers entry written and kubeconfig staged on ${k3s_host}"
  else
    warn "Could not push to ${k3s_host} — fetch kubeconfig manually:"
    blank
    printf "    On erebus, run:\n"
    printf "    echo '%s' | sudo tee %s\n" "$k3s_sudoers_rule" "$k3s_sudoers_dst"
    printf "    echo 'Defaults:%s !use_pty' | sudo tee -a %s\n" "$k3s_user" "$k3s_sudoers_dst"
    printf "    sudo chmod 440 %s\n" "$k3s_sudoers_dst"
    blank
    printf "    Then:\n"
    printf '%s\n' "    ssh ${k3s_user}@${k3s_host} 'sudo cat /etc/rancher/k3s/k3s.yaml' \\"
    printf '%s\n' "      | sed 's/127.0.0.1/${k3s_host}/' > ~/.kube/config"
    printf '%s\n' "    chmod 600 ~/.kube/config"
    blank
    WARNINGS+=("Fetch k3s kubeconfig manually from erebus (see instructions above)")
    return 0
  fi

  info "Fetching kubeconfig from ${k3s_host}..."
  mkdir -p "${HOME}/.kube"

  # cat the staged file — no sudo, no PTY issues
  if ssh -n -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
       "${k3s_user}@${k3s_host}" \
       "cat '${tmp_remote}'" 2>/dev/null \
     | sed "s/127.0.0.1/${k3s_ip}/" > "${kubeconfig}" \
     && [[ -s "${kubeconfig}" ]]; then
    chmod 600 "${kubeconfig}"
    ssh -n -o ConnectTimeout=5 "${k3s_user}@${k3s_host}" "rm -f '${tmp_remote}'" 2>/dev/null || true
    ok "kubeconfig written: ${kubeconfig}"
    _verify_kubectl "$kubeconfig" "$k3s_host"
  else
    ssh -n -o ConnectTimeout=5 "${k3s_user}@${k3s_host}" "rm -f '${tmp_remote}'" 2>/dev/null || true
    rm -f "${kubeconfig}"
    warn "Could not fetch staged kubeconfig from ${k3s_host}"
    blank
    printf "    Run this manually, then re-run setup:\n"
    printf '%s\n' "    ssh ${k3s_user}@${k3s_host} 'sudo cat /etc/rancher/k3s/k3s.yaml' \\"
    printf '%s\n' "      | sed 's/127.0.0.1/${k3s_host}/' > ~/.kube/config"
    printf '%s\n' "    chmod 600 ~/.kube/config"
    blank
    WARNINGS+=("Fetch k3s kubeconfig manually from erebus (see instructions above)")
  fi
}

# ──[ Step: Secrets validation ]────────────────────────────────────────────────
step_secrets() {
  step "Secrets validation"

  local secrets_file="${DEVKIT_ROOT}/config/secrets.env"

  if [[ ! -f "$secrets_file" ]]; then
    warn "secrets.env not found — run step_configs first"
    return 0
  fi

  # Source into current shell to read values
  # shellcheck source=/dev/null
  set -a; source "$secrets_file"; set +a

  # Keys that must be non-empty for modules to function, with guidance
  declare -A REQUIRED_KEYS=(
    [PROXMOX_TOKEN_SECRET]="Create token at Datacenter → Permissions → API Tokens. Privilege Separation ON = zero perms until you add roles at Datacenter → Permissions → Add → API Token Permission (path /, roles PVEVMAdmin + PVEAuditor). OFF = inherits user perms."
    [PIHOLE_PASSWORD]="Pi-hole admin password"
    [GITEA_TOKEN]="Create in Gitea: Settings → Applications → Personal Access Tokens (scopes: read:admin, read:repository, read:package)"
    [IPA_PASSWORD]="FreeIPA admin password"
  )

  local all_set=true
  for key in "${!REQUIRED_KEYS[@]}"; do
    local val="${!key:-}"
    if [[ -n "$val" ]]; then
      ok "${key}: set"
    else
      warn "${key}: not set — ${REQUIRED_KEYS[$key]}"
      all_set=false
    fi
  done

  if [[ "$all_set" == false ]]; then
    blank
    if ask "Open secrets.env in \$EDITOR now?" "n"; then
      "${EDITOR:-vi}" "$secrets_file"
    fi
  fi
}

# ──[ Summary ]─────────────────────────────────────────────────────────────────
print_summary() {
  blank
  printf "%s%s%s\n" "${C[cyan]}" "$(printf '─%.0s' {1..60})" "${C[reset]}"
  blank

  if [[ ${#WARNINGS[@]} -eq 0 ]]; then
    printf "%s Setup complete — devkit is ready.\n" "$(LAMBDA)"
    blank
    printf "  Run:  ./cc.sh\n"
  else
    printf "%s Setup complete with %d item(s) requiring attention:\n" \
      "$(COMPLETE)" "${#WARNINGS[@]}"
    blank
    local i=1
    for w in "${WARNINGS[@]}"; do
      printf "  %d. %s\n" "$i" "$w"
      (( i++ )) || true
    done
    blank
    printf "  Once resolved, re-run  ./setup.sh  to verify.\n"
    printf "  Modules with unset secrets will fail with a clear error when invoked.\n"
  fi

  blank
  printf "%s%s%s\n" "${C[cyan]}" "$(printf '─%.0s' {1..60})" "${C[reset]}"
  blank
}

# ──[ Main ]────────────────────────────────────────────────────────────────────
main() {
  clear
  printf "\n%s devkit setup — v1.0%s\n" "${C[purple]}" "${C[reset]}"
  blank

  _cache_sudo || true

  step_deps
  step_configs
  step_perms
  step_python
  step_wg_sudoers
  step_kubeconfig
  step_secrets
  print_summary
}

main "$@"
