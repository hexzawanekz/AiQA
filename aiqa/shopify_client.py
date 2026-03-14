"""Shopify API clients — Storefront and Admin GraphQL via httpx."""

from __future__ import annotations

import httpx
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProductVariant:
    variant_id: str
    title: str
    price: str
    currency: str
    available: bool


@dataclass
class Product:
    product_id: str
    title: str
    price_min: str
    price_max: str
    currency: str
    variants: list[ProductVariant] = field(default_factory=list)
    product_type: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class CartLine:
    line_id: str
    title: str
    quantity: int
    price: str
    currency: str


@dataclass
class Cart:
    cart_id: str
    total_amount: str
    currency: str
    checkout_url: str
    lines: list[CartLine] = field(default_factory=list)
    discount_codes: list[str] = field(default_factory=list)


@dataclass
class Order:
    order_id: str
    name: str
    email: str
    total_price: str
    currency: str
    financial_status: str
    fulfillment_status: str | None
    line_items: list[dict] = field(default_factory=list)
    discount_codes: list[str] = field(default_factory=list)


class ShopifyStorefrontClient:
    """GraphQL client for the Shopify Storefront API (public-facing)."""

    API_VERSION = "2025-01"

    def __init__(self, store_domain: str, storefront_access_token: str):
        self.store_domain = store_domain.rstrip("/")
        self.token = storefront_access_token
        self.endpoint = f"https://{self.store_domain}/api/{self.API_VERSION}/graphql.json"
        self._client = httpx.AsyncClient(
            headers={
                "X-Shopify-Storefront-Access-Token": self.token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def _query(self, gql: str, variables: dict | None = None) -> dict:
        payload: dict[str, Any] = {"query": gql}
        if variables:
            payload["variables"] = variables
        response = await self._client.post(self.endpoint, json=payload)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise ValueError(f"Storefront API errors: {data['errors']}")
        return data.get("data", {})

    async def search_products(self, query: str, limit: int = 10) -> list[Product]:
        gql = """
        query SearchProducts($query: String!, $first: Int!) {
          search(query: $query, first: $first, types: PRODUCT) {
            edges {
              node {
                ... on Product {
                  id
                  title
                  productType
                  tags
                  priceRange {
                    minVariantPrice { amount currencyCode }
                    maxVariantPrice { amount currencyCode }
                  }
                  variants(first: 5) {
                    edges {
                      node {
                        id
                        title
                        price { amount currencyCode }
                        availableForSale
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await self._query(gql, {"query": query, "first": limit})
        products = []
        for edge in data.get("search", {}).get("edges", []):
            node = edge["node"]
            price_range = node.get("priceRange", {})
            min_price = price_range.get("minVariantPrice", {})
            max_price = price_range.get("maxVariantPrice", {})
            variants = [
                ProductVariant(
                    variant_id=v["node"]["id"],
                    title=v["node"]["title"],
                    price=v["node"]["price"]["amount"],
                    currency=v["node"]["price"]["currencyCode"],
                    available=v["node"]["availableForSale"],
                )
                for v in node.get("variants", {}).get("edges", [])
            ]
            products.append(
                Product(
                    product_id=node["id"],
                    title=node["title"],
                    price_min=min_price.get("amount", "0"),
                    price_max=max_price.get("amount", "0"),
                    currency=min_price.get("currencyCode", ""),
                    product_type=node.get("productType", ""),
                    tags=node.get("tags", []),
                    variants=variants,
                )
            )
        return products

    async def create_cart(self, variant_id: str, quantity: int = 1) -> Cart:
        gql = """
        mutation CartCreate($variantId: ID!, $quantity: Int!) {
          cartCreate(input: {
            lines: [{ merchandiseId: $variantId, quantity: $quantity }]
          }) {
            cart {
              id
              checkoutUrl
              cost {
                totalAmount { amount currencyCode }
              }
              lines(first: 10) {
                edges {
                  node {
                    id
                    quantity
                    merchandise {
                      ... on ProductVariant {
                        title
                        price { amount currencyCode }
                        product { title }
                      }
                    }
                  }
                }
              }
            }
            userErrors { field message }
          }
        }
        """
        data = await self._query(gql, {"variantId": variant_id, "quantity": quantity})
        cart_data = data.get("cartCreate", {})
        user_errors = cart_data.get("userErrors", [])
        if user_errors:
            raise ValueError(f"Cart creation errors: {user_errors}")
        return self._parse_cart(cart_data["cart"])

    async def get_cart(self, cart_id: str) -> Cart:
        gql = """
        query GetCart($cartId: ID!) {
          cart(id: $cartId) {
            id
            checkoutUrl
            discountCodes { code applicable }
            cost {
              totalAmount { amount currencyCode }
            }
            lines(first: 10) {
              edges {
                node {
                  id
                  quantity
                  merchandise {
                    ... on ProductVariant {
                      title
                      price { amount currencyCode }
                      product { title }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await self._query(gql, {"cartId": cart_id})
        return self._parse_cart(data["cart"])

    async def apply_discount(self, cart_id: str, discount_code: str) -> Cart:
        gql = """
        mutation CartDiscountCodesUpdate($cartId: ID!, $discountCodes: [String!]!) {
          cartDiscountCodesUpdate(cartId: $cartId, discountCodes: $discountCodes) {
            cart {
              id
              checkoutUrl
              discountCodes { code applicable }
              cost {
                totalAmount { amount currencyCode }
              }
              lines(first: 10) {
                edges {
                  node {
                    id
                    quantity
                    merchandise {
                      ... on ProductVariant {
                        title
                        price { amount currencyCode }
                        product { title }
                      }
                    }
                  }
                }
              }
            }
            userErrors { field message }
          }
        }
        """
        data = await self._query(gql, {"cartId": cart_id, "discountCodes": [discount_code]})
        result = data.get("cartDiscountCodesUpdate", {})
        if result.get("userErrors"):
            raise ValueError(f"Discount errors: {result['userErrors']}")
        return self._parse_cart(result["cart"])

    def _parse_cart(self, cart: dict) -> Cart:
        lines = []
        for edge in cart.get("lines", {}).get("edges", []):
            node = edge["node"]
            merch = node.get("merchandise", {})
            product_title = merch.get("product", {}).get("title", "")
            variant_title = merch.get("title", "")
            label = f"{product_title} — {variant_title}" if variant_title != "Default Title" else product_title
            lines.append(CartLine(
                line_id=node["id"],
                title=label,
                quantity=node["quantity"],
                price=merch.get("price", {}).get("amount", "0"),
                currency=merch.get("price", {}).get("currencyCode", ""),
            ))
        discount_codes = [d["code"] for d in cart.get("discountCodes", [])]
        cost = cart.get("cost", {}).get("totalAmount", {})
        return Cart(
            cart_id=cart["id"],
            total_amount=cost.get("amount", "0"),
            currency=cost.get("currencyCode", ""),
            checkout_url=cart.get("checkoutUrl", ""),
            lines=lines,
            discount_codes=discount_codes,
        )

    async def close(self):
        await self._client.aclose()


class ShopifyAdminClient:
    """GraphQL client for the Shopify Admin API (private)."""

    API_VERSION = "2025-01"

    def __init__(self, store_domain: str, admin_api_token: str):
        self.store_domain = store_domain.rstrip("/")
        self.token = admin_api_token
        self.endpoint = f"https://{self.store_domain}/admin/api/{self.API_VERSION}/graphql.json"
        self._client = httpx.AsyncClient(
            headers={
                "X-Shopify-Access-Token": self.token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def _query(self, gql: str, variables: dict | None = None) -> dict:
        payload: dict[str, Any] = {"query": gql}
        if variables:
            payload["variables"] = variables
        response = await self._client.post(self.endpoint, json=payload)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise ValueError(f"Admin API errors: {data['errors']}")
        return data.get("data", {})

    async def get_products(self, search_title: str = "", limit: int = 10) -> list[dict]:
        query_str = f'title:"{search_title}"' if search_title else ""
        gql = """
        query GetProducts($first: Int!, $query: String) {
          products(first: $first, query: $query) {
            edges {
              node {
                id
                title
                status
                totalInventory
                priceRangeV2 {
                  minVariantPrice { amount currencyCode }
                  maxVariantPrice { amount currencyCode }
                }
                variants(first: 5) {
                  edges {
                    node {
                      id
                      title
                      price
                      inventoryQuantity
                      sku
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await self._query(gql, {"first": limit, "query": query_str})
        return [e["node"] for e in data.get("products", {}).get("edges", [])]

    async def get_orders(self, status: str = "any", limit: int = 10) -> list[dict]:
        query_str = f"status:{status}" if status != "any" else ""
        gql = """
        query GetOrders($first: Int!, $query: String) {
          orders(first: $first, query: $query, sortKey: CREATED_AT, reverse: true) {
            edges {
              node {
                id
                name
                email
                totalPriceSet { shopMoney { amount currencyCode } }
                financialStatus
                fulfillmentStatus
                discountCodes
                lineItems(first: 5) {
                  edges {
                    node {
                      title
                      quantity
                      originalTotalSet { shopMoney { amount currencyCode } }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await self._query(gql, {"first": limit, "query": query_str})
        return [e["node"] for e in data.get("orders", {}).get("edges", [])]

    async def get_order_by_id(self, order_id: str) -> dict | None:
        gql = """
        query GetOrder($id: ID!) {
          order(id: $id) {
            id
            name
            email
            totalPriceSet { shopMoney { amount currencyCode } }
            financialStatus
            fulfillmentStatus
            discountCodes
            lineItems(first: 10) {
              edges {
                node {
                  title
                  quantity
                  originalTotalSet { shopMoney { amount currencyCode } }
                }
              }
            }
          }
        }
        """
        data = await self._query(gql, {"id": order_id})
        return data.get("order")

    async def get_latest_order_for_email(self, email: str) -> dict | None:
        gql = """
        query GetOrdersByEmail($query: String!) {
          orders(first: 1, query: $query, sortKey: CREATED_AT, reverse: true) {
            edges {
              node {
                id
                name
                email
                totalPriceSet { shopMoney { amount currencyCode } }
                financialStatus
                fulfillmentStatus
                discountCodes
                lineItems(first: 5) {
                  edges {
                    node {
                      title
                      quantity
                      originalTotalSet { shopMoney { amount currencyCode } }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await self._query(gql, {"query": f"email:{email}"})
        edges = data.get("orders", {}).get("edges", [])
        return edges[0]["node"] if edges else None

    async def close(self):
        await self._client.aclose()
