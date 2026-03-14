"""Agent worker loop: claim case from queue, run browser-use, save results, pick next."""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from aiqa.browser_agent import run_task
from aiqa.config import ClientConfig, load_client
from aiqa.queue import QueuedCase, TestQueue
from aiqa.shopify_client import ShopifyAdminClient, ShopifyStorefrontClient


async def run_single_case(
    case: QueuedCase,
    config: ClientConfig,
    screenshots_dir: Path,
    storefront: ShopifyStorefrontClient | None,
    admin: ShopifyAdminClient | None,
    max_steps: int = 25,
) -> tuple[dict[str, Any], list[str], str]:
    """
    Run a single queued case through the browser agent.
    Returns (result_dict, screenshots, error_string).
    """
    screenshots: list[str] = []
    result_data: dict[str, Any] = {}
    err_msg = ""

    try:
        result_text, step_logs = await run_task(
            task=case.task_prompt,
            screenshots_dir=screenshots_dir,
            client_config=config,
            storefront=storefront,
            admin=admin,
            max_steps=max_steps,
        )
        screenshots = [log.screenshot for log in step_logs if log.screenshot]

        json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
        if json_match:
            try:
                result_data = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        if not result_data:
            result_data = {"raw_output": result_text[:500], "screenshots_count": len(screenshots)}

    except Exception as e:
        err_msg = str(e)
        result_data = {"error": err_msg}

    return result_data, screenshots, err_msg


async def worker_loop(
    run_id: str,
    agent_id: str,
    client_name: str,
    queue: TestQueue,
    config: ClientConfig,
    storefront: ShopifyStorefrontClient | None,
    admin: ShopifyAdminClient | None,
    screenshots_base: Path,
    max_steps: int = 25,
    on_case_start: Callable[[str, str], None] | None = None,
    on_case_done: Callable[[str, str, str, float], None] | None = None,
) -> int:
    """
    Run the worker loop: claim cases, execute, complete, repeat.
    Returns the number of cases completed.
    """
    completed = 0
    date_str = datetime.now().strftime("%Y-%m-%d")

    while True:
        case = queue.claim_next(run_id, agent_id)
        if case is None:
            break

        if on_case_start:
            on_case_start(case.case_id, case.name)

        screenshots_dir = screenshots_base / client_name / date_str / case.case_id.lower()
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        start = time.time()
        try:
            result_data, screenshots, err_msg = await run_single_case(
                case=case,
                config=config,
                screenshots_dir=screenshots_dir,
                storefront=storefront,
                admin=admin,
                max_steps=max_steps,
            )
            duration = time.time() - start
            queue.complete(
                run_id=run_id,
                case_id=case.case_id,
                result=result_data,
                screenshots=screenshots,
                error=err_msg,
            )
            completed += 1
            if on_case_done:
                status = "error" if err_msg else "done"
                on_case_done(case.case_id, case.name, status, duration)
        except Exception as e:
            duration = time.time() - start
            queue.complete(
                run_id=run_id,
                case_id=case.case_id,
                result={"error": str(e)},
                screenshots=[],
                error=str(e),
            )
            if on_case_done:
                on_case_done(case.case_id, case.name, "error", duration)
            completed += 1

    return completed


async def run_workers(
    run_id: str,
    client_name: str,
    num_workers: int,
    config: ClientConfig,
    storefront: ShopifyStorefrontClient | None,
    admin: ShopifyAdminClient | None,
    screenshots_base: Path | None = None,
    queue: TestQueue | None = None,
    max_steps: int = 25,
) -> dict[str, Any]:
    """
    Spawn multiple workers to process the queue concurrently.
    Returns final run status.
    """
    if screenshots_base is None:
        screenshots_base = Path(__file__).parent.parent / "screenshots"
    if queue is None:
        queue = TestQueue()

    def _on_start(cid: str, name: str) -> None:
        print(f"  [Worker] Started {cid}: {name}")

    def _on_done(cid: str, name: str, status: str, duration: float) -> None:
        icon = "[PASS]" if status == "done" else "[FAIL]"
        print(f"  [Worker] {icon} {cid} {status} ({duration:.1f}s)")

    tasks = [
        worker_loop(
            run_id=run_id,
            agent_id=f"agent-{i}",
            client_name=client_name,
            queue=queue,
            config=config,
            storefront=storefront,
            admin=admin,
            screenshots_base=screenshots_base,
            max_steps=max_steps,
            on_case_start=_on_start,
            on_case_done=_on_done,
        )
        for i in range(num_workers)
    ]
    await asyncio.gather(*tasks)

    return queue.get_run_status(run_id)
