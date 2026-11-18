#!/usr/bin/env bash
# ==============================================================================
# PolluSense Dedicated Access Configuration Script
# Configures mDNS (pollusense-edge.local) and permanent IP alias (192.168.1.50)
# ==============================================================================
set -e

echo "[1/3] Setting hostname to 'pollusense-edge'..."
sudo hostnamectl set-hostname pollusense-edge

echo "[2/3] Installing and enabling Avahi mDNS daemon..."
sudo apt update && sudo apt install -y avahi-daemon avahi-utils
sudo systemctl enable --now avahi-daemon

echo "[3/3] Creating and enabling permanent IP alias (192.168.1.50)..."
sudo tee /etc/systemd/system/permanent-ip-alias.service > /dev/null <<'EOF'
[Unit]
Description=Permanent Static IP Alias on wlan0 (192.168.1.50)
After=network.target network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'ip addr add 192.168.1.50/24 dev wlan0 label wlan0:alias || true'
ExecStop=/bin/sh -c 'ip addr del 192.168.1.50/24 dev wlan0:alias || true'

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now permanent-ip-alias.service

echo ""
echo "=================================================================="
echo "Dedicated Access Configured Successfully!"
echo "Access options:"
echo "  1. mDNS Hostname : ssh edgepi2@pollusense-edge.local"
echo "  2. Static Alias  : ssh edgepi2@192.168.1.50"
echo "  3. Standard DHCP : ssh edgepi2@<your-router-assigned-ip>"
echo "=================================================================="
