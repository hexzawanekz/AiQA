"""
TC-03: Visual Store Verification
Uses the browser agent to navigate the homepage, catalog, and a product
detail page. Captures screenshots and verifies key UI elements are present.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from aiqa.browser_agent import run_task
from aiqa.models import Check, TestResult

if TYPE_CHECKING:
    from aiqa.config import ClientConfig
    from aiqa.shopify_client import ShopifyStorefrontClient, ShopifyAdminClient


TEST_ID = "TC-03"
TEST_NAME = "Visual Store Verification (Browser)"


async def run(
    config: "ClientConfig",
    storefront: "ShopifyStorefrontClient | None",
    admin: "ShopifyAdminClient | None",
    screenshots_dir: Path | None = None,
) -> TestResult:
    start = time.time()
    screenshots: list[str] = []
    checks: list[Check] = []

    if screenshots_dir is None:
        screenshots_dir = Path("screenshots") / TEST_ID

    task = f"""
You are an AI QA agent testing a Shopify store. Complete these steps in order:

1. Navigate to {config.base_url}
2. If you see a password prompt page (with a password input field), fill in the password field with '{config.store_password}' and click the submit button, then wait for the page to load
3. Wait for the homepage to fully load
4. Use 'take_screenshot' with label 'homepage' to capture the homepage
5. Verify the page has: a header with the store name, a navigation menu, and at least one product or hero image visible
6. Navigate to {config.base_url}/collections/all
7. Use 'take_screenshot' with label 'catalog' to capture the catalog page
8. Verify the catalog shows: a page title, at least one product card with a name and price
9. Click on the first product in the catalog to go to its Product Detail Page (PDP)
10. Use 'take_screenshot' with label 'pdp' to capture the PDP
11. Verify the PDP shows: product title (H1), a price, and either an 'Add to Cart' button or a 'Configure'/'I'm Interested' button
12. Return a JSON summary with keys: homepage_loaded (bool), catalog_loaded (bool), pdp_loaded (bool), product_title (string), product_price (string), has_cta_button (bool)
"""

    try:
        result_text, step_logs = await run_task(
            task=task,
            screenshots_dir=screenshots_dir,
            client_config=config,
            storefront=storefront,
            admin=admin,
            max_steps=20,
        )

        screenshots = [log.screenshot for log in step_logs if log.screenshot]

        # Parse what the agent reported
        import json, re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        agent_summary: dict = {}
        if json_match:
            try:
                agent_summary = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        homepage_loaded = agent_summary.get("homepage_loaded", len(screenshots) > 0)
        catalog_loaded = agent_summary.get("catalog_loaded", len(screenshots) > 1)
        pdp_loaded = agent_summary.get("pdp_loaded", len(screenshots) > 2)
        product_title = agent_summary.get("product_title", "")
        product_price = agent_summary.get("product_price", "")
        has_cta = agent_summary.get("has_cta_button", True)

        checks = [
            Check("Homepage loads after password", "Page loaded", "Loaded" if homepage_loaded else "Not loaded", homepage_loaded),
            Check("Homepage screenshot captured", "Screenshot saved", f"{len([s for s in screenshots if 'homepage' in s.lower()])} screenshot(s)", any("homepage" in s.lower() for s in screenshots)),
            Check("Catalog page loads", "Catalog visible", "Loaded" if catalog_loaded else "Not loaded", catalog_loaded),
            Check("Catalog screenshot captured", "Screenshot saved", f"{len([s for s in screenshots if 'catalog' in s.lower()])} screenshot(s)", any("catalog" in s.lower() for s in screenshots)),
            Check("PDP loads after clicking product", "PDP visible", "Loaded" if pdp_loaded else "Not loaded", pdp_loaded),
            Check("PDP screenshot captured", "Screenshot saved", f"{len([s for s in screenshots if 'pdp' in s.lower()])} screenshot(s)", any("pdp" in s.lower() for s in screenshots)),
            Check("Product title visible on PDP", "Non-empty title", product_title or "(not reported)", bool(product_title)),
            Check("Product price visible on PDP", "Non-empty price", product_price or "(not reported)", bool(product_price)),
            Check("CTA button present on PDP", "Add to Cart or equivalent", "Present" if has_cta else "Missing", has_cta),
        ]

        all_passed = all(c.passed for c in checks)
        status = "pass" if all_passed else "fail"
        notes = f"Agent browsed store. Screenshots: {len(screenshots)}. Product: '{product_title}' @ {product_price}"

    except Exception as e:
        status = "error"
        notes = str(e)
        checks = [Check("Browser agent ran without error", "No exception", str(e), False)]

    return TestResult(
        test_id=TEST_ID,
        name=TEST_NAME,
        status=status,
        duration_seconds=round(time.time() - start, 2),
        checks=checks,
        screenshots=screenshots,
        notes=notes,
    )
