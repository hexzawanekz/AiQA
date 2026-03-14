#!/bin/bash
# Run on Oracle instance after copying agentchattr to /tmp/agentchattr (without config.local.toml or .env).
# Usage: sudo bash setup-agentchattr-on-server.sh

set -e
APP_USER=ubuntu
APP_DIR=/opt/agentchattr
TMP_SOURCE=/tmp/agentchattr

echo "==> Installing Python3 venv and pip if needed..."
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip

echo "==> Deploying to $APP_DIR..."
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -r "$TMP_SOURCE"/* "$APP_DIR/"
rm -f "$APP_DIR/config.local.toml"
cp "$APP_DIR/config.local.toml.server.example" "$APP_DIR/config.local.toml"
mkdir -p "$APP_DIR/data" "$APP_DIR/uploads"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Creating venv and installing dependencies..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> Creating secrets file placeholder (you must add your real key)..."
sudo -u "$APP_USER" tee "$APP_DIR/secrets.env" > /dev/null << 'EOF'
ZAI_API_KEY=replace_with_your_key
EOF
chmod 600 "$APP_DIR/secrets.env"
chown "$APP_USER:$APP_USER" "$APP_DIR/secrets.env"

echo "==> Installing systemd unit for agentchattr server..."
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

echo "==> Installing nginx site for agentchattr..."
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

echo "==> Enabling agentchattr (will fail until you set ZAI_API_KEY in secrets.env)..."
systemctl daemon-reload
systemctl enable agentchattr
systemctl restart agentchattr || true

echo ""
echo "Next steps:"
echo "  1. Edit $APP_DIR/secrets.env and set ZAI_API_KEY=your_real_key"
echo "  2. sudo systemctl restart agentchattr"
echo "  3. Open http://YOUR_ORACLE_IP/ in the browser"
echo "  4. (Optional) To run Codex agent: create agentchattr-codex.service and start it"
