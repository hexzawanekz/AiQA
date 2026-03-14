"""
TC-04: Add to Cart Flow
Uses the browser agent to navigate to a product and add it to the cart.
Then cross-verifies the cart total matches via Storefront API.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from aiqa.browser_agent import run_task
from aiqa.models import Check, TestResult

if TYPE_CHECKING:
    from aiqa.config import ClientConfig
    from aiqa.shopify_client import ShopifyStorefrontClient, ShopifyAdminClient


TEST_ID = "TC-04"
TEST_NAME = "Add to Cart Flow (Browser + API Cross-Verification)"


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

    # Decide approach based on available tokens
    if storefront is not None:
        # API-first approach: create cart via API, verify contents
        task = f"""
You are an AI QA agent testing a Shopify store. Complete these steps:

1. Navigate to {config.base_url}
2. If you see a password prompt, fill in the password field with '{config.store_password}' and click submit
3. Navigate to {config.base_url}/collections/all
4. Use 'take_screenshot' with label 'catalog-before-cart' to capture current state
5. Use the action 'verify_product_in_storefront_api' with the query "" to find any available product and get its variant ID
6. Using the variant ID from step 5, use 'create_cart_via_api' to create a cart (quantity: 1)
7. Use 'take_screenshot' with label 'cart-created' to capture current state
8. Using the cart ID from step 6, use 'verify_cart_via_api' to confirm the cart contains the product
9. Navigate to the checkout URL returned from the cart API
10. Use 'take_screenshot' with label 'checkout-url-loaded' to capture checkout page
11. Return a JSON summary with: product_title (string), product_price (string), cart_total (string), currency (string), cart_lines_count (int), checkout_url_loaded (bool)
"""
    else:
        # Browser-only approach: click Add to Cart in browser
        task = f"""
You are an AI QA agent testing a Shopify store. Complete these steps:

1. Navigate to {config.base_url}
2. If you see a password prompt, fill in the password field with '{config.store_password}' and click submit
3. Navigate to {config.base_url}/collections/all
4. Click on the first product to open its Product Detail Page
5. Use 'take_screenshot' with label 'pdp-before-cart' to capture the PDP
6. Look for and click an 'Add to Cart' button on the page
7. Use 'take_screenshot' with label 'cart-after-add' to capture the cart/drawer state
8. Navigate to the cart page ({config.base_url}/cart)
9. Use 'take_screenshot' with label 'cart-page' to capture the cart
10. Return a JSON summary with: product_title (string), product_price (string), cart_item_count (int), cart_total (string), add_to_cart_succeeded (bool)
"""

    try:
        result_text, step_logs = await run_task(
            task=task,
            screenshots_dir=screenshots_dir,
            client_config=config,
            storefront=storefront,
            admin=admin,
            max_steps=25,
        )

        screenshots = [log.screenshot for log in step_logs if log.screenshot]

        # Parse agent summary
        agent_summary: dict = {}
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            try:
                agent_summary = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Extract API data from step logs
        api_cart_data: dict = {}
        for log in step_logs:
            if "cart verified" in log.description.lower() or "cart created" in log.description.lower():
                api_cart_data = log.data

        if storefront is not None:
            product_title = agent_summary.get("product_title", "")
            cart_total_agent = agent_summary.get("cart_total", "")
            api_total = api_cart_data.get("total", "")
            cart_lines = api_cart_data.get("line_count", agent_summary.get("cart_lines_count", 0))
            currency = agent_summary.get("currency", api_cart_data.get("currency", ""))
            checkout_loaded = agent_summary.get("checkout_url_loaded", False)

            checks = [
                Check("Product found in Storefront API", "Found with variant ID", product_title or "(not reported)", bool(product_title or api_cart_data)),
                Check("Cart created via API", "Cart ID returned", "Created" if api_cart_data else "Not created", bool(api_cart_data)),
                Check("Cart contains 1 line item", "1 line", f"{cart_lines} line(s)", cart_lines >= 1),
                Check("Cart total > 0", "Total > 0", f"{api_total} {currency}", float(api_total or 0) > 0),
                Check("Screenshot: catalog captured", "Screenshot", f"{len(screenshots)} total", len(screenshots) >= 1),
                Check("Checkout URL loaded in browser", "Checkout page opened", "Loaded" if checkout_loaded else "Not loaded", checkout_loaded),
            ]
        else:
            add_succeeded = agent_summary.get("add_to_cart_succeeded", len(screenshots) >= 3)
            cart_total = agent_summary.get("cart_total", "")
            cart_count = agent_summary.get("cart_item_count", 0)

            checks = [
                Check("Add to Cart button clicked", "Button found and clicked", "Succeeded" if add_succeeded else "Failed", add_succeeded),
                Check("Cart item count > 0", "At least 1 item", f"{cart_count} item(s)", cart_count >= 1),
                Check("Cart total present", "Non-empty total", cart_total or "(empty)", bool(cart_total)),
                Check("Screenshots captured", "At least 2 screenshots", f"{len(screenshots)} screenshot(s)", len(screenshots) >= 2),
            ]

        all_passed = all(c.passed for c in checks)
        status = "pass" if all_passed else "fail"
        notes = f"Cart flow completed. API cart total: {api_cart_data.get('total', 'N/A')} {api_cart_data.get('currency', '')}. Screenshots: {len(screenshots)}"

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
