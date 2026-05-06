#!/usr/bin/env bash
# =============================================================================
# Script Name: sys_info.sh
# Description: Display local system info in summary or full mode. Robust
#              against missing tools — shows "n/a" for unavailable fields
#              instead of failing.
# Author: Juan Garcia (arpatek)
# Created: 2025-04-18
# Version: 0.3
# =============================================================================

set -u

# ——[ Configuration ]———————————————————————————————————————————————————————————

MODE="summary"
LOG_FILE=""
TERM_OUT=true

# ——[ Color Constants ]—————————————————————————————————————————————————————————

declare -A COLORS=(
    [reset]='\033[0m'
    [yellow]='\033[0;33m'
    [blue]='\033[0;34m'
    [green]='\033[0;32m'
    [red]='\033[0;31m'
    [purple]='\033[0;35m'
)

# ——[ Probes ]——————————————————————————————————————————————————————————————————

# Each probe outputs one line of plain text (or "n/a") and never fails.
# Pipelines swallow errors so missing tools degrade gracefully.

get_userhost() {
    printf '%s@%s' "$(whoami)" "$(hostname -s 2>/dev/null || hostname)"
}

get_fqdn() {
    local v
    v=$(hostname -f 2>/dev/null) || v=""
    echo "${v:-n/a}"
}

get_os() {
    if [ -r /etc/os-release ]; then
        awk -F= '/^PRETTY_NAME=/ {gsub(/"/, "", $2); print $2; exit}' /etc/os-release
    else
        echo "n/a"
    fi
}

get_kernel() { uname -r 2>/dev/null || echo "n/a"; }
get_arch()   { uname -m 2>/dev/null || echo "n/a"; }

get_uptime() {
    local v
    v=$(uptime -p 2>/dev/null | sed 's/^up //')
    echo "${v:-n/a}"
}

get_load() {
    if [ -r /proc/loadavg ]; then
        awk '{print $1, $2, $3}' /proc/loadavg
    else
        echo "n/a"
    fi
}

get_cores() { nproc 2>/dev/null || echo "n/a"; }

get_primary_ip() {
    local v
    v=$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
    if [ -z "$v" ]; then
        v=$(ip -o -4 addr 2>/dev/null | awk '$2 != "lo" {split($4, a, "/"); print a[1]; exit}')
    fi
    echo "${v:-n/a}"
}

get_default_gw() {
    local v
    v=$(ip route 2>/dev/null | awk '/^default/ {printf "%s via %s", $3, $5; exit}')
    echo "${v:-n/a}"
}

get_cpu() {
    local v=""
    # lscpu groups CPUs by cluster on heterogeneous systems (Apple Silicon,
    # big.LITTLE). On M1 it lists Icestorm (E-cores) first, then Firestorm
    # (P-cores) — take the *last* "Model name" to surface the perf core.
    if command -v lscpu >/dev/null 2>&1; then
        v=$(lscpu 2>/dev/null | awk -F: '/Model name/ {sub(/^[ \t]+/, "", $2); print $2}' | tail -1)
    fi
    # Fallback for systems without lscpu.
    if [ -z "$v" ] && [ -r /proc/cpuinfo ]; then
        v=$(awk -F: '/^model name/ {sub(/^[ \t]+/, "", $2); print $2}' /proc/cpuinfo | uniq | tail -1)
    fi
    if [ -z "$v" ] && [ -r /proc/cpuinfo ]; then
        v=$(awk -F: '/^Hardware/ {sub(/^[ \t]+/, "", $2); print $2; exit}' /proc/cpuinfo)
    fi
    echo "${v:-n/a}"
}

get_gpu() {
    local v=""
    if command -v lspci >/dev/null 2>&1; then
        v=$(lspci 2>/dev/null | grep -iE 'vga|3d|display' | head -1 | sed 's/^[^:]*: //')
    fi
    if [ -z "$v" ]; then
        # DRM driver fallback (Apple Silicon Asahi, embedded, headless)
        local card driver
        for card in /sys/class/drm/card*; do
            [ -d "$card/device" ] || continue
            driver=$(basename "$(readlink -f "$card/device/driver" 2>/dev/null)" 2>/dev/null)
            if [ -n "$driver" ] && [ "$driver" != "driver" ]; then
                v="$driver"
                break
            fi
        done
    fi
    echo "${v:-n/a}"
}

get_memory() {
    if command -v free >/dev/null 2>&1; then
        free -h 2>/dev/null | awk '/^Mem:/ {print $3 "/" $2}'
    else
        echo "n/a"
    fi
}

get_disk_root() {
    local v
    v=$(df -h / 2>/dev/null | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}')
    echo "${v:-n/a}"
}

get_disks() {
    if command -v lsblk >/dev/null 2>&1; then
        local v
        v=$(lsblk -dno NAME,SIZE,TYPE 2>/dev/null \
            | awk '$3=="disk" {print $1 " (" $2 ")"}' \
            | paste -sd "," - | sed 's/,/, /g')
        echo "${v:-n/a}"
    else
        echo "n/a"
    fi
}

get_users() {
    local v
    v=$(who 2>/dev/null | awk '{print $1}' | sort -u | paste -sd " " -)
    echo "${v:-n/a}"
}

get_listening_ports() {
    if command -v ss >/dev/null 2>&1; then
        local v
        v=$(ss -tunl 2>/dev/null \
            | awk 'NR>1 {n=split($5,a,":"); print a[n]}' \
            | sort -un \
            | paste -sd " " -)
        echo "${v:-n/a}"
    else
        echo "n/a"
    fi
}

# ——[ Output ]——————————————————————————————————————————————————————————————————

# Style: "color" for terminal, "plain" for log files / pipes.
print_kv() {
    local style="$1" label="$2" value="$3"
    if [ "$style" = "color" ]; then
        printf "${COLORS[yellow]}%-18s${COLORS[reset]} %s\n" "$label:" "$value"
    else
        printf "%-18s %s\n" "$label:" "$value"
    fi
}

print_summary() {
    local style="${1:-color}"
    print_kv "$style" "User@Host" "$(get_userhost)"
    print_kv "$style" "OS"        "$(get_os)"
    print_kv "$style" "Kernel"    "$(get_kernel) ($(get_arch))"
    print_kv "$style" "Uptime"    "$(get_uptime)"
    print_kv "$style" "Load Avg"  "$(get_load)"
    print_kv "$style" "IP Addr"   "$(get_primary_ip)"
    print_kv "$style" "CPU"       "$(get_cpu) ($(get_cores) cores)"
    print_kv "$style" "GPU"       "$(get_gpu)"
    print_kv "$style" "Memory"    "$(get_memory)"
    print_kv "$style" "Disk"      "$(get_disks)"
}

print_full() {
    local style="${1:-color}"
    print_summary "$style"
    print_kv "$style" "FQDN"             "$(get_fqdn)"
    print_kv "$style" "Default Gateway"  "$(get_default_gw)"
    print_kv "$style" "Listening Ports"  "$(get_listening_ports)"
    print_kv "$style" "Filesystem Usage" "$(get_disk_root)"
    print_kv "$style" "Logged-In Users"  "$(get_users)"
}

# ——[ Argument Parsing ]————————————————————————————————————————————————————————

while [[ $# -gt 0 ]]; do
    case $1 in
    --summary) MODE="summary"; shift ;;
    --full)    MODE="full";    shift ;;
    --noterm)  TERM_OUT=false; shift ;;
    --log)     LOG_FILE="$2";  shift 2 ;;
    --help)
        echo "Usage: $0 [--summary|--full] [--log <file>] [--noterm]"
        exit 0
        ;;
    *)
        echo "Unknown option: $1. Use --help for usage." >&2
        exit 1
        ;;
    esac
done

# ——[ Main ]————————————————————————————————————————————————————————————————————

if [ -n "$LOG_FILE" ]; then
    "print_$MODE" plain >> "$LOG_FILE"
fi

if [ "$TERM_OUT" = true ]; then
    "print_$MODE" color
    printf "\n"
fi
