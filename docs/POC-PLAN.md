# AiQA POC Plan — aware-cosmetics
**Target Store:** aware-cosmetics  
**Environment:** Local (Windows) + Cursor IDE + Cloud n8n  
**Date:** March 2026

---

## What You Already Have (No Setup Needed)

You're in a much better position than the feasibility doc assumed. You don't need a VPS, Docker, or `browser-use` for the POC — you already have everything in Cursor:

| Component | What the Report Assumed | What You Actually Have |
|---|---|---|
| Frontend Agent (browser) | `browser-use` + Docker | **Cursor Browser MCP** — 33 tools (navigate, click, fill, screenshot, etc.) |
| Backend Verification | Install `shopify-mcp` | **Shopify Admin MCP** — already connected (get-products, get-orders, get-customers, etc.) |
| Storefront API | Install Storefront MCP | **Shopify Storefront MCP** — already connected (search_shop_catalog, get_cart, update_cart, etc.) |
| AI Brain | Anthropic API key + Python | **Cursor Agent (Claude)** — you're talking to it right now |
| Orchestrator | n8n self-hosted on VPS | **Cloud n8n** — already have it |

**You can run the POC right now, in this conversation, without installing anything.**

---

## POC Goal

Prove that an AI agent can:
1. Browse the aware-cosmetics storefront in a real browser
2. Search for a product, add it to cart, verify cart data
3. Cross-verify the same product exists in the Admin API
4. Take screenshots at each step
5. Generate a pass/fail report

---

## Test Case List (5 Cases)

### TC-01: Product Catalog Search (Storefront MCP)
**Type:** Backend-only (MCP verification)  
**Steps:**
1. Use Storefront MCP `search_shop_catalog` to search for a product (e.g., "serum" or "moisturizer")
2. Verify: results returned, each product has a title, price, and variant ID
3. Record: product count, first product name + price

**Pass criteria:** At least 1 product returned with valid title and price

---

### TC-02: Product Data Consistency (Storefront MCP ↔ Admin MCP)
**Type:** Backend cross-verification  
**Steps:**
1. From TC-01, take the first product ID
2. Use Storefront MCP `get_product_details` to get full product info
3. Use Admin MCP `get-products` to search the same product by title
4. Compare: title, price, availability should match between both APIs

**Pass criteria:** Product title and price match between Storefront and Admin API

---

### TC-03: Browse Store & Visual Verification (Browser)
**Type:** Frontend — browser navigation  
**Steps:**
1. Open aware-cosmetics store URL in Cursor Browser
2. Take screenshot of homepage
3. Verify: page loaded, header visible, products visible
4. Click on a product from the collection
5. Take screenshot of product detail page (PDP)
6. Verify: product title, price, and "Add to Cart" button visible

**Pass criteria:** Screenshots show fully loaded pages with product info visible

---

### TC-04: Add to Cart Flow (Browser + Storefront MCP)
**Type:** Frontend + Backend verification  
**Steps:**
1. On the PDP from TC-03, click "Add to Cart"
2. Take screenshot of cart/drawer
3. Verify visually: item appears in cart with correct name
4. Use Storefront MCP `update_cart` to create a cart with the same variant ID
5. Use Storefront MCP `get_cart` to verify: item in cart, quantity = 1, price matches PDP
6. Compare: browser cart price vs API cart price

**Pass criteria:** Cart contains the product, price matches between UI and API

---

### TC-05: Full Checkout Flow (Browser — Stop Before Payment)
**Type:** Frontend only  
**Steps:**
1. From the cart, click "Checkout" or navigate to checkout URL
2. Take screenshot of checkout page
3. Fill in test customer info:
   - Name: QA Test / Agent
   - Email: qa-test@aware-cosmetics.test
   - Address: 123 Test St, Bangkok, 10110, TH
4. Take screenshot after filling shipping info
5. Verify: shipping options displayed, order summary visible
6. **STOP — do not submit payment**

**Pass criteria:** Checkout page loads, shipping info accepted, order summary matches cart

---

## Architecture for POC

```
┌─────────────────────────────────────────────────────────┐
│                    CURSOR IDE (You)                      │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │   Cursor     │  │  Shopify     │  │  Shopify       │  │
│  │   Browser    │  │  Storefront  │  │  Admin         │  │
│  │   MCP        │  │  MCP         │  │  MCP           │  │
│  │              │  │              │  │                │  │
│  │  • navigate  │  │ • search     │  │ • get-products │  │
│  │  • click     │  │ • get_cart   │  │ • get-orders   │  │
│  │  • fill      │  │ • update_cart│  │ • get-customers│  │
│  │  • screenshot│  │ • get_product│  │                │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                 │                  │           │
│         ▼                 ▼                  ▼           │
│  ┌──────────────────────────────────────────────────┐    │
│  │              AI Agent (Claude in Cursor)          │    │
│  │  • Executes test cases step-by-step              │    │
│  │  • Cross-verifies frontend vs backend            │    │
│  │  • Takes screenshots                             │    │
│  │  • Generates pass/fail report                    │    │
│  └──────────────────────┬───────────────────────────┘    │
│                         │                                │
│                         ▼                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │              QA Report (Markdown file)             │    │
│  │  • Test case results with PASS/FAIL               │    │
│  │  • Screenshots path references                    │    │
│  │  • Data comparison tables                         │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                          │
                Future: n8n Cloud triggers this
                via webhook on GitHub push
```

---

## How to Run (Step-by-Step)

### Step 1 — Verify MCP Connections
Ask the agent (me) to:
> "Search for products on aware-cosmetics using Storefront MCP"

This confirms the Storefront MCP is connected to the right store.

### Step 2 — Run TC-01 and TC-02 (Backend Only)
Ask the agent to:
> "Run TC-01 and TC-02 from the AiQA test plan"

This tests MCP queries only — no browser needed. Fast to verify.

### Step 3 — Run TC-03 (Browser Navigation)
Ask the agent to:
> "Open the aware-cosmetics store in the browser and run TC-03"

This tests the Browser MCP. You'll see it navigate and screenshot.

### Step 4 — Run TC-04 (Add to Cart Cross-Verification)
Ask the agent to:
> "Run TC-04 — add a product to cart and verify with Storefront MCP"

This is the first **frontend ↔ backend cross-check**.

### Step 5 — Run TC-05 (Checkout Flow)
Ask the agent to:
> "Run TC-05 — go through checkout with test data, stop before payment"

### Step 6 — Generate Report
Ask the agent to:
> "Generate the AiQA report for all test cases"

The report will be saved as a markdown file in `AiQA/reports/`.

---

## What Success Looks Like

After completing all 5 test cases, you should have:

```
f:\WindowsBackup\shopify\AiQA\
├── docs\POC-PLAN.md           (this file)
├── reports\
│   └── aware-cosmetics-YYYY-MM-DD.md   (generated report)
└── screenshots\
    ├── TC-03-homepage.png
    ├── TC-03-pdp.png
    ├── TC-04-cart.png
    ├── TC-05-checkout.png
    └── TC-05-shipping.png
```

And a report that looks like:

```
# AiQA Report — aware-cosmetics
Date: 2026-03-11

| Test Case | Description               | Status | Notes                              |
|-----------|---------------------------|--------|------------------------------------|
| TC-01     | Product Catalog Search     | ✅ PASS | 12 products found, first: "Serum"  |
| TC-02     | Data Consistency Check     | ✅ PASS | Price matches: ฿1,290 on both APIs |
| TC-03     | Visual Store Verification  | ✅ PASS | 2 screenshots captured             |
| TC-04     | Add to Cart Flow           | ✅ PASS | Cart total: ฿1,290 (UI = API)     |
| TC-05     | Checkout Flow              | ✅ PASS | Shipping info accepted             |

Overall: 5/5 PASSED
```

---

## After POC: What's Next

| Step | Action |
|---|---|
| **Automate triggers** | Connect your Cloud n8n to GitHub webhook → trigger AiQA on code push |
| **Add more test cases** | Discount codes, multi-item cart, mobile viewport, collection filtering |
| **Reuse for other clients** | Same plan, different store URL — just swap the MCP connection |
| **Generate PDF reports** | Use n8n + HTML-to-PDF node for client-facing reports |
| **Record demo video** | Screen-record one full AiQA run for your pitch deck |

---

## Ready?

Just tell me: **"Run TC-01"** and we start the POC.
