# AiQA Environment Setup

## Prerequisites

| Tool | Version | Required | Notes |
|------|---------|----------|-------|
| **Python** | 3.10+ | ✅ Yes | Core runtime for AiQA and Auto-Report2 |
| **Node.js** | 18+ | Optional | Only if you work on the `web-ui` submodule or other JS tooling |

---

## 1. Install Python (if not installed)

### Option A: Winget (Windows)

```powershell
winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
```

**Important:** After installation, **close and reopen your terminal** (or Cursor) so `python` is in PATH.

### Option B: Manual download

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download Python 3.12
3. Run installer — **check "Add Python to PATH"**
4. Restart terminal

### Verify

```powershell
python --version
# or
py --version
```

---

## 2. Install Node.js (optional)

Node.js is **not** required for AiQA CLI runs or **Auto-Report2** (Python only). Install Node only if you need it for the **`web-ui`** submodule or other tooling.

---

## 3. Install Python Dependencies

### Quick setup (recommended)

From the AiQA project root:

```powershell
.\setup_env.ps1
```

This creates a `.venv` and installs all packages.

### Manual setup

```powershell
# Create virtual environment
python -m venv .venv

# Activate (PowerShell)
.\.venv\Scripts\Activate.ps1

# Install main dependencies
pip install -r requirements.txt

# Auto-Report2 (Flask dashboard)
pip install -r Auto-Report2\requirements.txt
```

---

## 4. Environment Variables

Copy the example and fill in your keys:

```powershell
copy .env.example .env
```

Edit `.env` with:
- `ANTHROPIC_API_KEY` — for Claude (browser agent)
- `GOOGLE_API_KEY` — for Gemini (alternative)
- `OPENAI_API_KEY` — for OpenAI (alternative)
- Shopify tokens in `clients/*.yaml`

---

## 5. Run

```powershell
# Activate venv first
.\.venv\Scripts\Activate.ps1

# Run QA suite (CLI)
python run.py --client aware-test --suite

# Run Auto-Report2 dashboard (projects, test cases, run history, Browser Use hooks)
cd Auto-Report2
python run.py
# → http://localhost:3001

# Browser Use Web UI (Gradio — drive the browser agent; often used with Auto-Report2)
# Submodule: web-ui/ — see web-ui/README.md (venv + pip/uv inside that folder)
```

**Docs:** [docs/POC-PLAN.md](docs/POC-PLAN.md) — sample POC checklist (aware-cosmetics).

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `python` not found | Restart terminal after install; or use `py` |
| `pip` not found | `python -m pip install -r requirements.txt` |
| Execution policy | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| browser-use errors | Ensure Chrome/Chromium is installed |
