"""Parse test plan files (Markdown or CSV) into structured test case objects."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedTestCase:
    """A single test case parsed from a test plan file."""

    id: str
    name: str
    steps: list[str] = field(default_factory=list)
    verify_items: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    expected_json_keys: list[str] = field(default_factory=list)
    raw_text: str = ""


def _parse_md_section(content: str) -> ParsedTestCase | None:
    """Parse a single ## TC-XX: Name section from Markdown."""
    content = content.strip()
    if not content:
        return None

    lines = content.split("\n")
    header = lines[0].strip()
    match = re.match(r"^##\s*(TC-\d+)\s*:\s*(.+)$", header, re.IGNORECASE)
    if not match:
        match = re.match(r"^##\s*(.+?)\s*-\s*(.+)$", header)
        if match:
            tc_id = match.group(1).strip().upper().replace(" ", "-")
            name = match.group(2).strip()
        else:
            return None
    else:
        tc_id = match.group(1).upper()
        name = match.group(2).strip()

    steps: list[str] = []
    verify_items: list[str] = []
    screenshots: list[str] = []
    expected_json_keys: list[str] = []

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if line.startswith("- "):
            step = line[2:].strip()
            if step.lower().startswith("verify:"):
                verify_items.append(step[7:].strip())
            elif step.lower().startswith("screenshot:"):
                prefix_len = len("screenshot:")
                parts = step[prefix_len:].strip().split(",")
                screenshots.extend(p.strip() for p in parts if p.strip())
            elif step.lower().startswith("return json") or "json summary" in step.lower():
                keys_match = re.search(r"keys?\s*:\s*([^.]+)", step, re.IGNORECASE)
                if keys_match:
                    keys_str = keys_match.group(1)
                    for k in re.findall(r"[\w_]+", keys_str):
                        if k and k not in ("true", "false", "bool", "string", "int"):
                            expected_json_keys.append(k)
            else:
                steps.append(step)
        elif line.startswith("* "):
            step = line[2:].strip()
            steps.append(step)

    return ParsedTestCase(
        id=tc_id,
        name=name,
        steps=steps,
        verify_items=verify_items,
        screenshots=screenshots,
        expected_json_keys=expected_json_keys,
        raw_text=content,
    )


def parse_markdown(path: Path | str) -> list[ParsedTestCase]:
    """
    Parse a Markdown test plan file.
    Sections are identified by ## TC-XX: Name or ## Name - Description.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    # Split by ## headers
    sections = re.split(r"\n(?=##\s)", text, flags=re.MULTILINE)

    cases: list[ParsedTestCase] = []
    for section in sections:
        section = section.strip()
        if not section or section.startswith("# "):
            continue
        case = _parse_md_section(section)
        if case:
            cases.append(case)

    return cases


def parse_csv(path: Path | str) -> list[ParsedTestCase]:
    """
    Parse a CSV test plan file.
    Expected columns: id, name, steps, expected, screenshots (all optional except id/name).
    """
    path = Path(path)
    cases: list[ParsedTestCase] = []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tc_id = (row.get("id") or row.get("ID") or "").strip()
            name = (row.get("name") or row.get("Name") or "").strip()
            if not tc_id or not name:
                continue

            steps_str = row.get("steps") or row.get("Steps") or ""
            steps = [s.strip() for s in steps_str.split(";") if s.strip()] if steps_str else []

            expected_str = row.get("expected") or row.get("Expected") or ""
            verify_items = [s.strip() for s in expected_str.split(";") if s.strip()] if expected_str else []

            screenshots_str = row.get("screenshots") or row.get("Screenshots") or ""
            screenshots = [s.strip() for s in screenshots_str.split(",") if s.strip()] if screenshots_str else []

            cases.append(
                ParsedTestCase(
                    id=tc_id,
                    name=name,
                    steps=steps,
                    verify_items=verify_items,
                    screenshots=screenshots,
                    raw_text=f"{tc_id}: {name}",
                )
            )

    return cases


def parse_test_plan(path: Path | str) -> list[ParsedTestCase]:
    """
    Parse a test plan file. Auto-detects format by extension.
    - .md, .markdown -> Markdown
    - .csv -> CSV
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Test plan not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        return parse_markdown(path)
    if suffix == ".csv":
        return parse_csv(path)
    raise ValueError(f"Unsupported test plan format: {suffix}. Use .md or .csv")
