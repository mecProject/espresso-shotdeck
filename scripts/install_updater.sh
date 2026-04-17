#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="/opt/shotdeck"
CONFIG_ROOT="/etc/shotdeck"
VENV_PATH="$INSTALL_ROOT/updater-venv"
PUBLIC_KEY_SRC="${1:-$REPO_ROOT/examples/keys/example-ed25519.pub}"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this installer as root."
command -v python3 >/dev/null || die "python3 is required."

info "Installing system dependencies…"
apt-get update -q
apt-get install -y python3 python3-venv

info "Preparing directories…"
mkdir -p "$INSTALL_ROOT" "$CONFIG_ROOT" /var/log/shotdeck
mkdir -p "$INSTALL_ROOT/public-updater-installer/scripts"

info "Creating updater virtual environment…"
python3 -m venv "$VENV_PATH"
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install "$REPO_ROOT"

if [[ -f "$PUBLIC_KEY_SRC" ]]; then
    info "Installing update verification key…"
    install -m 0644 "$PUBLIC_KEY_SRC" "$CONFIG_ROOT/update-signing-key.pem"
else
    warn "Public key not found at $PUBLIC_KEY_SRC; install it manually before running the updater."
fi

if [[ ! -f "$CONFIG_ROOT/updater.json" ]]; then
    info "Installing example updater config…"
    install -m 0644 "$REPO_ROOT/examples/config/updater.example.json" "$CONFIG_ROOT/updater.json"
fi

info "Installing systemd units…"
install -m 0644 "$REPO_ROOT/systemd/shotdeck.service" /etc/systemd/system/shotdeck.service
install -m 0644 "$REPO_ROOT/systemd/shotdeck-updater.service" /etc/systemd/system/shotdeck-updater.service
install -m 0644 "$REPO_ROOT/systemd/shotdeck-updater.timer" /etc/systemd/system/shotdeck-updater.timer
install -m 0644 "$REPO_ROOT/systemd/shotdeck-update-response.service" /etc/systemd/system/shotdeck-update-response.service
install -m 0644 "$REPO_ROOT/systemd/shotdeck-update-response.path" /etc/systemd/system/shotdeck-update-response.path
install -m 0755 "$REPO_ROOT/scripts/check_update_connectivity.py" "$INSTALL_ROOT/public-updater-installer/scripts/check_update_connectivity.py"
install -m 0755 "$REPO_ROOT/scripts/prompted_update_flow.py" "$INSTALL_ROOT/public-updater-installer/scripts/prompted_update_flow.py"
install -m 0755 "$REPO_ROOT/scripts/run_configured_updater.sh" "$INSTALL_ROOT/public-updater-installer/scripts/run_configured_updater.sh"
systemctl daemon-reload
systemctl enable shotdeck.service shotdeck-updater.timer shotdeck-update-response.path

echo ""
echo "Shotdeck updater installed."
echo "Edit $CONFIG_ROOT/updater.json and then run:"
echo "  sudo systemctl start shotdeck-updater.service"
