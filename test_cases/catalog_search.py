"""
TC-01: Product Catalog Search
Tests that the Storefront API returns products with required fields.
No browser needed — pure API verification.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from aiqa.models import Check, TestResult

if TYPE_CHECKING:
    from aiqa.config import ClientConfig
    from aiqa.shopify_client import ShopifyStorefrontClient, ShopifyAdminClient


TEST_ID = "TC-01"
TEST_NAME = "Product Catalog Search (Storefront API)"


async def run(
    config: "ClientConfig",
    storefront: "ShopifyStorefrontClient | None",
    admin: "ShopifyAdminClient | None",
    screenshots_dir=None,
) -> TestResult:
    start = time.time()
    checks: list[Check] = []
    raw_data: dict = {}

    if storefront is None:
        return TestResult(
            test_id=TEST_ID,
            name=TEST_NAME,
            status="skip",
            notes="Skipped: no storefront_access_token configured in client YAML",
        )

    try:
        # Query blank search to get full catalog
        products = await storefront.search_products("", limit=10)
        raw_data["product_count"] = len(products)
        raw_data["products"] = [
            {
                "id": p.product_id,
                "title": p.title,
                "price_min": p.price_min,
                "currency": p.currency,
                "variants": len(p.variants),
                "available": any(v.available for v in p.variants),
            }
            for p in products
        ]

        # Check 1: At least 1 product returned
        checks.append(Check(
            name="Products returned",
            expected="At least 1 product",
            actual=f"{len(products)} products",
            passed=len(products) > 0,
        ))

        if products:
            p = products[0]

            # Check 2: First product has a title
            checks.append(Check(
                name="Product has title",
                expected="Non-empty string",
                actual=p.title or "(empty)",
                passed=bool(p.title),
            ))

            # Check 3: First product has a price
            checks.append(Check(
                name="Product has price",
                expected="Price > 0",
                actual=f"{p.price_min} {p.currency}",
                passed=float(p.price_min) > 0,
            ))

            # Check 4: First product has at least one variant
            checks.append(Check(
                name="Product has variants",
                expected="At least 1 variant",
                actual=f"{len(p.variants)} variant(s)",
                passed=len(p.variants) > 0,
            ))

            if p.variants:
                v = p.variants[0]
                # Check 5: Variant has a valid GID
                checks.append(Check(
                    name="Variant has Shopify GID",
                    expected="gid://shopify/ProductVariant/...",
                    actual=v.variant_id,
                    passed=v.variant_id.startswith("gid://shopify/"),
                ))

        # Check 6: Pagination available (implies more products)
        checks.append(Check(
            name="Catalog has products",
            expected="Product list is non-empty",
            actual=f"{len(products)} returned in page 1",
            passed=len(products) > 0,
        ))

        all_passed = all(c.passed for c in checks)
        status = "pass" if all_passed else "fail"
        notes = f"Found {len(products)} products. First: '{products[0].title}' @ {products[0].price_min} {products[0].currency}" if products else "No products found"

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
