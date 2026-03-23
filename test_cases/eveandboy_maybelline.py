"""
TC-DEMO: Eve & Boy — Add to Cart & Get Price
1. Go to Garnier brand page
2. Click Products tab
3. Click first product → product detail page
4. Click Add to Cart
5. Go to cart → scrape product name & price
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


TEST_ID = "TC-DEMO"
TEST_NAME = "Eve & Boy — Add Garnier Product to Cart & Get Price"

BRAND_URL = "https://www.eveandboy.com/brand/garnier?brand_id=5637146720"


async def run(
    config: "ClientConfig",
    storefront: "ShopifyStorefrontClient | None" = None,
    admin: "ShopifyAdminClient | None" = None,
    screenshots_dir: Path | None = None,
) -> TestResult:
    start = time.time()
    screenshots: list[str] = []

    if screenshots_dir is None:
        screenshots_dir = Path("screenshots") / TEST_ID

    task = f"""
You are a QA agent testing an e-commerce website. Follow these steps:

STEP 1 — Go to the brand page:
- Navigate to: {BRAND_URL}

STEP 2 — Open the Products tab:
- Click the tab or button labeled "Products" or "สินค้า"
- Wait for the product list to load

STEP 3 — Open the first product:
- Click the very first product card/image in the list
- Wait for the product detail page to load

STEP 4 — Add to cart:
- Find the "Add to Cart" or "เพิ่มลงตะกร้า" button and click it
- Wait for confirmation that the item was added

STEP 5 — Go to cart:
- Navigate to the cart page (look for a cart icon, or go to /cart)
- Wait for the cart to load

STEP 6 — Call scrape_products_js with max_count=5 to read the cart items
- This will extract product names and prices from the cart page

STEP 7 — Call done with the raw JSON from scrape_products_js
- Copy the JSON exactly into done's text field
"""

    try:
        result_text, step_logs = await run_task(
            task=task,
            screenshots_dir=screenshots_dir,
            client_config=config,
            storefront=storefront,
            admin=admin,
            max_steps=15,
        )

        screenshots = [log.screenshot for log in step_logs if log.screenshot]

        # Try to parse product data from JS scraper step log first
        products: list[dict] = []
        for log in step_logs:
            if log.data and "products" in log.data:
                products = log.data["products"]
                break

        # Fallback: parse JSON from agent's final text
        if not products:
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    products = data.get("products", [])
                except json.JSONDecodeError:
                    pass

        # Print result
        print("\n" + "=" * 60)
        print("  Eve & Boy — Cart Item")
        print("=" * 60)
        if products:
            for p in products:
                print(f"  Product : {p.get('name', 'N/A')}")
                print(f"  Price   : {p.get('price', 'N/A')}")
        else:
            print("  (no cart items parsed)")
            print(f"  Raw: {result_text[:200]}")
        print("=" * 60 + "\n")

        checks = [
            Check("Agent completed", "No exception", "OK" if result_text else "Empty", bool(result_text)),
            Check("Cart item found", ">=1 product in cart", f"{len(products)} item(s)", len(products) >= 1),
            Check("Price found", "Price not empty", products[0].get("price", "N/A") if products else "N/A", bool(products and products[0].get("price") not in ("N/A", "", None))),
        ]

        status = "pass" if all(c.passed for c in checks) else "fail"
        notes = f"Cart item: {products[0].get('name', 'N/A')} — {products[0].get('price', 'N/A')}" if products else "No cart data"

    except Exception as e:
        status = "error"
        notes = str(e)
        checks = [Check("Agent ran without error", "No exception", str(e), False)]
        products = []

    return TestResult(
        test_id=TEST_ID,
        name=TEST_NAME,
        status=status,
        duration_seconds=round(time.time() - start, 2),
        checks=checks,
        screenshots=screenshots,
        notes=notes,
        raw_data={"products": products},
    )
