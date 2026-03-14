# API Agent Status (agentchattr)

## Summary

**Why agents don't reply:** API keys have quota/billing issues. Direct tests on the server show:

| Agent | Status | Cause |
|-------|--------|-------|
| **Gemini** | 429 Quota exceeded | Google free tier limit reached |
| **Kimi** | 429 Insufficient balance | Z.AI account needs recharge |
| **Kilo** | ✅ Working | Fixed model: `kilo-auto/free` |

## Kilo Fix Applied

- **Old model:** `minimax/minimax-m2:free` (404 / alpha ended)
- **New model:** `kilo-auto/free` (routes to a free model automatically)

Config in `config.local.toml.server.example` and deployed via `scripts/push-agentchattr-overrides.ps1`.

## What You Need To Do

1. **Kilo** – Should work now. Try `@kilo` in chat at http://149.118.140.111/

2. **Gemini** – Check [Google AI Studio](https://aistudio.google.com/) billing/plan. Free tier resets periodically, or add billing.

3. **Kimi** – Recharge your Z.AI account at the Z.AI console.

## Debugging

- Run `python test_apis.py` on the server (with `secrets.env` loaded) to test all APIs.
- Wrapper output: `journalctl -u agentchattr-kilo -f` (PYTHONUNBUFFERED=1 added for live logs).
- If you see "appears offline" or no reply: restart services to clear stale registrations:
  ```bash
  sudo systemctl restart agentchattr agentchattr-gemini agentchattr-kimi agentchattr-kilo
  ```
