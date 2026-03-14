#!/usr/bin/env python3
"""Quick test of Gemini API - run on server with secrets.env loaded."""
import json
import os
import urllib.error
import urllib.request

key = os.environ.get("GEMINI_API_KEY", "")
if not key:
    print("GEMINI_API_KEY not set")
    exit(1)

url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
payload = {"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "Say hi in 3 words"}]}
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
        print("OK:", content[:200])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:500])
except Exception as e:
    print("Error:", e)
