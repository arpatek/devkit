#!/usr/bin/env bash
# =============================================================================
# Script Name: wireguard.sh
# Description: WireGuard peer status — SSHes to netrunner and runs
#              wg show all dump via a scoped NOPASSWD sudo rule.
# Author: Juan Garcia (arpatek)
# Created: 2026-06-08
# Version: 1.0
# =============================================================================

if ((BASH_VERSINFO[0] < 4)); then
  printf "wireguard.sh requires bash 4 or higher (detected: %s)\n" "$BASH_VERSION" >&2
  exit 1
fi

set -eo pipefail

DEVKIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=../lib/lib.sh
source "${DEVKIT_ROOT}/lib/lib.sh"

# ──[ Config ]──────────────────────────────────────────────────────────────────
readonly WG_HOST="netrunner.home.arpa"
readonly WG_USER="arpatek"

# Map VPN tunnel IPs (allowed_ips) to friendly device names.
# These are the static WireGuard peer assignments — not secrets.
declare -A PEER_NAMES=(
  ["10.10.10.10/32"]="malorian"
  ["10.10.10.11/32"]="uplink"
  ["10.10.10.12/32"]="dataslab"
  ["10.10.10.13/32"]="silverhand"
)

# ──[ Helpers ]─────────────────────────────────────────────────────────────────
fmt_bytes() {
  local bytes="$1"
  awk -v b="$bytes" 'BEGIN {
    if (b < 1024)           printf "%dB\n",     b
    else if (b < 1048576)   printf "%.1fKB\n",  b/1024
    else if (b < 1073741824) printf "%.1fMB\n", b/1048576
    else                    printf "%.1fGB\n",   b/1073741824
  }'
}

fmt_handshake() {
  local ts="$1"
  local now
  now=$(date +%s)
  local diff=$(( now - ts ))

  if [[ "$ts" == "0" ]]; then
    printf "never"
    return
  fi

  if (( diff < 180 )); then
    printf "active (%ds ago)" "$diff"
  elif (( diff < 3600 )); then
    printf "idle (%dm ago)" "$(( diff / 60 ))"
  elif (( diff < 86400 )); then
    printf "idle (%dh ago)" "$(( diff / 3600 ))"
  else
    printf "offline (%dd ago)" "$(( diff / 86400 ))"
  fi
}

peer_status_color() {
  local ts="$1"
  local now diff
  now=$(date +%s)
  diff=$(( now - ts ))
  if [[ "$ts" == "0" ]]; then
    printf "${C[white]}"
  elif (( diff < 180 )); then
    printf "${C[green]}"
  elif (( diff < 3600 )); then
    printf "${C[yellow]}"
  else
    printf "${C[red]}"
  fi
}

# ──[ Fetch ]───────────────────────────────────────────────────────────────────
printf "%s Fetching WireGuard status from %s...\n" "$(PLUS)" "$WG_HOST"

raw=$(ssh \
  -n \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 \
  "${WG_USER}@${WG_HOST}" "sudo /usr/bin/wg show all dump" 2>/dev/null) || {
  printf "%s SSH to %s failed — check connectivity\n" "$(FAILED)" "$WG_HOST" >&2
  exit 1
}

if [[ -z "$raw" ]]; then
  printf "%s No output from wg show all dump — is WireGuard running on netrunner?\n" "$(FAILED)" >&2
  exit 1
fi

# ──[ Parse + Render ]──────────────────────────────────────────────────────────
printf "\n"
printf "%s%-12s %-12s %-22s %-28s %-10s %-10s%s\n" \
  "${C[cyan]}" "Interface" "Device" "Endpoint" "Handshake" "RX" "TX" "${C[reset]}"
printf "%s%s%s\n" "${C[white]}" "$(printf '─%.0s' {1..90})" "${C[reset]}"

found_peers=0

while IFS=$'\t' read -r f1 f2 f3 f4 f5 f6 f7 f8 f9; do
  # Interface line has 5 fields; peer line has 9
  if [[ -z "$f6" ]]; then
    current_iface="$f1"
    continue
  fi

  # Peer line: f1=iface f2=pubkey f3=psk f4=endpoint f5=allowed_ips
  #            f6=last_handshake f7=rx f8=tx f9=keepalive
  peer_pub="$f2"
  endpoint="$f4"
  allowed_ips="$f5"
  last_handshake="$f6"
  rx_bytes="$f7"
  tx_bytes="$f8"

  device="${PEER_NAMES[$allowed_ips]:-${peer_pub:0:8}...}"
  endpoint_short="${endpoint%%:*}"   # strip port
  handshake_str=$(fmt_handshake "$last_handshake")
  rx_str=$(fmt_bytes "$rx_bytes")
  tx_str=$(fmt_bytes "$tx_bytes")
  color=$(peer_status_color "$last_handshake")

  printf "%s%-12s %-12s %-22s %-28s %-10s %-10s%s\n" \
    "$color" \
    "${current_iface}" \
    "$device" \
    "$endpoint_short" \
    "$handshake_str" \
    "$rx_str" \
    "$tx_str" \
    "${C[reset]}"

  (( found_peers++ )) || true
done <<< "$raw"

printf "\n"

if (( found_peers == 0 )); then
  printf "%s No peers configured.\n" "$(COMPLETE)"
else
  printf "%s %d peer(s) displayed.\n" "$(LAMBDA)" "$found_peers"
fi
