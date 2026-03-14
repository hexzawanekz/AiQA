"""Main orchestrator — loads config, runs test cases sequentially or via plan file + queue."""

from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from aiqa.config import ClientConfig, load_client
from aiqa.models import Check, TestResult
from aiqa.parser import ParsedTestCase, parse_test_plan
from aiqa.prompt_builder import build_task_prompt
from aiqa.queue import QueuedCase, TestQueue
from aiqa.reporter import generate_report, send_slack_notification
from aiqa.shopify_client import ShopifyAdminClient, ShopifyStorefrontClient
from aiqa.worker import run_workers

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
REPORTS_DIR = BASE_DIR / "reports"
SCREENSHOTS_BASE = BASE_DIR / "screenshots"
TEST_PLANS_DIR = BASE_DIR / "test_plans"

TEST_CASE_MODULES = {
    "catalog_search": "test_cases.catalog_search",
    "data_consistency": "test_cases.data_consistency",
    "visual_browse": "test_cases.visual_browse",
    "add_to_cart": "test_cases.add_to_cart",
    "checkout_flow": "test_cases.checkout_flow",
}


def _print(msg: str, prefix: str = "") -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {prefix}{msg}")


async def run_suite(client_name: str, test_filter: list[str] | None = None) -> list[TestResult]:
    """
    Load client config, initialise API clients, run all configured test cases,
    generate a report, and optionally notify Slack.
    """
    _print(f"Loading client config: {client_name}")
    config = load_client(client_name)

    # Initialise Shopify API clients (graceful if tokens missing)
    storefront: ShopifyStorefrontClient | None = None
    admin: ShopifyAdminClient | None = None

    if config.storefront_access_token:
        storefront = ShopifyStorefrontClient(
            store_domain=config.store_domain,
            storefront_access_token=config.storefront_access_token,
        )
        _print(f"Storefront API client ready for {config.store_domain}")
    else:
        _print("WARNING: No storefront_access_token -- API tests will be skipped")

    if config.admin_api_token:
        admin = ShopifyAdminClient(
            store_domain=config.store_domain,
            admin_api_token=config.admin_api_token,
        )
        _print(f"Admin API client ready for {config.store_domain}")
    else:
        _print("WARNING: No admin_api_token -- Admin API tests will be skipped")

    # Determine which test cases to run
    test_cases_to_run = config.test_cases
    if test_filter:
        test_cases_to_run = [tc for tc in test_cases_to_run if tc in test_filter]

    _print(f"Running {len(test_cases_to_run)} test case(s): {', '.join(test_cases_to_run)}")
    _print(f"Store: {config.base_url}")
    print("-" * 60)

    run_started = datetime.now()
    results: list[TestResult] = []

    for tc_name in test_cases_to_run:
        module_path = TEST_CASE_MODULES.get(tc_name)
        if not module_path:
            _print(f"Unknown test case '{tc_name}' — skipping", prefix="⚠️  ")
            continue

        screenshots_dir = SCREENSHOTS_BASE / client_name / datetime.now().strftime("%Y-%m-%d") / tc_name

        _print(f"Running {tc_name}...", prefix=">> ")
        try:
            module = importlib.import_module(module_path)
            result: TestResult = await module.run(
                config=config,
                storefront=storefront,
                admin=admin,
                screenshots_dir=screenshots_dir,
            )
        except Exception as e:
            result = TestResult(
                test_id=tc_name.upper(),
                name=tc_name,
                status="error",
                error=str(e),
                notes=f"Unexpected error running test case: {e}",
            )

        results.append(result)
        icon = {"pass": "[PASS]", "fail": "[FAIL]", "skip": "[SKIP]", "error": "[ERROR]"}.get(result.status, "[?]")
        _print(
            f"{icon} {result.test_id} {result.status.upper()} "
            f"({result.passed_checks}/{result.total_checks} checks, {result.duration_seconds}s)"
        )
        if result.status in ("fail", "error") and result.notes:
            _print(f"   {result.notes}", prefix="   ")

    run_finished = datetime.now()
    print("-" * 60)

    # Generate report
    report_path = generate_report(
        client_config=config,
        results=results,
        run_started=run_started,
        run_finished=run_finished,
        output_dir=REPORTS_DIR,
    )
    _print(f"Report saved: {report_path}")

    # Optional Slack notification
    if config.slack_webhook_url:
        await send_slack_notification(
            webhook_url=config.slack_webhook_url,
            client_name=client_name,
            results=results,
            report_path=report_path,
        )
        _print("Slack notification sent")

    # Clean up API clients
    if storefront:
        await storefront.close()
    if admin:
        await admin.close()

    passed = sum(1 for r in results if r.status == "pass")
    total = len(results)
    _print(f"Done. {passed}/{total} passed.")
    return results


def _queued_case_to_test_result(c: QueuedCase) -> TestResult:
    """Convert a completed QueuedCase to TestResult for reporting."""
    status = "pass" if not c.error else "error"
    result = c.result or {}
    if c.error:
        notes = c.error
    else:
        notes = str(result.get("raw_output", result))[:200] if result else ""

    checks: list[Check] = []
    for k, v in result.items():
        if k in ("raw_output", "error", "screenshots_count"):
            continue
        if isinstance(v, bool):
            checks.append(Check(k, "true", str(v).lower(), v))
        elif v is not None:
            checks.append(Check(k, "present", str(v), True))

    if not checks and not c.error:
        checks.append(Check("Task completed", "No error", "Completed", True))

    return TestResult(
        test_id=c.case_id,
        name=c.name,
        status=status,
        duration_seconds=0.0,
        checks=checks,
        screenshots=c.screenshots,
        notes=notes,
        error=c.error,
        raw_data=result,
    )


async def run_plan_suite(
    client_name: str,
    plan_path: Path | str,
    num_workers: int = 2,
    max_steps: int = 25,
) -> list[TestResult]:
    """
    Run a test plan file (MD/CSV) with multi-agent queue.
    Parses the plan, builds prompts, creates queue, spawns workers, generates report.
    """
    _print(f"Loading client config: {client_name}")
    config = load_client(client_name)

    storefront: ShopifyStorefrontClient | None = None
    admin: ShopifyAdminClient | None = None
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

    plan_path = Path(plan_path)
    if not plan_path.is_absolute():
        plan_path = TEST_PLANS_DIR / plan_path
    if not plan_path.exists():
        raise FileNotFoundError(f"Test plan not found: {plan_path}")

    _print(f"Parsing test plan: {plan_path}")
    parsed = parse_test_plan(plan_path)
    if not parsed:
        _print("No test cases found in plan", prefix="WARNING: ")
        return []

    _print(f"Building prompts for {len(parsed)} test case(s)")
    queued_cases: list[QueuedCase] = []
    for p in parsed:
        prompt = build_task_prompt(p, config)
        queued_cases.append(
            QueuedCase(
                case_id=p.id,
                name=p.name,
                task_prompt=prompt,
                status="pending",
                run_id="",
            )
        )

    queue = TestQueue()
    run_id = queue.create_run(queued_cases, client_name=client_name, plan_path=str(plan_path))
    _print(f"Run ID: {run_id} | Workers: {num_workers}")
    _print(f"Store: {config.base_url}")
    print("-" * 60)

    run_started = datetime.now()
    await run_workers(
        run_id=run_id,
        client_name=client_name,
        num_workers=num_workers,
        config=config,
        storefront=storefront,
        admin=admin,
        screenshots_base=SCREENSHOTS_BASE,
        queue=queue,
        max_steps=max_steps,
    )
    run_finished = datetime.now()

    cases = queue.get_run_cases(run_id)
    results = [_queued_case_to_test_result(c) for c in cases]

    report_path = generate_report(
        client_config=config,
        results=results,
        run_started=run_started,
        run_finished=run_finished,
        output_dir=REPORTS_DIR,
    )
    _print(f"Report saved: {report_path}")

    if config.slack_webhook_url:
        await send_slack_notification(
            webhook_url=config.slack_webhook_url,
            client_name=client_name,
            results=results,
            report_path=report_path,
        )

    if storefront:
        await storefront.close()
    if admin:
        await admin.close()

    passed = sum(1 for r in results if r.status == "pass")
    total = len(results)
    _print(f"Done. {passed}/{total} passed.")
    return results
