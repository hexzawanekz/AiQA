"""
TC-02: Data Consistency Check
Cross-verifies that a product's price and title match between
the Storefront API and the Admin API.
No browser needed — pure API verification.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from aiqa.models import Check, TestResult

if TYPE_CHECKING:
    from aiqa.config import ClientConfig
    from aiqa.shopify_client import ShopifyStorefrontClient, ShopifyAdminClient


TEST_ID = "TC-02"
TEST_NAME = "Data Consistency (Storefront API vs Admin API)"


async def run(
    config: "ClientConfig",
    storefront: "ShopifyStorefrontClient | None",
    admin: "ShopifyAdminClient | None",
    screenshots_dir=None,
) -> TestResult:
    start = time.time()
    checks: list[Check] = []
    raw_data: dict = {}

    if storefront is None or admin is None:
        missing = []
        if storefront is None:
            missing.append("storefront_access_token")
        if admin is None:
            missing.append("admin_api_token")
        return TestResult(
            test_id=TEST_ID,
            name=TEST_NAME,
            status="skip",
            notes=f"Skipped: missing {', '.join(missing)} in client YAML",
        )

    try:
        # Step 1: Get a product from the Storefront API
        sf_products = await storefront.search_products("", limit=1)
        if not sf_products:
            return TestResult(
                test_id=TEST_ID,
                name=TEST_NAME,
                status="fail",
                duration_seconds=round(time.time() - start, 2),
                checks=[Check("Storefront has products", "At least 1", "0", False)],
                notes="No products found in Storefront API",
            )

        sf_product = sf_products[0]
        raw_data["storefront_product"] = {
            "title": sf_product.title,
            "price_min": sf_product.price_min,
            "currency": sf_product.currency,
        }

        # Step 2: Find the same product in Admin API by title
        admin_products = await admin.get_products(sf_product.title, limit=5)
        admin_match = None
        for ap in admin_products:
            if ap["title"].lower() == sf_product.title.lower():
                admin_match = ap
                break
        if admin_match is None and admin_products:
            admin_match = admin_products[0]

        if admin_match is None:
            checks.append(Check(
                name="Product found in Admin API",
                expected=sf_product.title,
                actual="Not found",
                passed=False,
            ))
            return TestResult(
                test_id=TEST_ID,
                name=TEST_NAME,
                status="fail",
                duration_seconds=round(time.time() - start, 2),
                checks=checks,
                notes=f"'{sf_product.title}' not found in Admin API",
                raw_data=raw_data,
            )

        admin_price_range = admin_match.get("priceRangeV2", {})
        admin_min_price = admin_price_range.get("minVariantPrice", {}).get("amount", "0")
        admin_currency = admin_price_range.get("minVariantPrice", {}).get("currencyCode", "")
        raw_data["admin_product"] = {
            "title": admin_match["title"],
            "price_min": admin_min_price,
            "currency": admin_currency,
            "status": admin_match.get("status"),
            "inventory": admin_match.get("totalInventory"),
        }

        # Check 1: Product found in Admin API
        checks.append(Check(
            name="Product found in Admin API",
            expected=sf_product.title,
            actual=admin_match["title"],
            passed=True,
        ))

        # Check 2: Title matches (case-insensitive)
        title_match = sf_product.title.lower() == admin_match["title"].lower()
        checks.append(Check(
            name="Title matches between APIs",
            expected=sf_product.title,
            actual=admin_match["title"],
            passed=title_match,
        ))

        # Check 3: Price matches (rounded to 2 decimal places)
        sf_price = round(float(sf_product.price_min), 2)
        admin_price = round(float(admin_min_price), 2)
        price_match = sf_price == admin_price
        checks.append(Check(
            name="Price matches between APIs",
            expected=f"{sf_price} {sf_product.currency}",
            actual=f"{admin_price} {admin_currency}",
            passed=price_match,
        ))

        # Check 4: Currency matches
        currency_match = sf_product.currency == admin_currency
        checks.append(Check(
            name="Currency matches between APIs",
            expected=sf_product.currency,
            actual=admin_currency,
            passed=currency_match,
        ))

        # Check 5: Product is ACTIVE in Admin
        is_active = admin_match.get("status") == "ACTIVE"
        checks.append(Check(
            name="Product is ACTIVE in Admin",
            expected="ACTIVE",
            actual=admin_match.get("status", "unknown"),
            passed=is_active,
        ))

        all_passed = all(c.passed for c in checks)
        status = "pass" if all_passed else "fail"
        notes = (
            f"Compared '{sf_product.title}': "
            f"Storefront {sf_product.price_min} {sf_product.currency} vs "
            f"Admin {admin_min_price} {admin_currency}"
        )

    except Exception as e:
        status = "error"
        notes = str(e)

    return TestResult(
        test_id=TEST_ID,
        name=TEST_NAME,
        status=status,
        duration_seconds=round(time.time() - start, 2),
        checks=checks,
        notes=notes,
        raw_data=raw_data,
    )
