#!/usr/bin/env bash
# =============================================================================
# Script Name: log_entry.sh
# Description: Prompt via dialog for a DEV log entry and append it to
#              devkit.log at the project root. No Python dependency.
# Author: Juan Garcia (arpatek)
# Created: 2026-05-06
# Version: 0.2
# =============================================================================

set -u

# ——[ Configuration ]———————————————————————————————————————————————————————————

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DEVKIT_ROOT="${DEVKIT_ROOT:-$(dirname "$SCRIPT_DIR")}"
LOG_FILE="$DEVKIT_ROOT/devkit.log"

WHITE='\033[37m'
MAGENTA='\033[35m'
GREEN='\033[32m'
DEV_BADGE='\033[1;30;47m'
RESET='\033[0m'

# ——[ Main ]————————————————————————————————————————————————————————————————————

msg=$(dialog --inputbox "Enter DEV comment to log:" 10 60 3>&1 1>&2 2>&3)
rc=$?
clear

if [ $rc -ne 0 ] || [ -z "$msg" ]; then
    echo "Cancelled — no entry recorded."
    exit 0
fi

ts=$(date '+%Y-%m-%d %H:%M:%S')

# Append plain entry to log file.
printf '[%s] [DEV]: %s\n' "$ts" "$msg" >> "$LOG_FILE"

# Echo a colorized confirmation to the terminal.
printf "${WHITE}[${MAGENTA}%s${WHITE}] [${DEV_BADGE}DEV${RESET}${WHITE}]: \"${GREEN}%s${WHITE}\"${RESET}\n" "$ts" "$msg"
