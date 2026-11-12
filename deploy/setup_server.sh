#!/bin/bash
# One-time server setup for Ubuntu (Oracle Cloud). Run from the project folder:
#   bash deploy/setup_server.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TIMEZONE="${TIMEZONE:-Asia/Bangkok}"   # UTC+7, same as the laptop
cd "$APP_DIR"

echo "== Installing Python =="
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip

echo "== Setting time zone to $TIMEZONE (used for daily/weekly threads) =="
sudo timedatectl set-timezone "$TIMEZONE"
timedatectl | grep "Time zone"

echo "== Creating virtual environment =="
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements-server.txt

mkdir -p data downloads
chmod 700 data
[ -f telegram_session.session ] && chmod 600 telegram_session.session
[ -f data/config.json ] && chmod 600 data/config.json

echo "== Installing systemd service =="
sed -e "s#/home/ubuntu/forward_to_slack#$APP_DIR#g" \
    -e "s#^User=ubuntu#User=$(whoami)#" \
    deploy/telegram-forwarder.service | sudo tee /etc/systemd/system/telegram-forwarder.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable telegram-forwarder >/dev/null

echo
echo "== Checking configuration =="
venv/bin/python run_server.py --check || true

echo
echo "Setup done. The service is installed but NOT started."
echo "Make sure forwarding is stopped on the laptop, then run:"
echo "  sudo systemctl start telegram-forwarder"
