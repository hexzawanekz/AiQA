"""Run project test cases through browser agent. Queue-based, one-by-one."""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Add project root for aiqa import
_BASE = Path(__file__).resolve().parent
if str(_BASE.parent) not in sys.path:
    sys.path.insert(0, str(_BASE.parent))


@dataclass
class ProjectConfig:
    """Minimal config from project for browser agent."""
    name: str
    base_url: str
    store_password: str = ""


def _project_to_config(project: dict) -> ProjectConfig:
    url = (project.get("project_url") or "").strip().rstrip("/")
    name = project.get("project_name") or "project"
    return ProjectConfig(
        name=name,
        base_url=url or "https://example.com",
        store_password=(project.get("project_password") or "").strip(),
    )


def _build_task_from_content(content: str, tc_id: str, title: str, base_url: str, password: str) -> str:
    """Build task prompt from test case markdown content. Uses project base_url for navigation."""
    lines = [
        f"You are an AI QA agent. Complete this test case {tc_id}: {title}.",
        "IMPORTANT: You MUST use the take_screenshot tool for every step that says 'Screenshot:' — do not skip these.",
        "",
        f"1. Navigate to {base_url}",
    ]
    if password:
        lines.append(f"2. If you see a password prompt, fill with '{password}' and submit, then wait for load")
        lines.append("3. Wait for the page to fully load")
        step_num = 4
    else:
        lines.append("2. Wait for the page to fully load")
        step_num = 3

    # Parse bullet steps from content; replace navigate URLs with project base_url
    for line in (content or "").split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            step = line[2:].strip()
            if step.lower().startswith("verify:"):
                lines.append(f"{step_num}. Verify: {step[7:].strip()}")
            elif step.lower().startswith("screenshot:"):
                label = step[10:].strip().split(",")[0].strip() or "screenshot"
                lines.append(f"{step_num}. Use take_screenshot with label '{label}'")
            elif step and not step.lower().startswith("#"):
                # Expand navigate: use project base_url
                step_lower = step.lower()
                if "navigate to" in step_lower or "go to" in step_lower:
                    m = re.search(r"(navigate to|go to)\s+(/[\w/.-]*)", step, re.I)
                    if m and m.group(2).startswith("/") and "http" not in m.group(2):
                        step = f"{m.group(1)} {base_url.rstrip('/')}{m.group(2)}"
                    else:
                        step = f"Navigate to {base_url}"
                lines.append(f"{step_num}. {step}")
            step_num += 1

    return "\n".join(lines)


async def run_project_cases(
    project_id: int,
    get_project_fn: Callable[[int], dict | None],
    get_cases_fn: Callable[[int], list[dict]],
    event_callback: Callable[[str, dict], None],
    max_steps: int = 100,
) -> dict[str, Any]:
    """
    Run all test cases for a project one by one.
    event_callback(event_type, data) for: case_start, case_done, run_complete.
    """
    project = get_project_fn(project_id)
    if not project:
        event_callback("error", {"message": "Project not found"})
        return {"error": "Project not found"}

    cases = get_cases_fn(project_id)
    if not cases:
        event_callback("error", {"message": "No test cases assigned to this project"})
        return {"error": "No test cases"}

    config = _project_to_config(project)
    screenshots_base = _BASE / "data" / "screenshots" / config.name
    screenshots_base.mkdir(parents=True, exist_ok=True)

    try:
        from aiqa.browser_agent import run_task
        from aiqa.config import ClientConfig
    except ImportError as e:
        event_callback("error", {"message": f"Agent dependencies not available: {e}"})
        return {"error": str(e)}

    # Build minimal ClientConfig from project
    base = config.base_url.replace("https://", "").replace("http://", "").strip("/")
    store_domain = base.split("/")[0] if base else "example.com"
    client_config = ClientConfig(
        name=config.name,
        store_domain=store_domain,
        store_password=config.store_password,
        storefront_access_token="",
        admin_api_token="",
        base_url=config.base_url if config.base_url.startswith("http") else f"https://{config.base_url}",
    )

    results = []
    for i, case in enumerate(cases):
        tc_id = case.get("tc_id") or f"TC-{i+1:02d}"
        title = case.get("title") or "Test"
        content = case.get("content") or ""
        module = case.get("module") or ""

        event_callback("case_start", {
            "index": i + 1,
            "total": len(cases),
            "tc_id": tc_id,
            "title": title,
            "module": module,
        })

        task_prompt = _build_task_from_content(
            content, tc_id, title, config.base_url, config.store_password
        )
        screenshots_dir = screenshots_base / tc_id.lower().replace(" ", "_")
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        try:
            result_text, step_logs = await run_task(
                task=task_prompt,
                screenshots_dir=screenshots_dir,
                client_config=client_config,
                storefront=None,
                admin=None,
                max_steps=max_steps,
            )
            screenshots = [str(s.screenshot) for s in step_logs if getattr(s, "screenshot", None)]
            event_callback("case_done", {
                "tc_id": tc_id,
                "title": title,
                "status": "done",
                "result": result_text[:500] if result_text else "",
                "screenshots": len(screenshots),
            })
            results.append({"tc_id": tc_id, "title": title, "module": module, "status": "done", "result": result_text, "screenshots": screenshots})
        except Exception as e:
            event_callback("case_done", {
                "tc_id": tc_id,
                "title": title,
                "status": "error",
                "error": str(e),
            })
            results.append({"tc_id": tc_id, "title": title, "module": module, "status": "error", "error": str(e)})

    # Persist results to database so they appear in History
    try:
        import importlib.util
        from aiqa.models import TestResult
        # Load writer from same dir as agent_runner (robust when run from thread)
        _writer_spec = importlib.util.spec_from_file_location("_writer", _BASE / "writer.py")
        _writer_mod = importlib.util.module_from_spec(_writer_spec)
        _writer_spec.loader.exec_module(_writer_mod)
        write_results = _writer_mod.write_results

        test_results = []
        for r in results:
            status = "pass" if r.get("status") == "done" else "error"
            screenshots = r.get("screenshots") or []
            # Store paths relative to Auto-Report2 root for serving
            rel_screenshots = []
            for p in screenshots:
                try:
                    rel = Path(p).relative_to(_BASE).as_posix()
                    rel_screenshots.append(rel)
                except ValueError:
                    rel_screenshots.append(p.replace("\\", "/"))
            test_results.append(TestResult(
                test_id=r.get("tc_id", ""),
                name=r.get("title", r.get("tc_id", "")),
                status=status,
                duration_seconds=0.0,
                error=r.get("error", ""),
                screenshots=rel_screenshots,
                raw_data={"result": r.get("result", "")[:500]},
            ))
        if test_results:
            run_id = write_results(
                test_results,
                project_id=project_id,
                environment=config.name,
                app="Run Agent",
            )
            event_callback("run_complete", {"total": len(cases), "results": results, "run_id": run_id})
        else:
            event_callback("run_complete", {"total": len(cases), "results": results})
    except Exception as e:
        event_callback("run_complete", {"total": len(cases), "results": results})
        import logging
        logging.getLogger("agent_runner").exception("Could not persist results to DB")

    return {"total": len(cases), "results": results}
