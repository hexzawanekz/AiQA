#!/bin/bash
# Run Kilo as an API agent (wrapper_api.py) so replies are posted via POST /api/send.
# Requires [agents.kilo] type = "api" and base_url/model/api_key_env in config.local.toml.
# Set KILO_API_KEY in secrets.env (Kilo.ai; free plan uses MiniMax). EnvironmentFile in systemd.
set -e
cd "$(dirname "$0")"
exec .venv/bin/python -m wrapper_api kilo
