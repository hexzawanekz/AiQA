"""Client config loader — reads YAML files from the clients/ directory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ClientConfig:
    name: str
    store_domain: str            # e.g. aware-test.myshopify.com
    store_password: str          # password-protected dev store bypass
    storefront_access_token: str # public storefront token
    admin_api_token: str         # private admin token (shpat_...)
    base_url: str                # full URL e.g. https://aware-test.myshopify.com
    test_cases: list[str] = field(default_factory=list)
    slack_webhook_url: str = ""


def load_client(client_name: str, clients_dir: Path | None = None) -> ClientConfig:
    """Load a client config from clients/{client_name}.yaml."""
    if clients_dir is None:
        clients_dir = Path(__file__).parent.parent / "clients"

    config_path = clients_dir / f"{client_name}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Client config not found: {config_path}\n"
            f"Create it by copying clients/aware-test.yaml.example"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    store_domain = data["store_domain"]
    base_url = f"https://{store_domain}"

    return ClientConfig(
        name=client_name,
        store_domain=store_domain,
        store_password=data.get("store_password", ""),
        storefront_access_token=data.get("storefront_access_token", ""),
        admin_api_token=data.get("admin_api_token", ""),
        base_url=base_url,
        test_cases=data.get("test_cases", [
            "catalog_search",
            "data_consistency",
            "visual_browse",
            "add_to_cart",
            "checkout_flow",
        ]),
        slack_webhook_url=data.get("slack_webhook_url", ""),
    )


def load_llm_config() -> dict:
    """Load LLM provider settings from environment."""
    provider = os.getenv("AIQA_LLM", "claude").lower()
    model = os.getenv("AIQA_MODEL", "claude-sonnet-4-5")

    if provider == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        return {"provider": "claude", "model": model, "api_key": api_key}

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")
        return {"provider": "openai", "model": model, "api_key": api_key}

    raise ValueError(f"Unknown AIQA_LLM provider: {provider}. Use 'claude' or 'openai'.")
