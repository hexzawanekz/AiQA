#!/usr/bin/env python3
"""Quick test of all API agents - run on server with secrets.env loaded."""
import json
import os
import urllib.error
import urllib.request

def test_api(name, url, model, key_env):
    key = os.environ.get(key_env, "")
    if not key:
        print(f"{name}: {key_env} not set")
        return
    payload = {"model": model, "messages": [{"role": "user", "content": "Say hi"}]}
    req = urllib.request.Request(
        url + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"{name}: OK - {content[:80]}...")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"{name}: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"{name}: Error - {e}")

# Kimi (Z.AI)
test_api("Kimi", "https://api.z.ai/api/paas/v4", "glm-4.5", "ZAI_API_KEY")

# Kilo
test_api("Kilo", "https://api.kilo.ai/api/gateway", "kilo-auto/free", "KILO_API_KEY")
