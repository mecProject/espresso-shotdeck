#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-/etc/shotdeck/updater.json}"
COMMAND_MODE="${2:-scheduled}"
UPDATES_ENABLED_VALUE="${UPDATES_ENABLED:-yes}"
UPDATES_ENABLED_NORMALIZED="$(printf '%s' "$UPDATES_ENABLED_VALUE" | tr '[:upper:]' '[:lower:]')"
AUTO_UPDATE_VALUE="${AUTO_UPDATE:-yes}"
AUTO_UPDATE_NORMALIZED="$(printf '%s' "$AUTO_UPDATE_VALUE" | tr '[:upper:]' '[:lower:]')"

clear_prompt_files() {
    /usr/bin/python3 /opt/shotdeck/public-updater-installer/scripts/prompted_update_flow.py \
        --config "$CONFIG_PATH" clear
}

run_prompted_check() {
    exec /usr/bin/python3 /opt/shotdeck/public-updater-installer/scripts/prompted_update_flow.py \
        --config "$CONFIG_PATH" check
}

run_prompted_response() {
    exec /usr/bin/python3 /opt/shotdeck/public-updater-installer/scripts/prompted_update_flow.py \
        --config "$CONFIG_PATH" process-response
}

case "$UPDATES_ENABLED_NORMALIZED" in
    1|true|yes|on)
        ;;
    0|false|no|off)
        clear_prompt_files
        exit 0
        ;;
    *)
        echo "[WARN] Unrecognized UPDATES_ENABLED=$UPDATES_ENABLED_VALUE; defaulting to enabled" >&2
        ;;
esac

if [[ "$COMMAND_MODE" == "process-response" ]]; then
    if [[ "$AUTO_UPDATE_NORMALIZED" == "0" || "$AUTO_UPDATE_NORMALIZED" == "false" || "$AUTO_UPDATE_NORMALIZED" == "no" || "$AUTO_UPDATE_NORMALIZED" == "off" ]]; then
        run_prompted_response
    fi
    clear_prompt_files
    exit 0
fi

case "$AUTO_UPDATE_NORMALIZED" in
    1|true|yes|on)
        clear_prompt_files
        exec /opt/shotdeck/updater-venv/bin/shotdeck-updater --config "$CONFIG_PATH" unattended
        ;;
    0|false|no|off)
        run_prompted_check
        ;;
    *)
        echo "[WARN] Unrecognized AUTO_UPDATE=$AUTO_UPDATE_VALUE; defaulting to prompted mode" >&2
        run_prompted_check
        ;;
esac
