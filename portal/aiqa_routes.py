"""AiQA-specific API routes for test plan upload, run status, and ad-hoc testing."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add parent AiQA to path so we can import aiqa modules
_aiqa_root = Path(__file__).resolve().parent.parent
if str(_aiqa_root) not in sys.path:
    sys.path.insert(0, str(_aiqa_root))

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/aiqa", tags=["aiqa"])


@router.get("/dashboard", response_class=FileResponse)
async def qa_dashboard():
    """Serve the QA dashboard page."""
    static_dir = Path(__file__).parent / "static"
    path = static_dir / "qa-dashboard.html"
    if not path.exists():
        raise HTTPException(404, "Dashboard not found")
    return FileResponse(path)

# Lazy imports to avoid circular deps
_parser = None
_prompt_builder = None
_queue = None
_config_loader = None


def _get_parser():
    global _parser
    if _parser is None:
        from aiqa.parser import parse_test_plan
        _parser = parse_test_plan
    return _parser


def _get_prompt_builder():
    global _prompt_builder
    if _prompt_builder is None:
        from aiqa.prompt_builder import build_task_prompt
        _prompt_builder = build_task_prompt
    return _prompt_builder


def _get_queue():
    global _queue
    if _queue is None:
        from aiqa.queue import QueuedCase, TestQueue
        _queue = (QueuedCase, TestQueue)
    return _queue


def _get_config():
    global _config_loader
    if _config_loader is None:
        from aiqa.config import load_client
        _config_loader = load_client
    return _config_loader


class RunPlanRequest(BaseModel):
    client_name: str
    plan_path: str = "shopify-standard.md"
    num_workers: int = 2


class AdhocRequest(BaseModel):
    client_name: str
    test_description: str


@router.get("/clients")
async def list_clients():
    """List available client configs from clients/ directory."""
    clients_dir = _aiqa_root / "clients"
    if not clients_dir.exists():
        return {"clients": []}
    clients = []
    for f in clients_dir.glob("*.yaml"):
        if f.name.endswith(".example"):
            continue
        clients.append(f.stem)
    return {"clients": sorted(clients)}


@router.post("/upload-plan")
async def upload_test_plan(file: UploadFile = File(...)):
    """Upload a test plan file (MD or CSV). Saves to test_plans/ and returns parsed case count."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".md", ".markdown", ".csv"):
        raise HTTPException(400, "Only .md, .markdown, or .csv files allowed")
    content = await file.read()
    plans_dir = _aiqa_root / "test_plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    dest = plans_dir / (file.filename or "uploaded.md")
    dest.write_bytes(content)
    parse_test_plan = _get_parser()
    cases = parse_test_plan(dest)
    return {
        "saved": str(dest),
        "filename": file.filename,
        "case_count": len(cases),
        "cases": [{"id": c.id, "name": c.name} for c in cases],
    }


@router.post("/run")
async def start_run(req: RunPlanRequest):
    """Start a test run with the given client and plan. Returns run_id."""
    QueuedCase, TestQueue = _get_queue()
    load_client = _get_config()
    parse_test_plan = _get_parser()
    build_task_prompt = _get_prompt_builder()

    config = load_client(req.client_name)
    plan_path = _aiqa_root / "test_plans" / req.plan_path
    if not plan_path.exists():
        raise HTTPException(404, f"Plan not found: {req.plan_path}")

    parsed = parse_test_plan(plan_path)
    if not parsed:
        raise HTTPException(400, "No test cases in plan")

    queued = [
        QueuedCase(
            case_id=p.id,
            name=p.name,
            task_prompt=build_task_prompt(p, config),
            status="pending",
            run_id="",
        )
        for p in parsed
    ]
    queue = TestQueue()
    run_id = queue.create_run(queued, client_name=req.client_name, plan_path=str(plan_path))

    # Start workers in background
    from aiqa.worker import run_workers
    from aiqa.shopify_client import ShopifyAdminClient, ShopifyStorefrontClient

    storefront = None
    admin = None
    if config.storefront_access_token:
        storefront = ShopifyStorefrontClient(
            store_domain=config.store_domain,
            storefront_access_token=config.storefront_access_token,
        )
    if config.admin_api_token:
        admin = ShopifyAdminClient(
            store_domain=config.store_domain,
            admin_api_token=config.admin_api_token,
        )

    asyncio.create_task(
        run_workers(
            run_id=run_id,
            client_name=req.client_name,
            num_workers=req.num_workers,
            config=config,
            storefront=storefront,
            admin=admin,
            screenshots_base=_aiqa_root / "screenshots",
            queue=queue,
        )
    )

    return {"run_id": run_id, "client": req.client_name, "total_cases": len(queued)}


def _screenshot_url(path: str) -> str:
    """Convert absolute screenshot path to API URL."""
    base = str(_aiqa_root / "screenshots").replace("\\", "/")
    p = path.replace("\\", "/")
    if p.startswith(base):
        rel = p[len(base) :].lstrip("/")
        return f"/api/aiqa/screenshots/{rel}"
    return ""


@router.get("/status/{run_id}")
async def get_run_status(run_id: str):
    """Get status of a test run."""
    from aiqa.queue import TestQueue
    queue = TestQueue()
    meta = queue.get_run_status(run_id)
    if not meta:
        raise HTTPException(404, f"Run not found: {run_id}")
    cases = queue.get_run_cases(run_id)
    meta["cases"] = [
        {
            "case_id": c.case_id,
            "name": c.name,
            "status": c.status,
            "screenshots": [_screenshot_url(s) for s in c.screenshots if _screenshot_url(s)],
        }
        for c in cases
    ]
    return meta


@router.get("/reports/latest")
async def get_latest_report(client_name: str = ""):
    """Get the latest report path or content for a client."""
    reports_dir = _aiqa_root / "reports"
    if not reports_dir.exists():
        return {"path": "", "content": "No reports yet."}
    files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"path": "", "content": "No reports yet."}
    if client_name:
        files = [f for f in files if client_name in f.name]
    if not files:
        return {"path": "", "content": "No reports for this client."}
    latest = files[0]
    content = latest.read_text(encoding="utf-8", errors="replace")
    return {"path": str(latest), "content": content, "name": latest.name}


@router.get("/screenshots/{path:path}")
async def serve_screenshot(path: str):
    """Serve a screenshot file from the AiQA screenshots directory."""
    from fastapi.responses import FileResponse
    base = _aiqa_root / "screenshots"
    full = (base / path).resolve()
    if not str(full).startswith(str(base.resolve())):
        raise HTTPException(403, "Invalid path")
    if full.exists():
        return FileResponse(full)
    raise HTTPException(404, "Not found")


@router.post("/adhoc")
async def run_adhoc(req: AdhocRequest):
    """Run an ad-hoc test case from chat. Creates a single-case run."""
    QueuedCase, TestQueue = _get_queue()
    load_client = _get_config()

    config = load_client(req.client_name)
    prompt = f"""You are an AI QA agent testing a Shopify store. The user requested this test:

{req.test_description}

1. Navigate to {config.base_url}
2. If you see a password prompt, enter '{config.store_password}' and submit
3. Complete the test as described above
4. Use 'take_screenshot' to capture key steps
5. Return a JSON summary with: test_completed (bool), notes (string)
"""

    case = QueuedCase(
        case_id="ADHOC",
        name="Ad-hoc test",
        task_prompt=prompt,
        status="pending",
        run_id="",
    )
    queue = TestQueue()
    run_id = queue.create_run([case], client_name=req.client_name, plan_path="adhoc")

    from aiqa.worker import run_workers
    from aiqa.shopify_client import ShopifyAdminClient, ShopifyStorefrontClient

    storefront = None
    admin = None
    if config.storefront_access_token:
        storefront = ShopifyStorefrontClient(
            store_domain=config.store_domain,
            storefront_access_token=config.storefront_access_token,
        )
    if config.admin_api_token:
        admin = ShopifyAdminClient(
            store_domain=config.store_domain,
            admin_api_token=config.admin_api_token,
        )

    asyncio.create_task(
        run_workers(
            run_id=run_id,
            client_name=req.client_name,
            num_workers=1,
            config=config,
            storefront=storefront,
            admin=admin,
            screenshots_base=_aiqa_root / "screenshots",
            queue=queue,
        )
    )

    return {"run_id": run_id, "client": req.client_name, "adhoc": True}
