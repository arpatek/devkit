#!/usr/bin/env bash
# =============================================================================
# Script Name: cc.sh
# Description: DevKit Command Center – data-driven TUI launcher. Reads the
#              menu from config/menu.json and dispatches to scripts under
#              modules/. Supports nested submenus and per-item args.
# Author: Juan Garcia (arpatek)
# Created: 2025-04-17
# Version: 1.0
# =============================================================================

# ——[ Configuration ]———————————————————————————————————————————————————————————

DEVKIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
export DEVKIT_ROOT
cd "$DEVKIT_ROOT"

MENU_FILE="$DEVKIT_ROOT/config/menu.json"

: "${DIALOG_OK=0}"
: "${DIALOG_CANCEL=1}"
: "${DIALOG_ESC=255}"

declare -A COLORS=(
    [red]='\033[0;31m'
    [green]='\033[0;32m'
    [yellow]='\033[0;33m'
    [blue]='\033[0;34m'
    [purple]='\033[0;35m'
    [reset]='\033[0m'
)

# ——[ Pre-flight ]——————————————————————————————————————————————————————————————

function require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Required command not found: $1" >&2
        exit 1
    fi
}

require_cmd dialog
require_cmd jq

if [ ! -f "$MENU_FILE" ]; then
    echo "Menu config not found: $MENU_FILE" >&2
    exit 1
fi

if [ ! -d "${DEVKIT_ROOT}/.venv" ]; then
    echo "Python venv not found — run ./setup.sh first" >&2
    exit 1
fi

# ——[ Theme ]———————————————————————————————————————————————————————————————————
# Available: amber  cyan  green  purple  blue
: "${DEVKIT_THEME:=amber}"

_write_dialogrc() {
    local accent
    case "$DEVKIT_THEME" in
        amber)  accent=YELLOW  ;;
        cyan)   accent=CYAN    ;;
        green)  accent=GREEN   ;;
        purple) accent=MAGENTA ;;
        blue)   accent=BLUE    ;;
        *)      accent=YELLOW  ;;
    esac

    cat > "${DEVKIT_ROOT}/.dialogrc" << EOF
use_shadow = OFF
use_colors = ON

screen_color              = (${accent},BLACK,OFF)
dialog_color              = (WHITE,BLACK,OFF)
title_color               = (${accent},BLACK,ON)
border_color              = (${accent},BLACK,ON)
border2_color             = (${accent},BLACK,ON)

button_active_color       = (BLACK,${accent},ON)
button_inactive_color     = (${accent},BLACK,OFF)
button_key_active_color   = (BLACK,${accent},ON)
button_key_inactive_color = (${accent},BLACK,OFF)
button_label_active_color = (BLACK,${accent},ON)
button_label_inactive_color = (${accent},BLACK,OFF)

menubox_color             = (WHITE,BLACK,OFF)
menubox_border_color      = (${accent},BLACK,ON)
menubox_border2_color     = (${accent},BLACK,ON)
item_color                = (WHITE,BLACK,OFF)
item_selected_color       = (BLACK,${accent},ON)
tag_color                 = (${accent},BLACK,ON)
tag_selected_color        = (BLACK,${accent},ON)
tag_key_color             = (${accent},BLACK,OFF)
tag_key_selected_color    = (BLACK,${accent},ON)
itemhelp_color            = (GREEN,BLACK,OFF)

inputbox_color            = (WHITE,BLACK,OFF)
inputbox_border_color     = (${accent},BLACK,ON)
inputbox_border2_color    = (${accent},BLACK,ON)
searchbox_color           = (WHITE,BLACK,OFF)
searchbox_border_color    = (${accent},BLACK,ON)
searchbox_border2_color   = (${accent},BLACK,ON)
searchbox_title_color     = (${accent},BLACK,ON)
position_indicator_color  = (${accent},BLACK,ON)

check_color               = (WHITE,BLACK,OFF)
check_selected_color      = (BLACK,${accent},ON)
uarrow_color              = (${accent},BLACK,ON)
darrow_color              = (${accent},BLACK,ON)
gauge_color               = (BLACK,${accent},ON)

form_active_text_color    = (WHITE,BLACK,ON)
form_text_color           = (WHITE,BLACK,OFF)
form_item_readonly_color  = (${accent},BLACK,OFF)
EOF
}

_write_dialogrc
export DIALOGRC="${DEVKIT_ROOT}/.dialogrc"

# ——[ Handlers ]————————————————————————————————————————————————————————————————

trap ctrl_c INT

function ctrl_c() {
    clear
    echo -e "\n${COLORS[yellow]}[${COLORS[blue]}CTRL+C${COLORS[yellow]}] ${COLORS[green]}Exiting DevKit Command Center...${COLORS[reset]}\n"
    exit 1
}

# ——[ Menu Engine ]—————————————————————————————————————————————————————————————

# Recursively render menus. Reads items at the given jq path. An item is
# either a leaf (has .script) which dispatches to a module, or a group
# (has .items) which descends into a submenu.
function show_menu() {
    local jq_path="$1"
    local title="$2"
    local back_label="$3"

    while true; do
        local items_json count
        items_json=$(jq -c "$jq_path" "$MENU_FILE")
        count=$(jq 'length' <<< "$items_json")

        local args=()
        local i
        for ((i = 0; i < count; i++)); do
            local label desc
            label=$(jq -r ".[$i].label" <<< "$items_json")
            desc=$(jq -r ".[$i].description // \"\"" <<< "$items_json")
            args+=("$((i + 1))" "$label" "$desc")
        done

        local choice rc
        exec 3>&1
        choice=$(dialog --clear --backtitle "DevKit Command Center" \
            --title "[ $title ]" \
            --ok-label "SELECT" --cancel-label "$back_label" --help-label "HELP" \
            --item-help --help-button \
            --menu "Choose:" 20 72 10 "${args[@]}" 2>&1 1>&3)
        rc=$?
        exec 3>&-

        if [ $rc -eq 2 ]; then
            dialog --backtitle "DevKit Command Center" \
                --title "[ HELP ]" \
                --msgbox "\
Modules:\n\
  Status      — Homelab probe summary and Prometheus targets\n\
  Proxmox     — VM list, lifecycle actions, node resources\n\
  K3s         — Kubernetes nodes, pods, namespaces\n\
  Pi-hole     — DNS stats, top blocked, DHCP leases, blocking toggle\n\
  WireGuard   — VPN peer status and handshake times\n\
  Identity    — IPA users, groups, hosts, HBAC, user ops\n\
  Monitoring  — Prometheus targets, alerts, Grafana launcher\n\
  Gitea       — CI runner status, pipeline runs, registry images\n\
  System      — Local system info and dev notes\n\
\n\
Setup:        ./setup.sh\n\
Secrets:      config/secrets.env\n\
Menu config:  config/menu.json" 22 62
            continue
        fi

        if [ $rc -ne $DIALOG_OK ]; then
            return $rc
        fi

        local idx item_label script
        idx=$((choice - 1))
        item_label=$(jq -r ".[$idx].label" <<< "$items_json")
        script=$(jq -r ".[$idx].script // empty" <<< "$items_json")

        if [ -n "$script" ]; then
            local script_path="$DEVKIT_ROOT/$script"
            local -a script_args=()
            mapfile -t script_args < <(jq -r ".[$idx].args // [] | .[]" <<< "$items_json")

            clear
            if [ ! -x "$script_path" ]; then
                echo -e "${COLORS[red]}Module missing or not executable:${COLORS[reset]} $script_path"
            else
                "$script_path" "${script_args[@]}"
            fi
            echo -e "\n${COLORS[green]}Press ${COLORS[yellow]}[${COLORS[blue]}ENTER${COLORS[yellow]}]${COLORS[green]} to return...${COLORS[reset]}"
            read -r
        else
            show_menu "${jq_path}[${idx}].items" "$item_label" "BACK"
        fi
    done
}

# ——[ Banner ]——————————————————————————————————————————————————————————————————

clear
echo -e "

██████╗ ███████╗██╗   ██╗██╗  ██╗██╗████████╗
██╔══██╗██╔════╝██║   ██║██║ ██╔╝██║╚══██╔══╝
██║  ██║█████╗  ██║   ██║█████╔╝ ██║   ██║
██║  ██║██╔══╝  ╚██╗ ██╔╝██╔═██╗ ██║   ██║
██████╔╝███████╗ ╚████╔╝ ██║  ██╗██║   ██║
╚═════╝ ╚══════╝  ╚═══╝  ╚═╝  ╚═╝╚═╝   ╚═╝

                    ${COLORS[red]}Dev${COLORS[yellow]}Kit ${COLORS[green]}Command Center ${COLORS[purple]}v1.0${COLORS[reset]}"
sleep 2

# ——[ Main ]————————————————————————————————————————————————————————————————————

show_menu ".items" "MAIN MENU" "EXIT"

clear
echo -e "${COLORS[yellow]}[${COLORS[blue]}EXITING${COLORS[reset]} ${COLORS[red]}DevKit Command Center${COLORS[yellow]}] ${COLORS[green]}Goodbye${COLORS[reset]}, ${COLORS[purple]}$USER${COLORS[reset]}!"
