#!/usr/bin/env bash
# ==============================================================================
# PolluSense Raspberry Pi (RPi) Automated Setup Script
# Installs and configures all RPi software, broker, and systemd services
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${HOME}/pollusense"
VENV_DIR="${HOME}/venv"

echo "=================================================================="
echo "    POLLUSENSE RASPBERRY PI INSTALLER (RPi 5)                     "
echo "=================================================================="
echo "Installing to user: ${USER} (${HOME})"
echo "Source directory  : ${SCRIPT_DIR}"
echo "Target directory  : ${TARGET_DIR}"
echo "=================================================================="

# 1. Install prerequisites
echo "[1/6] Installing required system packages..."
sudo apt update
sudo apt install -y mosquitto mosquitto-clients sqlite3 python3-venv python3-pip avahi-daemon avahi-utils

# 2. Configure Mosquitto Broker
echo "[2/6] Configuring Mosquitto broker (external listening on 0.0.0.0:1883)..."
sudo cp "${SCRIPT_DIR}/config/pollusense.conf" /etc/mosquitto/conf.d/pollusense.conf
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

# 3. Create target deployment directory and copy files
echo "[3/6] Deploying scripts and configurations to ${TARGET_DIR}..."
mkdir -p "${TARGET_DIR}"

# Copy configs (preserve existing calibration if already adjusted)
if [ -f "${TARGET_DIR}/calibration.json" ]; then
    echo "  -> Found existing calibration.json, backing up to calibration.json.bak"
    cp "${TARGET_DIR}/calibration.json" "${TARGET_DIR}/calibration.json.bak"
fi
cp "${SCRIPT_DIR}/config/hardware.json" "${TARGET_DIR}/"
cp "${SCRIPT_DIR}/config/calibration.json" "${TARGET_DIR}/"

# Copy python scripts
cp "${SCRIPT_DIR}/scripts/"*.py "${TARGET_DIR}/"
chmod +x "${TARGET_DIR}/"*.py

# 4. Setup Python Virtual Environment
echo "[4/6] Setting up Python virtual environment in ${VENV_DIR}..."
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install paho-mqtt

# 5. Install systemd services
echo "[5/6] Installing and enabling systemd background services..."
sudo cp "${SCRIPT_DIR}/systemd/ps-ingest.service" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/systemd/ps-aggregate.service" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/systemd/ps-aggregate.timer" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/systemd/permanent-ip-alias.service" /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now permanent-ip-alias.service
sudo systemctl enable --now ps-ingest.service
sudo systemctl enable --now ps-aggregate.timer

# 6. Verification
echo "[6/6] Verifying service statuses..."
echo "--- Ingest Service Status ---"
systemctl is-active ps-ingest || true
echo "--- 15-Minute Timer Status ---"
systemctl is-active ps-aggregate.timer || true
echo "--- Mosquitto Status ---"
systemctl is-active mosquitto || true

echo ""
echo "=================================================================="
echo "    POLLUSENSE RPI INSTALLATION COMPLETE!                         "
echo "=================================================================="
echo "Useful Commands:"
echo "  * View Live 15-min CSV : tail -n 10 ~/pollusense/records_15min.csv"
echo "  * Live Terminal Stream : ~/venv/bin/python ~/pollusense/live_calibrated.py"
echo "  * Ingestion Logs       : journalctl -u ps-ingest -f"
echo "  * Check System Timers  : systemctl list-timers | grep ps-aggregate"
echo "=================================================================="
