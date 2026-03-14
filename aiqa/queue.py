"""TestQueue — pending/claimed/done case distribution for multi-agent runs."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class QueuedCase:
    """A test case in the queue."""

    case_id: str
    name: str
    task_prompt: str
    status: str  # pending, claimed, done, error
    run_id: str
    claimed_by: str = ""
    claimed_at: str = ""
    completed_at: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    screenshots: list[str] = field(default_factory=list)


class TestQueue:
    """
    Queue of test cases for multi-agent distribution.
    Backed by JSONL file for simplicity.
    """

    def __init__(self, data_dir: Path | None = None):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "data"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._queue_path = self.data_dir / "queue.jsonl"
        self._run_meta_path = self.data_dir / "run_meta.json"

    def _load_cases(self) -> list[dict]:
        if not self._queue_path.exists():
            return []
        cases = []
        with open(self._queue_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cases.append(json.loads(line))
        return cases

    def _save_cases(self, cases: list[dict]) -> None:
        with open(self._queue_path, "w", encoding="utf-8") as f:
            for c in cases:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    def create_run(
        self,
        cases: list[QueuedCase],
        client_name: str,
        plan_path: str = "",
    ) -> str:
        """Create a new run with the given cases. Returns run_id."""
        run_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        for c in cases:
            c.run_id = run_id
            c.status = "pending"
            c.claimed_by = ""
            c.claimed_at = ""
            c.completed_at = ""
            c.result = {}
            c.error = ""
            c.screenshots = []

        records = [asdict(c) for c in cases]
        self._save_cases(records)

        meta = {
            "run_id": run_id,
            "client_name": client_name,
            "plan_path": plan_path,
            "created_at": now,
            "total": len(cases),
            "pending": len(cases),
            "claimed": 0,
            "done": 0,
            "error": 0,
        }
        meta_path = self.data_dir / f"run_{run_id}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        return run_id

    def claim_next(self, run_id: str, agent_id: str) -> QueuedCase | None:
        """Claim the next pending case for the given run. Returns None if none available."""
        cases = self._load_cases()
        run_cases = [c for c in cases if c.get("run_id") == run_id and c.get("status") == "pending"]
        if not run_cases:
            return None

        case = run_cases[0]
        case["status"] = "claimed"
        case["claimed_by"] = agent_id
        case["claimed_at"] = datetime.now().isoformat()

        for i, c in enumerate(cases):
            if c.get("case_id") == case["case_id"] and c.get("run_id") == run_id:
                cases[i] = case
                break
        self._save_cases(cases)
        self._update_run_meta(run_id, cases)
        return QueuedCase(**case)

    def complete(
        self,
        run_id: str,
        case_id: str,
        result: dict[str, Any],
        screenshots: list[str],
        error: str = "",
    ) -> None:
        """Mark a case as done with result."""
        cases = self._load_cases()
        for c in cases:
            if c.get("run_id") == run_id and c.get("case_id") == case_id:
                c["status"] = "error" if error else "done"
                c["completed_at"] = datetime.now().isoformat()
                c["result"] = result
                c["screenshots"] = screenshots
                c["error"] = error
                break
        self._save_cases(cases)
        self._update_run_meta(run_id, cases)

    def release_claimed(self, run_id: str, case_id: str) -> None:
        """Release a claimed case back to pending (e.g. agent crashed)."""
        cases = self._load_cases()
        for c in cases:
            if c.get("run_id") == run_id and c.get("case_id") == case_id and c.get("status") == "claimed":
                c["status"] = "pending"
                c["claimed_by"] = ""
                c["claimed_at"] = ""
                break
        self._save_cases(cases)
        self._update_run_meta(run_id, cases)

    def _update_run_meta(self, run_id: str, cases: list[dict]) -> None:
        run_cases = [c for c in cases if c.get("run_id") == run_id]
        meta_path = self.data_dir / f"run_{run_id}.json"
        if not meta_path.exists():
            return
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["pending"] = sum(1 for c in run_cases if c.get("status") == "pending")
        meta["claimed"] = sum(1 for c in run_cases if c.get("status") == "claimed")
        meta["done"] = sum(1 for c in run_cases if c.get("status") == "done")
        meta["error"] = sum(1 for c in run_cases if c.get("status") == "error")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def get_run_status(self, run_id: str) -> dict[str, Any]:
        """Get status of a run."""
        meta_path = self.data_dir / f"run_{run_id}.json"
        if not meta_path.exists():
            return {}
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_run_cases(self, run_id: str) -> list[QueuedCase]:
        """Get all cases for a run."""
        cases = self._load_cases()
        run_cases = [c for c in cases if c.get("run_id") == run_id]
        return [QueuedCase(**c) for c in run_cases]
