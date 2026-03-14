# Auto-Report2

Python port of [Auto-Report](../Auto-Report). A web-based dashboard for viewing and managing automation test results, integrated with the AiQA Python ecosystem.

## Features

- **API-compatible** with Node.js Auto-Report (same REST endpoints, same SQLite schema)
- **Shared database** with Auto-Report: uses `Auto-Report/reports/database/test-results.db`
- **Shared frontend**: reuses `Auto-Report/views` and `Auto-Report/assets`
- **AiQA integration**: `writer.write_results()` to push `TestResult` data into the dashboard DB

## Quick Start

```bash
# From AiQA directory
cd Auto-Report2
pip install -r requirements.txt
python run.py
```

Or from Auto-Report:

```bash
npm run report:python
```

Dashboard: http://localhost:3001

## AiQA Integration

After running tests, write results to the dashboard:

```python
from Auto_Report2 import write_results
from aiqa.models import TestResult

results: list[TestResult] = [...]  # from runner or run_plan_suite
run_id = write_results(
    results,
    project_id=1,      # optional
    environment="prod",
    app="AiQA",
)
print(f"Results written to run_id={run_id}")
```

Or integrate in `aiqa.reporter`:

```python
# In generate_report() or after run_suite:
from Auto_Report2 import write_results
write_results(results, environment=config.name, app="AiQA")
```

## Requirements

- Python 3.10+
- Flask, flask-cors, python-docx-template (for Word export)

## Project Structure

```
Auto-Report2/
├── server.py      # Flask API server
├── db.py          # SQLite schema and helpers
├── writer.py      # AiQA TestResult → DB writer
├── run.py         # Entry point
├── requirements.txt
└── README.md
```

## Environment

- `PORT` — Server port (default: 3001)
- `AGENTCHATTR_PORT` — For /api/chat-status check (default: 8300)
