#!/bin/bash
# Add only the Kimi agent to an existing agentchattr install on Oracle. Run: sudo bash add-kimi-agent-on-oracle.sh
set -e
APP_USER=ubuntu
APP_DIR=/opt/agentchattr

echo "==> Installing uv as $APP_USER if needed..."
if [ ! -x /home/$APP_USER/.local/bin/uv ]; then
  sudo -u "$APP_USER" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
echo "==> Installing Kimi CLI (kimi-cli) for $APP_USER..."
sudo -u "$APP_USER" env PATH="/home/$APP_USER/.local/bin:$PATH" /home/$APP_USER/.local/bin/uv tool install --python 3.12 kimi-cli 2>/dev/null || true

echo "==> Installing systemd unit for Kimi..."
KIMI_PATH="/home/$APP_USER/.local/bin:$APP_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
tee /etc/systemd/system/agentchattr-kimi.service > /dev/null << SVC
[Unit]
Description=agentchattr Kimi CLI agent (wrapper_kimi.py)
After=network.target agentchattr.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$KIMI_PATH
ExecStart=$APP_DIR/.venv/bin/python wrapper_kimi.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable agentchattr-kimi
systemctl start agentchattr-kimi
echo "Kimi agent started. Check: sudo systemctl status agentchattr-kimi"
