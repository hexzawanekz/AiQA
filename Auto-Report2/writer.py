"""Write AiQA TestResult to Auto-Report2 SQLite DB. Use from aiqa.reporter or runner."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from db import get_connection, init_schema

if TYPE_CHECKING:
    from aiqa.models import TestResult

# Status mapping: AiQA uses "pass"/"fail"/"skip"/"error" -> DB uses "PASSED"/"FAILED"/"SKIPPED"
STATUS_MAP = {
    "pass": "PASSED",
    "fail": "FAILED",
    "skip": "SKIPPED",
    "error": "FAILED",
}


def write_results(
    results: list["TestResult"],
    project_id: int | None = None,
    environment: str = "",
    app: str = "AiQA",
) -> int:
    """
    Write AiQA test results to the Auto-Report database.
    Returns the run_id for the new run.
    """
    if not results:
        return 0

    now = datetime.now()
    executed_at = now.strftime("%d/%m/%Y, %H:%M.%S")
    run_started = now
    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status in ("fail", "error"))
    skipped = sum(1 for r in results if r.status == "skip")
    duration_sec = sum(r.duration_seconds for r in results)
    execution_time = f"{duration_sec:.1f}s"

    with get_connection() as conn:
        init_schema(conn)
        # Get next run_id
        row = conn.execute("SELECT MAX(run_id) as last FROM reports").fetchone()
        run_id = (row["last"] or 0) + 1

        conn.execute(
            """INSERT INTO reports_summary
               (run_id, passed, failed, skipped, total, environment, app, executedAt, executionTime, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, passed, failed, skipped, total, environment, app, executed_at, execution_time, project_id),
        )

        for row_idx, r in enumerate(results):
            status = STATUS_MAP.get(r.status, "FAILED")
            param = {"code": r.test_id, "name": r.name}
            if r.raw_data:
                param.update(r.raw_data)
            param_str = json.dumps(param)
            error_str = r.error or ""
            duration_str = f"{r.duration_seconds}s"
            screenshot = r.screenshots[0] if r.screenshots else None
            if screenshot and isinstance(screenshot, str):
                # Store relative path from reports dir
                screenshot = screenshot.replace("\\", "/")

            conn.execute(
                """INSERT INTO reports
                   (run_id, row, case_name, param, status, error, duration, screenshot, video, module, environment, app, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    row_idx + 1,
                    r.name,
                    param_str,
                    status,
                    error_str,
                    duration_str,
                    screenshot,
                    None,
                    r.test_id,
                    environment,
                    app,
                    now.isoformat(),
                ),
            )

    return run_id
