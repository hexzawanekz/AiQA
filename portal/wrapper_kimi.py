"""Kimi CLI wrapper — runs kimi in non-interactive (--print) mode per trigger.

Kimi's Python TUI does not accept WriteConsoleInput keystrokes on Windows,
so instead of the interactive wrapper (wrapper.py), we:
  1. Register with agentchattr and write a per-session MCP config file.
  2. Poll the queue file for @mention triggers.
  3. On trigger: spawn  kimi --print --mcp-config-file <cfg> --prompt "..."
     Kimi calls chat_read / chat_send via MCP tools itself.
  4. Heartbeat every 5 s to stay online in the UI.

Usage:
    python wrapper_kimi.py
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
KIMI_CMD = shutil.which("kimi") or "kimi"

TRIGGER_PROMPT = "mcp read #{channel} - you were mentioned, take appropriate action"


def _auth_headers(token: str, *, include_json: bool = False) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if include_json:
        h["Content-Type"] = "application/json"
    return h


def _register(server_port: int) -> dict:
    data = json.dumps({"base": "kimi", "label": "Kimi"}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{server_port}/api/register",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _write_mcp_config(config_path: Path, mcp_url: str, token: str) -> None:
    """Write kimi-format MCP config (uses 'transport' key, not 'type')."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mcpServers": {
            "agentchattr": {
                "transport": "http",
                "url": mcp_url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }
    config_path.write_text(json.dumps(payload, indent=2), "utf-8")


def main():
    from config_loader import load_config

    config = load_config(ROOT)
    server_port = config.get("server", {}).get("port", 8300)
    data_dir = ROOT / config.get("server", {}).get("data_dir", "./data")
    mcp_cfg = config.get("mcp", {})
    mcp_url = f"http://127.0.0.1:{mcp_cfg.get('http_port', 8200)}/mcp"

    data_dir.mkdir(parents=True, exist_ok=True)
    config_dir = data_dir / "provider-config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Register
    try:
        reg = _register(server_port)
    except Exception as exc:
        print(f"  Registration failed: {exc}")
        print("  Is agentchattr running? Start with: python run.py")
        sys.exit(1)

    name: str = reg["name"]
    token: str = reg["token"]
    print(f"  Registered as: {name}")

    _lock = threading.Lock()
    _state = {"name": name, "token": token, "working": False}

    def get_name() -> str:
        with _lock:
            return _state["name"]

    def get_token() -> str:
        with _lock:
            return _state["token"]

    def set_identity(new_name=None, new_token=None):
        with _lock:
            if new_name:
                _state["name"] = new_name
            if new_token:
                _state["token"] = new_token

    def set_working(val: bool):
        with _lock:
            _state["working"] = val

    def is_working() -> bool:
        with _lock:
            return _state["working"]

    # Write initial MCP config
    mcp_config_path = config_dir / f"{name}-mcp.json"
    _write_mcp_config(mcp_config_path, mcp_url, token)

    # Heartbeat thread
    def _heartbeat():
        while True:
            try:
                n, t = get_name(), get_token()
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server_port}/api/heartbeat/{n}",
                    method="POST",
                    data=json.dumps({"active": is_working()}).encode(),
                    headers=_auth_headers(t, include_json=True),
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp_data = json.loads(resp.read())
                server_name = resp_data.get("name", n)
                if server_name != n:
                    set_identity(new_name=server_name)
                    # Rewrite MCP config with same token but new name reference
                    new_cfg = config_dir / f"{server_name}-mcp.json"
                    _write_mcp_config(new_cfg, mcp_url, get_token())
                    mcp_config_path_ref[0] = new_cfg
                    print(f"  Renamed: {n} -> {server_name}")
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    try:
                        r = _register(server_port)
                        set_identity(r["name"], r["token"])
                        new_cfg = config_dir / f"{r['name']}-mcp.json"
                        _write_mcp_config(new_cfg, mcp_url, r["token"])
                        mcp_config_path_ref[0] = new_cfg
                        print(f"  Re-registered as: {r['name']}")
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(5)

    mcp_config_path_ref = [mcp_config_path]
    threading.Thread(target=_heartbeat, daemon=True).start()

    # Announce presence
    try:
        body = json.dumps({"sender": name, "text": f"{name} connected (Kimi CLI + Z.AI)", "channel": "general"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server_port}/api/send",
            method="POST", data=body,
            headers=_auth_headers(token, include_json=True),
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

    # Handle trigger: spawn kimi --print
    def handle_trigger(channel: str = "general"):
        set_working(True)
        cfg_path = mcp_config_path_ref[0]
        prompt = TRIGGER_PROMPT.format(channel=channel)
        try:
            print(f"  [{channel}] Spawning kimi --print ...")
            result = subprocess.run(
                [KIMI_CMD, "--print", "--mcp-config-file", str(cfg_path), "--prompt", prompt, "--final-message-only"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ},
            )
            if result.returncode != 0:
                print(f"  kimi exited {result.returncode}: {result.stderr[:200]}")
            else:
                print(f"  [{channel}] kimi responded OK")
        except subprocess.TimeoutExpired:
            print(f"  [{channel}] kimi timed out")
        except Exception as exc:
            print(f"  [{channel}] Error: {exc}")
        finally:
            set_working(False)

    print(f"\n  === Kimi CLI Wrapper (Z.AI) ===")
    print(f"  MCP: {mcp_url}")
    print(f"  @{name} mentions trigger kimi --print")
    print(f"  Ctrl+C to stop\n")

    try:
        while True:
            current_name = get_name()
            qf = data_dir / f"{current_name}_queue.jsonl"
            try:
                if qf.exists() and qf.stat().st_size > 0:
                    with open(qf, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    qf.write_text("", "utf-8")

                    channels_triggered: set[str] = set()
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            ch = d.get("channel", "general") if isinstance(d, dict) else "general"
                            channels_triggered.add(ch)
                        except json.JSONDecodeError:
                            channels_triggered.add("general")

                    for ch in channels_triggered:
                        handle_trigger(channel=ch)
            except Exception as exc:
                print(f"  Queue error: {exc}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Shutting down...")
    finally:
        try:
            n, t = get_name(), get_token()
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/deregister/{n}",
                method="POST", data=b"",
                headers=_auth_headers(t),
            )
            urllib.request.urlopen(req, timeout=5)
            print(f"  Deregistered {n}")
        except Exception:
            pass
    print("  Wrapper stopped.")


if __name__ == "__main__":
    main()
