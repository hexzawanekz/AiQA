## TC-01: Homepage Loads Correctly
#module: Homepage
- Navigate to the store homepage
- If password prompt appears, enter the store password
- store password is itsaraphap
- Verify: header with store name visible, navigation menu present, hero section loads
- Screenshot: homepage

## TC-02: Product Catalog
#module: Catalog
- Navigate to the store homepage
- If password prompt appears, enter the store password
- store password is itsaraphap
- Navigate to /collections/all
- Verify: page title visible, at least 1 product card with name and price
- Screenshot: catalog

## TC-03: Add to Cart
#module: Cart
- Navigate to the store homepage
- If password prompt appears, enter the store password
- store password is itsaraphap
- From catalog, click any in-stock product
- Click "Add to Cart"
- Verify: cart count increases or cart drawer opens
- Screenshot: cart-state

## TC-04: Checkout Flow (stop before payment)
#module: Checkout
- Navigate to the store homepage
- If password prompt appears, enter the store password
- store password is itsaraphap
- Add any product to cart
- Navigate to /checkout
- Fill: email=qa@test.com, name=QA Agent, address=123 Test St, city=Bangkok, zip=10110, country=Thailand
- Click "Continue to shipping"
- STOP -- do not enter payment
- Verify: checkout page loaded, shipping options visible
- Screenshot: checkout-form, checkout-shipping
