# Auto-Report2

Standalone Python web dashboard for viewing and managing automation test results. Integrated with the AiQA Python ecosystem.

**No dependency on Auto-Report (Node.js).** Auto-Report2 is a complete, self-contained fork.

## Features

- **Standalone** — All data and frontend bundled in Auto-Report2
- **API** — REST endpoints for projects, test cases, run history, reports
- **Dashboard** — Summary stats, run history, run details
- **AiQA integration** — `writer.write_results()` to push `TestResult` data into the dashboard DB

## Quick Start

```bash
cd Auto-Report2
pip install -r requirements.txt
python run.py
```

Dashboard: http://localhost:3001

## Project Structure

```
Auto-Report2/
├── server.py          # Flask API server
├── db.py              # SQLite schema and helpers
├── writer.py          # AiQA TestResult → DB writer
├── run.py             # Entry point
├── views/html/        # Dashboard frontend
│   └── index.html
├── data/              # DB, reports (gitignored)
├── requirements.txt
└── README.md
```

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
from Auto_Report2 import write_results
write_results(results, environment=config.name, app="AiQA")
```

## Requirements

- Python 3.10+
- Flask, flask-cors, docxtpl (for Word export)

## Environment

- `PORT` — Server port (default: 3001)
- `BROWSER_USE_WEBUI_PORT` — For /api/webui-status check (default: 7788)
