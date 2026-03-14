# Qwen Setup for agentchattr

Qwen offers **1,000 requests/day free** via Qwen OAuth (CLI) or paid usage via Alibaba DashScope API.

## Local: Qwen CLI (free 1000 req/day)

### 1. Install Qwen Code CLI

**Option A: npm** (requires Node.js 20+)
```bash
npm install -g @qwen-code/qwen-code@latest
```

**Option B: Homebrew** (macOS/Linux)
```bash
brew install qwen-code
```

**Option C: Install script** (Linux/macOS)
```bash
curl -fsSL https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen.sh | bash
```

### 2. Authenticate (free tier)

```bash
qwen
```

Then in the CLI:
```
/auth
```

Select **Qwen OAuth** → opens browser → sign in with qwen.ai account.  
After login, credentials are cached. **60 req/min, 1,000 req/day** free.

### 3. Run with agentchattr

agentchattr config already includes Qwen. Start the wrapper:

```bash
cd agentchattr
.venv/bin/python wrapper.py qwen
```

Or use the API mode locally (requires DASHSCOPE_API_KEY):

```bash
# In config.local.toml add [agents.qwen] type="api" (see server example)
.venv/bin/python -m wrapper_api qwen
```

---

## Oracle Server: API mode (DashScope)

OAuth won't work headless. Use Alibaba DashScope API instead.

### 1. Get API key

1. Sign up at [Alibaba Cloud Model Studio](https://modelstudio.console.alibabacloud.com/) (outside China)
2. Or [Bailian Console](https://bailian.console.aliyun.com/) (China)
3. Create an API key from the Key Management page

### 2. Add to secrets

```bash
ssh ubuntu@YOUR_ORACLE_IP
nano /opt/agentchattr/secrets.env
```

Add:
```
DASHSCOPE_API_KEY=sk-your-key-here
```

### 3. Push overrides

From your PC:
```powershell
.\scripts\push-agentchattr-overrides.ps1
```

This pushes Qwen config and starts the agentchattr-qwen service.

### 4. (Optional) Install Qwen CLI on server

If you want the CLI for manual use:
```bash
ssh ubuntu@YOUR_ORACLE_IP
curl -sSL https://raw.githubusercontent.com/.../install-qwen-on-oracle.sh | sudo bash
```

Or run the deploy script:
```bash
sudo bash /opt/agentchattr/deploy/install-qwen-on-oracle.sh
```

---

## Config reference

**CLI mode** (config.toml):
```toml
[agents.qwen]
command = "qwen"
cwd = ".."
color = "#2593fc"
label = "Qwen"
mcp_inject = "settings_file"
mcp_settings_path = ".qwen/settings.json"
mcp_transport = "sse"
```

**API mode** (config.local.toml.server.example):
```toml
[agents.qwen]
type = "api"
base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
model = "qwen3-coder-plus"
color = "#2593fc"
label = "Qwen"
api_key_env = "DASHSCOPE_API_KEY"
```

---

## Free tier summary

| Method | Quota | Notes |
|-------|-------|-------|
| Qwen OAuth (CLI) | 60 req/min, 1000 req/day | Free, browser login once |
| DashScope API | Pay-as-you-go | Get key from Alibaba Cloud |

Reset: OAuth quota resets at UTC 00:00.
