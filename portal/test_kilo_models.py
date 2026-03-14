#!/usr/bin/env python3
"""Test Kilo model names - run with secrets.env loaded."""
import json
import os
import urllib.error
import urllib.request

key = os.environ.get("KILO_API_KEY", "")
if not key:
    print("KILO_API_KEY not set")
    exit(1)

url = "https://api.kilo.ai/api/gateway/chat/completions"
models = [
    "kilo/minimax/minimax-m2.5:free",
    "minimax/minimax-m2.5:free",
    "kilo-auto/free",
]
for model in models:
    payload = {"model": model, "messages": [{"role": "user", "content": "Hi"}]}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"{model}: OK - {content[:60]}...")
            break
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:250]
        print(f"{model}: HTTP {e.code} - {body}")
