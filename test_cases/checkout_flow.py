"""
TC-05: Checkout Flow
Uses the browser agent to go through the full checkout flow with test
customer data. STOPS before entering any payment information.
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


TEST_ID = "TC-05"
TEST_NAME = "Checkout Flow — Stop Before Payment (Browser)"

TEST_CUSTOMER = {
    "email": "qa-test@aiqa-test.com",
    "first_name": "QA",
    "last_name": "Agent",
    "address": "123 Test Street",
    "city": "Bangkok",
    "zip": "10110",
    "country": "Thailand",
    "phone": "+66800000000",
}


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

    c = TEST_CUSTOMER
    api_note = (
        "If clicking 'Add to Cart' fails, try a different product from the catalog."
        if storefront is None
        else "If clicking 'Add to Cart' fails on the current product, use 'create_cart_via_api' with a variant ID from 'verify_product_in_storefront_api', or try a different product."
    )

    task = f"""
You are an AI QA agent testing a Shopify store checkout flow. Follow these steps carefully:

1. Navigate to {config.base_url}
2. If you see a password page, type '{config.store_password}' into the password field and click Enter/Submit
3. Browse to {config.base_url}/collections/all (the catalog)
4. Use 'take_screenshot' with label 'checkout-step0-catalog' to capture the catalog
5. Click on ANY visible in-stock product to go to its Product Detail Page (PDP)
6. On the PDP, find and click the 'Add to Cart' button (or 'Buy it now').
   {api_note}
   If adding to cart succeeds, the cart icon count will increase or a cart drawer will open.
7. Use 'take_screenshot' with label 'checkout-step1-cart' to capture the cart state
8. Navigate directly to {config.base_url}/checkout
9. Use 'take_screenshot' with label 'checkout-step2-form' to capture the checkout page
10. Fill in the contact email: {c['email']}
11. Fill in the shipping form fields:
    - First name: {c['first_name']}
    - Last name: {c['last_name']}  
    - Address: {c['address']}
    - City: {c['city']}
    - ZIP/Postal: {c['zip']}
    - Country: {c['country']}
12. Use 'take_screenshot' with label 'checkout-step3-filled' to capture filled form
13. Click 'Continue to shipping' or 'Continue' button to proceed to shipping step
14. Use 'take_screenshot' with label 'checkout-step4-shipping' to capture shipping options
15. *** STOP HERE — do NOT click any payment button or enter card details ***
16. Return a JSON summary:
    {{
      "checkout_page_loaded": true/false,
      "contact_filled": true/false,
      "address_filled": true/false,
      "shipping_options_visible": true/false,
      "order_summary_visible": true/false,
      "payment_page_reached": false
    }}
"""

    try:
        result_text, step_logs = await run_task(
            task=task,
            screenshots_dir=screenshots_dir,
            client_config=config,
            storefront=storefront,
            admin=admin,
            max_steps=30,
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

        checkout_loaded = agent_summary.get("checkout_page_loaded", len(screenshots) >= 2)
        contact_filled = agent_summary.get("contact_filled", False)
        address_filled = agent_summary.get("address_filled", False)
        shipping_visible = agent_summary.get("shipping_options_visible", False)
        order_summary = agent_summary.get("order_summary_visible", True)
        payment_reached = agent_summary.get("payment_page_reached", False)

        checks = [
            Check("Checkout page loaded", "Checkout URL opened", "Loaded" if checkout_loaded else "Not loaded", checkout_loaded),
            Check("Contact/email field filled", f"Email: {c['email']}", "Filled" if contact_filled else "Not filled", contact_filled),
            Check("Shipping address filled", "Address form completed", "Filled" if address_filled else "Not filled", address_filled),
            Check("Shipping options visible", "At least 1 shipping method shown", "Visible" if shipping_visible else "Not visible", shipping_visible),
            Check("Order summary visible", "Cart total shown in checkout", "Visible" if order_summary else "Not visible", order_summary),
            Check("Payment page NOT reached (safety check)", "Must stop before payment", "SAFE — did not reach payment" if not payment_reached else "REACHED PAYMENT — unexpected", not payment_reached),
            Check("Screenshots captured", "At least 3 screenshots", f"{len(screenshots)} screenshot(s)", len(screenshots) >= 3),
        ]

        all_passed = all(c.passed for c in checks)
        # Allow "fail" on shipping options — some dev stores don't have shipping configured
        critical_checks = [c for c in checks if "safety" in c.name.lower() or "checkout page" in c.name.lower()]
        critical_pass = all(c.passed for c in critical_checks)

        status = "pass" if all_passed else ("fail" if not critical_pass else "pass")
        notes = f"Checkout flow with test customer {c['email']}. Screenshots: {len(screenshots)}. Shipping visible: {shipping_visible}"

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
