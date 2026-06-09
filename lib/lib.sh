#!/usr/bin/env bash
# =============================================================================
# Script Name: lib.sh
# Description: Shared utilities for devkit modules — ANSI colors, status
#              decorations, and sudo session caching.
# Author: Juan Garcia (arpatek)
# Created: 2026-06-08
# Version: 1.0
# =============================================================================

# ──[ ANSI Color Codes ]────────────────────────────────────────────────────────
declare -A C=(
  [black]=$'\033[0;30m'
  [red]=$'\033[0;31m'
  [green]=$'\033[0;32m'
  [yellow]=$'\033[0;33m'
  [blue]=$'\033[0;34m'
  [purple]=$'\033[0;35m'
  [cyan]=$'\033[0;36m'
  [white]=$'\033[0;37m'
  [reset]=$'\033[0m'
)

# ──[ Status Decorators ]───────────────────────────────────────────────────────
BANNER()   { printf "%s[%s^%s]%s" "${C[yellow]}" "${C[purple]}" "${C[yellow]}" "${C[reset]}"; }
PLUS()     { printf "%s[%s+%s]%s" "${C[yellow]}" "${C[green]}"  "${C[yellow]}" "${C[reset]}"; }
COMPLETE() { printf "%s[%s*%s]%s" "${C[yellow]}" "${C[blue]}"   "${C[yellow]}" "${C[reset]}"; }
FAILED()   { printf "%s[%s!%s]%s" "${C[yellow]}" "${C[red]}"    "${C[yellow]}" "${C[reset]}"; }
# #79be9a — sage green from arpatek.dev, used for environment entry messages
LAMBDA()   { printf "%s[%sλ%s]%s" "${C[yellow]}" $'\033[38;2;121;190;154m' "${C[yellow]}" "${C[reset]}"; }

# ──[ Sudo Session Caching ]────────────────────────────────────────────────────
cache_sudo() {
  sudo -v || exit 1
  while true; do
    sudo -n true
    sleep 60
    kill -0 "$$" || exit
  done 2>/dev/null &
}
