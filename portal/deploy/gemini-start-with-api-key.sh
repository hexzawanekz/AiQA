#!/bin/bash
# Write GEMINI_API_KEY from env to ~/.gemini/.env and /opt/.gemini/.env so the CLI skips "Waiting for auth".
# Wrapper uses cwd=.. (i.e. /opt), so CLI may look for .gemini in /opt.
set -e
# Only write to ~/.gemini (ubuntu can write). Skip /opt/.gemini - ubuntu often can't create it.
GEMINI_DIR="${HOME:-/home/ubuntu}/.gemini"
mkdir -p "$GEMINI_DIR"
if [ -n "$GEMINI_API_KEY" ]; then
  printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY" > "$GEMINI_DIR/.env"
  chmod 600 "$GEMINI_DIR/.env" 2>/dev/null || true
fi
export GEMINI_API_KEY
exec /usr/bin/script -q -c "/opt/agentchattr/.venv/bin/python wrapper.py gemini" /dev/null
