#!/usr/bin/env python
"""
AiQA — Agentic AI Quality Assurance for Shopify
Entry point: python run.py --client aware-test [--plan FILE] [--tests tc01,tc03]

Usage:
  python run.py --client aware-test
  python run.py --client aware-test --plan shopify-standard.md
  python run.py --client aware-test --plan shopify-standard.md --workers 3
  python run.py --client aware-test --tests catalog_search,visual_browse
"""

import argparse
import asyncio
import sys
import io
from pathlib import Path

# Ensure the project root is on the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Force UTF-8 output on Windows to avoid encoding errors with unicode chars
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AiQA — Agentic AI QA for Shopify stores",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  Default: Run test cases from client YAML (Python modules)
  --plan:  Run test plan file (MD/CSV) with multi-agent queue

Available test cases (client YAML mode):
  catalog_search     TC-01: Search product catalog via Storefront API
  data_consistency   TC-02: Cross-verify prices between Storefront and Admin API
  visual_browse      TC-03: Browse homepage, catalog, and PDP in browser
  add_to_cart        TC-04: Add product to cart, verify via API
  checkout_flow      TC-05: Fill checkout form (stops before payment)

Examples:
  python run.py --client aware-test
  python run.py --client aware-test --plan shopify-standard.md --workers 2
  python run.py --client aware-test --tests visual_browse,add_to_cart
        """,
    )
    parser.add_argument(
        "--client",
        required=True,
        help="Client name matching a file in clients/{name}.yaml",
    )
    parser.add_argument(
        "--plan",
        default="",
        help="Test plan file (MD/CSV) in test_plans/ — enables queue-based multi-agent run",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Number of concurrent agents when using --plan (default: 2)",
    )
    parser.add_argument(
        "--tests",
        default="",
        help="Comma-separated list of test cases (client YAML mode only)",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    if args.plan:
        from aiqa.runner import run_plan_suite
        results = await run_plan_suite(
            client_name=args.client,
            plan_path=args.plan,
            num_workers=args.workers,
        )
    else:
        test_filter = [t.strip() for t in args.tests.split(",") if t.strip()] or None
        from aiqa.runner import run_suite
        results = await run_suite(client_name=args.client, test_filter=test_filter)

    failed = sum(1 for r in results if r.status in ("fail", "error"))
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
