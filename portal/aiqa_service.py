"""AiQA service — shared logic for routes and WebSocket /test handler."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_aiqa_root = Path(__file__).resolve().parent.parent
if str(_aiqa_root) not in sys.path:
    sys.path.insert(0, str(_aiqa_root))


async def run_adhoc(client_name: str, test_description: str) -> dict:
    """Start an ad-hoc test run. Returns {run_id, client, adhoc}."""
    from aiqa.config import load_client
    from aiqa.queue import QueuedCase, TestQueue
    from aiqa.worker import run_workers
    from aiqa.shopify_client import ShopifyAdminClient, ShopifyStorefrontClient

    config = load_client(client_name)
    prompt = f"""You are an AI QA agent testing a Shopify store. The user requested this test:

{test_description}

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
    run_id = queue.create_run([case], client_name=client_name, plan_path="adhoc")

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
            client_name=client_name,
            num_workers=1,
            config=config,
            storefront=storefront,
            admin=admin,
            screenshots_base=_aiqa_root / "screenshots",
            queue=queue,
        )
    )

    return {"run_id": run_id, "client": client_name, "adhoc": True}


def get_default_client() -> str:
    """Return first available client or 'aware-test'."""
    clients_dir = _aiqa_root / "clients"
    if not clients_dir.exists():
        return "aware-test"
    for f in sorted(clients_dir.glob("*.yaml")):
        if not f.name.endswith(".example"):
            return f.stem
    return "aware-test"
