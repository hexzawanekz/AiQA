#!/bin/bash
# Install Qwen Code CLI on Oracle (Ubuntu) for agentchattr.
# Run on the instance: sudo bash install-qwen-on-oracle.sh
# Prereqs: Node.js 20+ (from install-cli-agents-on-oracle.sh or: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - && sudo apt-get install -y nodejs)

set -e
APP_USER=ubuntu
APP_DIR=/opt/agentchattr

echo "==> Checking Node.js..."
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js not found. Installing Node 20.x..."
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> Installing Qwen Code CLI globally..."
npm install -g @qwen-code/qwen-code@latest

echo "==> Creating .qwen dir for MCP config..."
mkdir -p /opt/.qwen
chown "$APP_USER:$APP_USER" /opt/.qwen

echo ""
echo "Qwen CLI installed. For agentchattr:"
echo "  - API mode (recommended on server): Add DASHSCOPE_API_KEY to secrets.env, then push overrides."
echo "  - CLI mode: Run 'qwen' then /auth, select Qwen OAuth (1000 req/day free)."
echo "    Headless: Use API mode instead — OAuth needs browser login."
