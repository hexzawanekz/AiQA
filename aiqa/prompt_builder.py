"""Convert parsed test case + client config into browser-use task prompt."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from aiqa.parser import ParsedTestCase

if TYPE_CHECKING:
    from aiqa.config import ClientConfig


def _expand_url(step: str, base_url: str) -> str:
    """Expand relative paths like /collections/all to full URLs."""
    step_lower = step.lower()
    if "navigate to" in step_lower or "go to" in step_lower:
        match = re.search(r"(navigate to|go to)\s+(/[\w/-]*)", step, re.IGNORECASE)
        if match:
            path = match.group(2)
            if path.startswith("/"):
                return step.replace(match.group(2), f"{base_url}{path}")
        if base_url not in step and "/" in step:
            match = re.search(r"(navigate to|go to)\s+(.+?)(?:\s|$)", step, re.IGNORECASE)
            if match:
                target = match.group(2).strip()
                if target in ("homepage", "store homepage", "the store homepage"):
                    return f"{match.group(1)} {base_url}"
                if target in ("catalog", "collections", "/collections/all"):
                    return f"{match.group(1)} {base_url}/collections/all"
                if target in ("cart", "/cart"):
                    return f"{match.group(1)} {base_url}/cart"
                if target in ("checkout", "/checkout"):
                    return f"{match.group(1)} {base_url}/checkout"
    return step


def build_task_prompt(case: ParsedTestCase, config: "ClientConfig") -> str:
    """
    Build the full browser-use task prompt from a parsed test case and client config.
    """
    lines: list[str] = [
        f"You are an AI QA agent testing a Shopify store. Complete these steps in order for test case {case.id}: {case.name}.",
        "",
        f"1. Navigate to {config.base_url}",
        f"2. If you see a password prompt page (with a password input field), fill in the password field with '{config.store_password}' and click the submit button, then wait for the page to load",
        "3. Wait for the page to fully load",
        "",
    ]

    step_num = 4
    for step in case.steps:
        step_lower = step.lower()
        expanded = _expand_url(step, config.base_url)
        if step_lower.startswith("screenshot:") or step_lower.startswith("take screenshot"):
            label = step.split(":", 1)[-1].strip() if ":" in step else step.replace("take screenshot", "").strip()
            if label:
                lines.append(f"{step_num}. Use 'take_screenshot' with label '{label}' to capture the current state")
            step_num += 1
            continue
        if "screenshot" in step_lower and case.screenshots:
            for label in case.screenshots:
                lines.append(f"{step_num}. Use 'take_screenshot' with label '{label}' to capture the current state")
                step_num += 1
            continue
        lines.append(f"{step_num}. {expanded}")
        step_num += 1

    if case.screenshots and not any("screenshot" in s.lower() for s in case.steps):
        for label in case.screenshots:
            lines.append(f"{step_num}. Use 'take_screenshot' with label '{label}' to capture the current state")
            step_num += 1

    if case.verify_items:
        lines.append("")
        lines.append("Verify the following:")
        for v in case.verify_items:
            lines.append(f"- {v}")

    if case.expected_json_keys:
        keys_str = ", ".join(case.expected_json_keys)
        lines.append("")
        lines.append(f"Return a JSON summary with keys: {keys_str}")

    return "\n".join(lines)
