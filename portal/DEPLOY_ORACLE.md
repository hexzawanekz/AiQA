# Deploy agentchattr to Oracle Cloud (Always Free) — credentials safe

This guide keeps **tokens and API keys off disk in config files** and only in a restricted env file and process memory.

---

## Quick flow: install on Oracle, then push only your changes

1. **Install agentchattr on Oracle** (clones from GitHub on the server; no big upload from your PC):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/bootstrap-agentchattr-on-oracle.ps1
   ```
   This uploads one small script and runs it on the instance; the script clones `https://github.com/bcurts/agentchattr.git` into `/opt/agentchattr`, creates venv, nginx, systemd, and a placeholder secrets file.

2. **Push only your modified files** (config + gemini/kilo/kimi wrappers):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/push-agentchattr-overrides.ps1
   ```
   This copies only: `config.toml`, `config.local.toml.server.example`, `wrapper.py`, `wrapper_kimi.py` to `/opt/agentchattr/` and restarts the service.

3. **On the server:** set your API key in `/opt/agentchattr/secrets.env` and restart:
   ```bash
   ssh -i "F:\WindowsBackup\.ssh\oracle.pem" ubuntu@149.118.140.111
   nano /opt/agentchattr/secrets.env   # ZAI_API_KEY=your_real_key
   sudo systemctl restart agentchattr
   ```

4. Open **http://YOUR_ORACLE_IP/** in the browser.

### Optional: run Gemini CLI and Kilo CLI as agents on the server

From your PC (one time):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-cli-agents-on-oracle.ps1
```

This installs Node.js, then `npm install -g @google/gemini-cli @kilocode/cli`, and adds systemd services `agentchattr-gemini` and `agentchattr-kilo` so the wrappers run in the background. In the chat UI you can @gemini and @kilo.

- **Gemini @mentioned but no answer in chat (CLI):** The CLI must call the MCP tool `chat_send` to post replies; many CLI versions never do. **Recommended:** use **Gemini API mode** (see below) so the server posts replies via the API — no CLI/MCP needed.
- **Gemini on headless (no browser):** Use an API key. Get a key at [Google AI Studio](https://aistudio.google.com/app/apikey), add to `/opt/agentchattr/secrets.env`: `GEMINI_API_KEY=your_key`. Ensure `agentchattr-gemini.service` has `EnvironmentFile=/opt/agentchattr/secrets.env`.

### Gemini, Kimi, Kilo: API mode (reliable @mention replies)

**Push script applies this automatically.** After `push-agentchattr-overrides.ps1`, all three agents run via `wrapper_api.py` and post replies with `POST /api/send`. No CLI/MCP needed.

To enable manually (or to have **@Gemini** replies always appear in chat):

1. **Config:** In `/opt/agentchattr/config.local.toml` ensure you have the Gemini API override (from `config.local.toml.server.example`):
   ```toml
   [agents.gemini]
   type = "api"
   base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
   model = "gemini-2.0-flash"
   color = "#4285f4"
   label = "Gemini"
   api_key_env = "GEMINI_API_KEY"
   ```
2. **Secrets:** In `/opt/agentchattr/secrets.env` set:  
   `GEMINI_API_KEY=...` (Google AI Studio), `ZAI_API_KEY=...` (Z.AI — Codex + Kimi), `KILO_API_KEY=...` (Kilo.ai, free = MiniMax).  
   Push script adds `EnvironmentFile=/opt/agentchattr/secrets.env` to agent units if missing.
3. **Switch services to API scripts:**  
   `ExecStart=/opt/agentchattr/gemini-api-start.sh` (and kimi-api-start.sh, kilo-api-start.sh). Push script does this automatically.

Then @Gemini, @Kimi, and @Kilo are handled by `wrapper_api.py`; replies always show in chat.

### Run in background and start on Oracle reboot

All services are configured to start automatically when the instance boots. To ensure everything is enabled (run once on the server):

```bash
sudo systemctl enable nginx agentchattr agentchattr-gemini agentchattr-kilo agentchattr-kimi
sudo systemctl daemon-reload
```

Check that they are enabled and running:

```bash
systemctl is-enabled nginx agentchattr agentchattr-gemini agentchattr-kilo agentchattr-kimi
sudo systemctl status agentchattr agentchattr-gemini agentchattr-kilo agentchattr-kimi
```

After an Oracle restart, the app and agents come up automatically; open **http://YOUR_ORACLE_IP/** to use the chat.

### Password-protect the chat (only you can access)

You can require a password so only you can open the URL and chat with your agents. Two options:

**Option A — App password (recommended)**  
The app shows a sign-in page; after the correct password, you get a cookie and can use the chat.

1. On the server, add the password to your secrets file (same as API keys):
   ```bash
   nano /opt/agentchattr/secrets.env
   # Add (use a strong password):
   AGENTCHATTR_PASSWORD=your_secret_password
   ```
2. In `config.local.toml` on the server, enable the option:
   ```toml
   [server]
   auth_password_env = "AGENTCHATTR_PASSWORD"
   ```
3. Restart: `sudo systemctl restart agentchattr`
4. Open **http://YOUR_ORACLE_IP/** — you’ll see a sign-in page. Enter the password; you stay signed in for 7 days (or until you sign out via `/auth/logout`).

**Option B — Nginx HTTP Basic Auth**  
Browser shows a username/password popup before any content. No app code change.

1. On the server, create a password file (one-time):
   ```bash
   sudo apt-get install -y apache2-utils
   sudo htpasswd -c /etc/nginx/.htpasswd_agentchattr your_username
   # Enter password when prompted
   ```
2. Edit the nginx site so the `location /` block has auth:
   ```nginx
   location / {
       auth_basic "agentchattr";
       auth_basic_user_file /etc/nginx/.htpasswd_agentchattr;
       proxy_pass http://127.0.0.1:8300;
       # ... rest unchanged (proxy_set_header, etc.)
   }
   ```
3. `sudo nginx -t && sudo systemctl reload nginx`

With either option, only someone who has the password can access the chat and talk to your agents.

---

## Principle: secrets only in environment

- **Never** put API keys or tokens in `config.toml` or `config.local.toml` on the server.
- Use **environment variables** for all secrets. The app already supports this (e.g. `api_key_env = "ZAI_API_KEY"` in config, key set in env).
- On the server, store secrets in **one file** with strict permissions, and load it only into the process (e.g. systemd `EnvironmentFile=`).

---

## 1. Server-side config (no secrets)

On the Oracle instance, use a config that references env vars only:

```bash
# On the instance, after copying agentchattr to e.g. /opt/agentchattr
cd /opt/agentchattr
cp config.local.toml.server.example config.local.toml
# Edit if needed (e.g. different agents); do NOT add api_key = "..." anywhere.
```

Your `config.local.toml` on the server should look like the example: `api_key_env = "ZAI_API_KEY"` and **no** `api_key = "..."` line.

---

## 2. Secrets file (one place, restricted)

Create a file that only the app user can read, and that is **never** committed or copied from your dev machine.

On the Oracle instance:

```bash
sudo mkdir -p /opt/agentchattr
sudo chown ubuntu:ubuntu /opt/agentchattr

# Create secrets file (you'll add the real key in the next step)
# Systemd EnvironmentFile expects KEY=value (no 'export')
sudo -u ubuntu tee /opt/agentchattr/secrets.env > /dev/null << 'EOF'
# API keys — loaded by systemd into the process environment only
ZAI_API_KEY=your_zai_api_key_here
EOF

chmod 600 /opt/agentchattr/secrets.env
```

Then edit the file and put your real Z.AI key in place of `your_zai_api_key_here`:

```bash
nano /opt/agentchattr/secrets.env   # or: vi /opt/agentchattr/secrets.env
```

- **Permissions:** `chmod 600` so only the owner can read it.
- **Never** commit `secrets.env` or copy your local `config.local.toml` (which may contain a key) to the server.

---

## 3. Bind server to localhost only

Keep agentchattr listening only on 127.0.0.1 so it is not exposed directly. Put **nginx in front** so only nginx is exposed on 80/443.

In `config.toml` on the server, keep:

```toml
[server]
port = 8300
host = "127.0.0.1"
data_dir = "./data"
```

No need for `--allow-network`; nginx will proxy to 127.0.0.1:8300.

---

## 4. Run with environment loaded (systemd)

Example systemd unit that loads the secrets file into the environment and runs the app (no secrets in the unit file):

```ini
# /etc/systemd/system/agentchattr.service
[Unit]
Description=agentchattr web + MCP server
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/agentchattr

# Load API keys from a file only the app user can read
EnvironmentFile=/opt/agentchattr/secrets.env

ExecStart=/opt/agentchattr/.venv/bin/python run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable agentchattr
sudo systemctl start agentchattr
```

Secrets exist only in memory of the agentchattr process (and in the restricted file on disk).

---

## 5. Nginx reverse proxy

Serve agentchattr over HTTP (and optionally HTTPS later) via nginx so the app stays on localhost:

```nginx
# /etc/nginx/sites-available/agentchattr
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8300;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

Enable and reload:

```bash
sudo ln -sf /etc/nginx/sites-available/agentchattr /etc/nginx/sites-enabled/
# If you still have the oracle-instance proof site, you can replace it or add this as default.
sudo systemctl reload nginx
```

---

## 6. Optional: run API agents (e.g. Codex) under systemd

If you run `wrapper_api.py codex` on the server, it must see the same env. Run it as another service that loads the same secrets file:

```ini
# /etc/systemd/system/agentchattr-codex.service
[Unit]
Description=agentchattr Codex (Z.AI) API agent
After=network.target agentchattr.service

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/agentchattr
EnvironmentFile=/opt/agentchattr/secrets.env

ExecStart=/opt/agentchattr/.venv/bin/python wrapper_api.py codex
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 7. Firewall (iptables) on Oracle instance

You already opened port 80 in the Security List. On the instance, ensure iptables allows 80 (you did this for the proof page). If you add HTTPS later, open 443 and allow it in iptables too.

---

## 8. Checklist — credentials safe

- [ ] No `api_key = "..."` in any config file on the server; only `api_key_env = "ZAI_API_KEY"`.
- [ ] Secrets only in `/opt/agentchattr/secrets.env` with `chmod 600`.
- [ ] `EnvironmentFile=/opt/agentchattr/secrets.env` in systemd units that need the keys.
- [ ] agentchattr bound to `127.0.0.1:8300`; nginx is the only public entry point.
- [ ] Do not commit or scp `config.local.toml` from your dev machine (it may contain a key); use the server example and env instead.

---

## 9. Deploying the code (no secrets in the bundle)

Use the **Quick flow** at the top: `bootstrap-agentchattr-on-oracle.ps1` then `push-agentchattr-overrides.ps1`. Agentchattr is installed from GitHub on the server; only your overrides (config + wrappers) are pushed from your PC.

**Alternative — full upload:** Use `scripts/deploy-agentchattr-to-oracle.ps1` only if you cannot clone from GitHub on the server; it copies the whole tree and runs `setup-agentchattr-on-server.sh`.
