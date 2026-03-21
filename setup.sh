#!/bin/bash
# Amazon Keyword Rank Tracker - Oracle Cloud Ubuntu Setup Script
# Tested on Ubuntu 22.04 (ARM Ampere A1)

set -e

echo "=== Amazon Rank Tracker Setup ==="

# ── System packages ──────────────────────────────────────────────────────────
sudo apt-get update -y
sudo apt-get install -y \
    python3.11 python3.11-venv python3-pip \
    git curl wget unzip \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2

# ── Python venv ───────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/amazon-tracker"
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$USER:$USER" "$INSTALL_DIR"

cd "$INSTALL_DIR"
python3.11 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

# ── Playwright Chromium ───────────────────────────────────────────────────────
playwright install chromium
playwright install-deps chromium

# ── systemd service ───────────────────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/amazon-tracker.service"
sudo cp amazon-tracker.service "$SERVICE_FILE"
sudo sed -i "s|/opt/amazon-tracker|$INSTALL_DIR|g" "$SERVICE_FILE"
sudo sed -i "s|User=ubuntu|User=$USER|g" "$SERVICE_FILE"

sudo systemctl daemon-reload
sudo systemctl enable amazon-tracker
sudo systemctl start amazon-tracker

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Tracker service status:"
sudo systemctl status amazon-tracker --no-pager
echo ""
echo "Dashboard: streamlit run $INSTALL_DIR/dashboard.py --server.port 8501 --server.address 0.0.0.0"
echo ""
echo "NOTE: Open port 8501 in Oracle Cloud Security List to access the dashboard."
echo "      http://$(curl -s ifconfig.me):8501"
