#!/bin/bash
# Run Kimi as an API agent (wrapper_api.py) so replies are posted via POST /api/send.
# Requires [agents.kimi] type = "api" and base_url/model/api_key_env in config.local.toml.
# Set ZAI_API_KEY in secrets.env (same as Codex; or EnvironmentFile in systemd).
set -e
cd "$(dirname "$0")"
exec .venv/bin/python -m wrapper_api kimi
