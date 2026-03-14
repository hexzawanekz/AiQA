#!/usr/bin/env python3
"""Test DashScope/Qwen API - run with secrets.env loaded."""
import json
import os
import sys
import urllib.error
import urllib.request

key = os.environ.get("DASHSCOPE_API_KEY", "")
if not key:
    print("DASHSCOPE_API_KEY not set")
    exit(1)

url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
models = sys.argv[1:] if len(sys.argv) > 1 else ["qwen3-coder-plus", "qwen3-8b", "qwen3-4b", "qwen-turbo"]

for model in models:
    payload = {"model": model, "messages": [{"role": "user", "content": "Say hi"}]}
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
            print(f"{model}: OK - {content[:80]}...")
            break
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"{model}: HTTP {e.code} - {body}")
