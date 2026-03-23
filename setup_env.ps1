# AiQA Environment Setup Script (PowerShell)
# Run this after Python is installed

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "=== AiQA Environment Setup ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    try {
        $v = & $cmd --version 2>$null
        if ($v) { $pythonCmd = $cmd; break }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "ERROR: Python not found. Install Python 3.10+ first:" -ForegroundColor Red
    Write-Host "  winget install Python.Python.3.12" -ForegroundColor White
    Write-Host "  Then restart your terminal and run this script again." -ForegroundColor White
    exit 1
}
Write-Host "  Found: $pythonCmd" -ForegroundColor Green
& $pythonCmd --version

# 2. Check Node.js (optional — portal CLI agents only)
Write-Host ""
Write-Host "[2/4] Checking Node.js..." -ForegroundColor Yellow
try {
    $nodeVer = node --version
    Write-Host "  Found: $nodeVer" -ForegroundColor Green
} catch {
    Write-Host "  Node.js not found (optional — only needed for some portal CLI agents)" -ForegroundColor Gray
}

# 3. Create virtual environment (recommended)
Write-Host ""
Write-Host "[3/4] Creating Python virtual environment..." -ForegroundColor Yellow
$venvPath = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $venvPath)) {
    & $pythonCmd -m venv $venvPath
    Write-Host "  Created: .venv" -ForegroundColor Green
} else {
    Write-Host "  Already exists: .venv" -ForegroundColor Green
}

# Activate and install
$pip = Join-Path $venvPath "Scripts\pip.exe"
$python = Join-Path $venvPath "Scripts\python.exe"

# 4. Install Python dependencies
Write-Host ""
Write-Host "[4/4] Installing Python packages..." -ForegroundColor Yellow
& $pip install --upgrade pip -q
& $pip install -r (Join-Path $ProjectRoot "requirements.txt")
& $pip install -r (Join-Path $ProjectRoot "Auto-Report2\requirements.txt")
& $pip install -r (Join-Path $ProjectRoot "portal\requirements.txt")
Write-Host "  Done." -ForegroundColor Green

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "To activate the virtual environment:" -ForegroundColor White
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Then run:" -ForegroundColor White
Write-Host "  python run.py --client aware-test --suite" -ForegroundColor Yellow
Write-Host "  python run_portal.py" -ForegroundColor Yellow
Write-Host "  cd Auto-Report2; python run.py" -ForegroundColor Yellow
Write-Host ""
