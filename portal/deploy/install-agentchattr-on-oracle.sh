#!/bin/bash
# Install agentchattr on Oracle (or any Ubuntu) by cloning from GitHub.
# Run on the instance: curl -sSL <url> | sudo bash   OR   sudo bash install-agentchattr-on-oracle.sh
# No need to upload the whole repo; afterwards push only your overrides (config.toml, wrapper*.py) with push-agentchattr-overrides.ps1

set -e
AGENTCHATTR_REPO="${AGENTCHATTR_REPO:-https://github.com/bcurts/agentchattr.git}"
APP_USER=ubuntu
APP_DIR=/opt/agentchattr

echo "==> Installing git, Python3 venv, nginx..."
apt-get update -qq
apt-get install -y -qq git python3-venv python3-pip nginx

echo "==> Cloning agentchattr into $APP_DIR..."
rm -rf "$APP_DIR"
git clone --depth 1 "$AGENTCHATTR_REPO" "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Creating venv and installing dependencies..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> Creating server config and secrets placeholder..."
mkdir -p "$APP_DIR/data" "$APP_DIR/uploads"
# If our overrides include config.local.toml.server.example, use it when we push. Until then, minimal server-safe config.
if [ -f "$APP_DIR/config.local.toml.server.example" ]; then
  sudo -u "$APP_USER" cp "$APP_DIR/config.local.toml.server.example" "$APP_DIR/config.local.toml"
else
  sudo -u "$APP_USER" tee "$APP_DIR/config.local.toml" > /dev/null << 'LOCAL'
# Server: API keys via env only (set in secrets.env)
[agents.codex]
type = "api"
base_url = "https://api.z.ai/api/coding/paas/v4"
model = "GLM-4.6"
color = "#10a37f"
label = "Codex"
api_key_env = "ZAI_API_KEY"
LOCAL
fi
sudo -u "$APP_USER" tee "$APP_DIR/secrets.env" > /dev/null << 'EOF'
ZAI_API_KEY=replace_with_your_key
EOF
chmod 600 "$APP_DIR/secrets.env"
chown "$APP_USER:$APP_USER" "$APP_DIR/secrets.env"

echo "==> Installing systemd unit..."
tee /etc/systemd/system/agentchattr.service > /dev/null << SVC
[Unit]
Description=agentchattr web + MCP server
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/secrets.env
ExecStart=$APP_DIR/.venv/bin/python run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

echo "==> Installing nginx site..."
tee /etc/nginx/sites-available/agentchattr > /dev/null << 'NGX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:8300;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
NGX

ln -sf /etc/nginx/sites-available/agentchattr /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/sites-enabled/oracle-instance
systemctl reload nginx

echo "==> Allowing port 80 in iptables (if needed)..."
iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 80 -j ACCEPT

echo "==> Enabling and starting agentchattr..."
systemctl daemon-reload
systemctl enable agentchattr
systemctl restart agentchattr || true

echo ""
echo "Done. agentchattr is installed from GitHub."
echo "Next:"
echo "  1. From your PC run: powershell -File scripts/push-agentchattr-overrides.ps1"
echo "     (pushes only config.toml, wrapper.py, wrapper_kimi.py, config.local.toml.server.example)"
echo "  2. On this server: nano $APP_DIR/secrets.env  and set ZAI_API_KEY=your_real_key"
echo "  3. sudo systemctl restart agentchattr"
echo "  4. Open http://YOUR_ORACLE_IP/ in the browser"
