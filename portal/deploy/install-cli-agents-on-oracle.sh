#!/bin/bash
# Install Gemini CLI and Kilo CLI on Oracle (Ubuntu), then run them as systemd services.
# Run on the instance: sudo bash install-cli-agents-on-oracle.sh
# Prereqs: agentchattr already installed at /opt/agentchattr (bootstrap + push overrides done).

set -e
APP_USER=ubuntu
APP_DIR=/opt/agentchattr

echo "==> Installing Node.js 20.x (Gemini CLI requires Node 20+), tmux..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl tmux
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y -qq nodejs

echo "==> Installing Gemini CLI and Kilo CLI globally (to /usr/local/bin for systemd)..."
npm install -g @google/gemini-cli @kilocode/cli

echo "==> Creating .kilo dir for Kilo MCP config (config.toml has cwd = '..' -> /opt)..."
mkdir -p /opt/.kilo
chown "$APP_USER:$APP_USER" /opt/.kilo

echo "==> Installing systemd unit for Gemini agent (PTY + TERM for tmux/CLI)..."
tee /etc/systemd/system/agentchattr-gemini.service > /dev/null << SVC
[Unit]
Description=agentchattr Gemini CLI agent
After=network.target agentchattr.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/secrets.env
Environment=PATH=$APP_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=TERM=xterm-256color
ExecStart=/usr/bin/script -q -c "$APP_DIR/.venv/bin/python wrapper.py gemini" /dev/null
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC

echo "==> Installing Kimi CLI (uv + kimi-cli) and systemd unit..."
UV_BIN=""
if [ -x /home/$APP_USER/.local/bin/uv ]; then
  UV_BIN="/home/$APP_USER/.local/bin/uv"
elif command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
else
  sudo -u "$APP_USER" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  UV_BIN="/home/$APP_USER/.local/bin/uv"
fi
sudo -u "$APP_USER" env PATH="/home/$APP_USER/.local/bin:$PATH" "$UV_BIN" tool install --python 3.12 kimi-cli 2>/dev/null || true
KIMI_PATH="/home/$APP_USER/.local/bin:$APP_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
tee /etc/systemd/system/agentchattr-kimi.service > /dev/null << SVC2
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
SVC2

echo "==> Installing systemd unit for Kilo agent..."
tee /etc/systemd/system/agentchattr-kilo.service > /dev/null << SVC
[Unit]
Description=agentchattr Kilo CLI agent
After=network.target agentchattr.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$APP_DIR/.venv/bin/python wrapper.py kilo
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable agentchattr-gemini agentchattr-kilo agentchattr-kimi
systemctl start agentchattr-gemini agentchattr-kilo agentchattr-kimi

echo ""
echo "Gemini, Kilo, and Kimi agents are installed and started."
echo "  status: sudo systemctl status agentchattr-gemini agentchattr-kilo agentchattr-kimi"
echo "  logs:   journalctl -u agentchattr-gemini -f   (or -kilo, -kimi)"
echo ""
echo "Gemini not answering? Run once for Google auth:"
echo "  sudo -u ubuntu script -q -c 'cd /opt/agentchattr && .venv/bin/python wrapper.py gemini' /dev/null"
echo "  Sign in when prompted, then Ctrl+C. Service will use cached auth."
echo "Kimi: first run may need /login in Kimi CLI; ensure kimi is on PATH (uv tool install kimi-cli)."
