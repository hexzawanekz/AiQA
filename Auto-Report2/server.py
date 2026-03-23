"""Auto-Report2 - Python Flask server. API-compatible with Node.js Auto-Report."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory, Response
from flask_cors import CORS
from werkzeug.routing import BaseConverter

from db import DB_PATH, get_connection, init_schema, row_to_dict


class NoApiPathConverter(BaseConverter):
    """Path converter that excludes paths starting with 'api/' so API routes take precedence."""

    regex = r"(?!api/).+"


# Auto-Report2 standalone paths (no dependency on Auto-Report)
_BASE = Path(__file__).resolve().parent
PROJECT_ROOT = _BASE
VIEWS_PATH = _BASE / "views" / "html"
REPORTS_DIR = _BASE / "data" / "reports"
EXPORTS_DIR = REPORTS_DIR / "exports"
TEMPLATE_PATH = _BASE / "templates" / "template_temp.docx"

app = Flask(__name__, static_folder=str(PROJECT_ROOT), static_url_path="/static")
app.url_map.converters["no_api_path"] = NoApiPathConverter
CORS(app)

# Ensure exports dir exists
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# --- Helpers ---


def parse_test_cases_from_md(content: str) -> list[dict]:
    """Parse .md content into test case blocks by ## TC-XX: Title."""
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = []
    parts = re.split(r"(?=^##\s)", normalized, flags=re.MULTILINE)
    now = datetime.utcnow().isoformat() + "Z"
    for part in parts:
        trimmed = part.strip()
        if not trimmed:
            continue
        # Match ## TC-XX: Title (case-insensitive TC, optional space before colon)
        match = re.match(r"^##\s*(TC-\d+)\s*:\s*(.+?)(?:\n|$)", trimmed, re.IGNORECASE)
        if match:
            tc_id = match.group(1).upper()
            module_match = re.search(r"^#module:\s*(.+?)(?:\n|$)", trimmed, re.MULTILINE)
            module = module_match.group(1).strip() if module_match else None
            blocks.append({
                "tc_id": tc_id,
                "title": match.group(2).strip(),
                "module": module,
                "content": trimmed,
                "created_at": now,
            })
    return blocks


def get_month_name(month: str) -> str:
    months = {
        "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun",
        "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
    }
    return months.get(month, month)


def parse_safe_json(s: str | None) -> dict:
    if s is None:
        return {}
    try:
        return json.loads(s) if isinstance(s, str) else s
    except (json.JSONDecodeError, TypeError):
        return {}


def extract_code_from_param(param_str: str | None) -> str:
    param = parse_safe_json(param_str)
    return param.get("code", "-")


def get_test_detail_by_run_id(run_id: int) -> dict:
    """Fetch summary and report rows for a run_id."""
    with get_connection() as conn:
        summary_row = conn.execute(
            """
            SELECT passed, failed, skipped, total, environment, executedAt, executionTime, app
            FROM reports_summary WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        rows_raw = conn.execute(
            """
            SELECT row, case_name, param, status, error, screenshot, video, module, environment, duration
            FROM reports WHERE run_id = ? ORDER BY row ASC
            """,
            (run_id,),
        ).fetchall()

    if not summary_row:
        return {"summary": None, "rows": []}

    rows_map: dict[int, dict] = {}
    for r in rows_raw:
        row_idx = r["row"]
        error = (r["error"] or "").replace("Error: ", "")
        if row_idx not in rows_map:
            rows_map[row_idx] = {
                "row": row_idx,
                "video": r["video"] or None,
                "cases": [],
                "environment": r["environment"],
            }
        rows_map[row_idx]["cases"].append({
            "code": extract_code_from_param(r["param"]),
            "name": r["case_name"],
            "status": r["status"],
            "error": error or "-",
            "param": parse_safe_json(r["param"]),
            "duration": r["duration"],
            "screenshot": r["screenshot"] or None,
            "isPassed": r["status"] == "PASSED",
            "isFailed": r["status"] == "FAILED",
            "isSkipped": r["status"] == "SKIPPED",
            "isError": r["error"] or None,
        })

    return {
        "summary": dict(summary_row),
        "rows": list(rows_map.values()),
    }


# --- Backfill test_cases from existing uploads ---
def _backfill_test_cases(conn) -> None:
    uploads = conn.execute("""
        SELECT u.id, u.content FROM test_case_uploads u
        LEFT JOIN test_cases tc ON tc.upload_id = u.id
        WHERE tc.id IS NULL AND u.content IS NOT NULL
    """).fetchall()
    if uploads:
        for u in uploads:
            blocks = parse_test_cases_from_md(u["content"])
            for b in blocks:
                conn.execute(
                    "INSERT INTO test_cases (upload_id, tc_id, title, module, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (u["id"], b["tc_id"], b["title"], b["module"] or None, b["content"], b["created_at"]),
                )
        print(f"Backfilled test_cases for {len(uploads)} upload(s)")


# --- Projects API ---


@app.route("/api/projects", methods=["GET"])
def api_projects_list():
    with get_connection() as conn:
        init_schema(conn)
        rows = conn.execute("""
            SELECT p.id, p.project_name, p.project_url, p.project_password, p.project_story, p.environment,
                   p.created_at, p.updated_at,
                   (SELECT COUNT(*) FROM project_testcases pt WHERE pt.project_id = p.id) as test_case_count,
                   (SELECT COUNT(*) FROM test_cases tc
                    JOIN project_testcases pt ON tc.upload_id = pt.test_case_id
                    WHERE pt.project_id = p.id) as parsed_case_count
            FROM projects p ORDER BY p.updated_at DESC
        """).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/projects/<int:pid>", methods=["GET"])
def api_project_get(pid):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_name, project_url, project_password, project_story, environment, created_at, updated_at FROM projects WHERE id = ?",
            (pid,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Project not found"}), 404
        assigned = conn.execute(
            "SELECT test_case_id as id FROM project_testcases WHERE project_id = ?",
            (pid,),
        ).fetchall()
        upload_ids = [r["id"] for r in assigned]
        parsed_count = 0
        if upload_ids:
            ph = ",".join("?" * len(upload_ids))
            parsed_count = conn.execute(
                f"SELECT COUNT(*) as c FROM test_cases WHERE upload_id IN ({ph})",
                upload_ids,
            ).fetchone()["c"]
    data = row_to_dict(row)
    data["assigned_test_case_ids"] = upload_ids
    data["parsed_case_count"] = parsed_count
    return jsonify(data)


@app.route("/api/projects", methods=["POST"])
def api_project_create():
    body = request.get_json() or {}
    name = body.get("project_name", "").strip()
    url = body.get("project_url", "").strip()
    if not name or not url:
        return jsonify({"error": "Project name and URL are required"}), 400
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        init_schema(conn)
        cur = conn.execute(
            """INSERT INTO projects (project_name, project_url, project_password, project_story, environment, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                url,
                (body.get("project_password") or "").strip() or None,
                (body.get("project_story") or "").strip() or None,
                (body.get("environment") or "").strip() or None,
                now,
                now,
            ),
        )
        new_id = cur.lastrowid
        ids = body.get("test_case_ids") or []
        if not isinstance(ids, list):
            ids = [ids] if ids else []
        for tid in ids:
            try:
                tid_int = int(tid)
                conn.execute("INSERT OR IGNORE INTO project_testcases (project_id, test_case_id) VALUES (?, ?)", (new_id, tid_int))
            except (ValueError, TypeError):
                pass
    return jsonify({
        "id": new_id,
        "project_name": name,
        "project_url": url,
        "project_password": (body.get("project_password") or "").strip() or None,
        "project_story": (body.get("project_story") or "").strip() or None,
        "environment": (body.get("environment") or "").strip() or None,
        "created_at": now,
        "updated_at": now,
    }), 201


@app.route("/api/projects/<int:pid>", methods=["PUT"])
def api_project_update(pid):
    body = request.get_json() or {}
    name = body.get("project_name", "").strip()
    url = body.get("project_url", "").strip()
    if not name or not url:
        return jsonify({"error": "Project name and URL are required"}), 400
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (pid,)).fetchone()
        if not row:
            return jsonify({"error": "Project not found"}), 404
        now = datetime.utcnow().isoformat() + "Z"
        conn.execute(
            """UPDATE projects SET project_name=?, project_url=?, project_password=?, project_story=?, environment=?, updated_at=?
               WHERE id=?""",
            (
                name,
                url,
                (body.get("project_password") or "").strip() or None,
                (body.get("project_story") or "").strip() or None,
                (body.get("environment") or "").strip() or None,
                now,
                pid,
            ),
        )
        conn.execute("DELETE FROM project_testcases WHERE project_id = ?", (pid,))
        ids = body.get("test_case_ids") or []
        if not isinstance(ids, list):
            ids = [ids] if ids else []
        for tid in ids:
            try:
                tid_int = int(tid)
                conn.execute("INSERT OR IGNORE INTO project_testcases (project_id, test_case_id) VALUES (?, ?)", (pid, tid_int))
            except (ValueError, TypeError):
                pass
    return jsonify({"id": pid, "updated_at": now})


@app.route("/api/projects/<int:pid>", methods=["DELETE"])
def api_project_delete(pid):
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
        if cur.rowcount == 0:
            return jsonify({"error": "Project not found"}), 404
    return jsonify({"message": "Deleted"})


# --- Test Case Upload API ---


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"ok": True, "testcases": True})


@app.route("/api/testcases/upload", methods=["POST"])
def api_testcases_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify({"error": "No file uploaded"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext != ".md":
        return jsonify({"error": "Only .md files are allowed"}), 400
    try:
        content = f.read().decode("utf-8-sig").lstrip("\ufeff")
        filename = f.filename
        size = len(content.encode("utf-8"))
        uploaded_at = datetime.utcnow().isoformat() + "Z"
        with get_connection() as conn:
            init_schema(conn)
            cur = conn.execute(
                "INSERT INTO test_case_uploads (filename, file_type, size, content, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                (filename, ext, size, content, uploaded_at),
            )
            upload_id = cur.lastrowid
            blocks = parse_test_cases_from_md(content)
            for b in blocks:
                conn.execute(
                    "INSERT INTO test_cases (upload_id, tc_id, title, module, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (upload_id, b["tc_id"], b["title"], b["module"] or None, b["content"], b["created_at"]),
                )
        return jsonify({
            "id": upload_id,
            "filename": filename,
            "file_type": ext,
            "size": size,
            "uploaded_at": uploaded_at,
            "parsed_count": len(blocks),
        }), 201
    except Exception as e:
        return jsonify({"error": "Failed to save test case"}), 500


@app.route("/api/testcases", methods=["GET"])
def api_testcases_list():
    with get_connection() as conn:
        init_schema(conn)
        rows = conn.execute(
            "SELECT id, filename, file_type, size, uploaded_at FROM test_case_uploads ORDER BY uploaded_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            count = conn.execute(
                "SELECT COUNT(*) as c FROM test_cases WHERE upload_id = ?", (r["id"],)
            ).fetchone()
            d["case_count"] = count["c"] if count else 0
            result.append(d)
    return jsonify(result)


@app.route("/api/testcases/<int:tid>/parsed", methods=["GET"])
def api_testcase_parsed(tid):
    with get_connection() as conn:
        upload = conn.execute("SELECT id, content FROM test_case_uploads WHERE id = ?", (tid,)).fetchone()
        if not upload:
            return jsonify({"error": "Upload not found"}), 404
        rows = conn.execute(
            "SELECT tc_id, title, module FROM test_cases WHERE upload_id = ? ORDER BY id ASC",
            (tid,),
        ).fetchall()
        # If no parsed cases, try backfill from upload content
        if not rows and upload["content"]:
            blocks = parse_test_cases_from_md(upload["content"])
            for b in blocks:
                conn.execute(
                    "INSERT INTO test_cases (upload_id, tc_id, title, module, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, b["tc_id"], b["title"], b["module"] or None, b["content"], b["created_at"]),
                )
            rows = conn.execute(
                "SELECT tc_id, title, module FROM test_cases WHERE upload_id = ? ORDER BY id ASC",
                (tid,),
            ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/testcases/<int:tid>", methods=["GET"])
def api_testcase_get(tid):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, filename, file_type, size, content, uploaded_at FROM test_case_uploads WHERE id = ?",
            (tid,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Test case not found"}), 404
    if request.args.get("download") == "true":
        from flask import Response
        return Response(row["content"], mimetype="text/plain; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="{row["filename"]}"',
        })
    return jsonify(row_to_dict(row))


@app.route("/api/testcases/<int:tid>", methods=["PUT"])
def api_testcase_update(tid):
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify({"error": "No file uploaded"}), 400
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM test_case_uploads WHERE id = ?", (tid,)).fetchone()
        if not existing:
            return jsonify({"error": "Test case not found"}), 404
    try:
        content = f.read().decode("utf-8-sig").lstrip("\ufeff")
        filename = f.filename
        size = len(content.encode("utf-8"))
        uploaded_at = datetime.utcnow().isoformat() + "Z"
        with get_connection() as conn:
            conn.execute(
                "UPDATE test_case_uploads SET filename=?, file_type=?, size=?, content=?, uploaded_at=? WHERE id=?",
                (filename, Path(filename).suffix.lower(), size, content, uploaded_at, tid),
            )
            conn.execute("DELETE FROM test_cases WHERE upload_id = ?", (tid,))
            blocks = parse_test_cases_from_md(content)
            for b in blocks:
                conn.execute(
                    "INSERT INTO test_cases (upload_id, tc_id, title, module, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, b["tc_id"], b["title"], b["module"] or None, b["content"], b["created_at"]),
                )
        return jsonify({
            "id": tid,
            "filename": filename,
            "file_type": Path(filename).suffix.lower(),
            "size": size,
            "uploaded_at": uploaded_at,
            "parsed_count": len(blocks),
        })
    except Exception:
        return jsonify({"error": "Failed to update test case"}), 500


@app.route("/api/testcases/<int:tid>", methods=["DELETE"])
def api_testcase_delete(tid):
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM test_case_uploads WHERE id = ?", (tid,))
        if cur.rowcount == 0:
            return jsonify({"error": "Test case not found"}), 404
    return jsonify({"message": "Deleted"})


# --- Summary & History API ---


@app.route("/api/summary", methods=["GET"])
def api_summary():
    project_id = request.args.get("project_id")
    where = ""
    params = []
    if project_id:
        where = " WHERE project_id = ?"
        params.append(project_id)
    with get_connection() as conn:
        init_schema(conn)
        total_cases = 0
        if project_id:
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM test_cases tc
                JOIN project_testcases pt ON tc.upload_id = pt.test_case_id
                WHERE pt.project_id = ?
            """, (project_id,)).fetchone()
            total_cases = row["cnt"] or 0
        passed = conn.execute(f"SELECT COALESCE(SUM(passed), 0) as passed FROM reports_summary{where}", params).fetchone()["passed"] or 0
        failed = conn.execute(f"SELECT COALESCE(SUM(failed), 0) as failed FROM reports_summary{where}", params).fetchone()["failed"] or 0
        skipped = conn.execute(f"SELECT COALESCE(SUM(skipped), 0) as skipped FROM reports_summary{where}", params).fetchone()["skipped"] or 0
    return jsonify({"total_cases": total_cases, "passed": passed, "failed": failed, "skipped": skipped})


@app.route("/api/last-run-summary", methods=["GET"])
def api_last_run_summary():
    project_id = request.args.get("project_id")
    where = ""
    params = []
    if project_id:
        where = " WHERE project_id = ?"
        params.append(project_id)
    with get_connection() as conn:
        init_schema(conn)
        row = conn.execute(f"SELECT MAX(run_id) as run_id FROM reports_summary{where}", params).fetchone()
        if not row or row["run_id"] is None:
            return jsonify({"run_id": None, "environment": "-", "date": "-", "duration": "-"})
        run_id = row["run_id"]
        summary = conn.execute(
            "SELECT executedAt as timestamp, executionTime as duration, environment FROM reports_summary WHERE run_id = ? LIMIT 1",
            (run_id,),
        ).fetchone()
    return jsonify({
        "run_id": run_id,
        "environment": summary["environment"] or "-",
        "date": summary["timestamp"] or "-",
        "duration": summary["duration"] or "-",
    })


@app.route("/api/total-cases-by-module", methods=["GET"])
def api_total_cases_by_module():
    project_id = request.args.get("project_id")
    rows = []
    with get_connection() as conn:
        init_schema(conn)
        if project_id:
            rows = conn.execute("""
                SELECT r.module, COUNT(*) as total FROM reports r
                JOIN reports_summary rs ON r.run_id = rs.run_id
                WHERE rs.project_id = ? AND r.module IS NOT NULL AND r.module != ''
                GROUP BY r.module
            """, (project_id,)).fetchall()
            if not rows:
                rows = conn.execute("""
                    SELECT COALESCE(tc.module, 'Uncategorized') as module, COUNT(*) as total
                    FROM test_cases tc
                    JOIN project_testcases pt ON tc.upload_id = pt.test_case_id
                    WHERE pt.project_id = ?
                    GROUP BY COALESCE(tc.module, 'Uncategorized')
                """, (project_id,)).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/cases-status-by-module", methods=["GET"])
def api_cases_status_by_module():
    project_id = request.args.get("project_id")
    rows = []
    with get_connection() as conn:
        init_schema(conn)
        if project_id:
            rows = conn.execute("""
                SELECT r.module,
                    SUM(CASE WHEN r.status = 'PASSED' THEN 1 ELSE 0 END) AS passed,
                    SUM(CASE WHEN r.status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN r.status = 'SKIPPED' THEN 1 ELSE 0 END) AS skipped
                FROM reports r
                JOIN reports_summary rs ON r.run_id = rs.run_id
                WHERE rs.project_id = ? AND r.module IS NOT NULL AND r.module != ''
                GROUP BY r.module
            """, (project_id,)).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/summary/last-7-days", methods=["GET"])
def api_summary_last_7_days():
    with get_connection() as conn:
        init_schema(conn)
        raw = conn.execute(
            "SELECT executedAt, passed, failed, skipped FROM reports_summary ORDER BY run_id DESC LIMIT 100"
        ).fetchall()
    grouped = {}
    for row in raw:
        date_part = (row["executedAt"] or "").split(",")[0].strip()
        parts = date_part.split("/")
        if len(parts) >= 3:
            day, month, year = parts[0], parts[1], parts[2]
            label = f"{day} {get_month_name(month)}"
            if label not in grouped:
                grouped[label] = {"passed": 0, "failed": 0, "skipped": 0}
            grouped[label]["passed"] += row["passed"] or 0
            grouped[label]["failed"] += row["failed"] or 0
            grouped[label]["skipped"] += row["skipped"] or 0
    today = datetime.now()
    labels = []
    for i in range(-6, 1):
        d = today + timedelta(days=i)
        label = f"{d.day:02d} {get_month_name(f'{d.month:02d}')}"
        labels.append(label)
    return jsonify({
        "labels": labels,
        "passedData": [grouped.get(l, {}).get("passed", 0) for l in labels],
        "failedData": [grouped.get(l, {}).get("failed", 0) for l in labels],
        "skippedData": [grouped.get(l, {}).get("skipped", 0) for l in labels],
    })


@app.route("/api/summary/environment-weekly", methods=["GET"])
def api_summary_environment_weekly():
    with get_connection() as conn:
        init_schema(conn)
        raw = conn.execute("SELECT environment, status FROM reports").fetchall()
    data = {}
    for row in raw:
        env = row["environment"] or "Unknown"
        status = row["status"]
        if env not in data:
            data[env] = {"PASSED": 0, "FAILED": 0, "SKIPPED": 0}
        if status == "PASSED":
            data[env]["PASSED"] += 1
        elif status == "FAILED":
            data[env]["FAILED"] += 1
        elif status == "SKIPPED":
            data[env]["SKIPPED"] += 1
    sorted_env = sorted(data.items(), key=lambda x: sum(x[1].values()), reverse=True)
    labels = [e[0] for e in sorted_env]
    return jsonify({
        "labels": labels,
        "passedData": [data[e]["PASSED"] for e in labels],
        "failedData": [data[e]["FAILED"] for e in labels],
        "skippedData": [data[e]["SKIPPED"] for e in labels],
    })


@app.route("/api/history", methods=["GET"])
def api_history():
    search = request.args.get("search", "").strip()
    field = request.args.get("field", "run_id")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 10))
    offset = (page - 1) * limit
    where = ""
    params = []
    if search:
        where = f" WHERE {field} LIKE ?"
        params.append(f"%{search}%")
    with get_connection() as conn:
        init_schema(conn)
        data = conn.execute(
            f"SELECT * FROM reports_summary {where} ORDER BY run_id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        total_row = conn.execute(f"SELECT COUNT(*) as count FROM reports_summary {where}", params).fetchone()
        total = total_row["count"]
    return jsonify({
        "data": [row_to_dict(r) for r in data],
        "total": total,
        "page": page,
        "totalPages": (total + limit - 1) // limit,
    })


@app.route("/api/history/delete/<int:run_id>", methods=["DELETE"])
def api_history_delete(run_id):
    try:
        with get_connection() as conn:
            media_rows = conn.execute("SELECT screenshot, video FROM reports WHERE run_id = ?", (run_id,)).fetchall()
        reports_path = Path(REPORTS_DIR)
        json_path = reports_path / "json" / f"report_{run_id}.json"
        if json_path.exists():
            json_path.unlink()
        screenshot_folder = reports_path / "screenshots" / f"report_{run_id}"
        if screenshot_folder.exists():
            shutil.rmtree(screenshot_folder)
        for row in media_rows:
            for key in ("screenshot", "video"):
                p = row.get(key)
                if p:
                    full = reports_path / p
                    if full.exists():
                        full.unlink()
                    parent = full.parent
                    if parent.exists() and parent != reports_path:
                        try:
                            shutil.rmtree(parent)
                        except OSError:
                            pass
        with get_connection() as conn:
            conn.execute("DELETE FROM reports WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM reports_summary WHERE run_id = ?", (run_id,))
        return jsonify({"message": f"Test ID : {run_id} and related files have been deleted."})
    except Exception as e:
        return jsonify({"error": "Failed to delete data or files."}), 500


@app.route("/api/history/detail/<int:run_id>", methods=["GET"])
def api_history_detail(run_id):
    try:
        result = get_test_detail_by_run_id(run_id)
        return jsonify(result)
    except Exception:
        return jsonify({"error": "Internal Server Error"}), 500


@app.route("/api/generate-report", methods=["GET"])
def api_generate_report():
    start_date = request.args.get("startDate")
    end_date = request.args.get("endDate")
    start_id = request.args.get("startId")
    end_id = request.args.get("endId")
    download = request.args.get("download") == "true"

    with get_connection() as conn:
        init_schema(conn)
        data = conn.execute("SELECT * FROM reports_summary").fetchall()

    def parse_date(s):
        if not s:
            return None
        parts = s.split(",")[0].split("/")
        if len(parts) >= 3:
            return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
        return None

    def parse_filter_date(s):
        if not s:
            return None
        s = s.replace("Z", "").split("T")[0]
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    filtered = []
    for row in data:
        row_date = parse_date(row["executedAt"])
        start_dt = parse_filter_date(start_date) if start_date else None
        end_dt = parse_filter_date(end_date) if end_date else None
        ok_date = (not start_dt or (row_date and row_date >= start_dt)) and (
            not end_dt or (row_date and row_date <= end_dt)
        )
        ok_id = (not start_id or row["run_id"] >= int(start_id)) and (not end_id or row["run_id"] <= int(end_id))
        if ok_date and ok_id:
            filtered.append(dict(row))

    filtered.sort(key=lambda x: x["run_id"])
    if not filtered:
        return jsonify({
            "message": "No data found for the given filters.",
            "all_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "final_report": [],
        }), 404

    all_summary = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    final_report = []
    for item in filtered:
        detail = get_test_detail_by_run_id(item["run_id"])
        final_report.append({"test_ID": item["run_id"], **detail})
        all_summary["total"] += item["total"] or 0
        all_summary["passed"] += item["passed"] or 0
        all_summary["failed"] += item["failed"] or 0
        all_summary["skipped"] += item["skipped"] or 0

    if download and TEMPLATE_PATH.exists():
        try:
            from docxtpl import DocxTemplate
            doc = DocxTemplate(str(TEMPLATE_PATH))
            doc.render({"all_summary": all_summary, "reports": final_report})
            out_path = EXPORTS_DIR / "report.docx"
            doc.save(str(out_path))
            return send_file(str(out_path), as_attachment=True, download_name="automation-report.docx")
        except ImportError:
            return jsonify({"error": "python-docx-template required for Word export"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"all_summary": all_summary, "final_report": final_report})


# --- WebUI Config (browser-use merged) ---

WEBUI_CONFIG_PATH = _BASE / "data" / "webui_config.json"
WEBUI_SETTINGS_DIR = _BASE / "data" / "webui_settings"


def _ensure_webui_dirs():
    WEBUI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEBUI_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def _load_webui_config() -> dict:
    """Load merged agent + browser config from JSON."""
    _ensure_webui_dirs()
    if not WEBUI_CONFIG_PATH.exists():
        return _default_webui_config()
    try:
        with open(WEBUI_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {**_default_webui_config(), **data}
    except (json.JSONDecodeError, OSError):
        return _default_webui_config()


def _default_webui_config() -> dict:
    return {
        "agent": {
            "llm_provider": os.getenv("DEFAULT_LLM", "openai"),
            "llm_model_name": "gpt-4o",
            "llm_temperature": 0.6,
            "use_vision": True,
            "llm_base_url": "",
            "llm_api_key": "",
            "override_system_prompt": "",
            "extend_system_prompt": "",
            "max_steps": 100,
            "max_actions": 10,
            "max_input_tokens": 128000,
            "tool_calling_method": "auto",
        },
        "browser": {
            "browser_binary_path": "",
            "browser_user_data_dir": "",
            "use_own_browser": False,
            "keep_browser_open": True,
            "headless": False,
            "disable_security": False,
            "window_w": 1280,
            "window_h": 1100,
            "save_recording_path": "",
            "save_trace_path": "",
            "save_agent_history_path": "./tmp/agent_history",
            "save_download_path": "./tmp/downloads",
        },
    }


def _save_webui_config(data: dict) -> None:
    _ensure_webui_dirs()
    with open(WEBUI_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@app.route("/api/webui/config", methods=["GET"])
def api_webui_config_get():
    return jsonify(_load_webui_config())


@app.route("/api/webui/config", methods=["POST"])
def api_webui_config_save():
    body = request.get_json() or {}
    current = _load_webui_config()
    if "agent" in body:
        current["agent"] = {**current.get("agent", {}), **body["agent"]}
    if "browser" in body:
        current["browser"] = {**current.get("browser", {}), **body["browser"]}
    _save_webui_config(current)
    return jsonify(current)


# --- Run Agent (project test cases queue) ---

_agent_runs: dict[str, dict] = {}
_agent_events: dict[str, queue.Queue] = {}


def _get_project(pid: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_name, project_url, project_password FROM projects WHERE id = ?",
            (pid,),
        ).fetchone()
        return dict(row) if row else None


def _get_project_cases(pid: int) -> list[dict]:
    with get_connection() as conn:
        upload_ids = [
            r["test_case_id"]
            for r in conn.execute(
                "SELECT test_case_id FROM project_testcases WHERE project_id = ?",
                (pid,),
            ).fetchall()
        ]
        if not upload_ids:
            return []
        placeholders = ",".join("?" * len(upload_ids))
        rows = conn.execute(
            f"SELECT tc_id, title, module, content FROM test_cases WHERE upload_id IN ({placeholders}) ORDER BY upload_id, id",
            upload_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def _run_agent_loop(run_id: str, project_id: int):
    event_queue = _agent_events.get(run_id)
    if not event_queue:
        return

    def emit(evt: str, data: dict):
        try:
            event_queue.put_nowait({"event": evt, "data": data})
        except queue.Full:
            pass

    async def _run():
        from agent_runner import run_project_cases
        cfg = _load_webui_config()
        max_steps = int(cfg.get("agent", {}).get("max_steps", 100))
        await run_project_cases(
            project_id=project_id,
            get_project_fn=lambda p: _get_project(p),
            get_cases_fn=lambda p: _get_project_cases(p),
            event_callback=emit,
            max_steps=max_steps,
        )

    try:
        asyncio.run(_run())
    except Exception as e:
        emit("error", {"message": str(e)})
    finally:
        try:
            event_queue.put_nowait({"event": "_done", "data": {}})
        except queue.Full:
            pass


@app.route("/api/webui/run/start", methods=["GET", "POST", "OPTIONS"])
def api_webui_run_start():
    """Start running a project's test cases. Returns run_id for SSE stream."""
    if request.method == "GET":
        return jsonify({"ok": True, "message": "Use POST with {project_id} to start a run"})
    body = request.get_json() or {}
    project_id = body.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id required"}), 400
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid project_id"}), 400

    project = _get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    cases = _get_project_cases(project_id)
    if not cases:
        return jsonify({"error": "No test cases assigned to this project"}), 400

    run_id = str(uuid.uuid4())
    event_queue = queue.Queue()
    _agent_events[run_id] = event_queue
    _agent_runs[run_id] = {
        "project_id": project_id,
        "project_name": project.get("project_name", ""),
        "total": len(cases),
        "status": "running",
        "cases": [],
    }

    thread = threading.Thread(target=_run_agent_loop, args=(run_id, project_id), daemon=True)
    thread.start()

    return jsonify({"run_id": run_id, "total": len(cases)}), 201


@app.route("/api/webui/run/stream/<run_id>")
def api_webui_run_stream(run_id):
    """SSE stream for run progress."""

    def generate():
        event_queue = _agent_events.get(run_id)
        if not event_queue:
            yield f"data: {json.dumps({'event': 'error', 'data': {'message': 'Run not found'}})}\n\n"
            return
        try:
            while True:
                try:
                    msg = event_queue.get(timeout=60)
                    if msg.get("event") == "_done":
                        break
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            _agent_events.pop(run_id, None)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# --- Static & Routes ---

# Explicit 404 for unmatched /api/* GET/HEAD so catch-all never sees them
@app.route("/api/<path:subpath>", methods=["GET", "HEAD"])
def api_catchall_404(subpath):
    return jsonify({"error": "Not found"}), 404


@app.route("/")
def index():
    return send_from_directory(str(VIEWS_PATH), "index.html")


@app.route("/favicon.ico")
def favicon():
    from flask import Response
    return Response("", status=204)


@app.route("/views/html/<path:filename>")
def views_html(filename):
    return send_from_directory(str(VIEWS_PATH), filename)


@app.route("/<no_api_path:filename>", methods=["GET", "HEAD"])
def redirect_legacy(filename):
    if filename in ("index.html", "history.html", "report.html", "testcases.html", "detail.html", "project.html"):
        return send_from_directory(str(VIEWS_PATH), filename)
    return send_from_directory(str(PROJECT_ROOT), filename)


def main():
    with get_connection() as conn:
        init_schema(conn)
        try:
            _backfill_test_cases(conn)
        except Exception as e:
            print(f"Backfill warning: {e}")
    port = int(os.environ.get("PORT", "3001"))
    print(f"Auto-Report2 (Python) running on http://localhost:{port}")
    print(f"   Dashboard: http://localhost:{port}/")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
