#!/bin/bash
# Start Qwen API wrapper for agentchattr (DashScope).
# Requires DASHSCOPE_API_KEY in secrets.env.
cd "$(dirname "$0")"
exec .venv/bin/python -m wrapper_api qwen
